/* loadingeditor.js — the "Edit Loading Pattern" view: change-list tracking,
 * undo/redo, drag interaction, and generate/preview/download. Owns a slice
 * of the shared state object (the edit* fields in state.js), mutated
 * through the existing update()/subscribe() pub-sub -- the same pattern
 * views.js already uses to own state.view. No second dispatcher.
 *
 * The backend expands one dragged cell into its full symmetry orbit
 * (geometry.symmetry_orbit) and returns the fully-expanded result -- this
 * module never computes orbit membership itself.
 */

import { state, update } from './state.js';
import { fetchLoadingPattern, applyLoadingPattern, generateLoadingPattern } from './api.js';

/** Called once per successful run load (from app.js's load()). Populates
 *  editSupported/editReason/editOriginal/editTokenAssembly and pre-fills
 *  the generate-form fields from the server's own suggestion, or leaves
 *  editSupported false with a reason when this run can't be edited. */
export async function refreshEditorSupport(runId) {
  // fetchLoadingPattern does not exist on the offline single-file build
  // (s3dash/bundle.py's _OFFLINE_API has no live backend to ask) -- same
  // guard app.js's exportPdf() already uses for fetchReportPdf there.
  if (typeof fetchLoadingPattern !== 'function') {
    update({ editSupported: false, editReason: null }, 'editSupport');
    return;
  }
  try {
    const body = await fetchLoadingPattern(runId);
    if (state.runId !== runId) return; // a newer run loaded while this was in flight
    if (body.supported) {
      const tokenAssembly = buildTokenAssemblyMap(body.entries, state.payload);
      const suggested = body.suggested || {};
      update(
        {
          editSupported: true,
          editReason: null,
          editOriginal: body.entries,
          editTokenAssembly: tokenAssembly,
          editResFilename: suggested.resFilename || '',
          editResExposure: suggested.resExposure || '',
          editWreFilename: suggested.wreFilename || '',
        },
        'editSupport'
      );
    } else {
      update(
        { editSupported: false, editReason: body.reason, editOriginal: null, editTokenAssembly: null },
        'editSupport'
      );
    }
  } catch (err) {
    if (state.runId !== runId) return;
    update(
      { editSupported: false, editReason: err.message || String(err), editOriginal: null, editTokenAssembly: null },
      'editSupport'
    );
  }
}

/** token -> the one assembly (row,col) that token described in the
 *  ORIGINAL pattern, joined positionally via payload.assemblyIndex.
 *  Fresh tokens (a shared FUE.NEW batch label) can name many positions;
 *  the first is kept as the representative -- correct, not approximate,
 *  because fresh assemblies sharing one token are interchangeable by
 *  construction (same fuelType/batch/enrichment). Reused tokens are
 *  unique per assembly, so the map is exact for them. */
function buildTokenAssemblyMap(entries, payload) {
  const map = new Map();
  const asms = (payload && payload.assemblies) || [];
  const index = (payload && payload.assemblyIndex) || {};
  for (const e of entries) {
    if (map.has(e.token)) continue;
    const i = index[`${e.row},${e.col}`];
    if (i !== undefined && asms[i]) map.set(e.token, asms[i]);
  }
  return map;
}

/* -------------------------------------------------------------- dragging */

let dragHost = null;
let dragState = null; // {fromRow, fromCol, sourceEl} while a drag is live
let lastTargetEl = null;

function cellRC(el) {
  if (!el || !el.closest) return null;
  const cell = el.closest('.cell.is-editable');
  if (!cell) return null;
  const row = Number(cell.dataset.row);
  const col = Number(cell.dataset.col);
  return Number.isFinite(row) && Number.isFinite(col) ? { row, col, el: cell } : null;
}

function onPointerDown(evt) {
  if (state.view !== 'edit' || state.editBusy) return;
  const hit = cellRC(evt.target);
  if (!hit) return;
  evt.preventDefault();
  dragState = { fromRow: hit.row, fromCol: hit.col, sourceEl: hit.el };
  hit.el.classList.add('is-drag-source');
  document.addEventListener('pointermove', onPointerMove);
  document.addEventListener('pointerup', onPointerUp);
}

function onPointerMove(evt) {
  if (!dragState) return;
  const el = document.elementFromPoint(evt.clientX, evt.clientY);
  const hit = cellRC(el);
  const targetEl = hit ? hit.el : null;
  if (targetEl === lastTargetEl) return;
  if (lastTargetEl) lastTargetEl.classList.remove('is-drop-target');
  lastTargetEl = targetEl;
  if (targetEl && targetEl !== dragState.sourceEl) targetEl.classList.add('is-drop-target');
}

