/* coremap.js — hand-built SVG core map.
 *
 * The grid is sized from geometry.iafull; row/column headers come from
 * assemblies[].site. Fill comes from the active layer through either a
 * perceptually-ordered sequential ramp (viridis — colour-vision-deficiency
 * safe, no red/green pairing) or a categorical palette.
 *
 * Accessibility: role=grid / row / gridcell with a roving tabindex, arrow-key
 * navigation, Enter/Space to select, and a tooltip that also opens on focus.
 */

import {
  state,
  update,
  currentLayer,
  layerValues,
  statePoint,
  extent,
  categories,
  symmetryMap,
  visibilityMask,
  gridSize,
  axisLabels,
  controlRodSummary,
  inventoryByType,
  typeName,
  esc,
  fmt,
} from './state.js';

/* -------------------------------------------------------------- colour ramp */

// viridis anchors (perceptually uniform, monotonic in lightness)
const VIRIDIS = [
  [68, 1, 84], [72, 40, 120], [62, 74, 137], [49, 104, 142], [38, 130, 142],
  [31, 158, 137], [53, 183, 121], [109, 205, 89], [180, 222, 44], [253, 231, 37],
];

export function viridis(t) {
  const x = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0));
  const pos = x * (VIRIDIS.length - 1);
  const i = Math.min(VIRIDIS.length - 2, Math.floor(pos));
  const f = pos - i;
  const a = VIRIDIS[i];
  const b = VIRIDIS[i + 1];
  const c = [0, 1, 2].map((k) => Math.round(a[k] + (b[k] - a[k]) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

// Categorical palette: Okabe–Ito core (CVD-safe) extended with distinct hues.
const CATEGORICAL = [
  '#0072b2', '#e69f00', '#009e73', '#cc79a7', '#56b4e9', '#d55e00', '#8c6bb1',
  '#b8a600', '#1b7837', '#8c510a', '#4a7fb5', '#c994c7', '#3f8f8f', '#a35a00',
  '#5d6d7e', '#7f3b8c', '#00857c', '#b35a5a', '#4d4d4d', '#9a8c00',
];

export function categoricalColor(i) {
  return CATEGORICAL[((i % CATEGORICAL.length) + CATEGORICAL.length) % CATEGORICAL.length];
}

function rgbParts(color) {
  const m = color.match(/rgb\((\d+),(\d+),(\d+)\)/);
  if (m) return [+m[1], +m[2], +m[3]];
  const h = color.replace('#', '');
  if (h.length === 6) {
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }
  return [128, 128, 128];
}

/** Pick near-black or near-white text for legibility on `color`. */
export function textOn(color) {
  const [r, g, b] = rgbParts(color);
  const lin = (c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const L = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return L > 0.42 ? '#10161d' : '#f4f8fb';
}

/* --------------------------------------------------------------- formatting */

function cellNumber(v) {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '';
  const a = Math.abs(v);
  if (a >= 1000) return v.toFixed(0);
  if (a >= 100) return v.toFixed(1);
  if (a >= 10) return v.toFixed(2);
  return v.toFixed(3);
}

function cellText(v, asInteger = false) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'string') return v;
  if (asInteger) return Number.isFinite(v) ? String(Math.round(v)) : '';
  return cellNumber(v);
}

/* ------------------------------------------------------------------ palette */

/** Build a fill(index) function + legend descriptor for the active layer. */
export function buildScale(layer, values) {
  if (!layer) return { kind: 'none', fill: () => 'var(--cell-empty)', legend: null };

  if (layer.kind === 'category') {
    const cats = categories(values);
    const order = new Map(cats.map((c, i) => [String(c.value), i]));
    return {
      kind: 'category',
      cats,
      fill: (v) => (v === null || v === undefined ? null : categoricalColor(order.get(String(v)) || 0)),
      legend: { kind: 'category', cats, order },
    };
  }

  if (layer.kind === 'text') {
    return { kind: 'text', fill: () => null, legend: { kind: 'text' } };
  }

  const ex = extent(values);
  if (!ex) return { kind: 'none', fill: () => null, legend: null };
  const [lo, hi] = ex;
  const span = hi - lo || 1;
  return {
    kind: 'sequential',
    domain: [lo, hi],
    fill: (v) => (typeof v === 'number' && Number.isFinite(v) ? viridis((v - lo) / span) : null),
    legend: { kind: 'sequential', domain: [lo, hi] },
  };
}

/* -------------------------------------------------------------------- render */

const CELL = 100;
const PAD = 4;
const HEAD_W = 62;
const HEAD_H = 54;

let hostEl = null;
let legendEl = null;
let tooltipEl = null;
let resizeObserver = null;
let cellByRC = new Map();

export function initCoreMap(host, legendHost, tooltip) {
  hostEl = host;
  legendEl = legendHost;
  tooltipEl = tooltip;

  host.addEventListener('click', onClick);
  host.addEventListener('keydown', onKeyDown);
  host.addEventListener('mouseover', onOver);
  host.addEventListener('mousemove', onMove);
  host.addEventListener('mouseout', onOut);
  host.addEventListener('focusin', onFocusIn);
  host.addEventListener('focusout', hideTooltip);

  if ('ResizeObserver' in window) {
    let raf = 0;
    resizeObserver = new ResizeObserver(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => renderCoreMap());
    });
    resizeObserver.observe(host);
  }
}

