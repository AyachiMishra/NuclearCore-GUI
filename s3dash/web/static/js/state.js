/* state.js — single mutable app state + a tiny pub/sub, plus the derived
 * selectors every view needs.
 *
 * Nothing here reaches into the DOM. Renderers subscribe and are handed the
 * set of change-keys so they can skip work that cannot have changed.
 *
 * Payload rules honoured here (see docs/API_CONTRACT.md):
 *   - grid size comes from geometry.iafull (never hard-coded)
 *   - layers are built from variableOrder + sections[].variable (never a fixed list)
 *   - 2PLO values are strings: excluded from colour/number scales
 *   - values[code][i] aligns to assemblies[i]; null means "no value here"
 */

export const state = {
  runId: null,
  payload: null,

  loading: false,
  loadError: null,

  stepIndex: 0,
  layer: null, // layer id: a variable code, or "__fueltype__" / "__batch__"
  axialNode: null, // 1-based node number, only meaningful when is3d
  selection: null, // index into payload.assemblies

  fuelFilter: new Set(), // empty set == no filter
  batchFilter: new Set(),
  flaggedOnly: false,

  deplMetric: 'keff',
  axialColumn: null,

  tab: 'inspector',
  treeFilter: '',
  openNodes: new Set(),

  query: '',
  searching: false,
  hits: null, // {count, hits[], truncated} or null
  hitLine: null,

  section: null, // {id,label,name,start,end,page,kind,text,loading,error,offset}

  theme: 'auto', // 'auto' | 'light' | 'dark'
  view: 'map', // 'map' | 'plots' | 'sections' — mirrors location.hash
  diagSort: { key: 'severity', dir: 1 },
  // null = show everything; otherwise a severity ('ERROR' | 'WARNING' |
  // 'CAUTION' | 'NOTE') or the 'SYMMETRY' category.
  diagFilter: null,
};

/** Severities the diagnostics list can be narrowed to, plus the one category
 *  that is not a severity at all. */
export const DIAG_FILTERS = ['ERROR', 'WARNING', 'CAUTION', 'NOTE', 'SYMMETRY'];

/* ------------------------------------------------------------------ pub/sub */

const listeners = new Set();

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Merge `patch` into state and notify subscribers with the change keys. */
export function update(patch, ...changed) {
  Object.assign(state, patch);
  const keys = new Set(changed.length ? changed : Object.keys(patch));
  for (const fn of listeners) {
    try {
      fn(keys, state);
    } catch (err) {
      console.error('[s3dash] renderer failed', err);
    }
  }
}

/** Notify without changing anything (used for pure view-level redraws). */
export function emit(...changed) {
  update({}, ...changed);
}

/* ------------------------------------------------------- payload installation */

export const CATEGORICAL_LAYERS = {
  __fueltype__: { id: '__fueltype__', kind: 'category', label: 'Fuel type', unit: '', field: 'fuelType' },
  __batch__: { id: '__batch__', kind: 'category', label: 'Batch', unit: '', field: 'batch' },
};

export const CRD_LAYER = { id: '__controlrods__', kind: 'crd', label: 'Control rods', unit: 'steps' };

export function installPayload(payload, runId) {
  const layers = buildLayers(payload);
  const preferred =
    layers.find((l) => l.id === '2RPF') || layers.find((l) => l.kind === 'value') || layers[0];
  const axialCols = axialColumns(payload);
  update(
    {
      payload,
      runId,
      loading: false,
      loadError: null,
      stepIndex: 0,
      layer: preferred ? preferred.id : null,
      axialNode: payload.geometry && payload.geometry.is3d ? 1 : null,
      selection: null,
      fuelFilter: new Set(),
      batchFilter: new Set(),
      flaggedOnly: false,
      deplMetric: 'keff',
      axialColumn: axialCols.includes('RPF') ? 'RPF' : axialCols[0] || null,
      tab: 'inspector',
      treeFilter: '',
      openNodes: defaultOpenNodes(payload),
      query: '',
      hits: null,
      hitLine: null,
      section: null,
      diagFilter: null,
    },
    'payload'
  );
}

function defaultOpenNodes(payload) {
  const open = new Set();
  const tree = payload && Array.isArray(payload.navTree) ? payload.navTree : [];
  for (const c of tree) open.add(`case:${c.case}`);
  const main = tree.find((c) => Array.isArray(c.steps) && c.steps.length > 1) || tree[0];
  if (main && main.steps && main.steps[0]) open.add(`step:${main.case}:${main.steps[0].step}`);
  return open;
}