function endDrag() {
  document.removeEventListener('pointermove', onPointerMove);
  document.removeEventListener('pointerup', onPointerUp);
  if (dragState) dragState.sourceEl.classList.remove('is-drag-source');
  if (lastTargetEl) lastTargetEl.classList.remove('is-drop-target');
  lastTargetEl = null;
  dragState = null;
}

function onPointerUp(evt) {
  if (!dragState) { endDrag(); return; }
  const { fromRow, fromCol } = dragState;
  const el = document.elementFromPoint(evt.clientX, evt.clientY);
  const hit = cellRC(el);
  endDrag();
  if (!hit) return; // dropped outside any cell -- no-op, not an error
  if (hit.row === fromRow && hit.col === fromCol) return; // dropped on itself
  applyDrag(fromRow, fromCol, hit.row, hit.col);
}

/** Registers the pointerdown listener on the map host. Safe to call once;
 *  pointermove/pointerup are attached only while a drag is actually in
 *  progress, so there is no always-on document listener cost. */
export function initLoadingEditor(host) {
  dragHost = host;
  dragHost.addEventListener('pointerdown', onPointerDown);
}

/* -------------------------------------------------------------- mutating */

/** Push one drag as a new change, replaying from the original through the
 *  active history prefix. A new drag while editHistoryIndex is short of
 *  editChanges.length discards the redo tail -- standard undo/redo-with-
 *  new-action semantics, so the stored array itself is truncated here. */
export async function applyDrag(fromRow, fromCol, toRow, toCol) {
  const change = { fromRow, fromCol, toRow, toCol };
  const changes = state.editChanges.slice(0, state.editHistoryIndex);
  changes.push(change);
  await replay(changes, changes.length, changes);
}

/** POSTs `changesToSend` (the active prefix) and stores the result.
 *  `fullChanges` is what gets written to editChanges -- for a new drag
 *  this is the same (possibly redo-tail-truncated) array that was sent;
 *  for undo/redo it is the ORIGINAL, untouched editChanges, since moving
 *  the history pointer must never discard the array itself. On failure,
 *  neither editChanges nor editHistoryIndex advance -- a rejected attempt
 *  leaves state exactly as it was before it. */
async function replay(changesToSend, historyIndex, fullChanges) {
  update({ editBusy: true, editError: null }, 'editChange');
  try {
    const body = await applyLoadingPattern(state.runId, changesToSend);
    update(
      {
        editChanges: fullChanges,
        editHistoryIndex: historyIndex,
        editModified: body.entries,
        editOperations: body.operations,
        editProblems: body.problems,
        editValid: body.valid,
        editBusy: false,
        editError: null,
        editGenerated: null, // a changed pattern invalidates any previous preview
      },
      'editChange'
    );
  } catch (err) {
    update({ editBusy: false, editError: err.message || String(err) }, 'editChange');
  }
}

/** Steps one change earlier. A no-op at the start of history. */
export function undo() {
  if (state.editBusy || state.editHistoryIndex <= 0) return;
  const newIndex = state.editHistoryIndex - 1;
  replay(state.editChanges.slice(0, newIndex), newIndex, state.editChanges);
}

/** Steps one change later (re-applies a change undo() stepped back from,
 *  without discarding it -- only a NEW drag discards the redo tail). */
export function redo() {
  if (state.editBusy || state.editHistoryIndex >= state.editChanges.length) return;
  const newIndex = state.editHistoryIndex + 1;
  replay(state.editChanges.slice(0, newIndex), newIndex, state.editChanges);
}

/** Clears every change. No network call: editOriginal is the cached,
 *  never-mutated starting pattern, so there is nothing to re-fetch. */
export function resetEdits() {
  if (state.editBusy) return;
  update(
    {
      editChanges: [],
      editHistoryIndex: 0,
      editModified: null,
      editOperations: [],
      editProblems: [],
      editValid: false,
      editError: null,
      editGenerated: null,
    },
    'editChange'
  );
}

/** Calls /generate and stores the result as the preview -- the result IS
 *  the preview (the design's "preview before download" requirement); a
 *  separate downloadGenerated action in panels.js then saves it, with no
 *  second round trip. */
export async function generateInp(resFilename, resExposure, wreFilename) {
  if (!state.editValid || state.editBusy) return;
  const changes = state.editChanges.slice(0, state.editHistoryIndex);
  update({ editBusy: true, editError: null }, 'editChange');
  try {
    const body = await generateLoadingPattern(state.runId, changes, resFilename, resExposure, wreFilename);
    update({ editBusy: false, editGenerated: body }, 'editChange');
  } catch (err) {
    update({ editBusy: false, editError: err.message || String(err) }, 'editChange');
  }
}
