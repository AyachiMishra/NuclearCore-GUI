/* charts.js — hand-rolled SVG charts. No plotting library, no network.
 *
 * Every chart is a <figure> holding a responsive <svg role="img"> with
 * <title>/<desc>, a caption that states the reading in words, and a collapsed
 * data table so the figure is usable without seeing it.
 */

import {
  state,
  update,
  statePoint,
  depletionRow,
  currentLayer,
  layerValues,
  axialNodes,
  is3d,
  exposureUnit,
  extent,
  categories,
  controlRodSummary,
  fmt,
  esc,
} from './state.js';
import { viridis, categoricalColor } from './coremap.js';

const W = 660;
const H = 300;
const M = { top: 18, right: 18, bottom: 44, left: 62 };
const PW = W - M.left - M.right;
const PH = H - M.top - M.bottom;

export const DEPLETION_METRICS = [
  { id: 'keff', label: 'k-effective', unit: '', ref: 1.0 },
  { id: 'peakRadial', label: 'Peak radial (Fdh)', unit: '' },
  { id: 'peakNodal', label: 'Peak nodal (Fq)', unit: '' },
  { id: 'peak3pin', label: 'Peak 3-pin', unit: '' },
  { id: 'boron', label: 'Boron', unit: 'ppm' },
  { id: 'axialOffset', label: 'Axial offset', unit: '%' },
];

/* ------------------------------------------------------------------ helpers */

function niceTicks(lo, hi, target = 5) {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0];
  if (hi === lo) return [lo];
  const raw = (hi - lo) / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm >= 7.5 ? 10 : norm >= 3.5 ? 5 : norm >= 1.5 ? 2 : 1) * mag;
  const out = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + step * 1e-9; t += step) {
    out.push(Math.abs(t) < step * 1e-9 ? 0 : t);
  }
  return out.length ? out : [lo, hi];
}

function padDomain(lo, hi) {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
  if (hi === lo) {
    const d = Math.abs(lo) * 0.05 || 0.5;
    return [lo - d, hi + d];
  }
  const pad = (hi - lo) * 0.08;
  return [lo - pad, hi + pad];
}

function figure(id, title, desc, svgBody, caption, tableHtml, extraClass = '') {
  return (
    `<figure class="chart ${extraClass}">` +
    `<svg class="chart-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" ` +
    `role="img" aria-labelledby="${id}-t ${id}-d">` +
    `<title id="${id}-t">${esc(title)}</title><desc id="${id}-d">${esc(desc)}</desc>` +
    svgBody +
    `</svg>` +
    `<figcaption>${caption}</figcaption>` +
    (tableHtml
      ? `<details class="chart-data"><summary>Data table</summary><div class="table-wrap">${tableHtml}</div></details>`
      : '') +
    `</figure>`
  );
}

function emptyFigure(title, message, detail) {
  return (
    `<div class="chart-empty" role="note">` +
    `<div class="chart-empty-mark" aria-hidden="true">◫</div>` +
    `<div class="chart-empty-title">${esc(title)}</div>` +
    `<p>${esc(message)}</p>` +
    (detail ? `<p class="chart-empty-detail">${esc(detail)}</p>` : '') +
    `</div>`
  );
}

function axes(xTicks, yTicks, xScale, yScale, xLabel, yLabel, opts = {}) {
  const out = [];
  out.push(`<g class="grid">`);
  for (const t of yTicks) {
    const y = yScale(t);
    out.push(`<line x1="${M.left}" x2="${M.left + PW}" y1="${y}" y2="${y}"/>`);
  }
  for (const t of xTicks) {
    const x = xScale(t);
    out.push(`<line y1="${M.top}" y2="${M.top + PH}" x1="${x}" x2="${x}"/>`);
  }
  out.push(`</g>`);
  out.push(
    `<g class="axis"><line x1="${M.left}" y1="${M.top}" x2="${M.left}" y2="${M.top + PH}"/>` +
      `<line x1="${M.left}" y1="${M.top + PH}" x2="${M.left + PW}" y2="${M.top + PH}"/></g>`
  );
  out.push('<g class="tick-text">');
  for (const t of yTicks) {
    out.push(
      `<text x="${M.left - 9}" y="${yScale(t) + 4}" text-anchor="end">${esc(
        opts.yFmt ? opts.yFmt(t) : fmt(t, 4)
      )}</text>`
    );
  }
  for (const t of xTicks) {
    out.push(
      `<text x="${xScale(t)}" y="${M.top + PH + 20}" text-anchor="middle">${esc(
        opts.xFmt ? opts.xFmt(t) : fmt(t, 4)
      )}</text>`
    );
  }
  out.push('</g>');
  out.push(
    `<text class="axis-title" x="${M.left + PW / 2}" y="${H - 6}" text-anchor="middle">${esc(xLabel)}</text>`
  );
  out.push(
    `<text class="axis-title" transform="translate(13 ${M.top + PH / 2}) rotate(-90)" ` +
      `text-anchor="middle">${esc(yLabel)}</text>`
  );
  return out.join('');
}

