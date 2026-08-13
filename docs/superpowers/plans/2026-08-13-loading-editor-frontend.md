# Core Loading Editor — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user drag assemblies on the core map in a distinct "Edit Loading Pattern" view, track every move as an undo/redo-able change list, validate the result, and generate/preview/download a next-cycle `.inp` — using only the already-built, already-tested backend (`s3dash/parser/loadingpattern.py`, `s3dash/parser/nextcycle.py`, and the three HTTP/Pyodide endpoints already wired in `app.py`/`browser.py`, including `suggest_generation_inputs`).

**Architecture:** A new `state.view` value (`'edit'`) reuses the existing hash-routed view-switching machinery in `views.js` untouched — confirmed by reading it, its hiding/toolbar logic already generalizes to a 4th view with only the `VIEWS` array literal changing. A new `loadingeditor.js` module owns the change-list/undo-redo logic and the pointer-based drag interaction, mutating a set of new fields on the existing shared `state` object via the existing `update()`/`subscribe()` pub-sub — the same pattern `views.js` already uses to own `state.view`, not a second dispatcher. `coremap.js` gains a new sibling render function (`renderEditableCoreMap()`) rather than modifying the existing analysis-mode renderer, which (unlike the design spec's description of it) is not parameterized — it reads `state.payload` directly with zero arguments. `panels.js` gains one new panel render function modeled on the existing `renderDiagnostics()`.

**Tech Stack:** Vanilla ES modules (no framework, no build step, no JS test runner — matching the rest of this codebase). Pointer Events API for drag (no native HTML5 drag-and-drop, per the design spec's explicit choice). Verification is manual, via the Claude Browser pane tools, against the `s3dash` FastAPI dev server (`.claude/launch.json` already configures this on port 8000) and, for Task 7, the `webdemo` static server (port 8091, also already configured).

## Global Constraints

- Every new request/response JSON field is camelCase, matching the already-built backend exactly: `fromRow`/`fromCol`/`toRow`/`toCol`, `resFilename`/`resExposure`/`wreFilename`, and the response shapes `{supported, entries, geometry, suggested, reason}` / `{entries, operations, problems, valid}` / `{text, flaggedCards, filename}` (`s3dash/web/app.py`'s `PositionChangeIn`/`ApplyChangesIn`/`GenerateInpIn` and its three routes are the source of truth).
- `s3dash.web.browser`'s three mirrored functions are `loading_pattern(run_id)`, `apply_loading_pattern(run_id, changes_json)`, `generate_loading_pattern(run_id, changes_json, res_filename, res_exposure, wre_filename)` — positional args only.
- `suggest_generation_inputs(cards, cycle_end)` in `nextcycle.py` (already built, tested, and wired into both `GET /loading-pattern` routes as `body.suggested = {resFilename, resExposure, wreFilename}`, each possibly `null`) is the ONLY source of pre-filled RES/WRE values. Never re-derive this in JavaScript — it would duplicate tested Python inference logic in a second language.
- No JS test runner exists in this repo. Every task's verification is a concrete, scripted manual check using the Claude Browser pane tools (`preview_start`, `read_page`, `computer`, `read_network_requests`, `read_console_messages`), not "open it and look."
- The offline single-file build (`s3dash/bundle.py`) has **no live backend of any kind** — its `_OFFLINE_API` shim bakes JSON at build time and cannot answer `loading_pattern`/`apply_loading_pattern`/`generate_loading_pattern`. This feature must be invisible there, following the exact precedent already used for PDF export (`typeof fetchReportPdf !== 'function'` guard in `app.js`).
- The mandatory on-screen banner text is exactly: `HYPOTHETICAL LOADING PATTERN — uncalculated` (design spec, verbatim).
- Direct commits to `main` after each task, per this session's established convention. Test command per task: the specific manual Browser-pane check listed in that task's steps — there is no `pytest`/`npm test` for this plan.

---

## Task 1: Editor-support detection — `api.js` (both), `state.js`, new `loadingeditor.js`, `app.js` wiring

**Files:**
- Modify: `s3dash/web/static/js/api.js`
- Modify: `webdemo/js/api.js`
- Modify: `s3dash/web/static/js/state.js`
- Modify: `s3dash/web/static/js/app.js`
- Create: `s3dash/web/static/js/loadingeditor.js`

**Interfaces:**
- Consumes: `s3dash/web/app.py`'s `GET /api/run/{run_id}/loading-pattern` (already built, now returns `suggested`); `s3dash/web/browser.py`'s `loading_pattern(run_id)` (same); `state`/`update` from `state.js`; `installPayload`'s existing reset pattern.
- Produces: `fetchLoadingPattern(runId)` in both `api.js` files (Task 4/6 build on this). `refreshEditorSupport(runId)` and `buildTokenAssemblyMap(entries, payload)` in `loadingeditor.js` (`refreshEditorSupport` is called from `app.js`; later tasks append more exports to this same file). New `state` fields — every later task in this plan reads/writes these exact names: `editSupported`, `editReason`, `editOriginal`, `editTokenAssembly`, `editChanges`, `editHistoryIndex`, `editModified`, `editOperations`, `editProblems`, `editValid`, `editBusy`, `editError`, `editGenerated`, `editResFilename`, `editResExposure`, `editWreFilename`.

- [ ] **Step 1: Add `fetchLoadingPattern` to the server-backed `api.js`**

Append to `s3dash/web/static/js/api.js`, after `searchText`:

```js
/** GET /api/run/{id}/loading-pattern -> {supported, entries?, geometry?, suggested?, reason?} */
export async function fetchLoadingPattern(runId) {
  const res = await check(await fetch(`/api/run/${encodeURIComponent(runId)}/loading-pattern`));
  return res.json();
}
```

- [ ] **Step 2: Add the matching function to the Pyodide-backed `api.js`**

Append to `webdemo/js/api.js`, after `searchText`:

```js
export async function fetchLoadingPattern(runId) {
  const r = await call('loading_pattern', runId);
  const { ok, ...body } = r;
  return body;
}
```

- [ ] **Step 3: Add the new state fields**

In `s3dash/web/static/js/state.js`, add to the `state` object, right after `diagFilter: null,`:

```js

  // Loading-pattern editor (loadingeditor.js). editSupported is a tri-state:
  // null = not checked yet, false = checked and unsupported, true = ready.
  editSupported: null,
  editReason: null,
  editOriginal: null, // {row,col,token,kind}[] from the server -- never mutated
  editTokenAssembly: null, // Map<token, assembly> for display, built once per run
  editChanges: [], // {fromRow,fromCol,toRow,toCol}[] -- full history, append-only except reset
  editHistoryIndex: 0, // 0..editChanges.length; undo/redo move this, never truncate the array
  editModified: null, // {row,col,token,kind}[] from the last apply() response
  editOperations: [], // AppliedOperation.to_json()[] from the last apply() response
  editProblems: [], // string[] from the last apply() response
  editValid: false,
  editBusy: false, // an apply/generate call is in flight
  editError: null, // last apply/generate failure message, or null
  editGenerated: null, // {text, flaggedCards, filename} from the last successful generate(), or null
  editResFilename: '', // the RES/WRE generate-form fields; pre-filled from body.suggested
  editResExposure: '',
  editWreFilename: '',
```

- [ ] **Step 4: Reset the new fields on every run load**

In `s3dash/web/static/js/state.js`, `installPayload()`'s `update()` call ends with `section: null,\n      diagFilter: null,\n    },\n    'payload'\n  );`. Insert the same reset fields between `diagFilter: null,` and the closing `},`:

```js
      section: null,
      diagFilter: null,
      editSupported: null,
      editReason: null,
      editOriginal: null,
      editTokenAssembly: null,
      editChanges: [],
      editHistoryIndex: 0,
      editModified: null,
      editOperations: [],
      editProblems: [],
      editValid: false,
      editBusy: false,
      editError: null,
      editGenerated: null,
      editResFilename: '',
      editResExposure: '',
      editWreFilename: '',
    },
    'payload'
  );
}
```

- [ ] **Step 5: Create `loadingeditor.js` with support-detection only**

Create `s3dash/web/static/js/loadingeditor.js`:

```js
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
```

- [ ] **Step 6: Wire `refreshEditorSupport` into `app.js`'s load flow**

In `s3dash/web/static/js/app.js`, add the import (with the other local-module imports, after the `coremap.js` import line):

```js
import { refreshEditorSupport } from './loadingeditor.js';
```

Then in `load()`, call it right after `installPayload`:

```js
async function load(promise, label) {
  setBusy(true, label);
  update({ loading: true, loadError: null }, 'loading');
  try {
    const payload = await promise;
    const runId = payload.runId;
    installPayload(payload, runId);
    refreshEditorSupport(runId);
    setBusy(false);
```

(Only the `refreshEditorSupport(runId);` line is new — everything else in `load()` stays exactly as it is.)

- [ ] **Step 7: Verify — supported run**

- `preview_start({name: "s3dash"})`
- `navigate` to `http://127.0.0.1:8000/`
- `computer` click the `case_002495.out` sample button (use `read_page` first to find its exact location if needed)
- `read_network_requests` filtered to `urlPattern: "loading-pattern"` — expect one GET request whose response body is `{"supported": true, "entries": [...241 items...], "geometry": {...}, "suggested": {"resFilename": null, "resExposure": "<a number as a string>", "wreFilename": null}}` (this file has a RES card but no WRE card, confirmed against the real data in `tests/test_api.py`'s own test for this exact response).

- [ ] **Step 8: Verify — unsupported run (BEAVRS, no `FUE.LAB` card)**

- `computer` click "Load listing" then the `9074.out` sample button
- `read_network_requests` filtered to `urlPattern: "loading-pattern"` — expect the newest GET response to be `{"supported": false, "reason": "..."}` mentioning "FUE.LAB" or "restart file".

- [ ] **Step 9: Commit**

```bash
git add s3dash/web/static/js/api.js webdemo/js/api.js s3dash/web/static/js/state.js s3dash/web/static/js/app.js s3dash/web/static/js/loadingeditor.js
git commit -m "feat(loading-editor): detect per-run editor support and cache the original pattern"
```

---

## Task 2: The "Edit Loading Pattern" view — `views.js`, both `index.html`, CSS, `app.js`

**Files:**
- Modify: `s3dash/web/static/js/views.js`
- Modify: `s3dash/web/static/index.html`
- Modify: `webdemo/index.html`
- Modify: `s3dash/web/static/css/app.css`
- Modify: `s3dash/web/static/js/app.js`

**Interfaces:**
- Consumes: `state.editSupported` (Task 1).
- Produces: `state.view === 'edit'` as a real, routable view. `#view-edit`, `#edit-coremap`, `#edit-panel`, `#viewtab-edit` DOM ids — Tasks 3, 4, 5, 6 render into these.

- [ ] **Step 1: Add `'edit'` to the view list**

In `s3dash/web/static/js/views.js`, change:

```js
export const VIEWS = ['map', 'plots', 'sections'];
```

to:

```js
export const VIEWS = ['map', 'plots', 'sections', 'edit'];
```

and change:

```js
const VIEW_LABEL = { map: 'Core map', plots: 'Plots', sections: 'Sections & Search' };
```

to:

```js
const VIEW_LABEL = { map: 'Core map', plots: 'Plots', sections: 'Sections & Search', edit: 'Edit Loading Pattern' };
```

Nothing else in `views.js` needs to change — `applyView()`'s `#view-${v}` loop, the `rail-right` hiding (`name !== 'map'`), and the `data-views` toolbar-group hiding all already generalize correctly to a 4th view name (verified by reading the function: none of those conditions special-case the first three names by exhaustive listing, they either test the specific name or list `'map'` alone). This also means: the run-metadata card (`rail-left`) stays visible in edit mode (its hide condition is `name === 'sections'` only) — deliberate, matches `plots`' behaviour, useful context while editing.

- [ ] **Step 2: Add the nav tab (both `index.html` files)**

In `s3dash/web/static/index.html`, inside `<nav class="view-nav" id="view-nav" ...>`, add a 4th tab after `Sections &amp; Search`:

```html
<nav class="view-nav" id="view-nav" aria-label="Views" hidden>
  <a class="viewtab" href="#/map"      data-view="map">Core map</a>
  <a class="viewtab" href="#/plots"    data-view="plots">Plots</a>
  <a class="viewtab" href="#/sections" data-view="sections">Sections &amp; Search</a>
  <a class="viewtab" href="#/edit"     data-view="edit" id="viewtab-edit" hidden>Edit Loading Pattern</a>
</nav>
```

Make the identical change in `webdemo/index.html` (same `<nav class="view-nav" id="view-nav">` block, same insertion).

- [ ] **Step 3: Add the `#view-edit` container (both `index.html` files)**

In `s3dash/web/static/index.html`, inside `<div class="col-center">`, add a 4th view section after `#view-sections`'s closing `</div>` and before the `.col-center` closing `</div>`:

```html
    <!-- ------------------------------------------------------- edit loading pattern -->
    <div class="view" id="view-edit" hidden>
      <div class="edit-layout">
        <section class="card" id="edit-map-card" aria-label="Editable core map">
          <header class="card-head">
            <h2>Edit loading pattern</h2>
            <span class="card-head-note" id="edit-map-note"></span>
          </header>
          <div class="coremap-wrap">
            <div id="edit-coremap" class="coremap"></div>
          </div>
        </section>
        <aside class="card card-flush" id="edit-panel-card" aria-label="Change summary and validation">
          <div id="edit-panel"></div>
        </aside>
      </div>
    </div>

  </div>
```

(The final `</div>` shown is the pre-existing `.col-center` close — only the new `<div class="view" id="view-edit">` block above it is new.)

Make the identical change in `webdemo/index.html`.

- [ ] **Step 4: Give the edit view its own column split**

In `s3dash/web/static/css/app.css`, the per-view grid rules (around lines 469-485) currently include, among others:

```css
body[data-view="plots"] .layout {
  grid-template-columns: minmax(240px, 320px) minmax(0, 1fr);
}
```

Change it to also cover `edit` (identical split — meta rail + full-width content):

```css
body[data-view="plots"] .layout,
body[data-view="edit"] .layout {
  grid-template-columns: minmax(240px, 320px) minmax(0, 1fr);
}
```

In the `@media (max-width: 1340px)` block, change:

```css
  .layout,
  body[data-view="map"] .layout,
  body[data-view="plots"] .layout {
    grid-template-columns: minmax(210px, 260px) minmax(0, 1fr);
  }
```

to:

```css
  .layout,
  body[data-view="map"] .layout,
  body[data-view="plots"] .layout,
  body[data-view="edit"] .layout {
    grid-template-columns: minmax(210px, 260px) minmax(0, 1fr);
  }
```

In the `@media (max-width: 980px)` block, change:

```css
  .layout,
  body[data-view="map"] .layout,
  body[data-view="plots"] .layout,
  body[data-view="sections"] .layout,
  body[data-view="sections"].has-hits .layout {
    grid-template-columns: minmax(0, 1fr);
  }
```

to:

```css
  .layout,
  body[data-view="map"] .layout,
  body[data-view="plots"] .layout,
  body[data-view="edit"] .layout,
  body[data-view="sections"] .layout,
  body[data-view="sections"].has-hits .layout {
    grid-template-columns: minmax(0, 1fr);
  }
```

Then add the internal split for `.edit-layout` itself (map card + panel aside), near the existing `.coremap-wrap` rule:

```css
.edit-layout { display: flex; gap: 12px; align-items: start; }
.edit-layout #edit-map-card { flex: 1 1 auto; min-width: 0; }
.edit-layout #edit-panel-card { flex: 0 0 340px; max-height: 80vh; overflow: auto; }
@media (max-width: 900px) {
  .edit-layout { flex-direction: column; }
  .edit-layout #edit-panel-card { flex: 1 1 auto; max-height: none; }
}
```

- [ ] **Step 5: Show/hide the tab based on `editSupported`, and never leave a dead edit view showing**

In `s3dash/web/static/js/app.js`, add a new function near `renderTabs()`:

```js
function syncEditTab() {
  const tab = $('#viewtab-edit');
  if (!tab) return;
  const show = state.editSupported === true && !window.__S3_BUNDLE__;
  tab.hidden = !show;
  if (!show && state.view === 'edit') goTo('map');
}
```

Wire it into `flush()` for the case where support changes WHILE already on the edit view — find `if (any('layer')) syncLayerSelects();` and add right after it:

```js
  if (any('layer')) syncLayerSelects();
  if (any('payload', 'editSupport')) syncEditTab();
```

Also wire it into `onEnterView(view)` for the case of entering the edit view directly (a tab click, a pasted `#/edit` link, or a reload while an unsupported run happens to be loaded) — `flush()`'s `'payload'`/`'editSupport'` triggers alone do not cover a direct hash navigation that changes only `state.view`, so this second call site is required, not redundant:

```js
function onEnterView(view) {
  hideTooltip();
  if (view === 'edit') syncEditTab();
  renderView(view);
}
```

- [ ] **Step 6: Verify**

- `preview_start({name: "s3dash"})`, `navigate` to `http://127.0.0.1:8000/`
- Load `case_002495.out`. `read_page` — confirm a 4th nav link "Edit Loading Pattern" is present and not hidden.
- `computer` click it. `read_page` — confirm `#view-edit` is now the visible view (others `hidden`), `#edit-coremap` and `#edit-panel` exist (empty for now — Tasks 3/5 fill them), and the URL is `.../#/edit`.
- Click "Core map" to go back, then load `9074.out` (BEAVRS). `read_page` — confirm the "Edit Loading Pattern" tab is now `hidden` again.
- With BEAVRS still loaded, `navigate` directly to `http://127.0.0.1:8000/#/edit` (typing the full hash URL, simulating a pasted link or reload) — confirm the app settles on `map`, not a dead edit view (check the final `document.body.dataset.view` via `read_page`/`javascript_tool`, not just the very first paint).

- [ ] **Step 7: Commit**

```bash
git add s3dash/web/static/js/views.js s3dash/web/static/index.html webdemo/index.html s3dash/web/static/css/app.css s3dash/web/static/js/app.js
git commit -m "feat(loading-editor): add the Edit Loading Pattern view and its routing"
```

---

## Task 3: Read-only editable core map — `coremap.js`, `panels.js` (stub), `app.js`, CSS

**Files:**
- Modify: `s3dash/web/static/js/coremap.js`
- Modify: `s3dash/web/static/js/app.js`
- Modify: `s3dash/web/static/js/panels.js`
- Modify: `s3dash/web/static/css/app.css`

**Interfaces:**
- Consumes: `state.editSupported`/`editReason`/`editOriginal`/`editModified` (Task 1); `#edit-coremap`/`#edit-panel` DOM ids (Task 2); `gridSize`/`axisLabels`/`esc` (already imported into `coremap.js` from `state.js`); `categoricalColor`/`textOn`/`cellPixels`/`CELL`/`PAD`/`HEAD_W`/`HEAD_H` (already defined in `coremap.js` itself).
- Produces: `renderEditableCoreMap()` and `setEditMapHost(host)` exported from `coremap.js` — Task 4 calls `renderEditableCoreMap()` after every drag. `renderLoadingEditorPanel()` exported from `panels.js` (minimal stub here, replaced with a full implementation in Task 5).

- [ ] **Step 1: Add `renderEditableCoreMap()` and `setEditMapHost()` to `coremap.js`**

Append to `s3dash/web/static/js/coremap.js` (after the existing `tooltipHtml` function, i.e. at the end of the file):

```js
/* ------------------------------------------------------- editable core map */

let editHostEl = null;

/** Registers the host the edit-mode map renders into. Called once from
 *  loadingeditor.js's initLoadingEditor(), which also owns the pointer
 *  listeners that make this map draggable (Task 4). */
export function setEditMapHost(host) {
  editHostEl = host;
}

/** Read-only edit-mode render: no computed values, ever (design constraint
 *  -- this is a hypothetical, uncalculated layout). Colour marks fresh vs
 *  reused; the label is the FUE.LAB token itself, which is the actual
 *  loading-pattern identity SIMULATE-3 prints -- not a re-derived name. */
export function renderEditableCoreMap() {
  if (!editHostEl) return;
  const p = state.payload;
  if (!p || state.editSupported !== true) {
    editHostEl.innerHTML = state.editReason
      ? `<div class="empty-note">This run can't be edited: ${esc(state.editReason)}</div>`
      : '';
    return;
  }

  const entries = state.editModified || state.editOriginal || [];
  const byRC = new Map(entries.map((e) => [`${e.row},${e.col}`, e]));

  const n = gridSize(p);
  const { cols, rows } = axisLabels(p);
  const W = HEAD_W + n * CELL + PAD;
  const H = HEAD_H + n * CELL + PAD;
  const pxCell = cellPixels(editHostEl, W, H);
  const showLabel = pxCell >= 15;

  const parts = [];
  parts.push(
    `<svg class="coremap-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" ` +
      `role="grid" aria-label="Editable core map, ${n} by ${n} lattice" ` +
      `aria-rowcount="${n}" aria-colcount="${n}">`
  );

  parts.push('<g class="axis-head" aria-hidden="true">');
  for (let c = 1; c <= n; c += 1) {
    const x = HEAD_W + (c - 1) * CELL + CELL / 2;
    parts.push(`<text class="head-text" x="${x}" y="${HEAD_H - 16}" text-anchor="middle">${esc(cols[c])}</text>`);
  }
  for (let r = 1; r <= n; r += 1) {
    const y = HEAD_H + (r - 1) * CELL + CELL / 2 + 9;
    parts.push(`<text class="head-text" x="${HEAD_W - 14}" y="${y}" text-anchor="end">${esc(rows[r])}</text>`);
  }
  parts.push('</g>');

  for (let r = 1; r <= n; r += 1) {
    parts.push(`<g role="row" aria-rowindex="${r}">`);
    for (let c = 1; c <= n; c += 1) {
      const x = HEAD_W + (c - 1) * CELL;
      const y = HEAD_H + (r - 1) * CELL;
      const e = byRC.get(`${r},${c}`);

      if (!e) {
        parts.push(
          `<rect class="cell-void" x="${x + PAD}" y="${y + PAD}" width="${CELL - 2 * PAD}" ` +
            `height="${CELL - 2 * PAD}" rx="5"/>`
        );
        continue;
      }

      const fresh = e.kind === 'fresh';
      const fill = fresh ? categoricalColor(1) : categoricalColor(0);
      const fg = textOn(fill);
      const cls = ['cell', 'is-editable', fresh ? 'is-fresh' : 'is-reused'].join(' ');
      const aria = `${e.token}, ${fresh ? 'fresh' : 'reused'}, row ${r} column ${c}`;

      parts.push(
        `<g class="${cls}" role="gridcell" aria-colindex="${c}" data-row="${r}" data-col="${c}" ` +
          `tabindex="-1" aria-label="${esc(aria)}">`
      );
      parts.push(
        `<rect class="cell-bg" x="${x + PAD}" y="${y + PAD}" width="${CELL - 2 * PAD}" ` +
          `height="${CELL - 2 * PAD}" rx="5" fill="${fill}"/>`
      );
      if (showLabel) {
        parts.push(
          `<text class="cell-label is-solo" x="${x + CELL / 2}" y="${y + 60}" ` +
            `text-anchor="middle" fill="${fg}">${esc(e.token)}</text>`
        );
      }
      parts.push(
        `<rect class="cell-ring" x="${x + PAD}" y="${y + PAD}" width="${CELL - 2 * PAD}" ` +
          `height="${CELL - 2 * PAD}" rx="5"/>`
      );
      parts.push('</g>');
    }
    parts.push('</g>');
  }

  parts.push('</svg>');
  editHostEl.innerHTML = parts.join('');
}
```

No import changes are needed for this step: `gridSize`, `axisLabels`, and `esc` are already in `coremap.js`'s existing `import { ... } from './state.js';` block, and `categoricalColor`/`textOn`/`cellPixels`/`CELL`/`PAD`/`HEAD_W`/`HEAD_H` are already defined locally in this same file.

- [ ] **Step 2: Add a minimal `renderLoadingEditorPanel()` stub to `panels.js`**

Append to `s3dash/web/static/js/panels.js` (at end of file):

```js
/* ------------------------------------------------------- loading editor */

export function renderLoadingEditorPanel() {
  const host = $('#edit-panel');
  if (!host) return;
  const p = state.payload;
  if (!p || state.editSupported !== true) {
    host.innerHTML = state.editReason
      ? `<div class="empty-note">This run can't be edited: ${esc(state.editReason)}</div>`
      : '';
    return;
  }
  host.innerHTML = `<div class="empty-note">Drag an assembly on the map to begin. Every drag moves its full symmetry group together.</div>`;
}
```

- [ ] **Step 3: Wire both into `app.js`'s render dispatch**

Extend the existing `coremap.js` import line:

```js
import { initCoreMap, renderCoreMap, renderEditableCoreMap, setEditMapHost, hideTooltip } from './coremap.js';
```

Extend the existing `panels.js` import list to add `renderLoadingEditorPanel`:

```js
import {
  renderHeader,
  renderStatusBadge,
  renderInspector,
  renderDiagnostics,
  renderInventory,
  renderNavTree,
  renderSectionViewer,
  renderSearchResults,
  renderLoadingEditorPanel,
  buildLoadPanel,
  openSection,
  copyText,
} from './panels.js';
```

In `boot()`, register the edit-mode map host right after the existing `initCoreMap(...)` call:

```js
  initCoreMap($('#coremap'), $('#coremap-legend'), $('#tooltip'));
  setEditMapHost($('#edit-coremap'));
```

Add an `onEdit()` helper alongside the existing `onMap`/`onPlots`/`onSections`:

```js
const onMap = () => state.view === 'map';
const onPlots = () => state.view === 'plots';
const onSections = () => state.view === 'sections';
const onEdit = () => state.view === 'edit';
```

Extend `renderView(view)` with an `edit` branch:

```js
function renderView(view) {
  if (!state.payload) return;
  if (view === 'map') {
    renderCoreMap();
    renderCoreMapTitle();
    renderInspector();
    renderDiagnostics();
    renderInventory();
  } else if (view === 'plots') {
    drawCharts();
  } else if (view === 'sections') {
    renderNavTree();
    renderSectionViewer();
    renderSearchResults();
  } else if (view === 'edit') {
    renderEditableCoreMap();
    renderLoadingEditorPanel();
  }
}
```

Extend `flush()`'s dispatch so a change to any edit field redraws the edit view while it's showing. Find:

```js
  if (any('step', 'layer', 'selection', 'filters', 'flagged')) {
    if (onMap()) renderCoreMap();
    renderCoreMapTitle();
  }
```

and add right after it:

```js
  if (onEdit() && any('editSupport', 'editChange')) {
    renderEditableCoreMap();
    renderLoadingEditorPanel();
  }
```

(`'editChange'` is the changed-key name Tasks 4-6's `applyDrag`/`undo`/`redo`/`resetEdits`/`generateInp` all use for every mutation to the edit-in-progress fields — established here so this dispatch line never needs to change again.)

- [ ] **Step 4: CSS for the edit-mode cell classes**

Add to `s3dash/web/static/css/app.css`, near the existing `.cell-hatch`/`.cell-flag` rules:

```css
.cell.is-editable { cursor: grab; touch-action: none; }
.cell.is-editable:active { cursor: grabbing; }
```

- [ ] **Step 5: Verify**

- `preview_start({name: "s3dash"})`, `navigate` to the app, load `case_002495.out`.
- Click the "Edit Loading Pattern" tab. `computer` screenshot.
- Confirm visually: a core map renders inside `#edit-coremap` with two distinct fill colours (fresh vs reused), each cell labelled with a token like `N-03` or `TP01` — not blank, not a value ramp.
- `read_page` on `#edit-coremap` — confirm the cell count matches the run's assembly count (241 for `case_002495.out`) by counting `[role="gridcell"]` elements, and that each carries `data-row`/`data-col` (not `data-idx`).
- Confirm `#edit-panel` shows the "Drag an assembly..." placeholder text.
- Switch to "Core map" and back — confirm the analysis map is untouched (still shows its normal value ramp, not token labels) — the two renderers must not interfere with each other.

- [ ] **Step 6: Commit**

```bash
git add s3dash/web/static/js/coremap.js s3dash/web/static/js/panels.js s3dash/web/static/js/app.js s3dash/web/static/css/app.css
git commit -m "feat(loading-editor): render the read-only editable core map"
```

---

## Task 4: Drag interaction — `loadingeditor.js`, `api.js` (both), `app.js`, CSS

**Files:**
- Modify: `s3dash/web/static/js/api.js`
- Modify: `webdemo/js/api.js`
- Modify: `s3dash/web/static/js/loadingeditor.js`
- Modify: `s3dash/web/static/js/app.js`
- Modify: `s3dash/web/static/css/app.css`

**Interfaces:**
- Consumes: `renderEditableCoreMap`/`setEditMapHost` (Task 3); `state.editOriginal`/`editChanges`/`editHistoryIndex`/`editBusy` (Task 1).
- Produces: `applyLoadingPattern(runId, changes)` in both `api.js` files — Task 5's undo/redo and Task 6's generate both reuse it. `initLoadingEditor(host)` exported from `loadingeditor.js`, called once from `app.js`'s `boot()`. A private `replay(changes, historyIndex)` helper inside `loadingeditor.js` — Task 5 (`undo`/`redo`/`resetEdits`) and Task 6 (`generateInp`) both call it or its established `update(..., 'editChange')` convention.

- [ ] **Step 1: Add `applyLoadingPattern` to both `api.js` files**

Append to `s3dash/web/static/js/api.js`, after `fetchLoadingPattern`:

```js
/** POST /api/run/{id}/loading-pattern/apply -> {entries, operations, problems, valid} */
export async function applyLoadingPattern(runId, changes) {
  const res = await check(
    await fetch(`/api/run/${encodeURIComponent(runId)}/loading-pattern/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ changes }),
    })
  );
  return res.json();
}
```

Append to `webdemo/js/api.js`, after `fetchLoadingPattern`:

```js
export async function applyLoadingPattern(runId, changes) {
  const r = await call('apply_loading_pattern', runId, JSON.stringify(changes));
  const { ok, ...body } = r;
  return body;
}
```

- [ ] **Step 2: Add the drag state machine to `loadingeditor.js`**

Extend the existing `./api.js` import line:

```js
import { fetchLoadingPattern, applyLoadingPattern } from './api.js';
```

Append to `s3dash/web/static/js/loadingeditor.js`:

```js
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
 *  new-action semantics. */
