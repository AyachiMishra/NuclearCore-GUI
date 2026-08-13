/* coremap.js — hand-built SVG core map.
 *
 * The grid is sized from geometry.iafull; row/column headers come from
 * assemblies[].site. Fill comes from the active layer through either a
 * perceptually-ordered sequential ramp or a categorical palette.
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
  layerPrecision,
  esc,
  fmt,
} from './state.js';

/* -------------------------------------------------------------- colour ramp */

/* Sequential ramp: LIGHT = LOW value, DARK = HIGH value, so a higher magnitude
 * always carries more visual weight and the map reads the same way as the
 * standalone HTML report (report.py uses the same hue spine).
 *
 * Both sets were generated in OKLCH from that spine and verified:
 *   - monotonic in OKLab lightness (so "darker" is never ambiguous)
 *   - monotonic in printed greyscale — min adjacent step 19.4/255 (light),
 *     14.5/255 (dark), so the map survives a mono printer
 *   - ordering preserved under protanopia, deuteranopia and tritanopia
 *     (Machado-Oliveira-Fernandes 2009, severity 1.0)
 *
 * The dark set is re-anchored in lightness (L 0.905 -> 0.470) rather than
 * reused: the light set's darkest step sits at 1.57:1 against the dark panel,
 * i.e. invisible. Re-anchored it is 2.42:1 and still clearly a filled cell.
 */
const RAMP_LIGHT = [
  [247, 244, 236], [236, 218, 181], [225, 190, 129], [216, 160, 89], [204, 129, 67],
  [187, 100, 50], [162, 76, 44], [133, 58, 44], [100, 45, 39],
];
const RAMP_DARK = [
  [226, 223, 216], [221, 204, 170], [216, 184, 126], [213, 160, 93], [208, 135, 78],
  [197, 113, 67], [179, 96, 65], [156, 82, 67], [129, 73, 66],
];

/** True when the document is actually painting the dark token set. */
export function isDarkTheme() {
  const forced = document.documentElement.getAttribute('data-theme');
  if (forced === 'dark') return true;
  if (forced === 'light') return false;
  return typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches;
}

/** Sequential fill. t = 0 is the low end (light), t = 1 the high end (dark). */
export function sequential(t) {
  const ramp = isDarkTheme() ? RAMP_DARK : RAMP_LIGHT;
  const x = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0));
  const pos = x * (ramp.length - 1);
  const i = Math.min(ramp.length - 2, Math.floor(pos));
  const f = pos - i;
  const a = ramp[i];
  const b = ramp[i + 1];
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

function relLuminance(color) {
  const [r, g, b] = rgbParts(color);
  const lin = (c) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

/* Data tiles carry maximal-contrast ink. Picking whichever of the two actually
 * contrasts more is the only correct rule — a fixed luminance threshold puts
 * the crossover in the wrong place. (The previous threshold of 0.42 was more
 * than twice the correct crossover of 0.188 for its ink pair, which dropped
 * mid-ramp labels to 2.1:1.) Choosing best-of-two over pure black/white gives a
 * worst case of 4.98:1 on the light ramp, 4.67:1 on the dark ramp and 4.85:1 on
 * the categorical palette — AA on every step of every scale. */
const INK_DARK = '#000000';
const INK_LIGHT = '#ffffff';

export function textOn(color) {
  const L = relLuminance(color);
  const onDark = (L + 0.05) / 0.05; // contrast with pure black
  const onLight = 1.05 / (L + 0.05); // contrast with pure white
  return onDark >= onLight ? INK_DARK : INK_LIGHT;
}

/* --------------------------------------------------------------- formatting */

function cellText(v, digits) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'string') return v;
  if (!Number.isFinite(v)) return '';
  return v.toFixed(digits);
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
    digits: layerPrecision(values),
    fill: (v) => (typeof v === 'number' && Number.isFinite(v) ? sequential((v - lo) / span) : null),
    legend: { kind: 'sequential', domain: [lo, hi] },
  };
}

/* -------------------------------------------------------------------- render */

const CELL = 100;
const PAD = 4;
const HEAD_W = 62;
const HEAD_H = 54;

