/* app.js — entry point. Builds the toolbar, wires every control to state and
 * routes state changes to the renderers.
 */

import {
  state,
  update,
  subscribe,
  installPayload,
  buildLayers,
  currentLayer,
  statePoint,
  depletionRow,
  layerValues,
  axialColumns,
  axialNodes,
  is3d,
  exposureUnit,
  gridSize,
  anyFilterActive,
  visibilityMask,
  categories,
  controlRodSummary,
  scrollTo,
  fmt,
  fmtFixed,
  esc,
} from './state.js';
import {
  listSamples,
  parseSample,
  parseUpload,
  searchText,
  exportJson,
  exportCsv,
  fetchReportPdf,
} from './api.js';
import { initCoreMap, renderCoreMap, renderEditableCoreMap, setEditMapHost, hideTooltip } from './coremap.js';
import { refreshEditorSupport, initLoadingEditor } from './loadingeditor.js';
import {
  initCharts,
  renderDepletionChart,
  renderAxialChart,
  renderHistogram,
  renderInventoryChart,
  renderCpuChart,
  exportHostPng,
  DEPLETION_METRICS,
} from './charts.js';
import { initRouter, goTo, applyView } from './views.js';
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

const $ = (sel) => document.querySelector(sel);

/* --------------------------------------------------------------------- theme */

const THEMES = ['auto', 'light', 'dark'];
const THEME_GLYPH = { auto: '◐', light: '☀', dark: '☾' };

function applyTheme() {
  const t = state.theme;
  if (t === 'auto') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', t);
  const g = $('#theme-glyph');
  if (g) g.textContent = THEME_GLYPH[t];
  const btn = $('#btn-theme');
  if (btn) btn.title = `Colour theme: ${t} (click to change)`;
  try { localStorage.setItem('s3dash.theme', t); } catch (_) { /* private mode */ }
  // Light and dark carry different ramp anchors, so anything holding a baked
  // fill has to be redrawn — the CSS tokens alone cannot do it.
  if (state.payload) {
    renderCoreMap();
    drawCharts();
  }
}

function initTheme() {
  let saved = 'auto';
  try { saved = localStorage.getItem('s3dash.theme') || 'auto'; } catch (_) { /* ignore */ }
  state.theme = THEMES.includes(saved) ? saved : 'auto';
  applyTheme();
}

/* ---------------------------------------------------------------- loading */

let heroPanel = null;
let dialogPanel = null;

function setBusy(busy, message) {
  const html = busy
    ? `<span class="spinner" aria-hidden="true"></span> ${esc(message || 'Parsing listing…')}`
    : '';
  if (heroPanel) heroPanel.setStatus(html, busy ? 'is-busy' : '');
  if (dialogPanel) dialogPanel.setStatus(html, busy ? 'is-busy' : '');
  document.body.classList.toggle('is-busy', !!busy);
}

function setLoadError(message) {
  const html = `<strong>Could not load that listing.</strong> ${esc(message)}`;
  if (heroPanel) heroPanel.setStatus(html, 'is-error');
  if (dialogPanel) dialogPanel.setStatus(html, 'is-error');
}

async function load(promise, label) {
  setBusy(true, label);
  update({ loading: true, loadError: null }, 'loading');
  try {
    const payload = await promise;
    const runId = payload.runId;
    installPayload(payload, runId);
    refreshEditorSupport(runId);
    setBusy(false);
    const dlg = $('#load-dialog');
    if (dlg.open) dlg.close();
    toast(`Loaded ${payload.meta && payload.meta.fileName ? payload.meta.fileName : 'listing'}`);
  } catch (err) {
    setBusy(false);
    setLoadError(err.message || String(err));
    update({ loading: false, loadError: err.message || String(err) }, 'loading');
    if (!state.payload) $('#hero').scrollIntoView({ block: 'nearest' });
    else openLoadDialog();
  }
}

const loadHandlers = {
  onFile: (file) => load(parseUpload(file), `Uploading and parsing ${file.name}…`),
  onSample: (name) => load(parseSample(name), `Parsing ${name}…`),
};

function openLoadDialog() {
  const dlg = $('#load-dialog');
  if (!dlg.open) dlg.showModal();
}

/* ---------------------------------------------------------------- toolbar */

/* The layer control lives in two card headers now — the core map's and the
 * layer-distribution chart's — so both are filled from the same list and kept
 * in step with each other. */