export async function applyDrag(fromRow, fromCol, toRow, toCol) {
  const change = { fromRow, fromCol, toRow, toCol };
  const changes = state.editChanges.slice(0, state.editHistoryIndex);
  changes.push(change);
  await replay(changes, changes.length);
}

/** POSTs `changes` (the active prefix) and stores the result. On failure,
 *  editChanges/editHistoryIndex are NOT advanced -- a rejected attempt
 *  leaves state exactly as it was before it. */
async function replay(changes, historyIndex) {
  update({ editBusy: true, editError: null }, 'editChange');
  try {
    const body = await applyLoadingPattern(state.runId, changes);
    update(
      {
        editChanges: changes,
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
```

- [ ] **Step 3: Wire `initLoadingEditor` into `app.js`'s boot**

Extend the existing `./loadingeditor.js` import line from Task 1:

```js
import { refreshEditorSupport, initLoadingEditor } from './loadingeditor.js';
```

In `boot()`, call it right after `setEditMapHost(...)`:

```js
  initCoreMap($('#coremap'), $('#coremap-legend'), $('#tooltip'));
  setEditMapHost($('#edit-coremap'));
  initLoadingEditor($('#edit-coremap'));
```

- [ ] **Step 4: CSS for drag-state cells**

Add to `s3dash/web/static/css/app.css`, right after the `is-editable` rules from Task 3:

```css
.cell.is-drag-source { opacity: 0.55; }
.cell.is-drop-target .cell-bg { stroke: var(--accent); stroke-width: 3px; }
```

- [ ] **Step 5: Verify — a full drag**

- `preview_start({name: "s3dash"})`, load `case_002495.out`, go to "Edit Loading Pattern".
- Pick two visibly different-token cells, neither at (row 9, col 9) — `case_002495.out`'s 17-wide grid has exactly one rotational fixed point there (confirmed in `tests/test_nextcycle_acceptance.py`'s own comment); every other position has a 4-member orbit, so any other pair works.
- `computer` `left_click_drag` from the first cell's coordinates to the second's.
- `read_network_requests` filtered to `urlPattern: "loading-pattern/apply"` — confirm one POST fired with `{"changes":[{"fromRow":...,"fromCol":...,"toRow":...,"toCol":...}]}`, a 200 response with `"valid":true`, and `operations.length === 1` (one orbit-level operation per drag — the 4-position orbit expansion shows up in `entries`, not as 4 separate operations).
- `computer` screenshot — confirm the two dragged cells' tokens, and each of their three rotational partners, visibly swapped (8 cells total change: 4 in the source orbit, 4 in the destination orbit).

- [ ] **Step 6: Verify — a self-drop is a no-op, not a crash**

- Press down on a cell and release without moving (or drag it back onto itself) — confirm no POST fires (`read_network_requests` shows nothing new since the previous check) and nothing visually changes.

- [ ] **Step 7: Commit**

```bash
git add s3dash/web/static/js/api.js webdemo/js/api.js s3dash/web/static/js/loadingeditor.js s3dash/web/static/js/app.js s3dash/web/static/css/app.css
git commit -m "feat(loading-editor): drag assemblies to move or swap their full symmetry orbit"
```

---

## Task 5: Undo, redo, reset, validation panel, mandatory banner — `loadingeditor.js`, `panels.js`, CSS

**Files:**
- Modify: `s3dash/web/static/js/loadingeditor.js`
- Modify: `s3dash/web/static/js/panels.js`
- Modify: `s3dash/web/static/css/app.css`

**Interfaces:**
- Consumes: the private `replay()` helper (Task 4, extended here); `state.editChanges`/`editHistoryIndex`/`editOperations`/`editProblems`/`editValid`/`editBusy`/`editError` (Task 1/4).
- Produces: `undo()`, `redo()`, `resetEdits()` exported from `loadingeditor.js` — Task 6's panel wiring calls all three (already true from this task's own panel code) and no later task adds anything new to them.

- [ ] **Step 1: Add undo/redo/reset to `loadingeditor.js`**

Append to `s3dash/web/static/js/loadingeditor.js`:

```js
/** Steps one change earlier. A no-op at the start of history. */
export function undo() {
  if (state.editBusy || state.editHistoryIndex <= 0) return;
  replay(state.editChanges.slice(0, state.editHistoryIndex - 1), state.editHistoryIndex - 1);
}

/** Steps one change later (re-applies a change undo() stepped back from,
 *  without discarding it -- only a NEW drag discards the redo tail). */
export function redo() {
  if (state.editBusy || state.editHistoryIndex >= state.editChanges.length) return;
  replay(state.editChanges.slice(0, state.editHistoryIndex + 1), state.editHistoryIndex + 1);
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
```

- [ ] **Step 2: Replace the Task-3 stub with the real panel in `panels.js`**

Replace the entire `renderLoadingEditorPanel()` function in `s3dash/web/static/js/panels.js` (written in Task 3) with:

```js
/* ------------------------------------------------------- loading editor */

export function renderLoadingEditorPanel() {
  const host = $('#edit-panel');
  if (!host) return;
  const p = state.payload;
  if (!p || state.editSupported !== true) {
    host.innerHTML = state.editReason
      ? `<div class="empty-note">This run can't be edited: ${esc(state.editReason)}</div>`
      : '';
    return;
  }

  const changes = state.editChanges.slice(0, state.editHistoryIndex);
  const out = [];

  if (changes.length) {
    out.push(`<div class="notice-strip edit-banner">HYPOTHETICAL LOADING PATTERN — uncalculated</div>`);
  }

  out.push(
    `<div class="edit-toolbar">` +
      `<button type="button" class="btn btn-mini" id="edit-undo" ${state.editHistoryIndex <= 0 || state.editBusy ? 'disabled' : ''}>Undo</button>` +
      `<button type="button" class="btn btn-mini" id="edit-redo" ${state.editHistoryIndex >= state.editChanges.length || state.editBusy ? 'disabled' : ''}>Redo</button>` +
      `<button type="button" class="btn btn-mini" id="edit-reset" ${!changes.length || state.editBusy ? 'disabled' : ''}>Reset</button>` +
      `<span class="pill pill-mini">${changes.length} change${changes.length === 1 ? '' : 's'}</span>` +
      `</div>`
  );

  if (state.editError) {
    out.push(`<div class="error-note">${esc(state.editError)}</div>`);
  }

  if (!changes.length) {
    out.push(section('Changes', `<div class="empty-note">No changes yet. Drag an assembly on the map to begin.</div>`));
  } else {
    const ops = state.editOperations || [];
    out.push(
      section(
        'Changes',
        `<div class="table-wrap"><table class="data-table"><thead><tr>` +
          `<th>Op</th><th>From</th><th>To</th><th>Moved</th><th>Displaced</th>` +
          `</tr></thead><tbody>` +
          ops
            .map(
              (op) =>
                `<tr><td>${esc(op.operation)}</td><td class="mono">${esc(op.from)}</td>` +
                `<td class="mono">${esc(op.to)}</td><td class="mono">${esc(op.fromToken)}</td>` +
                `<td class="mono">${esc(op.toToken ?? '—')}</td></tr>`
            )
            .join('') +
          `</tbody></table></div>`
      )
    );
  }

  if (changes.length) {
    const problems = state.editProblems || [];
    out.push(
      section(
        'Validation',
        problems.length
          ? `<div class="error-note">${problems.map((msg) => `<div>${esc(msg)}</div>`).join('')}</div>`
          : `<div class="empty-note">Valid — every position is occupied exactly once and every symmetry group is intact.</div>`
      )
    );
  }

  host.innerHTML = out.join('');

  $('#edit-undo').addEventListener('click', undo);
  $('#edit-redo').addEventListener('click', redo);
  $('#edit-reset').addEventListener('click', resetEdits);
}
```

This needs `undo`, `redo`, `resetEdits` imported at the top of `panels.js` — add:

```js
import { undo, redo, resetEdits } from './loadingeditor.js';
```

- [ ] **Step 3: CSS for the banner and toolbar**

Add to `s3dash/web/static/css/app.css`, near the existing `.notice-strip` rule:

```css
.edit-banner { border-radius: var(--radius); margin-bottom: 10px; font-weight: 700; letter-spacing: 0.02em; }
.edit-toolbar { display: flex; align-items: center; gap: 8px; padding: 10px 12px 0; }
```

- [ ] **Step 4: Verify — the full undo/redo/reset cycle**

- `preview_start({name: "s3dash"})`, load `case_002495.out`, go to "Edit Loading Pattern".
- Perform two separate drags (two different pairs of cells, both away from the grid centre).
- `read_page` on `#edit-panel` — confirm the "Changes" table has 2 rows, "2 changes" pill, both Undo and Reset enabled, Redo disabled.
- Click Undo. Confirm the table drops to 1 row, "1 change" pill, both Undo and Redo now enabled.
- Click Undo again. Confirm 0 changes, no banner, Undo disabled, Redo enabled, Reset disabled.
- Click Redo twice. Confirm back to 2 changes, matching the state before either Undo.
- Click Reset. Confirm 0 changes, both Undo and Redo disabled — the redo tail is discarded by Reset, not merely history-index-zeroed (confirm Redo does NOT bring the two drags back after Reset).
- Confirm the "HYPOTHETICAL LOADING PATTERN — uncalculated" banner is visible whenever the active change count is above 0 and absent at 0.

- [ ] **Step 5: Commit**

```bash
git add s3dash/web/static/js/loadingeditor.js s3dash/web/static/js/panels.js s3dash/web/static/css/app.css
git commit -m "feat(loading-editor): undo, redo, reset, and the change/validation panel"
```

---

## Task 6: Generate, preview, and download the next-cycle `.inp` — `api.js` (both), `loadingeditor.js`, `panels.js`, CSS

**Files:**
- Modify: `s3dash/web/static/js/api.js`
- Modify: `webdemo/js/api.js`
- Modify: `s3dash/web/static/js/loadingeditor.js`
- Modify: `s3dash/web/static/js/panels.js`
- Modify: `s3dash/web/static/css/app.css`

**Interfaces:**
- Consumes: `state.editValid`/`editChanges`/`editHistoryIndex`/`editResFilename`/`editResExposure`/`editWreFilename` (Task 1, pre-filled from the backend's `suggested` field); `undo`/`redo`/`resetEdits` (Task 5).
- Produces: `generateInp(resFilename, resExposure, wreFilename)` exported from `loadingeditor.js`. `generateLoadingPattern(...)` in both `api.js` files. `state.editGenerated`. This is the last task in this plan that adds a new backend call or a new `loadingeditor.js`/`panels.js` export.

- [ ] **Step 1: Add `generateLoadingPattern` to both `api.js` files**

Append to `s3dash/web/static/js/api.js`, after `applyLoadingPattern`:

```js
/** POST /api/run/{id}/loading-pattern/generate -> {text, flaggedCards, filename} */
export async function generateLoadingPattern(runId, changes, resFilename, resExposure, wreFilename) {
  const res = await check(
    await fetch(`/api/run/${encodeURIComponent(runId)}/loading-pattern/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        changes,
        resFilename,
        resExposure,
        wreFilename: wreFilename || null,
      }),
    })
  );
  return res.json();
}
```

Append to `webdemo/js/api.js`, after `applyLoadingPattern`:

```js
export async function generateLoadingPattern(runId, changes, resFilename, resExposure, wreFilename) {
  const r = await call(
    'generate_loading_pattern', runId, JSON.stringify(changes),
    resFilename, resExposure, wreFilename || null
  );
  const { ok, ...body } = r;
  return body;
}
```

- [ ] **Step 2: Add `generateInp` to `loadingeditor.js`**

Extend the existing `./api.js` import line:

```js
import { fetchLoadingPattern, applyLoadingPattern, generateLoadingPattern } from './api.js';
```

Append:

```js
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
```

- [ ] **Step 3: Add the generate form, preview, and download to `panels.js`**

Extend the `./loadingeditor.js` import line from Task 5:

```js
import { undo, redo, resetEdits, generateInp } from './loadingeditor.js';
```

In `renderLoadingEditorPanel()` (in `s3dash/web/static/js/panels.js`), insert a new block right after the `Validation` `section(...)` push and before `host.innerHTML = out.join('');`:

```js
  if (changes.length) {
    out.push(
      section(
        'Generate next-cycle .inp',
        `<div class="edit-generate-fields">` +
          `<label>RES filename<input type="text" id="edit-res-filename" value="${esc(state.editResFilename)}" placeholder="s3.plant.c02.depl.res" /></label>` +
          `<label>RES exposure<input type="text" id="edit-res-exposure" value="${esc(state.editResExposure)}" placeholder="20000." /></label>` +
          `<label>WRE filename (optional)<input type="text" id="edit-wre-filename" value="${esc(state.editWreFilename)}" placeholder="s3.plant.c03.depl.res" /></label>` +
          `<button type="button" class="btn" id="edit-generate" ${state.editValid && !state.editBusy ? '' : 'disabled'}>Generate .inp</button>` +
          `</div>` +
          (state.editGenerated
            ? `<div class="edit-preview"><div class="edit-preview-head">` +
              `<span>${esc(state.editGenerated.filename)}</span>` +
              (state.editGenerated.flaggedCards.length
                ? `<span class="tag tag-warn">carried from the source cycle: ${esc(state.editGenerated.flaggedCards.join(', '))}</span>`
                : '') +
              `<button type="button" class="btn btn-mini" id="edit-download">Download</button>` +
              `</div><pre class="edit-preview-text">${esc(state.editGenerated.text)}</pre></div>`
            : '')
      )
    );
  }