/* -------------------------------------------------------- depletion history */

export function renderDepletionChart(host) {
  const p = state.payload;
  if (!host) return;
  if (!p) { host.innerHTML = ''; return; }

  const rows = Array.isArray(p.depletion) && p.depletion.length ? p.depletion : null;
  if (!rows) {
    host.innerHTML = emptyFigure(
      'No depletion table',
      'This listing has no end-of-run depletion summary table, so the progression chart cannot be drawn.'
    );
    return;
  }

  const metric = DEPLETION_METRICS.find((m) => m.id === state.deplMetric) || DEPLETION_METRICS[0];
  const unit = exposureUnit(p);
  const pts = rows
    .map((d, i) => ({ i, x: d.cycleExposure, y: d[metric.id], step: d.step, row: d }))
    .filter((d) => Number.isFinite(d.x) && Number.isFinite(d.y));

  if (!pts.length) {
    host.innerHTML = emptyFigure(
      'No data for this variable',
      `The depletion table has no ${metric.label} column in this listing.`
    );
    return;
  }

  const xe = extent(pts.map((d) => d.x));
  const ye0 = extent(pts.map((d) => d.y));
  const yVals = ye0.slice();
  if (metric.ref !== undefined) {
    yVals[0] = Math.min(yVals[0], metric.ref);
    yVals[1] = Math.max(yVals[1], metric.ref);
  }
  const [x0, x1] = padDomain(xe[0], xe[1]);
  const [y0, y1] = padDomain(yVals[0], yVals[1]);
  const xScale = (v) => M.left + ((v - x0) / (x1 - x0 || 1)) * PW;
  const yScale = (v) => M.top + PH - ((v - y0) / (y1 - y0 || 1)) * PH;

  const body = [];
  body.push(
    axes(niceTicks(x0, x1, 6), niceTicks(y0, y1, 5), xScale, yScale,
      `Cycle exposure${unit ? ` (${unit})` : ''}`, `${metric.label}${metric.unit ? ` (${metric.unit})` : ''}`)
  );

  if (metric.ref !== undefined && metric.ref >= y0 && metric.ref <= y1) {
    const yr = yScale(metric.ref);
    body.push(`<line class="ref-line" x1="${M.left}" x2="${M.left + PW}" y1="${yr}" y2="${yr}"/>`);
    body.push(
      `<text class="ref-text" x="${M.left + PW - 4}" y="${yr - 6}" text-anchor="end">k = ${metric.ref.toFixed(1)}</text>`
    );
  }

  const path = pts.map((d, i) => `${i ? 'L' : 'M'}${xScale(d.x).toFixed(2)} ${yScale(d.y).toFixed(2)}`).join(' ');
  body.push(`<path class="series-line" d="${path}"/>`);

  const cur = statePoint();
  for (const d of pts) {
    const isCur = cur && d.row.step === cur.step && d.row.case === cur.case;
    body.push(
      `<circle class="series-dot${isCur ? ' is-current' : ''}" cx="${xScale(d.x).toFixed(2)}" ` +
        `cy="${yScale(d.y).toFixed(2)}" r="${isCur ? 6.5 : 3.6}" data-step-index="${d.i}">` +
        `<title>Step ${d.row.step} — ${fmt(d.x, 4)} ${unit}, ${metric.label} ${fmt(d.y, 5)}</title></circle>`
    );
    if (isCur) {
      body.push(
        `<line class="cursor-line" x1="${xScale(d.x).toFixed(2)}" x2="${xScale(d.x).toFixed(2)}" ` +
          `y1="${M.top}" y2="${M.top + PH}"/>`
      );
    }
  }

  const curRow = depletionRow();
  const caption =
    `${esc(metric.label)} across ${pts.length} state points, ` +
    `${esc(fmt(xe[0], 4))}–${esc(fmt(xe[1], 4))} ${esc(unit)}. ` +
    `Range ${esc(fmt(ye0[0], 5))} to ${esc(fmt(ye0[1], 5))}. ` +
    (curRow
      ? `Current step ${curRow.step}: <b>${esc(fmt(curRow[metric.id], 5))}</b>.`
      : '') +
    ` Click a point to jump to that step.`;

  const table =
    `<table class="data-table"><caption class="sr-only">Depletion progression</caption><thead><tr>` +
    `<th>Step</th><th>Exposure (${esc(unit)})</th><th>${esc(metric.label)}</th></tr></thead><tbody>` +
    pts
      .map((d) => `<tr><td>${d.row.step}</td><td>${esc(fmt(d.x, 4))}</td><td>${esc(fmt(d.y, 5))}</td></tr>`)
      .join('') +
    `</tbody></table>`;

  host.innerHTML = figure(
    'depl',
    `Depletion progression — ${metric.label} vs cycle exposure`,
    `Line chart. X axis cycle exposure in ${unit || 'unitless'}, from ${fmt(xe[0], 4)} to ${fmt(
      xe[1], 4)}. Y axis ${metric.label} from ${fmt(ye0[0], 5)} to ${fmt(ye0[1], 5)}.`,
    body.join(''),
    caption,
    table
  );
}