const LAYER_SELECTS = ['#layer-select', '#layer-select-hist'];

function fillLayerSelects(p) {
  const layers = buildLayers(p);
  const values = layers.filter((l) => l.kind === 'value' || l.kind === 'text');
  const cats = layers.filter((l) => l.kind === 'category');
  const rods = layers.filter((l) => l.kind === 'crd');
  const opt = (l) =>
    `<option value="${esc(l.id)}"${l.id === state.layer ? ' selected' : ''}>` +
    `${esc(l.label)}${l.unit ? ` (${esc(l.unit)})` : ''}${l.kind === 'text' ? ' — text' : ''}` +
    `${l.code ? ` · ${esc(l.code)}` : ''}</option>`;
  const html =
    (values.length ? `<optgroup label="State-point edits">${values.map(opt).join('')}</optgroup>` : '') +
    (cats.length ? `<optgroup label="Loading pattern">${cats.map(opt).join('')}</optgroup>` : '') +
    (rods.length ? `<optgroup label="Core state">${rods.map(opt).join('')}</optgroup>` : '');
  for (const sel of LAYER_SELECTS) {
    const el = $(sel);
    if (el) el.innerHTML = html;
  }
}

function syncLayerSelects() {
  for (const sel of LAYER_SELECTS) {
    const el = $(sel);
    if (el && el.value !== state.layer) el.value = state.layer;
  }
}

function buildToolbar() {
  const p = state.payload;
  $('#toolbar').hidden = !p;
  $('#layout').hidden = !p;
  $('#view-nav').hidden = !p;
  $('#hero').hidden = !!p;
  $('#export-menu').hidden = !p;
  if (!p) return;

  /* layers ------------------------------------------------------------- */
  fillLayerSelects(p);

  /* step slider -------------------------------------------------------- */
  const n = (p.statePoints || []).length;
  const slider = $('#step-slider');
  slider.min = '0';
  slider.max = String(Math.max(0, n - 1));
  slider.value = String(state.stepIndex);
  slider.disabled = n <= 1;

  /* axial -------------------------------------------------------------- */
  const ax = $('#axial-select');
  const axGroup = ax.closest('.tool-group');
  if (is3d(p)) {
    const nodes = axialNodes();
    ax.disabled = false;
    ax.title = 'Axial node to highlight';
    axGroup.removeAttribute('title');
    axGroup.classList.remove('is-disabled');
    ax.innerHTML = nodes
      .slice()
      .sort((a, b) => b.node - a.node)
      .map(
        (nd) =>
          `<option value="${nd.node}"${nd.node === state.axialNode ? ' selected' : ''}>Node ${nd.node}</option>`
      )
      .join('');
  } else {
    ax.disabled = true;
    ax.innerHTML = `<option>n/a</option>`;
    ax.title = '2D case — single axial node';
    axGroup.title = '2D case — single axial node';
    axGroup.classList.add('is-disabled');
  }

  /* depletion metric --------------------------------------------------- */
  const dm = $('#depl-metric');
  const rows = p.depletion || [];
  const avail = DEPLETION_METRICS.filter((m) => rows.some((r) => Number.isFinite(r[m.id])));
  dm.innerHTML = (avail.length ? avail : DEPLETION_METRICS)
    .map((m) => `<option value="${m.id}"${m.id === state.deplMetric ? ' selected' : ''}>${esc(m.label)}</option>`)
    .join('');

  /* axial column ------------------------------------------------------- */
  const acSel = $('#axial-column');
  const cols = axialColumns(p);
  if (cols.length) {
    acSel.hidden = false;
    acSel.innerHTML = cols
      .map((c) => `<option value="${esc(c)}"${c === state.axialColumn ? ' selected' : ''}>${esc(c)}</option>`)
      .join('');
  } else {
    acSel.hidden = true;
    acSel.innerHTML = '';
  }

  /* flagged-only is meaningless when nothing is flagged — disabling it beats
     letting the user dim every cell and wonder what broke. */
  const flagCb = $('#flagged-only');
  const nFlagged = (p.symmetryGroups || []).length;
  flagCb.disabled = nFlagged === 0;
  const flagLabel = flagCb.closest('label');
  if (flagLabel) {
    flagLabel.classList.toggle('is-disabled', nFlagged === 0);
    flagLabel.title = nFlagged
      ? `Isolate the ${nFlagged} symmetry group(s) flagged in this run`
      : 'No symmetry violations in this run — nothing to isolate';
  }
  if (nFlagged === 0 && state.flaggedOnly) state.flaggedOnly = false;

  renderFilters();
  renderStepReadout();
  renderCoreMapTitle();
}