/* How big is one cell on screen?
 *
 * The map keeps its aspect ratio, so whichever of the two axes runs out first
 * decides the scale. Width alone was enough while the card's height was always
 * whatever the map needed — now that a card can be dragged short, a wide-but-
 * squat box would otherwise be told it had room for text it cannot show.
 * Height is only consulted when the host actually has one to give. */
function cellPixels(host, w, h) {
  const boxW = (host && host.clientWidth) || 640;
  const boxH = (host && host.clientHeight) || 0;
  const scale = boxH > 0 ? Math.min(boxW / w, boxH / h) : boxW / w;
  return scale * CELL;
}

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

  /* How much text fits in a cell at this size? The site label is the survivor:
   * it identifies the position, and the value is still one hover (or the
   * inspector) away. Below ~15 px a cell is a pure colour field and any glyph
   * would be noise. */
  const pxCell = cellPixels(hostEl, W, H);
  const showLabel = pxCell >= 15;
  const showValue = pxCell >= 26;
  // Tighter decimals on small cells so "1.23" fits where "1.234" would not.
  const digits = scale.digits === undefined ? 3 : (pxCell < 34 ? Math.max(0, scale.digits - 1) : scale.digits);

  // Hatching every symmetry-expanded position stripes three quarters of a
  // quarter-core map. Mark the minority instead: whichever set is smaller is
  // the one worth finding.
  const nExpanded = asms.reduce((a, x) => a + (x.printed === false ? 1 : 0), 0);
  const markExpanded = nExpanded > 0 && nExpanded <= asms.length / 2;
  const markCalculated = nExpanded > asms.length / 2;

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
      const fg = fill ? textOn(fill) : 'var(--text)';
      const label = a.site || a.label || a.serial || '';
      const valueStr =
        layer && layer.kind === 'category'
          ? cellText(v, 0)
          : cellText(v, digits);

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
      if (markExpanded && a.printed === false) {
        parts.push(
          `<rect class="cell-hatch" x="${x + PAD}" y="${y + PAD}" width="${CELL - 2 * PAD}" ` +
            `height="${CELL - 2 * PAD}" rx="5" fill="url(#s3-hatch)" style="color:${fg}"/>`
        );
      }
      if (markCalculated && a.printed !== false) {
        parts.push(
          `<rect class="cell-calc" x="${x + PAD + 3}" y="${y + PAD + 3}" ` +
            `width="${CELL - 2 * PAD - 6}" height="${CELL - 2 * PAD - 6}" rx="3" style="color:${fg}"/>`
        );
      }
      if (flagged) {
        // Outlined in the cell's own ink so it stays visible on the dark end
        // of the ramp, where a bare --err triangle drops to 1.6:1.
        parts.push(
          `<path class="cell-flag" stroke="${fg}" d="M${x + CELL - PAD - 30} ${y + PAD}h30v30z"/>`
        );
      }
      const twoLine = showValue && valueStr && showLabel && label;
      if (showLabel && label) {
        parts.push(
          `<text class="cell-label${twoLine ? '' : ' is-solo'}" x="${x + CELL / 2}" ` +
            `y="${twoLine ? y + 42 : y + 60}" text-anchor="middle" fill="${fg}">${esc(label)}</text>`
        );
      }
      if (showValue && valueStr) {
        parts.push(
          `<text class="cell-value" x="${x + CELL / 2}" y="${twoLine ? y + 76 : y + 60}" ` +
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

  // All-rods-out is the common case in these listings, and tiling the word
  // "OUT" across 225 identical cells is a screenful of no information. Show
  // the drive LAYOUT compactly instead, and let the banner carry the state.
  if (sum.aro) {
    renderAroSchematic(layer, sum, rMin, rMax, cMin, cMax);
    return;
  }

  const W = HEAD_W + nC * CELL + PAD;
  const H = HEAD_H + nR * CELL + PAD;
  const pxCell = cellPixels(hostEl, W, H);
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
      // Inverted on purpose: the plotted number is the WITHDRAWAL position, so
      // a smaller number is a more deeply inserted rod. Darker still means
      // "more" — more insertion, which is the physically significant end.
      const fill = isIn ? sequential(1 - (steps - lo) / (hi - lo || 1)) : null;
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
  legendEl.innerHTML =
    `<div class="legend-title">${esc(layer.label)} <span class="legend-unit">drive positions</span></div>` +
    `<div class="legend-bar" style="background:linear-gradient(90deg,${sequential(1)},${sequential(0)})"></div>` +
    `<div class="legend-scale"><span>${esc(fmt(lo, 2))} steps — deepest insertion</span>` +
    `<span>${esc(fmt(hi, 2))} steps — fully out</span></div>` +
    `<div class="legend-swatches"><span class="swatch"><i class="swatch-out"></i>OUT — fully withdrawn</span>` +
    `<span class="swatch"><i style="background:${sequential(0.72)}"></i>inserted · cell value = withdrawal steps</span>` +
    `</div>` +
    crdFoot(cr, sum);
}

function crdFoot(cr, sum) {
  const bits = [];
  if (Number.isFinite(cr.fullWithdrawalSteps)) {
    bits.push(`full withdrawal = ${fmt(cr.fullWithdrawalSteps, 2)} steps`);
  }
  if (Number.isFinite(cr.totalWithdrawn)) bits.push(`total withdrawn ${cr.totalWithdrawn} steps`);
  return (
    `<div class="legend-foot">${esc(sum.label)}${bits.length ? ` · ${esc(bits.join(' · '))}` : ''}` +
    (cr.note ? `<div class="legend-note">${esc(cr.note)}</div>` : '') +
    `</div>`
  );
}

/** All-rods-out: a compact map of WHERE the drives are, not 225 "OUT" tiles. */
function renderAroSchematic(layer, sum, rMin, rMax, cMin, cMax) {
  const cr = sum.cr;
  const out = new Set(sum.withdrawn.map((d) => `${d.row},${d.col}`));
  const nR = rMax - rMin + 1;
  const nC = cMax - cMin + 1;
  const S = 22; // schematic pitch, user units
  const W = nC * S + 8;
  const H = nR * S + 8;

  const dots = [];
  for (let r = rMin; r <= rMax; r += 1) {
    for (let c = cMin; c <= cMax; c += 1) {
      const cx = 4 + (c - cMin) * S + S / 2;
      const cy = 4 + (r - rMin) * S + S / 2;
      if (out.has(`${r},${c}`)) {
        dots.push(`<circle class="crd-dot" cx="${cx}" cy="${cy}" r="${S * 0.3}"/>`);
      } else {
        dots.push(`<circle class="crd-dot is-none" cx="${cx}" cy="${cy}" r="${S * 0.12}"/>`);
      }
    }
  }

  hostEl.innerHTML =
    `<div class="aro-block">` +
    `<div class="crd-banner"><span class="crd-aro">ARO</span>` +
    `<span>All rods withdrawn — every one of the ${sum.withdrawn.length} drive positions ` +
    `is fully out at this state point. No rod is inserted, so there is no insertion ` +
    `pattern to map.</span></div>` +
    `<svg class="crd-schematic" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" ` +
    `role="img" aria-label="Control rod drive layout, ${nR} by ${nC}, ` +
    `${sum.withdrawn.length} drive positions, all fully withdrawn">` +
    `<title>Control-rod drive layout — all ${sum.withdrawn.length} positions withdrawn</title>` +
    dots.join('') +
    `</svg>` +
    `<div class="aro-cap">Drive layout · ${nR}×${nC} grid · filled marks are drive ` +
    `positions. Control-rod coordinates are their own grid — they do not align ` +
    `with the assembly map.</div>` +
    `</div>`;

  if (legendEl) {
    legendEl.innerHTML =
      `<div class="legend-title">${esc(layer.label)} <span class="legend-unit">drive positions</span></div>` +
      crdFoot(cr, sum);
  }
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
    for (let i = 0; i <= 10; i += 1) stops.push(`${sequential(i / 10)} ${i * 10}%`);
    const mid = (lo + hi) / 2;
    const d = scale.digits === undefined ? 3 : scale.digits;
    legendEl.innerHTML =
      `<div class="legend-title">${esc(layer.label)}${unit}` +
      `<span class="legend-dir">light = low · dark = high</span></div>` +
      `<div class="legend-bar" style="background:linear-gradient(90deg,${stops.join(',')})"></div>` +
      `<div class="legend-scale"><span>${esc(fmt(lo, d))}</span><span>${esc(fmt(mid, d))}</span>` +
      `<span>${esc(fmt(hi, d))}</span></div>` +
      `<div class="legend-foot">Observed range across ${withData} of ${values.length} positions` +
      `${layer.basis ? ` · ${esc(layer.basis)}` : ''}` +
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
  const asms = p.assemblies || [];
  const nExpanded = asms.reduce((a, x) => a + (x.printed === false ? 1 : 0), 0);
  const hasFlags = (p.symmetryGroups || []).length > 0;
  const bits = [];
  if (hasFlags) bits.push('<span class="mark mark-flag"></span>symmetry-flagged');
  if (nExpanded > 0 && nExpanded <= asms.length / 2) {
    bits.push(`<span class="mark mark-hatch"></span>${nExpanded} symmetry-expanded (not printed)`);
  } else if (nExpanded > asms.length / 2) {
    bits.push(
      `<span class="mark mark-calc"></span>${asms.length - nExpanded} printed — the calculated ` +
        `quadrant; the rest is symmetry expansion`
    );
  }
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

/** Compact hover card.
 *
 * A hover card answers "what am I pointing at?" in one glance. The full
 * breakdown — every code at this step, the symmetry group, the type record —
 * is what click-to-select already puts in the Inspector, so repeating it here
 * only produced a 350 px wall that covered the map it described. */
export function tooltipHtml(idx) {
  const p = state.payload;
  const a = p.assemblies[idx];
  if (!a) return '';
  const sp = statePoint();
  const sym = symmetryMap(p).get(`${a.row},${a.col}`) || [];
  const layer = currentLayer();

  const invRow = inventoryByType(p).get(a.fuelType) || null;
  const enrich =
    a.enrichment !== null && a.enrichment !== undefined
      ? a.enrichment
      : invRow && Number.isFinite(invRow.enrichment)
      ? invRow.enrichment
      : null;

  // The active layer's reading, given the headline slot.
  let lead = '';
  if (layer && sp) {
    const v = layer.kind === 'category'
      ? (layer.id === '__fueltype__' ? a.fuelType : a.batch)
      : ((sp.values || {})[layer.id] || [])[idx];
    const shown =
      v === null || v === undefined
        ? '—'
        : typeof v === 'string'
        ? v
        : fmt(v, layer.kind === 'category' ? 0 : 4);
    lead =
      `<div class="tt-lead"><span class="tt-lead-v">${esc(shown)}</span>` +
      `<span class="tt-lead-k">${esc(layer.label)}${layer.unit ? ` (${esc(layer.unit)})` : ''}` +
      `${sp ? ` · step ${sp.step}` : ''}</span></div>`;
  }

  const idRows = [
    ['Position', `row ${a.row}, col ${a.col}`],
    ['Type', a.fuelType === null || a.fuelType === undefined
      ? null
      : `${a.fuelType}${typeName(a.fuelType, p) ? ` · ${typeName(a.fuelType, p)}` : ''}`],
    ['Batch', a.batch],
    ['Enrichment', enrich === null ? null : `${fmt(enrich, 3)} w/o`],
    ['BP rods', a.bpRods],
  ]
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`)
    .join('');

  const notes = [];
  if (a.printed === false) notes.push('Symmetry expansion — not printed in the listing.');
  for (const s of sym) {
    notes.push(`Symmetry group <b>${esc(s.group)}</b> (${esc(s.tag)}) fails the check.`);
  }

  return (
    `<div class="tt-head">${esc(a.site || a.label || `(${a.row}, ${a.col})`)}` +
    `<span class="tt-sub">${esc(a.serial || '')}</span></div>` +
    lead +
    `<table class="tt-table">${idRows}</table>` +
    (notes.length ? `<div class="tt-notes">${notes.map((n) => `<div>${n}</div>`).join('')}</div>` : '') +
    `<div class="tt-hint">Click for the full record</div>`
  );
}

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