/* ------------------------------------------------------------- axial profile */

export function renderAxialChart(host) {
  const p = state.payload;
  if (!host) return;
  if (!p) { host.innerHTML = ''; return; }

  if (!is3d(p)) {
    const g = p.geometry || {};
    host.innerHTML = emptyFigure(
      '2D case — single axial node',
      'This listing was run with one axial fuel node, so there is no axial power shape to plot.',
      `geometry.fuelNodes = ${g.fuelNodes} · kd = ${g.kd} · axialState.nodes is empty for every step.`
    );
    return;
  }

  const nodes = axialNodes();
  if (!nodes.length) {
    host.innerHTML = emptyFigure(
      'No axial edit at this step',
      'The listing is 3D but this state point carries no axial distribution table.'
    );
    return;
  }

  const col = state.axialColumn || 'RPF';
  const vals = nodes.map((nd) => ({ node: nd.node, v: nd[col] })).filter((d) => Number.isFinite(d.v));
  if (!vals.length) {
    host.innerHTML = emptyFigure('No values', `Column ${col} is empty at this state point.`);
    return;
  }

  const sp = statePoint();
  const ave = sp && sp.axialState && sp.axialState.summary && sp.axialState.summary.Ave
    ? sp.axialState.summary.Ave[col]
    : null;

  const xe = extent(vals.map((d) => d.v));
  let [x0, x1] = padDomain(Math.min(xe[0], Number.isFinite(ave) ? ave : xe[0]),
                           Math.max(xe[1], Number.isFinite(ave) ? ave : xe[1]));
  if (x0 > 0 && col === 'RPF') x0 = 0;
  const nodeLo = Math.min(...vals.map((d) => d.node));
  const nodeHi = Math.max(...vals.map((d) => d.node));

  const xScale = (v) => M.left + ((v - x0) / (x1 - x0 || 1)) * PW;
  // node 1 at the bottom, top node at the top
  const bandH = PH / (nodeHi - nodeLo + 1);
  const yScale = (n) => M.top + PH - (n - nodeLo + 0.5) * bandH;

  const body = [];
  const yTicks = [];
  for (let n = nodeLo; n <= nodeHi; n += 1) yTicks.push(n);
  body.push(
    axes(niceTicks(x0, x1, 5), yTicks, xScale, yScale, `${esc(col)}`, 'Axial node (bottom → top)', {
      yFmt: (t) => String(t),
    })
  );

  // filled bars for the profile, then a connecting line
  for (const d of vals) {
    const y = yScale(d.node) - bandH * 0.36;
    const w = Math.max(1, xScale(d.v) - xScale(Math.max(x0, 0)));
    const t = (d.v - xe[0]) / (xe[1] - xe[0] || 1);
    const isSel = state.axialNode === d.node;
    body.push(
      `<rect class="axial-bar${isSel ? ' is-current' : ''}" x="${xScale(Math.max(x0, 0)).toFixed(2)}" ` +
        `y="${y.toFixed(2)}" width="${w.toFixed(2)}" height="${(bandH * 0.72).toFixed(2)}" ` +
        `fill="${viridis(t)}" data-node="${d.node}"><title>Node ${d.node}: ${fmt(d.v, 5)}</title></rect>`
    );
  }
  const line = vals
    .slice()
    .sort((a, b) => a.node - b.node)
    .map((d, i) => `${i ? 'L' : 'M'}${xScale(d.v).toFixed(2)} ${yScale(d.node).toFixed(2)}`)
    .join(' ');
  body.push(`<path class="series-line axial-line" d="${line}"/>`);

  if (Number.isFinite(ave)) {
    const xa = xScale(ave);
    body.push(`<line class="ref-line" x1="${xa}" x2="${xa}" y1="${M.top}" y2="${M.top + PH}"/>`);
    body.push(`<text class="ref-text" x="${xa + 5}" y="${M.top + 12}">core ave ${fmt(ave, 4)}</text>`);
  }

  const peak = vals.reduce((a, b) => (b.v > a.v ? b : a), vals[0]);
  const ao = sp && sp.axialState && sp.axialState.summary && sp.axialState.summary['A-O']
    ? sp.axialState.summary['A-O'][col]
    : null;

  const caption =
    `Core-average axial ${esc(col)} over ${vals.length} nodes, drawn bottom to top. ` +
    `Peak ${esc(fmt(peak.v, 5))} at node ${peak.node}` +
    (Number.isFinite(ave) ? `, core average ${esc(fmt(ave, 5))}` : '') +
    (Number.isFinite(ao) ? `, axial offset ${esc(fmt(ao, 4))}` : '') +
    `. Per-assembly axial edits are not present in this listing, so the core average is shown.`;

  const table =
    `<table class="data-table"><thead><tr><th>Node</th><th>${esc(col)}</th></tr></thead><tbody>` +
    vals
      .slice()
      .sort((a, b) => b.node - a.node)
      .map((d) => `<tr><td>${d.node}</td><td>${esc(fmt(d.v, 5))}</td></tr>`)
      .join('') +
    `</tbody></table>`;

  host.innerHTML = figure(
    'axial',
    `Axial ${col} profile`,
    `Horizontal bar profile. ${vals.length} axial nodes from node ${nodeLo} at the bottom to node ${nodeHi} at the top. ` +
      `${col} ranges ${fmt(xe[0], 5)} to ${fmt(xe[1], 5)}, peaking at node ${peak.node}.`,
    body.join(''),
    caption,
    table
  );
}