function renderFilters() {
  const p = state.payload;
  const host = $('#filter-body');
  if (!p) { host.innerHTML = ''; return; }
  const asms = p.assemblies || [];
  const fuels = categories(asms.map((a) => a.fuelType));
  const batches = categories(asms.map((a) => a.batch));

  const block = (title, items, kind, selected) =>
    !items.length
      ? `<div class="filter-block"><div class="filter-title">${esc(title)}</div>` +
        `<div class="muted">Not recorded in this listing.</div></div>`
      : `<div class="filter-block"><div class="filter-title">${esc(title)}</div>` +
        items
          .map(
            (c) =>
              `<label class="check"><input type="checkbox" data-filter="${kind}" value="${esc(c.value)}"` +
              `${selected.has(String(c.value)) ? ' checked' : ''}/>` +
              `<span>${esc(c.value)}</span><span class="muted">${c.count}</span></label>`
          )
          .join('') +
        `</div>`;

  host.innerHTML =
    block('Fuel type', fuels, 'fuel', state.fuelFilter) +
    block('Batch', batches, 'batch', state.batchFilter) +
    `<div class="filter-actions"><button type="button" class="btn btn-mini" id="filter-clear">Clear filters</button></div>`;

  host.querySelectorAll('[data-filter]').forEach((cb) => {
    cb.addEventListener('change', () => {
      const set = cb.dataset.filter === 'fuel' ? new Set(state.fuelFilter) : new Set(state.batchFilter);
      if (cb.checked) set.add(cb.value);
      else set.delete(cb.value);
      update(cb.dataset.filter === 'fuel' ? { fuelFilter: set } : { batchFilter: set }, 'filters');
    });
  });
  const clear = $('#filter-clear');
  if (clear) {
    clear.addEventListener('click', () =>
      update({ fuelFilter: new Set(), batchFilter: new Set(), flaggedOnly: false }, 'filters', 'flagged')
    );
  }
  renderFilterPill();
}

function renderFilterPill() {
  const pill = $('#filter-count');
  const n = state.fuelFilter.size + state.batchFilter.size + (state.flaggedOnly ? 1 : 0);
  pill.hidden = n === 0;
  pill.textContent = String(n);
  const cb = $('#flagged-only');
  if (cb) cb.checked = state.flaggedOnly;
}

function renderStepReadout() {
  const p = state.payload;
  const out = $('#step-readout');
  if (!p) { out.textContent = '—'; return; }
  const sp = statePoint();
  const dep = depletionRow();
  const n = (p.statePoints || []).length;
  const unit = exposureUnit(p);
  const bits = [`Step ${state.stepIndex + 1} / ${n}`];
  if (sp) bits.push(`${fmt(sp.exposure, 3)} ${unit}`);
  const keff = sp && Number.isFinite(sp.keff) ? sp.keff : dep && dep.keff;
  if (Number.isFinite(keff)) bits.push(`k-eff ${fmtFixed(keff, 5)}`);
  if (sp && Number.isFinite(sp.boron)) bits.push(`${fmt(sp.boron, 1)} ppm`);
  out.textContent = bits.join('  ·  ');
  $('#step-slider').value = String(state.stepIndex);
}

function renderCoreMapTitle() {
  const p = state.payload;
  if (!p) return;
  const layer = currentLayer();
  const n = gridSize(p);
  const sp = statePoint();
  const g = p.geometry || {};
  const isCrd = layer && layer.kind === 'crd';

  $('#coremap-title').textContent = isCrd
    ? 'Control rod drive map'
    : `Core map — ${layer ? layer.label : 'no layer'}`;

  if (isCrd) {
    const crd = controlRodSummary();
    $('#coremap-note').textContent = crd
      ? `${crd.cr.rows.length}×${crd.cr.cols.length} drive grid · ${crd.label} · step ${sp ? sp.step : 0}`
      : `no control-rod map at step ${sp ? sp.step : 0}`;
  } else {
    const withValue = layerValues().filter((v) => v !== null && v !== undefined).length;
    const total = (p.assemblies || []).length;
    const note = $('#coremap-note');
    let text = `${n}×${n} lattice · ${g.nAssemblies ?? withValue} fuelled positions · step ${sp ? sp.step : 0}`;
    if (anyFilterActive()) {
      // Say what is being withheld — a dimmed cell is easy to misread as "no data".
      const visible = visibilityMask(p).filter(Boolean).length;
      text += ` · filtered to ${visible} of ${total}, ${total - visible} dimmed`;
    }
    note.textContent = text;
    note.classList.toggle('is-filtered', anyFilterActive());
  }

  const note = $('#hist-note');
  if (note) note.textContent = layer ? `${layer.label} at step ${sp ? sp.step : 0}` : '';
}