```

Add the wiring at the end of `renderLoadingEditorPanel()`, right after the existing `$('#edit-reset').addEventListener(...)` line:

```js
  const genBtn = $('#edit-generate');
  if (genBtn) {
    genBtn.addEventListener('click', () => {
      const resFilename = $('#edit-res-filename').value.trim();
      const resExposure = $('#edit-res-exposure').value.trim();
      const wreFilename = $('#edit-wre-filename').value.trim() || null;
      update({ editResFilename: resFilename, editResExposure: resExposure, editWreFilename: wreFilename }, 'editChange');
      generateInp(resFilename, resExposure, wreFilename);
    });
  }
  const dlBtn = $('#edit-download');
  if (dlBtn) {
    dlBtn.addEventListener('click', () => {
      const g = state.editGenerated;
      if (!g) return;
      const blob = new Blob([g.text], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = g.filename;
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    });
  }
```

- [ ] **Step 4: CSS for the generate form and preview**

Add to `s3dash/web/static/css/app.css`, near the `.edit-toolbar` rule from Task 5. `--mono` is already defined in the `:root` token block (line 50) and used throughout this file (e.g. `.mono { font-family: var(--mono); }`, line 171) — reuse it directly for the preview text:

```css
.edit-generate-fields { display: flex; flex-direction: column; gap: 8px; }
.edit-generate-fields label { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--text-dim); }
.edit-generate-fields input { padding: 5px 8px; border: 1px solid var(--border); border-radius: 5px; background: var(--bg); color: var(--text); font: inherit; }
.edit-preview { margin-top: 10px; }
.edit-preview-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.edit-preview-text {
  max-height: 320px; overflow: auto; padding: 8px 10px; background: var(--bg);
  border: 1px solid var(--border); border-radius: var(--radius);
  font: 400 11.5px/1.5 var(--mono); white-space: pre-wrap; word-break: break-word;
}
```

- [ ] **Step 5: Verify — the full generate/preview/download flow**

- `preview_start({name: "s3dash"})`, load `case_002495.out`, go to "Edit Loading Pattern", perform one valid drag.
- `read_page` — confirm the "Generate next-cycle .inp" section appears with 3 input fields (RES exposure pre-filled from `state.payload.meta.cycleEnd` via the backend's `suggested` field; RES/WRE filename blank for this specific sample, since it has no WRE card) and a "Generate .inp" button.
- `computer` type a RES filename (e.g. `s3.test.c02.depl.res`) into the RES filename field (required since this sample's own suggestion is empty), leave the pre-filled exposure as-is, leave WRE blank.
- Click "Generate .inp". `read_network_requests` filtered to `urlPattern: "loading-pattern/generate"` — confirm a 200 response with `text`/`flaggedCards`/`filename`.
- `read_page` — confirm a preview `<pre>` block appeared containing the typed RES filename and the moved token at its new position, plus a "Download" button.
- Click "Download" — confirm no console error fires (`read_console_messages`) and the browser's download mechanism was invoked (a triggered `<a download>` click).
- Undo the drag — confirm the preview block disappears (per `replay`'s `editGenerated: null` reset) and the Generate button becomes disabled again (0 changes).

- [ ] **Step 6: Commit**

```bash
git add s3dash/web/static/js/api.js webdemo/js/api.js s3dash/web/static/js/loadingeditor.js s3dash/web/static/js/panels.js s3dash/web/static/css/app.css
git commit -m "feat(loading-editor): generate, preview, and download the next-cycle .inp"
```

---

## Task 7: Sync the Pyodide-hosted build — `tools/build_webdemo.py`

**Files:**
- Modify: `tools/build_webdemo.py`

**Interfaces:**
- Consumes: every file from Tasks 1-6 that's already on the existing `SHARED_JS` list, plus the one new file this plan added.
- Produces: nothing new — this task's only job is making the existing copy mechanism include `loadingeditor.js`.

- [ ] **Step 1: Add `loadingeditor.js` to `SHARED_JS`**

In `tools/build_webdemo.py`, change:

```python
SHARED_JS = ["state.js", "coremap.js", "panels.js", "charts.js", "views.js", "app.js"]
```

to:

```python
SHARED_JS = ["state.js", "coremap.js", "panels.js", "charts.js", "views.js", "app.js", "loadingeditor.js"]
```

- [ ] **Step 2: Build and verify**

```bash
python tools/build_webdemo.py
```

Expected: succeeds; `site/js/loadingeditor.js` now exists. (If it fails complaining about a missing wheel in `dist/`, run `python -m build --wheel` first — the wheel itself is unaffected by this plan, so this is only needed if a fresh checkout has no `dist/` yet.)

- `preview_start({name: "webdemo"})` (serves `site/` on port 8091 per `.claude/launch.json`)
- `navigate` to `http://127.0.0.1:8091/` and wait for the Pyodide boot message to clear — this takes noticeably longer than the FastAPI surface (it downloads and initialises a Python runtime in the browser); give it real time rather than assuming instant readiness.
- Load the bundled BEAVRS sample (`9074.out`, the only sample this surface ships) — confirm the "Edit Loading Pattern" tab stays hidden (BEAVRS has no `FUE.LAB` card, same result as the FastAPI surface's Task 1 check).
- webdemo ships only BEAVRS, so exercising `supported: true` on this surface needs a different file: use the load dialog's dropzone to upload `sample_data/case_002495.out` from the repo (the same file used throughout this plan). Once it's loaded through Pyodide, repeat Task 4's drag verification and Task 6's generate verification against it. This is the one check in this plan that exercises `s3dash.web.browser`'s three functions end-to-end through a real browser, rather than only through the `pytest` suite that already covers them directly.

- [ ] **Step 3: Commit**

```bash
git add tools/build_webdemo.py
git commit -m "feat(loading-editor): ship loadingeditor.js in the Pyodide-hosted build"
```

---

## Task 8: Keep the offline single-file bundle building — `s3dash/bundle.py`

**Files:**
- Modify: `s3dash/bundle.py`

**Interfaces:**
- Consumes: `app.js`'s now-present static `import ... from './loadingeditor.js'` (Task 1).
- Produces: nothing new — confirms the existing bundler still works and correctly excludes the feature's UI on this surface.

- [ ] **Step 1: Add `loadingeditor.js` to `MODULE_ORDER`**

In `s3dash/bundle.py`, change:

```python
MODULE_ORDER = ["state.js", "coremap.js", "views.js", "charts.js", "panels.js", "app.js"]
```

to:

```python
MODULE_ORDER = ["state.js", "coremap.js", "views.js", "charts.js", "panels.js", "loadingeditor.js", "app.js"]
```

`loadingeditor.js` must be listed before `app.js`, matching the file's own module-order comment ("a module may only depend on ones already registered") — `app.js` imports from `loadingeditor.js`, exactly like every other module it already depends on in this list.

- [ ] **Step 2: Verify the bundle still builds and correctly hides the feature**

```bash
python -m s3dash.bundle sample_data/case_002495.out -o "$SCRATCHPAD/bundle_check.html"
```

(Use this session's scratchpad directory rather than `/tmp`, per this environment's convention; `$SCRATCHPAD` is `C:\Users\HUAWEI\AppData\Local\Temp\claude\D--OneDrive---IITD-Abu-Dhabi-Documents-Internship-KU-Datewise-outputs-02-5thAug\f6e2993c-3e81-4474-bebe-99418e83efdc\scratchpad` for this session.)

Expected: exits 0, no `RuntimeError` about unhandled module syntax — the exact failure mode `loadingeditor.js`'s `import`/`export` statements would trigger if they used anything `_to_module()` doesn't already handle. Tasks 1-6 only ever used plain named `import { a, b } from './x.js'` and `export function`/`export async function`, both already handled for every other module in this list, so this should pass with no change to `bundle.py`'s parsing logic itself.

- `navigate` to the produced file (a `file://` URL, or `preview_start({url: "file:///<path>"})`).
- Confirm the page loads and behaves exactly as it did before this whole plan (load `case_002495.out` — it's baked in as one of the file's two samples) — critically, confirm the "Edit Loading Pattern" nav tab never becomes visible (`read_page` — `#viewtab-edit` stays `hidden`), since `window.__S3_BUNDLE__` is set on this surface and `syncEditTab()`'s guard checks it unconditionally.
- `read_console_messages` — confirm no uncaught exception, specifically from `refreshEditorSupport`'s `typeof fetchLoadingPattern !== 'function'` guard path (it must silently set `editSupported: false` and return, not throw, since this surface's `_OFFLINE_API` never defines `fetchLoadingPattern`).