/* --------------------------------------------------------------- histogram */

export function renderHistogram(host) {
  const p = state.payload;
  if (!host) return;
  if (!p) { host.innerHTML = ''; return; }

  const layer = currentLayer();
  const values = layerValues();
  if (!layer) { host.innerHTML = emptyFigure('No layer', 'Nothing selected.'); return; }

  if (layer.kind === 'crd') {
    const sum = controlRodSummary();
    if (!sum) {
      host.innerHTML = emptyFigure('No control-rod map', 'This state point has no CRD edit.');
      return;
    }
    if (sum.aro) {
      host.innerHTML = emptyFigure(
        'All rods withdrawn (ARO)',
        `Every one of the ${sum.withdrawn.length} control-rod drive positions is fully out at this ` +
          `state point, so there is no insertion distribution to plot.`,
        sum.cr.note || ''
      );
      return;
    }
    return renderCategoryBars(
      host,
      { ...layer, kind: 'value' },
      sum.inserted.map((d) => d.steps)
    );
  }

  if (layer.kind !== 'value') {
    return renderCategoryBars(host, layer, values);
  }

  const nums = values.filter((v) => typeof v === 'number' && Number.isFinite(v));
  if (nums.length < 2) {
    host.innerHTML = emptyFigure(
      'Not enough numeric values',
      `${layer.label} has ${nums.length} numeric value(s) at this step.`
    );
    return;
  }

  const [lo, hi] = extent(nums);
  const nBins = Math.min(20, Math.max(6, Math.round(Math.sqrt(nums.length))));
  const width = (hi - lo) / nBins || 1;
  const bins = new Array(nBins).fill(0);
  for (const v of nums) {
    let b = Math.floor((v - lo) / width);
    if (b >= nBins) b = nBins - 1;
    if (b < 0) b = 0;
    bins[b] += 1;
  }
  const mean = nums.reduce((a, b) => a + b, 0) / nums.length;
  const maxCount = Math.max(...bins);

  const xScale = (v) => M.left + ((v - lo) / (hi - lo || 1)) * PW;
  const yScale = (c) => M.top + PH - (c / (maxCount || 1)) * PH;

  const body = [];
  body.push(
    axes(niceTicks(lo, hi, 5), niceTicks(0, maxCount, 4), xScale, yScale,
      `${layer.label}${layer.unit ? ` (${layer.unit})` : ''}`, 'Assemblies', {
        yFmt: (t) => String(Math.round(t)),
      })
  );

  for (let b = 0; b < nBins; b += 1) {
    if (!bins[b]) continue;
    const x = xScale(lo + b * width);
    const w = Math.max(1, (PW / nBins) - 1.5);
    const y = yScale(bins[b]);
    body.push(
      `<rect class="hist-bar" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${w.toFixed(2)}" ` +
        `height="${(M.top + PH - y).toFixed(2)}" fill="${viridis((b + 0.5) / nBins)}">` +
        `<title>${fmt(lo + b * width, 4)} – ${fmt(lo + (b + 1) * width, 4)}: ${bins[b]} assemblies</title></rect>`
    );
  }

  for (const [value, label, cls] of [[mean, `mean ${fmt(mean, 4)}`, 'stat-mean'], [hi, `max ${fmt(hi, 4)}`, 'stat-max']]) {
    const x = xScale(value);
    body.push(`<line class="stat-line ${cls}" x1="${x}" x2="${x}" y1="${M.top}" y2="${M.top + PH}"/>`);
    body.push(
      `<text class="stat-text" x="${x > M.left + PW * 0.62 ? x - 6 : x + 6}" y="${M.top + 13}" ` +
        `text-anchor="${x > M.left + PW * 0.62 ? 'end' : 'start'}">${esc(label)}</text>`
    );
  }

  const sp = statePoint();
  const caption =
    `Distribution of ${esc(layer.label)} across ${nums.length} assemblies at step ${sp ? sp.step : 0}. ` +
    `Min ${esc(fmt(lo, 4))}, mean ${esc(fmt(mean, 4))}, max ${esc(fmt(hi, 4))}` +
    `${layer.unit ? ` ${esc(layer.unit)}` : ''}, ${nBins} bins.`;

  const table =
    `<table class="data-table"><thead><tr><th>Bin</th><th>Assemblies</th></tr></thead><tbody>` +
    bins
      .map(
        (c, b) =>
          `<tr><td>${esc(fmt(lo + b * width, 4))} – ${esc(fmt(lo + (b + 1) * width, 4))}</td><td>${c}</td></tr>`
      )
      .join('') +
    `</tbody></table>`;

  host.innerHTML = figure(
    'hist',
    `${layer.label} distribution`,
    `Histogram of ${layer.label} over ${nums.length} assemblies. Minimum ${fmt(lo, 4)}, mean ${fmt(
      mean, 4)}, maximum ${fmt(hi, 4)}.`,
    body.join(''),
    caption,
    table
  );
}