/* ------------------------------------------------------------------ search */

async function runSearch() {
  const q = state.query.trim();
  if (!q) { update({ hits: null, searching: false }, 'search'); return; }
  const p = state.payload;

  if (p) {
    const needle = q.toLowerCase();
    const pick = (test) => (p.assemblies || []).findIndex((a) =>
      [a.site, a.serial, a.label].some((v) => v && test(String(v).toLowerCase()))
    );
    let idx = pick((v) => v === needle);
    if (idx < 0) idx = pick((v) => v.replace(/[\s-]/g, '') === needle.replace(/[\s-]/g, ''));
    if (idx < 0) idx = pick((v) => v.includes(needle));
    if (idx >= 0) update({ selection: idx, tab: 'inspector' }, 'selection', 'tab');
  }

  if (!state.runId) return;
  update({ searching: true, hits: null }, 'search');
  try {
    const r = await searchText(state.runId, q);
    update({ searching: false, hits: r }, 'search');
  } catch (err) {
    update({ searching: false, hits: { query: q, count: 0, hits: [], truncated: false } }, 'search');
    toast(err.message || 'Search failed', 'error');
  }
}

function gotoLine(line) {
  openSection(
    { id: `line-${line}`, name: `Line ${line}`, label: `Listing around line ${line}`, kind: 'text', start: line, end: line + 1, page: null },
    { context: 12, highlight: line }
  );
  goTo('sections');
  scrollTo($('#view-sections'));
}

/* -------------------------------------------------------------------- tabs */

function setTab(tab) {
  update({ tab }, 'tab');
}

function syncEditTab() {
  const tab = $('#viewtab-edit');
  if (!tab) return;
  const show = state.editSupported === true && !window.__S3_BUNDLE__;
  tab.hidden = !show;
  if (!show && state.view === 'edit') goTo('map');
}

function renderTabs() {
  for (const name of ['inspector', 'diagnostics', 'inventory']) {
    const on = state.tab === name;
    const tab = $(`#tab-${name}`);
    const panel = $(`#panel-${name}`);
    tab.setAttribute('aria-selected', String(on));
    tab.classList.toggle('is-active', on);
    panel.hidden = !on;
  }
}

/* ------------------------------------------------------------------- toast */

let toastTimer = 0;
function toast(message, kind = '') {
  const el = $('#toast');
  el.textContent = message;
  el.className = `toast ${kind}`;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
}

/* ------------------------------------------------------------------- wiring */