- [ ] **Step 3: Commit**

```bash
git add s3dash/bundle.py
git commit -m "feat(loading-editor): keep the offline bundle building with the editor correctly hidden"
```

---

## Task 9: Document the three new endpoints — `docs/API_CONTRACT.md`

**Files:**
- Modify: `docs/API_CONTRACT.md`

**Interfaces:**
- Consumes: nothing code-level — documentation only.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Append the three new endpoints**

`docs/API_CONTRACT.md`'s `## Endpoints` section (line 29) is a single Markdown table ending with:

```markdown
| `GET`  | `/api/run/{runId}/export.csv?step=N` | download assembly table for a step |

Errors are `{"detail": "..."}` with 4xx/5xx.
```

Add three rows to that same table, immediately before the `Errors are...` line:

```markdown
| `GET`  | `/api/run/{runId}/export.csv?step=N` | download assembly table for a step |
| `GET`  | `/api/run/{runId}/loading-pattern` | `{supported,entries,geometry,suggested}` or `{supported:false,reason}` |
| `POST` | `/api/run/{runId}/loading-pattern/apply` | replay a change list from the original pattern → `{entries,operations,problems,valid}` |
| `POST` | `/api/run/{runId}/loading-pattern/generate` | replay, validate, and generate the next-cycle `.inp` text → `{text,flaggedCards,filename}`; 422 if invalid |

Errors are `{"detail": "..."}` with 4xx/5xx.
```