function renderCategoryBars(host, layer, values) {
  const cats = categories(values);
  if (!cats.length) {
    host.innerHTML = emptyFigure('No values', `${layer.label} is empty for every assembly.`);
    return;
  }
  const shown = cats.slice(0, 24);
  const maxCount = Math.max(...shown.map((c) => c.count));
  const band = PW / shown.length;
  const yScale = (c) => M.top + PH - (c / (maxCount || 1)) * PH;

  const body = [];
  body.push(`<g class="grid">`);
  for (const t of niceTicks(0, maxCount, 4)) {
    body.push(`<line x1="${M.left}" x2="${M.left + PW}" y1="${yScale(t)}" y2="${yScale(t)}"/>`);
  }
  body.push(`</g>`);
  body.push(
    `<g class="axis"><line x1="${M.left}" y1="${M.top}" x2="${M.left}" y2="${M.top + PH}"/>` +
      `<line x1="${M.left}" y1="${M.top + PH}" x2="${M.left + PW}" y2="${M.top + PH}"/></g>`
  );
  body.push('<g class="tick-text">');
  for (const t of niceTicks(0, maxCount, 4)) {
    body.push(`<text x="${M.left - 9}" y="${yScale(t) + 4}" text-anchor="end">${Math.round(t)}</text>`);
  }
  body.push('</g>');

  shown.forEach((c, i) => {
    const x = M.left + i * band + band * 0.14;
    const w = band * 0.72;
    const y = yScale(c.count);
    const color = layer.kind === 'category' ? categoricalColor(i) : viridis((i + 0.5) / shown.length);
    body.push(
      `<rect class="hist-bar" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${w.toFixed(2)}" ` +
        `height="${(M.top + PH - y).toFixed(2)}" fill="${color}"><title>${esc(c.value)}: ${c.count}</title></rect>`
    );
    body.push(
      `<text class="cat-tick" x="${(x + w / 2).toFixed(2)}" y="${M.top + PH + 17}" text-anchor="middle">${esc(
        c.value
      )}</text>`
    );
    body.push(
      `<text class="bar-count" x="${(x + w / 2).toFixed(2)}" y="${(y - 5).toFixed(2)}" text-anchor="middle">${c.count}</text>`
    );
  });
  body.push(
    `<text class="axis-title" x="${M.left + PW / 2}" y="${H - 6}" text-anchor="middle">${esc(layer.label)}</text>`
  );
  body.push(
    `<text class="axis-title" transform="translate(13 ${M.top + PH / 2}) rotate(-90)" text-anchor="middle">Assemblies</text>`
  );

  const total = cats.reduce((a, c) => a + c.count, 0);
  host.innerHTML = figure(
    'hist',
    `${layer.label} counts`,
    `Bar chart of assembly counts by ${layer.label}. ${cats.length} distinct values over ${total} assemblies.`,
    body.join(''),
    `Assembly count by ${esc(layer.label)} — ${cats.length} distinct value(s) over ${total} assemblies` +
      (cats.length > shown.length ? `, first ${shown.length} shown` : '') +
      `.`,
    `<table class="data-table"><thead><tr><th>${esc(layer.label)}</th><th>Assemblies</th></tr></thead><tbody>` +
      cats.map((c) => `<tr><td>${esc(c.value)}</td><td>${c.count}</td></tr>`).join('') +
      `</tbody></table>`
  );
}