/* --------------------------------------------------------------- derivations */

/** Map of variable code -> {code, name, unit, basis} taken from sections[]. */
export function variableMeta(payload) {
  const out = new Map();
  for (const s of payload.sections || []) {
    const v = s && s.variable;
    if (v && v.code && !out.has(v.code)) out.set(v.code, v);
  }
  return out;
}

/** View layers: every code in variableOrder, plus the two categorical layers. */
export function buildLayers(payload) {
  if (!payload) return [];
  const meta = variableMeta(payload);
  const codes = Array.isArray(payload.variableOrder) ? payload.variableOrder : [];
  const present = new Set();
  for (const sp of payload.statePoints || []) {
    for (const c of Object.keys(sp.values || {})) present.add(c);
  }
  // variableOrder first (first-seen order), then anything only the state
  // points mention. Never a fixed list.
  const ordered = codes.slice();
  for (const c of present) if (!ordered.includes(c)) ordered.push(c);

  const layers = ordered.map((code) => {
    const v = meta.get(code);
    return {
      id: code,
      code,
      kind: isTextCode(payload, code) ? 'text' : 'value',
      label: v && v.name ? v.name : code,
      unit: v && v.unit ? v.unit : '',
      basis: v && v.basis ? v.basis : '',
    };
  });

  const hasFuel = (payload.assemblies || []).some((a) => a.fuelType !== null && a.fuelType !== undefined);
  const hasBatch = (payload.assemblies || []).some((a) => a.batch !== null && a.batch !== undefined);
  if (hasFuel) layers.push({ ...CATEGORICAL_LAYERS.__fueltype__ });
  if (hasBatch) layers.push({ ...CATEGORICAL_LAYERS.__batch__ });
  if (hasControlRods(payload)) layers.push({ ...CRD_LAYER });
  return layers;
}

/* ------------------------------------------------------------- fuel types */

/** fuelType -> assemblyTypes[] entry (physical description of the type). */
export function typeInfo(payload = state.payload) {
  const map = new Map();
  for (const t of (payload && payload.assemblyTypes) || []) {
    if (t && t.fuelType !== null && t.fuelType !== undefined) map.set(t.fuelType, t);
  }
  return map;
}

/** fuelType -> inventory[] row. Enrichment comes from HERE, never from
 *  segments[] — fuel-type numbers and segment numbers are separate
 *  namespaces and only coincide by accident in some listings. */
export function inventoryByType(payload = state.payload) {
  const map = new Map();
  for (const r of (payload && payload.inventory) || []) {
    if (r && r.fuelType !== null && r.fuelType !== undefined) map.set(r.fuelType, r);
  }
  return map;
}

/** Display name for a fuel type, or null when the listing never describes it. */
export function typeName(fuelType, payload = state.payload) {
  const t = typeInfo(payload).get(fuelType);
  if (t && t.name) return t.name;
  const inv = inventoryByType(payload).get(fuelType);
  return inv && inv.typeName ? inv.typeName : null;
}

/* ------------------------------------------------------------ control rods */

/** controlRods block for a step, or null when the listing has no CRD map.
 *  This is indexed by control-rod DRIVE location on its own grid — it does
 *  NOT align with assemblies[] / assemblyIndex. Always read rows/cols. */
export function controlRods(index = state.stepIndex) {
  const sp = statePoint(index);
  const cr = sp && sp.controlRods;
  if (!cr) return null;
  const rows = Array.isArray(cr.rows) ? cr.rows : [];
  const cols = Array.isArray(cr.cols) ? cr.cols : [];
  if (!rows.length || !cols.length) return null;
  return cr;
}

export function hasControlRods(payload = state.payload) {
  for (const sp of (payload && payload.statePoints) || []) {
    const cr = sp && sp.controlRods;
    if (cr && Array.isArray(cr.rows) && cr.rows.length && Array.isArray(cr.cols) && cr.cols.length) {
      return true;
    }
  }
  return false;
}