- [ ] **Step 2: Commit**

```bash
git add docs/API_CONTRACT.md
git commit -m "docs: add the loading-pattern editor endpoints to the API contract"
```

---

## Task 10: Full manual verification against the design spec's testing checklist

**Files:** none (verification only).

**Interfaces:** none — this task exercises everything Tasks 1-9 built, end to end.

- [ ] **Step 1: Work through the design spec's own frontend testing checklist**

Using `preview_start({name: "s3dash"})` against `case_002495.out` (per `docs/superpowers/specs/2026-08-12-loading-editor-design.md`'s "Testing" section, frontend half), confirm each of the following, taking a screenshot at the milestones marked 📷:

1. Move one assembly — confirm its 3 symmetry partners moved too (📷 before/after).
2. Swap two occupied positions — confirm both orbits fully exchanged.
3. Perform 3+ sequential moves, then Undo twice, Redo once, then Reset — confirm the change count and map state match at every step.
4. Attempt an invalid drop — drag between (row 9, col 9) (this deck's one rotational fixed point, orbit size 1) and any other cell (orbit size 4) — confirm the orbit-size mismatch surfaces a visible reason via `editError`, not a silent no-op or a crash.
5. Confirm the validation panel reflects real state at every step — a pattern built purely from drags always validates clean (`apply_change` only ever produces symmetric results by construction), so this specifically confirms the "problems" rendering path itself is wired correctly, not that it's exercised with real content from this UI alone.
6. Confirm `Generate .inp` stays disabled until `editValid` is true, and enables immediately once it is.
7. Confirm the preview shows the exact change reflected in the text before any download happens (📷).
8. Confirm the "HYPOTHETICAL LOADING PATTERN — uncalculated" banner is visible throughout editing and gone at 0 changes.
9. Switch to the normal "Core map" view mid-edit — confirm it renders `state.payload` untouched (the original computed values, unaffected by any hypothetical drag) and is not itself editable (no drag classes, no pointerdown handling — analysis-mode cells never carry `is-editable`).

- [ ] **Step 2: Confirm both alternate builds still work**

- `python tools/build_webdemo.py` succeeds (already checked in Task 7; Tasks 8-9 didn't touch shared JS, so this is a quick re-confirmation).
- `python -m s3dash.bundle sample_data/case_002495.out -o "$SCRATCHPAD/bundle_final_check.html"` succeeds (already checked in Task 8; re-confirm).

- [ ] **Step 3: Report to the user**

Summarise the whole three-plan arc (backend, wiring, frontend) in the A-I structure the user's original feature request specified: which files changed and which were newly created; how the modified core is represented in-browser (the `edit*` state fields plus `loadingeditor.js`); exactly which SIMULATE-3 input cards the generator modifies vs. preserves verbatim (point to the design spec's own card-by-card table rather than re-deriving it); how symmetry is handled (server-side orbit expansion via `geometry.symmetry_orbit`, by construction, not after-the-fact validation); what validation is performed (both `nextcycle.validate()`'s backend rules and this plan's frontend disabled-until-valid gating); what limitations remain (verbatim from the design spec's "Known limitations" section: quarter-core/rotational only, no `rotation`/`subType` support, the reused-reference convention is inferred from within-deck consistency and not proven across a real 3+-cycle sequence, `WRE`'s inferred filename rests on a single within-deck example, no official SIMULATE-3 manual exists in this repository); and exactly how to test locally (`python -m s3dash`, load a sample, click "Edit Loading Pattern").

(No commit for this task — it produces a report to the user, not a file change.)