/* -------------------------------------------------- small inline bar chart */

/** Compact horizontal bars used by the inventory panel. */
export function miniBars(rows, opts = {}) {
  if (!rows.length) return '';
  const max = Math.max(...rows.map((r) => r.value)) || 1;
  const rowH = 22;
  const h = rows.length * rowH + 8;
  const labelW = opts.labelWidth || 82;
  const barW = 260;
  const body = rows
    .map((r, i) => {
      const y = 4 + i * rowH;
      const w = (r.value / max) * barW;
      const color = r.color || viridis((i + 0.5) / rows.length);
      return (
        `<text class="mini-label" x="${labelW - 8}" y="${y + 14}" text-anchor="end">${esc(r.label)}</text>` +
        `<rect class="mini-bar" x="${labelW}" y="${y + 3}" width="${Math.max(1, w).toFixed(1)}" height="13" ` +
        `rx="2" fill="${color}"><title>${esc(r.label)}: ${r.value}</title></rect>` +
        `<text class="mini-value" x="${labelW + Math.max(1, w) + 6}" y="${y + 14}">${esc(r.value)}</text>`
      );
    })
    .join('');
  return (
    `<svg class="mini-chart" viewBox="0 0 ${labelW + barW + 48} ${h}" preserveAspectRatio="xMinYMin meet" ` +
    `role="img" aria-label="${esc(opts.title || 'Bar chart')}"><title>${esc(opts.title || 'Bar chart')}</title>` +
    body +
    `</svg>`
  );
}

/* ---------------------------------------------------------------- wiring */

export function initCharts(deplHost, axialHost) {
  if (deplHost) {
    deplHost.addEventListener('click', (evt) => {
      const dot = evt.target.closest && evt.target.closest('[data-step-index]');
      if (!dot) return;
      const di = Number(dot.dataset.stepIndex);
      const p = state.payload;
      if (!p || !Number.isFinite(di)) return;
      const row = p.depletion[di];
      const idx = p.statePoints.findIndex((s) => s.step === row.step && s.case === row.case);
      update({ stepIndex: idx >= 0 ? idx : Math.min(di, p.statePoints.length - 1) }, 'step');
    });
  }
  if (axialHost) {
    axialHost.addEventListener('click', (evt) => {
      const bar = evt.target.closest && evt.target.closest('[data-node]');
      if (!bar) return;
      update({ axialNode: Number(bar.dataset.node) }, 'axial');
    });
  }
}
