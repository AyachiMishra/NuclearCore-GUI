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
import { fetchLoadingPattern } from './api.js';

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