/** Summary of the rod pattern at a step: ARO, or how many drives are in. */
export function controlRodSummary(index = state.stepIndex) {
  const cr = controlRods(index);
  if (!cr) return null;
  const inserted = Array.isArray(cr.inserted) ? cr.inserted : [];
  const withdrawn = Array.isArray(cr.withdrawn) ? cr.withdrawn : [];
  const positions = inserted.length + withdrawn.length;
  const aro = !cr.anyInserted && inserted.length === 0;
  return {
    cr,
    inserted,
    withdrawn,
    positions,
    aro,
    label: aro
      ? `All rods withdrawn (ARO) — ${withdrawn.length} drive position${withdrawn.length === 1 ? '' : 's'}`
      : `${inserted.length} drive${inserted.length === 1 ? '' : 's'} inserted of ${positions}`,
  };
}

/** True when a code's values are strings (2PLO peak-pin location, etc.). */
function isTextCode(payload, code) {
  for (const sp of payload.statePoints || []) {
    const arr = sp.values && sp.values[code];
    if (!arr) continue;
    for (const v of arr) {
      if (v === null || v === undefined) continue;
      return typeof v === 'string';
    }
  }
  return false;
}

export function currentLayer() {
  const layers = buildLayers(state.payload);
  return layers.find((l) => l.id === state.layer) || layers[0] || null;
}

export function statePoint(index = state.stepIndex) {
  const pts = (state.payload && state.payload.statePoints) || [];
  if (!pts.length) return null;
  return pts[Math.min(Math.max(0, index), pts.length - 1)] || null;
}

export function stepCount() {
  return ((state.payload && state.payload.statePoints) || []).length;
}

/** depletion[] row matching the current state point (fall back to index). */
export function depletionRow(index = state.stepIndex) {
  const p = state.payload;
  if (!p || !Array.isArray(p.depletion) || !p.depletion.length) return null;
  const sp = statePoint(index);
  if (sp) {
    const hit = p.depletion.find((d) => d.step === sp.step && d.case === sp.case);
    if (hit) return hit;
  }
  return p.depletion[Math.min(index, p.depletion.length - 1)] || null;
}

/** Raw per-assembly values for the active layer (numbers, strings or null). */
export function layerValues(layerId = state.layer, index = state.stepIndex) {
  const p = state.payload;
  if (!p) return [];
  const asms = p.assemblies || [];
  if (layerId === '__fueltype__') return asms.map((a) => a.fuelType);
  if (layerId === '__batch__') return asms.map((a) => a.batch);
  const sp = statePoint(index);
  const arr = sp && sp.values ? sp.values[layerId] : null;
  if (!arr) return asms.map(() => null);
  return asms.map((_, i) => (i < arr.length ? arr[i] : null));
}

/** [min, max] over the finite numeric entries of an array; null when none. */
export function extent(values) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (typeof v !== 'number' || !Number.isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return lo === Infinity ? null : [lo, hi];
}

/** Sorted distinct category values for a categorical layer. */
export function categories(values) {
  const seen = new Map();
  for (const v of values) {
    if (v === null || v === undefined) continue;
    seen.set(v, (seen.get(v) || 0) + 1);
  }
  return [...seen.entries()]
    .sort((a, b) => (a[0] > b[0] ? 1 : a[0] < b[0] ? -1 : 0))
    .map(([value, count]) => ({ value, count }));
}

/** "row,col" -> [{group, tag, member}] for every symmetry-group member. */
export function symmetryMap(payload = state.payload) {
  const map = new Map();
  if (!payload) return map;
  for (const g of payload.symmetryGroups || []) {
    for (const m of g.members || []) {
      const key = `${m.row},${m.col}`;
      if (!map.has(key)) map.set(key, []);
      map.get(key).push({ group: g.group, tag: m.tag, member: m, groupRef: g });
    }
  }
  return map;
}

/** Indices of assemblies named in symmetryGroups. */
export function flaggedIndices(payload = state.payload) {
  const out = new Set();
  if (!payload) return out;
  const idx = payload.assemblyIndex || {};
  for (const g of payload.symmetryGroups || []) {
    for (const m of g.members || []) {
      const i = idx[`${m.row},${m.col}`];
      if (i !== undefined) out.add(i);
    }
  }
  return out;
}

/** Filter predicate for the core map: dim anything that fails. */
export function visibilityMask(payload = state.payload) {
  const asms = (payload && payload.assemblies) || [];
  const flagged = state.flaggedOnly ? flaggedIndices(payload) : null;
  const fuelOn = state.fuelFilter.size > 0;
  const batchOn = state.batchFilter.size > 0;
  return asms.map((a, i) => {
    if (flagged && !flagged.has(i)) return false;
    if (fuelOn && !state.fuelFilter.has(String(a.fuelType))) return false;
    if (batchOn && !state.batchFilter.has(String(a.batch))) return false;
    return true;
  });
}