export function renderCoreMap() {
  if (!hostEl) return;
  const p = state.payload;
  if (!p) {
    hostEl.innerHTML = '';
    if (legendEl) legendEl.innerHTML = '';
    return;
  }

  const layerNow = currentLayer();
  if (layerNow && layerNow.kind === 'crd') {
    renderCrdMap(layerNow);
    return;
  }

  const n = gridSize(p);
  const { cols, rows } = axisLabels(p);
  const layer = layerNow;
  const values = layerValues();
  const scale = buildScale(layer, values);
  const sym = symmetryMap(p);
  const mask = visibilityMask(p);
  const asms = p.assemblies || [];
  const index = p.assemblyIndex || {};

  cellByRC = new Map();
  for (const [key, i] of Object.entries(index)) cellByRC.set(key, i);

  const W = HEAD_W + n * CELL + PAD;
  const H = HEAD_H + n * CELL + PAD;

  // How big is one cell on screen? Drives text visibility.
  const boxW = hostEl.clientWidth || 720;
  const pxCell = (boxW / W) * CELL;
  const showValue = pxCell >= 25;
  const showLabel = pxCell >= 40;

  const active = pickActive(asms, mask);
  const parts = [];

  parts.push(
    `<svg class="coremap-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" ` +
      `role="grid" aria-label="Core map, ${n} by ${n} lattice, layer ${esc(layer ? layer.label : 'none')}" ` +
      `aria-rowcount="${n}" aria-colcount="${n}">`
  );
  parts.push(
    `<defs><pattern id="s3-hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">` +
      `<line x1="0" y1="0" x2="0" y2="10" stroke="currentColor" stroke-width="3" opacity="0.30"/></pattern></defs>`
  );

  // column headers
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
      const i = cellByRC.get(`${r},${c}`);

      if (i === undefined) {
        parts.push(
          `<rect class="cell-void" x="${x + PAD}" y="${y + PAD}" width="${CELL - 2 * PAD}" ` +
            `height="${CELL - 2 * PAD}" rx="5"/>`
        );
        continue;
      }

      const a = asms[i] || {};
      const v = values[i];
      const fill = scale.fill(v);
      const dimmed = !mask[i];
      const selected = state.selection === i;
      const flagged = sym.has(`${r},${c}`);
      const fillAttr = fill ? `fill="${fill}"` : 'class="no-data"';
      const fg = fill ? textOn(fill) : 'var(--text)';
      const label = a.site || a.label || a.serial || '';
      const valueStr = cellText(v, layer && layer.kind === 'category');

      const cls = [
        'cell',
        dimmed ? 'is-dim' : '',
        selected ? 'is-selected' : '',
        flagged ? 'is-flagged' : '',
      ]
        .filter(Boolean)
        .join(' ');

      const aria = `${label || `row ${r} column ${c}`}, ${layer ? layer.label : 'value'} ${
        valueStr || 'no value'
      }${flagged ? ', symmetry flagged' : ''}`;

      parts.push(
        `<g class="${cls}" role="gridcell" aria-colindex="${c}" data-idx="${i}" ` +
          `tabindex="${i === active ? 0 : -1}" aria-selected="${selected}" aria-label="${esc(aria)}">`
      );
      parts.push(
        `<rect class="cell-bg${fill ? '' : ' no-data'}" x="${x + PAD}" y="${y + PAD}" ` +
          `width="${CELL - 2 * PAD}" height="${CELL - 2 * PAD}" rx="5" ${fill ? `fill="${fill}"` : ''}/>`
      );
      if (a.printed === false) {
        parts.push(
          `<rect class="cell-hatch" x="${x + PAD}" y="${y + PAD}" width="${CELL - 2 * PAD}" ` +
            `height="${CELL - 2 * PAD}" rx="5" fill="url(#s3-hatch)" style="color:${fg}"/>`
        );
      }
      if (flagged) {
        parts.push(
          `<path class="cell-flag" d="M${x + CELL - PAD - 26} ${y + PAD}h26v26z"/>`
        );
      }
      if (showLabel && label) {
        parts.push(
          `<text class="cell-label" x="${x + CELL / 2}" y="${y + 34}" text-anchor="middle" ` +
            `fill="${fg}">${esc(label)}</text>`
        );
      }
      if (showValue && valueStr) {
        parts.push(
          `<text class="cell-value" x="${x + CELL / 2}" y="${showLabel ? y + 70 : y + 58}" ` +
            `text-anchor="middle" fill="${fg}">${esc(valueStr)}</text>`
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
  swapContent(parts.join(''));
  renderLegend(layer, scale, values);
}

/** Replace the map, keeping keyboard focus on the active cell if it had it. */
function swapContent(html) {
  const hadFocus = hostEl.contains(document.activeElement);
  hostEl.innerHTML = html;
  if (hadFocus) {
    const el = hostEl.querySelector('[tabindex="0"]');
    if (el) el.focus({ preventScroll: true });
  }
}

/* ---------------------------------------------------------- control rod map */

/** Control-rod drive map. Its own coordinate space — built from rows/cols,
 *  never from assemblies[]. Withdrawn ≠ inserted-by-0-steps. */
function renderCrdMap(layer) {
  const sum = controlRodSummary();
  if (!sum) {
    hostEl.innerHTML =
      `<div class="empty-note">This state point carries no control-rod map.</div>`;
    if (legendEl) legendEl.innerHTML = '';
    return;
  }

  const cr = sum.cr;
  const rowsArr = cr.rows;
  const colsArr = cr.cols;
  const rMin = Math.min(...rowsArr);
  const rMax = Math.max(...rowsArr);
  const cMin = Math.min(...colsArr);
  const cMax = Math.max(...colsArr);
  const nR = rMax - rMin + 1;
  const nC = cMax - cMin + 1;

  const insMap = new Map();
  for (const d of sum.inserted) insMap.set(`${d.row},${d.col}`, d.steps);
  const outSet = new Set();
  for (const d of sum.withdrawn) outSet.add(`${d.row},${d.col}`);

  const full = Number.isFinite(cr.fullWithdrawalSteps) ? cr.fullWithdrawalSteps : null;
  const insVals = [...insMap.values()].filter((v) => Number.isFinite(v));
  const ex = insVals.length ? extent(insVals) : null;
  const lo = ex ? Math.min(ex[0], 0) : 0;
  const hi = ex ? Math.max(ex[1], full || ex[1]) : full || 1;

  const W = HEAD_W + nC * CELL + PAD;
  const H = HEAD_H + nR * CELL + PAD;
  const pxCell = ((hostEl.clientWidth || 720) / W) * CELL;
  const showText = pxCell >= 25;

  const parts = [];
  parts.push(
    `<svg class="coremap-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" ` +
      `role="grid" aria-label="Control rod drive map, ${nR} by ${nC} drive positions, ${esc(sum.label)}">`
  );

  parts.push('<g class="axis-head" aria-hidden="true">');
  for (let c = cMin; c <= cMax; c += 1) {
    const x = HEAD_W + (c - cMin) * CELL + CELL / 2;
    parts.push(`<text class="head-text" x="${x}" y="${HEAD_H - 16}" text-anchor="middle">${c}</text>`);
  }
  for (let r = rMin; r <= rMax; r += 1) {
    const y = HEAD_H + (r - rMin) * CELL + CELL / 2 + 9;
    parts.push(`<text class="head-text" x="${HEAD_W - 14}" y="${y}" text-anchor="end">${r}</text>`);
  }
  parts.push('</g>');

  let first = true;
  for (let r = rMin; r <= rMax; r += 1) {
    parts.push(`<g role="row" aria-rowindex="${r}">`);
    for (let c = cMin; c <= cMax; c += 1) {
      const x = HEAD_W + (c - cMin) * CELL;
      const y = HEAD_H + (r - rMin) * CELL;
      const key = `${r},${c}`;
      const isIn = insMap.has(key);
      const isOut = outSet.has(key);

      if (!isIn && !isOut) {
        parts.push(
          `<rect class="cell-void" x="${x + PAD}" y="${y + PAD}" width="${CELL - 2 * PAD}" ` +
            `height="${CELL - 2 * PAD}" rx="5"/>`
        );
        continue;
      }

      const steps = isIn ? insMap.get(key) : null;
      const fill = isIn ? viridis(1 - (steps - lo) / (hi - lo || 1)) : null;
      const fg = fill ? textOn(fill) : 'var(--crd-out-text)';
      const label = isIn ? cellNumber(steps) : 'OUT';
      const aria = isIn
        ? `drive ${r}, ${c}, inserted, ${fmt(steps, 3)} steps`
        : `drive ${r}, ${c}, fully withdrawn`;

      parts.push(
        `<g class="cell crd-cell ${isIn ? 'is-in' : 'is-out'}" role="gridcell" aria-colindex="${c}" ` +
          `data-crd="${key}" tabindex="${first ? 0 : -1}" aria-label="${esc(aria)}">`
      );
      first = false;
      parts.push(
        `<rect class="cell-bg${isIn ? '' : ' crd-out'}" x="${x + PAD}" y="${y + PAD}" ` +
          `width="${CELL - 2 * PAD}" height="${CELL - 2 * PAD}" rx="5" ${fill ? `fill="${fill}"` : ''}/>`
      );
      if (showText) {
        parts.push(
          `<text class="cell-value${isIn ? '' : ' crd-out-text'}" x="${x + CELL / 2}" y="${y + 58}" ` +
            `text-anchor="middle" fill="${fg}">${esc(label)}</text>`
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
  swapContent(parts.join(''));

  if (!legendEl) return;
  const bits = [];
  if (full !== null) bits.push(`full withdrawal = ${fmt(full, 2)} steps`);
  if (Number.isFinite(cr.totalWithdrawn)) bits.push(`total withdrawn ${cr.totalWithdrawn} steps`);
  legendEl.innerHTML =
    `<div class="legend-title">${esc(layer.label)} <span class="legend-unit">drive positions</span></div>` +
    (sum.aro
      ? `<div class="crd-banner"><span class="crd-aro">ARO</span>` +
        `<span>All rods withdrawn — every one of the ${sum.withdrawn.length} drive positions is fully out.</span></div>`
      : `<div class="legend-bar" style="background:linear-gradient(90deg,${viridis(1)},${viridis(0)})"></div>` +
        `<div class="legend-scale"><span>${esc(fmt(lo, 3))} steps (in)</span>` +
        `<span>${esc(fmt(hi, 3))} steps (out)</span></div>`) +
    `<div class="legend-swatches"><span class="swatch"><i class="swatch-out"></i>OUT — fully withdrawn</span>` +
    (sum.inserted.length
      ? `<span class="swatch"><i style="background:${viridis(0.35)}"></i>inserted, value = steps</span>`
      : '') +
    `</div>` +
    `<div class="legend-foot">${esc(sum.label)}${bits.length ? ` · ${esc(bits.join(' · '))}` : ''}` +
    (cr.note ? `<div class="legend-note">${esc(cr.note)}</div>` : '') +
    `</div>`;
}

function pickActive(asms, mask) {
  if (state.selection !== null && state.selection !== undefined && asms[state.selection]) {
    return state.selection;
  }
  const first = mask.findIndex(Boolean);
  return first >= 0 ? first : 0;
}

/* -------------------------------------------------------------------- legend */

function renderLegend(layer, scale, values) {
  if (!legendEl) return;
  if (!layer) {
    legendEl.innerHTML = '';
    return;
  }
  const unit = layer.unit ? ` <span class="legend-unit">${esc(layer.unit)}</span>` : '';
  const withData = values.filter((v) => v !== null && v !== undefined).length;

  if (scale.kind === 'sequential') {
    const [lo, hi] = scale.domain;
    const stops = [];
    for (let i = 0; i <= 10; i += 1) stops.push(`${viridis(i / 10)} ${i * 10}%`);
    const mid = (lo + hi) / 2;
    legendEl.innerHTML =
      `<div class="legend-title">${esc(layer.label)}${unit}</div>` +
      `<div class="legend-bar" style="background:linear-gradient(90deg,${stops.join(',')})"></div>` +
      `<div class="legend-scale"><span>${esc(fmt(lo, 4))}</span><span>${esc(fmt(mid, 4))}</span>` +
      `<span>${esc(fmt(hi, 4))}</span></div>` +
      `<div class="legend-foot">${withData} of ${values.length} positions carry a value` +
      legendMarks() +
      `</div>`;
    return;
  }

  if (scale.kind === 'category') {
    const named = layer.id === '__fueltype__';
    const swatches = scale.cats
      .map((c, i) => {
        const nm = named ? typeName(c.value) : null;
        return (
          `<span class="swatch"><i style="background:${categoricalColor(i)}"></i>` +
          `${esc(c.value)}${nm ? ` <span class="muted">${esc(nm)}</span>` : ''} <b>${c.count}</b></span>`
        );
      })
      .join('');
    legendEl.innerHTML =
      `<div class="legend-title">${esc(layer.label)}${unit}</div>` +
      `<div class="legend-swatches">${swatches}</div>` +
      `<div class="legend-foot">${scale.cats.length} distinct values` + legendMarks() + `</div>`;
    return;
  }

  if (scale.kind === 'text') {
    legendEl.innerHTML =
      `<div class="legend-title">${esc(layer.label)}${unit}</div>` +
      `<div class="legend-foot">Text-valued edit — shown as labels, excluded from colour scales.` +
      legendMarks() +
      `</div>`;
    return;
  }

  legendEl.innerHTML =
    `<div class="legend-title">${esc(layer.label)}${unit}</div>` +
    `<div class="legend-foot">No numeric values at this step.` + legendMarks() + `</div>`;
}

function legendMarks() {
  const p = state.payload;
  const hasUnprinted = (p.assemblies || []).some((a) => a.printed === false);
  const hasFlags = (p.symmetryGroups || []).length > 0;
  const bits = [];
  if (hasFlags) bits.push('<span class="mark mark-flag"></span>symmetry-flagged');
  if (hasUnprinted) bits.push('<span class="mark mark-hatch"></span>symmetry-expanded (not printed)');
  return bits.length ? ` <span class="legend-marks">${bits.join('<span class="sep">·</span>')}</span>` : '';
}

/* -------------------------------------------------------------- interaction */

function cellOf(evt) {
  const el = evt.target && evt.target.closest ? evt.target.closest('.cell') : null;
  if (!el) return null;
  if (el.dataset.crd) return { el, idx: null, crd: el.dataset.crd };
  const idx = Number(el.dataset.idx);
  return Number.isFinite(idx) ? { el, idx, crd: null } : null;
}

function onClick(evt) {
  const hit = cellOf(evt);
  if (!hit || hit.idx === null) return;
  update({ selection: hit.idx, tab: 'inspector' }, 'selection', 'tab');
}

function onKeyDown(evt) {
  const hit = cellOf(evt);
  if (!hit || hit.idx === null) return;
  const p = state.payload;
  if (!p) return;
  const a = p.assemblies[hit.idx];
  const n = gridSize(p);

  if (evt.key === 'Enter' || evt.key === ' ' || evt.key === 'Spacebar') {
    evt.preventDefault();
    update({ selection: hit.idx, tab: 'inspector' }, 'selection', 'tab');
    return;
  }

  const steps = {
    ArrowRight: [0, 1], ArrowLeft: [0, -1], ArrowDown: [1, 0], ArrowUp: [-1, 0],
  };
  let target = null;
  if (steps[evt.key]) {
    const [dr, dc] = steps[evt.key];
    let r = a.row;
    let c = a.col;
    for (let k = 0; k < n; k += 1) {
      r += dr;
      c += dc;
      if (r < 1 || c < 1 || r > n || c > n) break;
      const i = cellByRC.get(`${r},${c}`);
      if (i !== undefined) { target = i; break; }
    }
  } else if (evt.key === 'Home' || evt.key === 'End') {
    const order = [];
    for (let c = 1; c <= n; c += 1) {
      const i = cellByRC.get(`${a.row},${c}`);
      if (i !== undefined) order.push(i);
    }
    if (order.length) target = evt.key === 'Home' ? order[0] : order[order.length - 1];
  } else {
    return;
  }

  evt.preventDefault();
  if (target === null) return;
  const el = hostEl.querySelector(`.cell[data-idx="${target}"]`);
  if (el) {
    hit.el.setAttribute('tabindex', '-1');
    el.setAttribute('tabindex', '0');
    el.focus();
  }
}

function onOver(evt) {
  const hit = cellOf(evt);
  if (!hit) { hideTooltip(); return; }
  showTooltip(hit, evt.clientX + 16, evt.clientY + 16);
}

function onMove(evt) {
  if (!tooltipEl || tooltipEl.hidden) return;
  const hit = cellOf(evt);
  if (!hit) { hideTooltip(); return; }
  placeTooltip(evt.clientX + 16, evt.clientY + 16);
}

function onOut(evt) {
  const to = evt.relatedTarget;
  if (to && to.closest && to.closest('.cell')) return;
  hideTooltip();
}

function onFocusIn(evt) {
  const hit = cellOf(evt);
  if (!hit) return;
  const r = hit.el.getBoundingClientRect();
  showTooltip(hit, r.right + 10, r.top);
}

export function hideTooltip() {
  if (!tooltipEl) return;
  tooltipEl.hidden = true;
  tooltipEl.setAttribute('aria-hidden', 'true');
}

function placeTooltip(x, y) {
  const pad = 12;
  const w = tooltipEl.offsetWidth;
  const h = tooltipEl.offsetHeight;
  const left = Math.min(x, window.innerWidth - w - pad);
  const top = Math.min(y, window.innerHeight - h - pad);
  tooltipEl.style.left = `${Math.max(pad, left)}px`;
  tooltipEl.style.top = `${Math.max(pad, top)}px`;
}

function showTooltip(hit, x, y) {
  if (!tooltipEl) return;
  tooltipEl.innerHTML = hit.crd ? crdTooltipHtml(hit.crd) : tooltipHtml(hit.idx);
  tooltipEl.hidden = false;
  tooltipEl.setAttribute('aria-hidden', 'false');
  placeTooltip(x, y);
}

function crdTooltipHtml(key) {
  const sum = controlRodSummary();
  if (!sum) return '';
  const [r, c] = key.split(',').map(Number);
  const ins = sum.inserted.find((d) => d.row === r && d.col === c);
  const cr = sum.cr;
  const rows = [
    ['Drive position', `(${r}, ${c})`],
    ['State', ins ? 'inserted' : 'fully withdrawn (out)'],
    ['Position', ins ? `${fmt(ins.steps, 3)} steps` : '—'],
    ['Full withdrawal', Number.isFinite(cr.fullWithdrawalSteps) ? `${fmt(cr.fullWithdrawalSteps, 2)} steps` : '—'],
  ]
    .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`)
    .join('');
  return (
    `<div class="tt-head">Control rod drive<span class="tt-sub">${esc(key)}</span></div>` +
    `<table class="tt-table">${rows}</table>` +
    `<div class="tt-notes"><div>Control-rod drive coordinates — a separate grid from the assembly map.</div>` +
    (cr.note ? `<div>${esc(cr.note)}</div>` : '') +
    `</div>`
  );
}

/** Full hover card: identity, every value at this step, and diagnostics. */
export function tooltipHtml(idx) {
  const p = state.payload;
  const a = p.assemblies[idx];
  if (!a) return '';
  const sp = statePoint();
  const sym = symmetryMap(p).get(`${a.row},${a.col}`) || [];
  const layer = currentLayer();

  const invRow = inventoryByType(p).get(a.fuelType) || null;
  const idRows = [
    ['Position', `(${a.row}, ${a.col})`],
    ['Site', a.site],
    ['Serial', a.serial],
    ['Label', a.label],
    ['Fuel type', a.fuelType],
    ['Type name', typeName(a.fuelType, p)],
    ['Batch', a.batch],
    [
      'Enrichment',
      a.enrichment !== null && a.enrichment !== undefined
        ? `${fmt(a.enrichment, 3)} w/o`
        : invRow && Number.isFinite(invRow.enrichment)
        ? `${fmt(invRow.enrichment, 3)} w/o`
        : null,
    ],
    ['BP rods', a.bpRods],
    ['Rotation', a.rotation],
  ]
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`)
    .join('');

  let valueRows = '';
  if (sp && sp.values) {
    valueRows = Object.keys(sp.values)
      .map((code) => {
        const arr = sp.values[code] || [];
        const v = idx < arr.length ? arr[idx] : null;
        const on = layer && layer.id === code ? ' class="is-active"' : '';
        return `<tr${on}><th>${esc(code)}</th><td>${v === null || v === undefined ? '—' : esc(
          typeof v === 'string' ? v : fmt(v, 4)
        )}</td></tr>`;
      })
      .join('');
  }

  const notes = [];
  if (a.printed === false) notes.push('Filled by symmetry expansion — not printed in the listing.');
  for (const s of sym) {
    notes.push(`Symmetry group <b>${esc(s.group)}</b> (${esc(s.tag)}) — fails symmetry check.`);
  }

  return (
    `<div class="tt-head">${esc(a.site || a.label || `(${a.row}, ${a.col})`)}` +
    `<span class="tt-sub">${esc(a.serial || '')}</span></div>` +
    `<table class="tt-table">${idRows}</table>` +
    (valueRows
      ? `<div class="tt-sec">Step ${sp.step} values</div><table class="tt-table">${valueRows}</table>`
      : '') +
    (notes.length ? `<div class="tt-notes">${notes.map((n) => `<div>${n}</div>`).join('')}</div>` : '')
  );
}
