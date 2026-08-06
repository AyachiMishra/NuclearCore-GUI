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
import { listSamples, parseSample, parseUpload, searchText, exportJsonUrl, exportCsvUrl } from './api.js';
import { initCoreMap, renderCoreMap, hideTooltip } from './coremap.js';
import {
  initCharts,
  renderDepletionChart,
  renderAxialChart,
  renderHistogram,
  renderInventoryChart,
  renderCpuChart,
  DEPLETION_METRICS,
} from './charts.js';
import { initRouter, goTo, applyView } from './views.js';
import {
  renderHeader,
  renderInspector,
  renderDiagnostics,
  renderInventory,
  renderNavTree,
  renderSectionViewer,
  renderSearchResults,
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

function buildToolbar() {
  const p = state.payload;
  $('#toolbar').hidden = !p;
  $('#layout').hidden = !p;
  $('#view-nav').hidden = !p;
  $('#hero').hidden = !!p;
  if (!p) return;

  /* layers ------------------------------------------------------------- */
  const sel = $('#layer-select');
  const layers = buildLayers(p);
  const values = layers.filter((l) => l.kind === 'value' || l.kind === 'text');
  const cats = layers.filter((l) => l.kind === 'category');
  const rods = layers.filter((l) => l.kind === 'crd');
  const opt = (l) =>
    `<option value="${esc(l.id)}"${l.id === state.layer ? ' selected' : ''}>` +
    `${esc(l.label)}${l.unit ? ` (${esc(l.unit)})` : ''}${l.kind === 'text' ? ' — text' : ''}` +
    `${l.code ? ` · ${esc(l.code)}` : ''}</option>`;
  sel.innerHTML =
    (values.length ? `<optgroup label="State-point edits">${values.map(opt).join('')}</optgroup>` : '') +
    (cats.length ? `<optgroup label="Loading pattern">${cats.map(opt).join('')}</optgroup>` : '') +
    (rods.length ? `<optgroup label="Core state">${rods.map(opt).join('')}</optgroup>` : '');

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

  $('#status-badge').addEventListener('click', () => {
    goTo('map');
    setTab('diagnostics');
    scrollTo($('#panel-diagnostics'));
    $('#tab-diagnostics').focus();
  });

  $('#layer-select').addEventListener('change', (e) => update({ layer: e.target.value }, 'layer'));

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

  $('#exp-json').addEventListener('click', () => {
    if (!state.runId) return;
    download(exportJsonUrl(state.runId));
  });
  $('#exp-csv').addEventListener('click', () => {
    const sp = statePoint();
    if (!state.runId || !sp) return;
    download(exportCsvUrl(state.runId, sp.step));
  });
  $('#exp-print').addEventListener('click', () => window.print());

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
  if (onMap() && any('diag')) renderDiagnostics();
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
  }
}

function onEnterView(view) {
  hideTooltip();
  renderView(view);
}

/* -------------------------------------------------------------------- boot */

async function boot() {
  initTheme();

  heroPanel = buildLoadPanel($('#hero'), loadHandlers);
  dialogPanel = buildLoadPanel($('#load-dialog-host'), loadHandlers);

  initCoreMap($('#coremap'), $('#coremap-legend'), $('#tooltip'));
  initCharts($('#chart-depletion'), $('#chart-axial'));
  wireControls();
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