export function anyFilterActive() {
  return state.flaggedOnly || state.fuelFilter.size > 0 || state.batchFilter.size > 0;
}

/** Grid width: geometry.iafull, with a defensive fall-back to the data. */
export function gridSize(payload = state.payload) {
  const g = (payload && payload.geometry) || {};
  let n = Number(g.iafull);
  if (!Number.isFinite(n) || n <= 0) {
    n = 0;
    for (const a of (payload && payload.assemblies) || []) {
      n = Math.max(n, a.row || 0, a.col || 0);
    }
  }
  return Math.max(1, n | 0);
}

/** Column letters + row labels derived from assemblies[].site ("M-01"). */
export function axisLabels(payload = state.payload) {
  const n = gridSize(payload);
  const cols = new Array(n + 1).fill('');
  const rows = new Array(n + 1).fill('');
  for (const a of (payload && payload.assemblies) || []) {
    const site = typeof a.site === 'string' ? a.site : '';
    const m = site.match(/^\s*([A-Za-z]+)\s*[-_ ]?\s*(\d+)\s*$/);
    if (!m) continue;
    if (a.col >= 1 && a.col <= n && !cols[a.col]) cols[a.col] = m[1].toUpperCase();
    if (a.row >= 1 && a.row <= n && !rows[a.row]) rows[a.row] = String(parseInt(m[2], 10));
  }
  for (let i = 1; i <= n; i += 1) {
    if (!rows[i]) rows[i] = String(i);
    if (!cols[i]) cols[i] = String(i);
  }
  return { cols, rows };
}

/** Axial columns available on this run ([] for 2D listings). */
export function axialColumns(payload = state.payload) {
  for (const sp of (payload && payload.statePoints) || []) {
    const ax = sp.axialState;
    if (ax && Array.isArray(ax.columns) && ax.columns.length && (ax.nodes || []).length) {
      return ax.columns.slice();
    }
  }
  return [];
}

export function axialNodes(index = state.stepIndex) {
  const sp = statePoint(index);
  const ax = sp && sp.axialState;
  return ax && Array.isArray(ax.nodes) ? ax.nodes : [];
}

export function is3d(payload = state.payload) {
  return !!(payload && payload.geometry && payload.geometry.is3d);
}

export function exposureUnit(payload = state.payload) {
  const sp = statePoint();
  if (sp && sp.exposureUnit) return sp.exposureUnit;
  return (payload && payload.meta && payload.meta.exposureUnit) || '';
}

/* ------------------------------------------------------------ number helpers */

/** Fixed-decimal formatting.
 *
 * Deliberately does NOT strip trailing zeros. The previous implementation
 * stripped them only when the whole fractional part was zero, which printed
 * "0.4300" and "1" from the same call — ragged precision in one sentence.
 * An engineering read-out keeps the decimals it asked for. */
export function fmt(value, digits = 3) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string') return value;
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const a = Math.abs(value);
  if (a !== 0 && (a < 1e-3 || a >= 1e6)) return value.toExponential(2);
  return value.toFixed(digits);
}

/** One decimal count for a whole layer, so every cell in it lines up.
 *  Driven by the magnitude of the layer's extent, not by each value. */
export function layerPrecision(values, tight = false) {
  const ex = extent(values);
  if (!ex) return 3;
  const mag = Math.max(Math.abs(ex[0]), Math.abs(ex[1]));
  const base = mag >= 1000 ? 0 : mag >= 100 ? 1 : mag >= 10 ? 2 : 3;
  return tight ? Math.max(0, base - 1) : base;
}

/** True when the reader has asked the OS for less animation. */
export function reducedMotion() {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** scrollIntoView that honours prefers-reduced-motion. */
export function scrollTo(el, block = 'nearest') {
  if (!el) return;
  el.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block });
}

export function fmtFixed(value, digits = 3) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return value.toFixed(digits);
}

export function titleCase(s) {
  if (!s) return '';
  return String(s).charAt(0).toUpperCase() + String(s).slice(1);
}

/** Escape for safe interpolation into innerHTML. */
export function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