function wireControls() {
  $('#btn-theme').addEventListener('click', () => {
    const next = THEMES[(THEMES.indexOf(state.theme) + 1) % THEMES.length];
    update({ theme: next }, 'theme');
  });

  $('#btn-load').addEventListener('click', openLoadDialog);
  $('#load-close').addEventListener('click', () => $('#load-dialog').close());

  for (const sel of LAYER_SELECTS) {
    const el = $(sel);
    if (el) el.addEventListener('change', (e) => update({ layer: e.target.value }, 'layer'));
  }

  $('#step-slider').addEventListener('input', (e) => update({ stepIndex: Number(e.target.value) }, 'step'));
  $('#step-prev').addEventListener('click', () => stepBy(-1));
  $('#step-next').addEventListener('click', () => stepBy(1));

  $('#axial-select').addEventListener('change', (e) => update({ axialNode: Number(e.target.value) }, 'axial'));
  $('#axial-column').addEventListener('change', (e) => update({ axialColumn: e.target.value }, 'axial'));
  $('#depl-metric').addEventListener('change', (e) => update({ deplMetric: e.target.value }, 'depl'));

  const searchInput = $('#search-input');
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { update({ query: searchInput.value }, 'query'); runSearch(); }
  });
  $('#search-go').addEventListener('click', () => {
    update({ query: searchInput.value }, 'query');
    runSearch();
  });

  $('#flagged-only').addEventListener('change', (e) =>
    update({ flaggedOnly: e.target.checked }, 'flagged', 'filters')
  );

  // Only the export menu gets the hover treatment: the filter menu is a
  // multi-select the reader dwells in, and opening that in passing is a
  // nuisance rather than a shortcut.
  wireMenu($('#export-menu'));

  $('#exp-json').addEventListener('click', async () => {
    if (!state.runId) return;
    try {
      const { blob, filename } = await exportJson(state.runId);
      saveBlob(blob, filename || `${fileStem()}.parsed.json`);
    } catch (err) {
      toast(err.message || 'The JSON export failed.', 'error');
    }
    closeMenu($('#export-menu'));
  });
  $('#exp-csv').addEventListener('click', async () => {
    const sp = statePoint();
    if (!state.runId || !sp) return;
    try {
      const { blob, filename } = await exportCsv(state.runId, sp.step);
      saveBlob(blob, filename || `${fileStem()}.step${sp.step}.csv`);
    } catch (err) {
      toast(err.message || 'The CSV export failed.', 'error');
    }
    closeMenu($('#export-menu'));
  });
  $('#exp-pdf').addEventListener('click', exportPdf);
  $('#exp-print').addEventListener('click', () => {
    closeMenu($('#export-menu'));
    window.print();
  });

  for (const name of ['inspector', 'diagnostics', 'inventory']) {
    $(`#tab-${name}`).addEventListener('click', () => setTab(name));
  }

  $('#tree-filter').addEventListener('input', (e) => update({ treeFilter: e.target.value }, 'tree'));

  $('#nav-tree').addEventListener('click', (e) => {
    const toggle = e.target.closest('[data-toggle]');
    if (toggle) {
      const key = toggle.dataset.toggle;
      const open = new Set(state.openNodes);
      if (open.has(key)) open.delete(key);
      else open.add(key);
      update({ openNodes: open }, 'tree');
      return;
    }
    const leaf = e.target.closest('[data-section]');
    if (leaf) {
      let sec = null;
      try { sec = JSON.parse(leaf.dataset.section); } catch (_) { sec = null; }
      if (sec) {
        openSection(sec);
        goTo('sections');
        scrollTo($('#view-sections'));
      }
    }
  });

  $('#search-results').addEventListener('click', (e) => {
    const hit = e.target.closest('[data-hit-line]');
    if (hit) gotoLine(Number(hit.dataset.hitLine));
  });

  $('#section-copy').addEventListener('click', async () => {
    if (!state.section || !state.section.text) return;
    const ok = await copyText(state.section.text);
    toast(ok ? 'Section text copied' : 'Copy blocked by the browser', ok ? '' : 'error');
  });

  // symmetry members + diagnostic line links live in both right-hand panels
  document.addEventListener('click', (e) => {
    const png = e.target.closest('[data-png]');
    if (png) { exportPng(png); return; }

    // Status-badge counters and the panel's own severity chips are the same
    // control in two places: they filter the diagnostics list.
    const df = e.target.closest('[data-diag-filter]');
    if (df) { applyDiagFilter(df.dataset.diagFilter); return; }

    const rc = e.target.closest('[data-select-rc]');
    if (rc) {
      const idx = (state.payload.assemblyIndex || {})[rc.dataset.selectRc];
      if (idx !== undefined) {
        update({ selection: idx, tab: 'inspector' }, 'selection', 'tab');
        goTo('map');
        scrollTo($('#view-map'));
      }
      return;
    }
    const gl = e.target.closest('[data-goto-line]');
    if (gl) gotoLine(Number(gl.dataset.gotoLine));
  });

  $('#panel-diagnostics').addEventListener('click', (e) => {
    const th = e.target.closest('[data-sort]');
    if (!th) return;
    const key = th.dataset.sort;
    const dir = state.diagSort.key === key ? -state.diagSort.dir : 1;
    update({ diagSort: { key, dir } }, 'diag');
  });
  $('#panel-diagnostics').addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const th = e.target.closest('[data-sort]');
    if (!th) return;
    e.preventDefault();
    const key = th.dataset.sort;
    const dir = state.diagSort.key === key ? -state.diagSort.dir : 1;
    update({ diagSort: { key, dir } }, 'diag');
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') hideTooltip();
    const el = document.activeElement;
    const typing = el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT');
    if (typing || !state.payload) return;
    if (state.view !== 'map' && state.view !== 'plots') return;
    if (e.key === 'ArrowLeft' && !el.closest('.coremap')) { e.preventDefault(); stepBy(-1); }
    if (e.key === 'ArrowRight' && !el.closest('.coremap')) { e.preventDefault(); stepBy(1); }
  });

  window.addEventListener('scroll', hideTooltip, { passive: true });

  // In "auto" the OS can flip the theme under us, and the ramp anchors differ.
  if (typeof matchMedia === 'function') {
    const mq = matchMedia('(prefers-color-scheme: dark)');
    const onScheme = () => { if (state.theme === 'auto' && state.payload) { renderCoreMap(); drawCharts(); } };
    if (mq.addEventListener) mq.addEventListener('change', onScheme);
    else if (mq.addListener) mq.addListener(onScheme);
  }
}

function stepBy(delta) {
  const n = ((state.payload || {}).statePoints || []).length;
  if (!n) return;
  const next = Math.min(n - 1, Math.max(0, state.stepIndex + delta));
  if (next !== state.stepIndex) update({ stepIndex: next }, 'step');
}

function download(url) {
  const a = document.createElement('a');
  a.href = url;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/* ------------------------------------------------------------------- menus
 *
 * A <details> menu opens on click and on Enter/Space for free. Hover is added
 * on top — with a close delay, so crossing the 2 px seam to the panel does not
 * dismiss it — and keyboard focus opens it too, but only when the focus ring
 * is actually showing: without that guard a mouse click would open the menu on
 * focus and immediately close it again on the click.
 */
function closeMenu(details) {
  if (details) details.open = false;
}

function wireMenu(details) {
  if (!details) return;
  const summary = details.querySelector('summary');
  const body = details.querySelector('.menu-body');
  let timer = 0;
  /* Narrow layouts pin the panel to the viewport (see app.css) because the
   * header stops being a positioned ancestor there — which leaves exactly one
   * number for JS: where the button currently is. */
  const place = () => {
    if (!body) return;
    const narrow = typeof matchMedia === 'function' && matchMedia('(max-width: 720px)').matches;
    body.style.top = narrow ? `${Math.round(summary.getBoundingClientRect().bottom + 4)}px` : '';
  };
  const open = () => { clearTimeout(timer); place(); details.open = true; };
  const closeSoon = () => {
    clearTimeout(timer);
    timer = setTimeout(() => { details.open = false; }, 220);
  };

  /* Click keeps the native <details> toggle. Enter and Space are driven here
   * instead: a <summary> carrying role="button" does not reliably activate on
   * a key press, and "reachable by keyboard" is not negotiable for the only
   * way out of this app with a file. The stamp stops a native activation that
   * does fire from undoing the toggle a moment later. */
  let keyToggledAt = 0;
  summary.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
    e.preventDefault();
    keyToggledAt = Date.now();
    clearTimeout(timer);
    if (!details.open) place();
    details.open = !details.open;
  });
  summary.addEventListener('click', () => {
    clearTimeout(timer);
    if (Date.now() - keyToggledAt < 400) return;
    if (!details.open) place();
  });
  // role="button" hides the disclosure state a bare <summary> would expose.
  const syncExpanded = () => summary.setAttribute('aria-expanded', String(details.open));
  details.addEventListener('toggle', syncExpanded);
  syncExpanded();
  details.addEventListener('mouseenter', open);
  details.addEventListener('mouseleave', closeSoon);
  // Escape hands focus back to the button, and a keyboard-driven focus is
  // exactly what opens this menu — so that one move has to be exempt or the
  // menu springs straight back open.
  let returning = false;
  summary.addEventListener('focus', () => {
    if (returning) return;
    let visible = false;
    try { visible = summary.matches(':focus-visible'); } catch (_) { visible = false; }
    if (visible) open();
  });
  details.addEventListener('focusout', () => {
    // A focusout fires before the new element takes focus, so ask afterwards.
    setTimeout(() => {
      if (!details.contains(document.activeElement)) details.open = false;
    }, 0);
  });
  details.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    e.stopPropagation();
    clearTimeout(timer);
    details.open = false;
    returning = true;
    summary.focus(); // focus() dispatches synchronously, so this window is tight
    returning = false;
  });
  document.addEventListener('click', (e) => {
    if (!details.contains(e.target)) details.open = false;
  });
}

/* ---------------------------------------------------------------- exports */

/** A filename stem from the listing, safe for a Content-Disposition-free save. */
function fileStem() {
  const name = ((state.payload || {}).meta || {}).fileName || 'run';
  return String(name).replace(/\.[^.]+$/, '').replace(/[^\w.-]+/g, '_') || 'run';
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

/* The PDF is built server-side and takes a second or three, so the menu item
 * carries the wait itself and a backend {"detail": ...} comes back as the same
 * error toast every other failure uses. */
async function exportPdf() {
  const btn = $('#exp-pdf');
  const sp = statePoint();
  if (!state.runId || btn.disabled) return;
  if (typeof fetchReportPdf !== 'function') {
    toast('PDF reports need the dashboard server — this is a standalone snapshot.', 'error');
    return;
  }
  const note = btn.querySelector('.menu-item-note');
  const wasNote = note ? note.textContent : '';
  btn.disabled = true;
  btn.classList.add('is-busy');
  if (note) note.textContent = 'building the report…';
  try {
    const { blob, filename } = await fetchReportPdf(state.runId, sp ? sp.step : 0);
    saveBlob(blob, filename || `${fileStem()}.report.pdf`);
    toast(`Saved ${filename || 'the PDF report'}`);
    closeMenu($('#export-menu'));
  } catch (err) {
    toast(err.message || 'The PDF report could not be built.', 'error');
  } finally {
    btn.disabled = false;
    btn.classList.remove('is-busy');
    if (note) note.textContent = wasNote;
  }
}

/** Rasterise the figure a button points at and save it. */
async function exportPng(btn) {
  const host = document.getElementById(btn.dataset.png);
  const name = `${fileStem()}-${btn.dataset.pngName || 'chart'}.png`;
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Rendering…';
  try {
    await exportHostPng(host, name);
    toast(`Saved ${name}`);
  } catch (err) {
    toast(err.message || 'That figure could not be exported.', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

/* -------------------------------------------------------- diagnostics filter */

/** Narrow the diagnostics list to one severity or category. An empty value —
 *  or clicking the active one again — clears it. Always lands the reader on
 *  the panel it just filtered. */
function applyDiagFilter(raw) {
  const wanted = raw || null;
  const next = wanted && state.diagFilter === wanted ? null : wanted;
  update({ diagFilter: next, tab: 'diagnostics' }, 'diag', 'tab');
  goTo('map');
  requestAnimationFrame(() => scrollTo($('#panel-diagnostics')));
}

/* ------------------------------------------------------------ resizable cards
 *
 * `resize` does the dragging; this only reacts to it. A card that has been
 * given a size gets `is-sized`, which hands its inner scroller the room, and
 * anything measured in pixels — the core map's label thresholds, the charts —
 * is redrawn once the width has actually moved.
 */
const CHART_RENDERERS = {
  'chart-depletion': renderDepletionChart,
  'chart-axial': renderAxialChart,
  'chart-hist': renderHistogram,
  'chart-inventory': renderInventoryChart,
  'chart-cpu': renderCpuChart,
};

let redrawQueue = null;
let redrawRaf = 0;

function scheduleRedraw(card) {
  if (!redrawQueue) redrawQueue = new Set();
  redrawQueue.add(card);
  if (redrawRaf) return;
  redrawRaf = requestAnimationFrame(() => {
    redrawRaf = 0;
    const cards = redrawQueue;
    redrawQueue = null;
    for (const card of cards) {
      if (card.hidden || !card.isConnected) continue;
      if (card.querySelector('#coremap')) renderCoreMap();
      for (const host of card.querySelectorAll('.chart-host')) {
        const fn = CHART_RENDERERS[host.id];
        if (fn) fn(host);
      }
    }
  });
}

function initResizable() {
  if (!('ResizeObserver' in window)) return;
  const widths = new WeakMap();
  const ro = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const card = entry.target;
      card.classList.toggle('is-sized', !!(card.style.height || card.style.width));
      const w = Math.round(entry.contentRect.width);
      const was = widths.get(card);
      widths.set(card, w);
      // Skip the first observation and anything under a few pixels: a redraw
      // inside a resize callback that fires on its own output is a loop.
      if (was === undefined || Math.abs(was - w) < 4) continue;
      scheduleRedraw(card);
    }
  });
  document.querySelectorAll('[data-resizable]').forEach((el) => ro.observe(el));
}

function drawCharts() {
  renderDepletionChart($('#chart-depletion'));
  renderAxialChart($('#chart-axial'));
  renderHistogram($('#chart-hist'));
  renderInventoryChart($('#chart-inventory'));
  renderCpuChart($('#chart-cpu'));
}

/* ---------------------------------------------------------------- dispatch
 *
 * Renders are coalesced into one animation frame. A single `input` from the
 * step slider used to cost 19-27 ms — it rebuilds ~1260 SVG nodes plus three
 * charts and the inspector — so dragging across 30-odd steps fired several
 * full redraws per frame and stuttered. Collapsing every update inside a frame
 * into one render keeps the drag at one redraw per frame.
 */

let pendingKeys = null;
let rafId = 0;

function onChange(keys) {
  if (!pendingKeys) pendingKeys = new Set();
  for (const k of keys) pendingKeys.add(k);
  if (rafId) return;
  rafId = requestAnimationFrame(() => {
    rafId = 0;
    const batch = pendingKeys;
    pendingKeys = null;
    flush(batch);
  });
}

/* Only the visible view is drawn. A hidden container has zero width anyway, so
 * rendering into it is both wasted work and wrong — anything that measures its
 * host would read 0. Entering a view redraws it from current state, which is
 * what keeps switching lossless. */
const onMap = () => state.view === 'map';
const onPlots = () => state.view === 'plots';
const onSections = () => state.view === 'sections';
const onEdit = () => state.view === 'edit';

function flush(keys) {
  const any = (...k) => k.some((x) => keys.has(x));

  if (any('theme')) applyTheme();

  if (any('payload')) {
    renderHeader();
    buildToolbar();
    applyView(state.view);
    renderView(state.view);
    renderTabs();
    return;
  }

  if (any('step', 'layer', 'selection', 'filters', 'flagged')) {
    if (onMap()) renderCoreMap();
    renderCoreMapTitle();
  }
  if (onEdit() && any('editSupport', 'editChange')) {
    renderEditableCoreMap();
    renderLoadingEditorPanel();
  }
  // Two headers carry the layer control; whichever was used, both must agree.
  if (any('layer')) syncLayerSelects();
  if (any('payload', 'editSupport')) syncEditTab();
  if (any('step')) {
    renderStepReadout();
    if (onSections()) renderNavTree();
  }
  if (onPlots()) {
    if (any('step', 'layer')) renderHistogram($('#chart-hist'));
    if (any('step', 'depl')) renderDepletionChart($('#chart-depletion'));
    if (any('step', 'axial')) renderAxialChart($('#chart-axial'));
  }
  if (onMap() && any('step', 'layer', 'selection', 'axial')) renderInspector();
  if (any('filters', 'flagged')) renderFilterPill();
  if (any('tab', 'selection')) renderTabs();
  if (any('diag')) {
    renderStatusBadge(); // the header counters carry the pressed state
    if (onMap()) renderDiagnostics();
  }
  if (onSections() && any('tree', 'section')) renderNavTree();
  if (onSections() && any('section')) renderSectionViewer();
  // Text hits live in the left rail, which every view shows — a search run from
  // the map still has to report back.
  if (any('search')) renderSearchResults();
}

/** Draw everything the given view shows, from current state. */
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

function onEnterView(view) {
  hideTooltip();
  if (view === 'edit') syncEditTab();
  renderView(view);
}

/* -------------------------------------------------------------------- boot */

async function boot() {
  initTheme();

  heroPanel = buildLoadPanel($('#hero'), loadHandlers);
  dialogPanel = buildLoadPanel($('#load-dialog-host'), loadHandlers);

  initCoreMap($('#coremap'), $('#coremap-legend'), $('#tooltip'));
  setEditMapHost($('#edit-coremap'));
  initLoadingEditor($('#edit-coremap'));
  initCharts($('#chart-depletion'), $('#chart-axial'));
  wireControls();
  initResizable();

  // A standalone snapshot carries the parsed results but no server, so there
  // is nothing to render a PDF. Say so by not offering it.
  if (window.__S3_BUNDLE__) {
    const pdf = $('#exp-pdf');
    if (pdf) pdf.hidden = true;
  }

  subscribe(onChange);
  initRouter(onEnterView);

  renderHeader();
  renderTabs();

  try {
    const samples = await listSamples();
    heroPanel.setSamples(samples);
    dialogPanel.setSamples(samples);
  } catch (err) {
    heroPanel.setStatus(`<strong>Could not list samples.</strong> ${esc(err.message)}`, 'is-error');
  }
}

boot();
