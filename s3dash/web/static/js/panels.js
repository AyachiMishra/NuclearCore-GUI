/* panels.js — every non-chart, non-map surface:
 * header metadata strip, assembly inspector, diagnostics, inventory,
 * listing navigator, section viewer, text-hit list and the load panel.
 */

import {
  state,
  update,
  statePoint,
  depletionRow,
  currentLayer,
  controlRodSummary,
  typeInfo,
  inventoryByType,
  typeName,
  symmetryMap,
  gridSize,
  exposureUnit,
  is3d,
  axialNodes,
  fmt,
  fmtFixed,
  esc,
} from './state.js';
import { categoricalColor } from './coremap.js';
import { fetchSection } from './api.js';

const $ = (sel) => document.querySelector(sel);

const SEVERITY_RANK = { ERROR: 0, WARNING: 1, CAUTION: 2, NOTE: 3 };

const FILTER_LABEL = {
  ERROR: 'errors',
  WARNING: 'warnings',
  CAUTION: 'cautions',
  NOTE: 'notes',
  SYMMETRY: 'symmetry violations',
};

/* ------------------------------------------------------------------- header */

export function renderHeader() {
  const p = state.payload;
  const fileEl = $('#hdr-file');
  const strip = $('#meta-strip');
  const badge = $('#status-badge');
  const notes = $('#parse-notes');
  const chip = $('#completion-chip');

  if (!p) {
    fileEl.textContent = 'No listing loaded';
    strip.innerHTML = '';
    badge.hidden = true;
    chip.hidden = true;
    notes.hidden = true;
    return;
  }

  const m = p.meta || {};
  const g = p.geometry || {};
  const s = p.status || {};
  const unit = exposureUnit(p);

  fileEl.textContent = m.fileName || 'listing';
  fileEl.title = m.caseTitle || '';

  const n = gridSize(p);
  const geometrySummary = [
    `${g.reactorType || 'PWR'} · ${n}×${n}`,
    `${g.fraction ? `${g.fraction}-core` : 'core'}${g.symmetry ? ` ${g.symmetry.toLowerCase()}` : ''}`,
    g.is3d ? `3D · ${g.fuelNodes} nodes` : '2D',
  ].join(' · ');

  const t = m.timing || null;
  const exec = [];
  if (t && Number.isFinite(t.cpuSeconds)) exec.push(`${fmt(t.cpuSeconds, 3)} s CPU`);
  if (t && Number.isFinite(t.elapsedSeconds)) exec.push(`${fmt(t.elapsedSeconds, 3)} s elapsed`);
  if (t && Number.isFinite(t.cpuUtilisation)) exec.push(`${fmt(t.cpuUtilisation, 1)} % util`);

  /* Stacked in the left column rather than strung across the header: in the
   * horizontal strip the case title, geometry and timing were all clipped to
   * an ellipsis at 1440 px (needing 434 / 320 / 200 px of 173 px), and below
   * 980 px the strip was hidden outright. Here every value wraps in full. */
  const items = [
    ['Plant', m.plant || m.project || '—'],
    ['Case', m.caseTitle || m.runName || 'untitled case'],
    ['Code', `${m.code || 'SIMULATE-3'} ${m.version || ''}`.trim()],
    ['Run', `${m.runDate || '—'} ${m.runTime ? String(m.runTime).replace(/\.$/, '') : ''}`.trim()],
    ['Geometry', `${geometrySummary} · ${g.nAssemblies ?? '—'} assemblies`],
    [
      'Depletion',
      `${(p.statePoints || []).length} steps · ` +
        (m.cycleStart === null || m.cycleStart === undefined
          ? '—'
          : `${fmt(m.cycleStart, 3)} – ${fmt(m.cycleEnd, 3)} ${unit}`),
    ],
    ['Execution', exec.length ? exec.join(' · ') : `${m.pageCount ?? '—'} pages`],
    ['Listing', `${m.pageCount ?? '—'} pages · ${m.lineCount ?? '—'} lines`],
  ];
  if (m.restartFile) {
    items.push([
      'Restart',
      `${m.restartFile}${Number.isFinite(m.restartExposure) ? ` @ ${fmt(m.restartExposure, 3)} ${unit}` : ''}`,
    ]);
  }

  strip.innerHTML = items
    .map(
      ([k, v]) =>
        `<div class="meta-item"><span class="meta-k">${esc(k)}</span>` +
        `<span class="meta-v">${esc(v)}</span></div>`
    )
    .join('');

  // Termination status: anything but a normal termination means the results
  // may be incomplete, so it is styled as a warning.
  const completion = t && t.completion ? String(t.completion) : null;
  if (completion) {
    const normal = /normal\s+termination/i.test(completion);
    chip.hidden = false;
    chip.className = `completion-chip ${normal ? 'is-normal' : 'is-abnormal'}`;
    chip.innerHTML =
      `<span class="chip-mark" aria-hidden="true">${normal ? '✓' : '⚠'}</span>` +
      `<span>${esc(completion)}</span>`;
    chip.title = normal
      ? 'SIMULATE-3 finished normally.'
      : 'Abnormal termination — results in this listing may be incomplete.';
  } else {
    chip.hidden = false;
    chip.className = 'completion-chip is-unknown';
    chip.innerHTML = `<span class="chip-mark" aria-hidden="true">?</span><span>Termination unknown</span>`;
    chip.title = 'No termination line was found in this listing.';
  }

  renderStatusBadge();

  const pn = p.parseNotes || [];
  if (pn.length) {
    notes.hidden = false;
    notes.innerHTML =
      `<strong>Parse notes</strong> — the listing loaded but ${pn.length} item(s) were skipped: ` +
      `<span>${pn.map((x) => esc(typeof x === 'string' ? x : JSON.stringify(x))).join(' · ')}</span>`;
  } else {
    notes.hidden = true;
    notes.innerHTML = '';
  }
}

/* Header status badge.
 *
 * Every counter on it is a way in, not just a number: clicking one opens the
 * diagnostics panel already narrowed to that severity, and clicking it again
 * clears the filter. Which is why this is a group of buttons rather than the
 * single button it used to be. */
export function renderStatusBadge() {
  const badge = $('#status-badge');
  const p = state.payload;
  if (!badge) return;
  if (!p) { badge.hidden = true; badge.innerHTML = ''; return; }

  const s = p.status || {};
  const level = (s.level || 'OK').toUpperCase();
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
  const full = [
    plural(s.errors || 0, 'error'),
    plural(s.warnings || 0, 'warning'),
    plural(s.cautions || 0, 'caution'),
    plural(s.notes || 0, 'note'),
    plural(s.symmetryViolations || 0, 'symmetry violation'),
  ].join(', ');

  const segs = [
    `<button type="button" class="status-seg status-level" data-diag-filter="" ` +
      `aria-pressed="${state.diagFilter === null}" ` +
      `title="${esc(full)} — open the diagnostics panel unfiltered">` +
      `<span class="status-dot" aria-hidden="true"></span>${esc(level)}</button>`,
  ];

  const counters = [
    ['SYMMETRY', s.symmetryViolations, 'symmetry violation'],
    ['ERROR', s.errors, 'error'],
    ['WARNING', s.warnings, 'warning'],
    ['CAUTION', s.cautions, 'caution'],
    ['NOTE', s.notes, 'note'],
  ].filter(([, n]) => n);
  // The loud two always earn their place; cautions and notes only when nothing
  // louder is present, so the header stays a summary rather than a list.
  const loud = counters.filter(([k]) => k !== 'CAUTION' && k !== 'NOTE');
  for (const [key, n, word] of loud.length ? loud : counters) {
    const on = state.diagFilter === key;
    segs.push(
      `<button type="button" class="status-seg status-count" data-diag-filter="${key}" ` +
        `aria-pressed="${on}" title="Show only the ${esc(plural(n, word))} in the ` +
        `diagnostics panel">${esc(plural(n, word))}</button>`
    );
  }

  badge.hidden = false;
  badge.className = `status-badge level-${level.toLowerCase()}`;
  badge.innerHTML = segs.join('');
  badge.removeAttribute('title');
}

/* ---------------------------------------------------------------- inspector */

export function renderInspector() {
  const host = $('#panel-inspector');
  const p = state.payload;
  if (!p) { host.innerHTML = ''; return; }

  const sp = statePoint();
  const dep = depletionRow();
  const unit = exposureUnit(p);
  const out = [];

  /* --- step summary, always shown ------------------------------------- */
  const stepRows = [
    ['Step', sp ? `${sp.step} (case ${sp.case})` : '—'],
    ['Cycle exposure', sp ? `${fmt(sp.exposure, 4)} ${unit}` : '—'],
    ['Core exposure', sp && sp.coreExposure !== null ? `${fmt(sp.coreExposure, 4)} ${unit}` : '—'],
    ['k-effective', sp ? fmtFixed(sp.keff, 5) : '—'],
    ['Boron', sp && sp.boron !== null ? `${fmt(sp.boron, 2)} ppm` : '—'],
    ['Axial offset', sp && sp.axialOffset !== null ? `${fmt(sp.axialOffset, 3)} %` : '—'],
  ];
  if (dep) {
    stepRows.push(['Peak radial', fmt(dep.peakRadial, 3)]);
    stepRows.push(['Peak nodal', fmt(dep.peakNodal, 3)]);
    stepRows.push(['Peak 3-pin', fmt(dep.peak3pin, 3)]);
  }
  if (is3d(p) && state.axialNode) {
    const nd = axialNodes().find((x) => x.node === state.axialNode);
    if (nd) {
      const cols = Object.keys(nd).filter((k) => k !== 'node');
      stepRows.push([
        `Axial node ${nd.node}`,
        cols.map((c) => `${c} ${fmt(nd[c], 4)}`).join(' · '),
      ]);
    }
  }
  out.push(section('State point', kvTable(stepRows)));

  out.push(outputSummaryBlock(sp));
  out.push(batchEditBlock(sp, p));

  /* --- control rods (own drive grid, not the assembly index space) ------ */
  const crd = controlRodSummary();
  if (crd) {
    const cr = crd.cr;
    const rodRows = [
      ['Pattern', crd.label],
      ['Drive grid', `${cr.rows.length} × ${cr.cols.length} positions`],
      [
        'Full withdrawal',
        Number.isFinite(cr.fullWithdrawalSteps) ? `${fmt(cr.fullWithdrawalSteps, 2)} steps` : '—',
      ],
      ['Total withdrawn', Number.isFinite(cr.totalWithdrawn) ? `${cr.totalWithdrawn} steps` : '—'],
    ];
    let body = kvTable(rodRows);
    if (crd.aro) {
      body =
        `<div class="crd-inline"><span class="crd-aro">ARO</span>` +
        `<span>All ${crd.withdrawn.length} drive positions fully withdrawn.</span></div>` + body;
    } else {
      body +=
        `<div class="table-wrap"><table class="data-table"><thead><tr><th>Drive</th>` +
        `<th class="num">Steps</th></tr></thead><tbody>` +
        crd.inserted
          .map((d) => `<tr><td class="mono">(${d.row}, ${d.col})</td><td class="num">${esc(fmt(d.steps, 2))}</td></tr>`)
          .join('') +
        `</tbody></table></div>`;
    }
    if (cr.note) body += `<p class="sym-msg">${esc(cr.note)}</p>`;
    out.push(section('Control rods', body));
  }

  /* --- selected assembly ---------------------------------------------- */
  const i = state.selection;
  const a = i === null || i === undefined ? null : (p.assemblies || [])[i];

  if (!a) {
    out.push(
      `<div class="empty-note"><strong>No assembly selected.</strong> ` +
        `Click a cell on the core map — or focus it and press Enter — to inspect it.</div>`
    );
    host.innerHTML = out.join('');
    return;
  }

  // Type-level facts. inventory[] is keyed by fuelType, so this lookup is
  // sound — unlike indexing segments[] by fuelType, which is a different
  // namespace.
  const invRow = inventoryByType(p).get(a.fuelType) || null;
  const tRow = typeInfo(p).get(a.fuelType) || null;
  const enrich =
    a.enrichment !== null && a.enrichment !== undefined
      ? `${fmt(a.enrichment, 4)} w/o`
      : invRow && Number.isFinite(invRow.enrichment)
      ? `${fmt(invRow.enrichment, 4)} w/o (type)`
      : null;

  const idRows = [
    ['Site', a.site],
    ['Position', `row ${a.row}, col ${a.col}`],
    ['Serial', a.serial],
    ['Label', a.label],
    ['Fuel type', a.fuelType],
    ['Type name', typeName(a.fuelType, p)],
    ['Segment', invRow && invRow.segment !== null && invRow.segment !== undefined
      ? `${invRow.segment}${invRow.segmentName ? ` · ${invRow.segmentName}` : ''}`
      : null],
    ['Sub-type', a.subType],
    ['Batch', a.batch],
    ['Rotation', a.rotation],
    ['Enrichment', enrich],
    ['BP rods', a.bpRods],
    ['Loading', tRow && Number.isFinite(tRow.loadingGrams) ? `${fmt(tRow.loadingGrams / 1000, 1)} kg` : null],
    ['Previous location', a.previousLocation],
    ['Source', a.printed === false ? 'symmetry expansion (not printed)' : 'printed in listing'],
  ].filter(([, v]) => v !== null && v !== undefined && v !== '');

  out.push(
    section(
      `Assembly ${esc(a.site || a.label || `(${a.row}, ${a.col})`)}`,
      kvTable(idRows),
      a.printed === false ? '<span class="tag tag-hatch">expanded</span>' : ''
    )
  );

  const layer = currentLayer();
  if (sp && sp.values) {
    const rows = Object.keys(sp.values).map((code) => {
      const arr = sp.values[code] || [];
      const v = i < arr.length ? arr[i] : null;
      return [code, v === null || v === undefined ? '—' : typeof v === 'string' ? v : fmt(v, 5), layer && layer.id === code];
    });
    out.push(
      section(
        `Values at step ${sp.step}`,
        `<table class="kv"><tbody>${rows
          .map(
            ([k, v, on]) =>
              `<tr${on ? ' class="is-active"' : ''}><th>${esc(k)}</th><td class="num">${esc(v)}</td></tr>`
          )
          .join('')}</tbody></table>`
      )
    );
  }

  /* --- symmetry group breakdown --------------------------------------- */
  const groups = symmetryMap(p).get(`${a.row},${a.col}`) || [];
  for (const g of groups) {
    out.push(symmetryCard(g.groupRef, `${a.row},${a.col}`));
  }

  host.innerHTML = out.join('');
}

function section(title, body, badge = '') {
  return (
    `<section class="sub"><h3>${title}${badge}</h3>${body}</section>`
  );
}

/** Collapsible section — for reference data that must be reachable without
 *  pushing the reader's actual subject below the fold. */
function foldSection(title, count, body, note = '') {
  return (
    `<details class="sub fold"><summary><span class="fold-title">${esc(title)}</span>` +
    (count === null ? '' : `<span class="pill pill-mini">${esc(count)}</span>`) +
    (note ? `<span class="fold-note">${esc(note)}</span>` : '') +
    `</summary>${body}</details>`
  );
}

/* The Output Summary block: every dot-leader entry SIMULATE prints for the
 * state point, with the unit and the code it uses internally. Roughly 25
 * values per step that the UI previously parsed and then threw away. */
function outputSummaryBlock(sp) {
  const sum = sp && sp.summary ? sp.summary : null;
  const keys = sum ? Object.keys(sum) : [];
  if (!keys.length) {
    return foldSection(
      'Output summary',
      null,
      `<div class="empty-note">This state point printed no Output Summary block.</div>`
    );
  }
  const rows = keys
    .map((k) => {
      const e = sum[k] || {};
      const v = Number.isFinite(e.value) ? fmt(e.value, 4) : e.value === null || e.value === undefined ? '—' : String(e.value);
      return (
        `<tr><th>${esc(k)}${e.code ? `<span class="code-tag">${esc(e.code)}</span>` : ''}</th>` +
        `<td class="num">${esc(v)}</td><td class="unit">${esc(e.unit || '')}</td></tr>`
      );
    })
    .join('');
  return foldSection(
    'Output summary',
    keys.length,
    `<div class="table-wrap"><table class="data-table sum-table">` +
      `<thead><tr><th>Quantity</th><th class="num">Value</th><th>Unit</th></tr></thead>` +
      `<tbody>${rows}</tbody></table></div>`,
    `step ${sp.step}`
  );
}

/* Per-batch edits (BAT.EDT). Absent from runs that never requested them —
 * BEAVRS is one — so the empty state has to say "not in this run", not
 * silently render nothing. */
function batchEditBlock(sp, p) {
  const be = sp && sp.batchEdits ? sp.batchEdits : null;
  const codes = be ? Object.keys(be) : [];
  if (!codes.length) {
    const everHad = (p.statePoints || []).some(
      (s) => s.batchEdits && Object.keys(s.batchEdits).length
    );
    return foldSection(
      'Batch edits',
      null,
      `<div class="empty-note">` +
        (everHad
          ? `No batch edit was printed at this step, though other steps in this run have one.`
          : `<strong>Not present in this run.</strong> This listing contains no ` +
            `<code>BAT.EDT</code> block, so SIMULATE-3 printed no per-batch summary.`) +
        `</div>`
    );
  }
  const blocks = codes
    .map((code) => {
      const rows = (be[code] || [])
        .map(
          (b) =>
            `<tr><td class="mono">${esc(b.batch)}${b.name ? ` · ${esc(b.name)}` : ''}</td>` +
            `<td class="num">${esc(b.assemblies ?? '—')}</td>` +
            `<td class="num">${esc(fmt(b.value, 4))}</td>` +
            `<td class="mono">${esc(b.label || '—')}${b.serial ? `<span class="sub-id">${esc(b.serial)}</span>` : ''}</td>` +
            `<td class="mono">${esc(b.location || '—')}</td></tr>`
        )
        .join('');
      return (
        `<div class="be-block"><div class="be-code">${esc(code)}</div>` +
        `<div class="table-wrap"><table class="data-table"><thead><tr><th>Batch</th>` +
        `<th class="num">Asm</th><th class="num">Value</th><th>Limiting</th><th>Location</th>` +
        `</tr></thead><tbody>${rows}</tbody></table></div></div>`
      );
    })
    .join('');
  return foldSection(
    'Batch edits',
    codes.length,
    blocks + `<p class="foot-note">Value is the batch maximum; <b>Limiting</b> names the ` +
      `assembly that carries it and <b>Location</b> is its (row, col, node).</p>`,
    `step ${sp.step}`
  );
}

function kvTable(rows) {
  return (
    `<table class="kv"><tbody>` +
    rows
      .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v === null || v === undefined ? '—' : v)}</td></tr>`)
      .join('') +
    `</tbody></table>`
  );
}

/** One symmetry group.
 *
 * The point of this card is to answer "which position disagrees, and by how
 * much?" — so each member carries its signed deviation from the group mean and
 * its own 2x2 quadrant spread, and the worst offender is called out by name
 * rather than left for the reader to subtract. */
function symmetryCard(group, hereKey) {
  const members = group.members || [];
  const aves = members.map((m) => m.aveExp).filter((v) => Number.isFinite(v));
  const spread = aves.length ? Math.max(...aves) - Math.min(...aves) : null;
  const mean = aves.length ? aves.reduce((a, b) => a + b, 0) / aves.length : null;
  const types = new Set(members.map((m) => m.fuelType));

  const quadSpread = (m) => {
    const q = Array.isArray(m.quadrantExp) ? m.quadrantExp.filter(Number.isFinite) : [];
    return q.length > 1 ? Math.max(...q) - Math.min(...q) : null;
  };
  const dev = (m) => (mean !== null && Number.isFinite(m.aveExp) ? m.aveExp - mean : null);
  const worst = members.reduce(
    (a, b) => (Math.abs(dev(b) ?? -1) > Math.abs(dev(a) ?? -1) ? b : a),
    members[0] || null
  );

  const rows = members
    .map((m) => {
      const isHere = `${m.row},${m.col}` === hereKey;
      const isWorst = worst && m === worst && members.length > 1 && Math.abs(dev(m) ?? 0) > 0;
      const quads = Array.isArray(m.quadrantExp) ? m.quadrantExp : [];
      const d = dev(m);
      const qs = quadSpread(m);
      return (
        `<tr class="${[isHere ? 'is-here' : '', isWorst ? 'is-worst' : ''].filter(Boolean).join(' ')}">` +
        `<td><button type="button" class="linkish" data-select-rc="${m.row},${m.col}">` +
        `${esc(m.label || `(${m.row},${m.col})`)}</button>` +
        `<span class="sym-tag">${esc(m.tag || '')}</span>` +
        (isWorst ? `<span class="tag tag-warn">worst</span>` : '') +
        `</td>` +
        `<td class="num">${m.row}, ${m.col}</td>` +
        `<td class="num">${esc(m.fuelType ?? '—')}</td>` +
        `<td class="num">${esc(fmt(m.aveExp, 3))}</td>` +
        `<td class="num delta">${
          d === null ? '—' : `${d > 0 ? '+' : d < 0 ? '−' : '±'}${esc(fmt(Math.abs(d), 3))}`
        }</td>` +
        `<td class="num">${qs === null ? '—' : esc(fmt(qs, 3))}</td>` +
        `<td class="quad">${
          quads.length
            ? `<span class="quad-grid">${quads
                .map((q) => `<i>${esc(fmt(q, 3))}</i>`)
                .join('')}</span>`
            : '—'
        }</td></tr>`
      );
    })
    .join('');

  const worstBit =
    worst && Number.isFinite(dev(worst))
      ? `Largest disagreement at <b>${esc(worst.label || `(${worst.row}, ${worst.col})`)}</b> ` +
        `(${worst.row}, ${worst.col}), ${esc(fmt(Math.abs(dev(worst)), 4))} from the group mean ` +
        `of ${esc(fmt(mean, 4))}.`
      : '';

  return (
    `<section class="sub sym-card">` +
    `<h3>Symmetry group ${esc(group.group)}<span class="tag tag-warn">violation</span></h3>` +
    `<p class="sym-msg">${esc(group.message || '')}</p>` +
    (worstBit ? `<p class="sym-worst">${worstBit}</p>` : '') +
    `<div class="table-wrap"><table class="data-table sym-table">` +
    `<thead><tr><th>Member</th><th class="num">row, col</th><th class="num">Type</th>` +
    `<th class="num">Ave exp</th><th class="num" title="Signed deviation from the group mean">Δ mean</th>` +
    `<th class="num" title="Max minus min of this member's own 2×2 quadrant exposures">Quad spread</th>` +
    `<th>2×2 quadrant exposures</th></tr></thead><tbody>${rows}</tbody></table></div>` +
    `<div class="sym-foot">` +
    (spread !== null ? `Ave-exposure spread <b>${esc(fmt(spread, 4))}</b>` : '') +
    (group.expSpread !== null && group.expSpread !== undefined
      ? ` · reported spread <b>${esc(fmt(group.expSpread, 4))}</b>`
      : '') +
    (types.size > 1 || group.typeMismatch ? ` · <b class="bad">fuel-type mismatch</b>` : '') +
    (group.line !== null && group.line !== undefined
      ? ` · <button type="button" class="linkish" data-goto-line="${group.line}">listing line ${group.line}</button>`
      : '') +
    `</div></section>`
  );
}

/* -------------------------------------------------------------- diagnostics */

export function renderDiagnostics() {
  const host = $('#panel-diagnostics');
  const p = state.payload;
  const countPill = $('#tab-diag-count');
  if (!p) { host.innerHTML = ''; if (countPill) countPill.textContent = ''; return; }

  const all = (p.diagnostics || []).slice();
  const groups = p.symmetryGroups || [];
  if (countPill) countPill.textContent = String(all.length + groups.length);

  /* The counters above the list are filters. A severity narrows the table and
   * drops the symmetry cards; SYMMETRY does the reverse. Clicking the active
   * one again clears it. */
  const filter = state.diagFilter;
  const bySeverity = !!filter && filter !== 'SYMMETRY';
  const diags = bySeverity
    ? all.filter((d) => String(d.severity || '').toUpperCase() === filter)
    : filter === 'SYMMETRY'
    ? []
    : all;
  const showGroups = !bySeverity;

  const { key, dir } = state.diagSort;
  diags.sort((x, y) => {
    let a = x[key];
    let b = y[key];
    if (key === 'severity') {
      a = SEVERITY_RANK[String(a).toUpperCase()] ?? 9;
      b = SEVERITY_RANK[String(b).toUpperCase()] ?? 9;
    }
    if (typeof a === 'string') a = a.toLowerCase();
    if (typeof b === 'string') b = b.toLowerCase();
    if (a === b) return 0;
    if (a === null || a === undefined) return 1;
    if (b === null || b === undefined) return -1;
    return (a > b ? 1 : -1) * dir;
  });

  const s = p.status || {};
  const out = [];

  out.push(
    `<div class="sev-summary">` +
      sevChip('ERROR', s.errors) +
      sevChip('WARNING', s.warnings) +
      sevChip('CAUTION', s.cautions) +
      sevChip('NOTE', s.notes) +
      sevChip('SYMMETRY', s.symmetryViolations ?? groups.length, 'sym', 'symmetry violation') +
      `</div>`
  );

  const total = all.length + groups.length;
  const shown = diags.length + (showGroups ? groups.length : 0);
  out.push(
    `<div class="diag-filter-line${filter ? ' is-filtered' : ''}">` +
      `<span>Showing ${shown} of ${total}` +
      (filter ? ` — ${esc(FILTER_LABEL[filter] || filter)} only` : ' entries') +
      `</span>` +
      (filter
        ? `<button type="button" class="btn btn-mini" data-diag-filter="" ` +
          `title="Clear the diagnostics filter">Show all</button>`
        : '') +
      `</div>`
  );

  if (!diags.length) {
    out.push(
      `<div class="empty-note">` +
        (bySeverity
          ? `No <b>${esc(FILTER_LABEL[filter] || filter)}</b> entries in this listing.`
          : filter === 'SYMMETRY'
          ? `Filtered to symmetry violations — the diagnostics table is hidden.`
          : `No diagnostics were printed in this listing.`) +
        `</div>`
    );
  } else {
    const th = (k, label, cls = '') =>
      `<th class="${cls} sortable${key === k ? (dir > 0 ? ' sort-asc' : ' sort-desc') : ''}" ` +
      `data-sort="${k}" tabindex="0" role="button" aria-label="Sort by ${esc(label)}">${esc(label)}</th>`;
    out.push(
      `<div class="table-wrap"><table class="data-table diag-table"><thead><tr>` +
        th('severity', 'Sev') +
        th('label', 'Label') +
        th('times', '×', 'num') +
        th('where', 'Where') +
        th('info', 'Info') +
        `</tr></thead><tbody>` +
        diags
          .map((d) => {
            const sev = String(d.severity || '').toUpperCase();
            return (
              `<tr class="sev-${sev.toLowerCase()}">` +
              `<td><span class="sev-badge sev-${sev.toLowerCase()}">${esc(sev.slice(0, 4))}</span></td>` +
              `<td class="mono">${esc(d.label)}</td>` +
              `<td class="num">${esc(d.times ?? '')}</td>` +
              `<td class="mono">${esc(d.where || '')}</td>` +
              `<td class="info">${esc(d.info || '')}` +
              (d.line !== null && d.line !== undefined
                ? ` <button type="button" class="linkish" data-goto-line="${d.line}">line ${d.line}</button>`
                : '') +
              `</td></tr>`
            );
          })
          .join('') +
        `</tbody></table></div>`
    );
  }

  if (showGroups) {
    out.push(`<h3 class="panel-h">Symmetry groups <span class="pill">${groups.length}</span></h3>`);
    if (!groups.length) {
      out.push(`<div class="empty-note">No symmetry violations — every group passed the check.</div>`);
    } else {
      for (const g of groups) out.push(symmetryCard(g, null));
    }
  }

  // Execution is context, not a diagnostic: while a filter is on, the panel
  // shows what was asked for and nothing else.
  if (!filter) out.push(executionBlock(p));
  host.innerHTML = out.join('');
}

/** Termination status, wall-clock cost and the CPU profile from meta.timing. */
function executionBlock(p) {
  const m = p.meta || {};
  const t = m.timing || {};
  const normal = t.completion ? /normal\s+termination/i.test(t.completion) : false;
  const rows = [
    ['Completion', t.completion || 'unknown'],
    ['CPU', Number.isFinite(t.cpuSeconds) ? `${fmt(t.cpuSeconds, 3)} s` : '—'],
    ['Elapsed', Number.isFinite(t.elapsedSeconds) ? `${fmt(t.elapsedSeconds, 3)} s` : '—'],
    ['CPU utilisation', Number.isFinite(t.cpuUtilisation) ? `${fmt(t.cpuUtilisation, 2)} %` : '—'],
    ['Container', Number.isFinite(t.containerWords) ? `${t.containerWords.toLocaleString()} words` : '—'],
    [
      'Window',
      t.startTime ? `${t.startDate || ''} ${t.startTime} → ${t.endDate || ''} ${t.endTime || ''}`.trim() : '—',
    ],
    ['Listing', `${m.pageCount ?? '—'} pages · ${m.lineCount ?? '—'} lines`],
    ['Restart file', m.restartFile || '—'],
    [
      'Restart exposure',
      Number.isFinite(m.restartExposure) ? `${fmt(m.restartExposure, 3)} ${exposureUnit(p)}` : '—',
    ],
    ['Power / flow', `${fmt(m.percentPower, 1)} % / ${fmt(m.percentFlow, 1)} %`],
  ];
  const subs = Array.isArray(t.subroutines) ? t.subroutines : [];
  return (
    `<h3 class="panel-h">Execution</h3>` +
    `<section class="sub">` +
    (t.completion && !normal
      ? `<div class="error-note">Abnormal termination — “${esc(t.completion)}”. Results in this ` +
        `listing may be incomplete.</div>`
      : '') +
    kvTable(rows) +
    (subs.length
      ? `<p class="foot-note">The per-subroutine CPU profile (${subs.length} entries) is ` +
        `charted on the <b>Plots</b> view.</p>`
      : '') +
    `</section>`
  );
}

/** One clickable counter. Pressing it narrows the list to that severity or
 *  category; pressing the pressed one clears the filter. */
function sevChip(label, count, cls = label.toLowerCase(), word = label.toLowerCase()) {
  const n = count || 0;
  const on = state.diagFilter === label;
  const text = `${n} ${word}${n === 1 ? '' : 's'}`;
  return (
    `<button type="button" class="sev-chip sev-${esc(cls)}${n ? '' : ' is-zero'}" ` +
    `data-diag-filter="${esc(label)}" aria-pressed="${on}" ` +
    `title="${on ? 'Clear this filter' : `Show only ${esc(text)}`}">${esc(text)}</button>`
  );
}

/* ---------------------------------------------------------------- inventory */

export function renderInventory() {
  const host = $('#panel-inventory');
  const p = state.payload;
  if (!p) { host.innerHTML = ''; return; }

  const inv = p.inventory || [];
  const segs = p.segments || [];
  const types = p.assemblyTypes || [];
  const byType = typeInfo(p);
  const total = inv.reduce((a, r) => a + (r.count || 0), 0);
  const expected = (p.geometry || {}).nAssemblies;
  const declaredTotal = types
    .filter((t) => t.isFuel)
    .reduce((a, t) => a + (Number.isFinite(t.countInCore) ? t.countInCore : 0), 0);
  const out = [];

  if (!inv.length) {
    out.push(`<div class="empty-note">No fuel inventory summary in this listing.</div>`);
  } else {
    out.push(
      `<section class="sub"><h3>Fuel inventory</h3>` +
        `<div class="table-wrap"><table class="data-table"><thead><tr>` +
        `<th>Type</th><th>Name</th><th>Segment</th><th class="num">Enrich<br>(w/o)</th>` +
        `<th class="num">Count</th><th class="num" title="The listing's own declared count for this type">Decl.</th>` +
        `<th>Batch</th><th>Fresh</th></tr></thead><tbody>` +
        inv
          .map((r, i) => {
            const t = byType.get(r.fuelType);
            const decl = t && Number.isFinite(t.countInCore) ? t.countInCore : null;
            return (
              `<tr><td class="num"><span class="swatch-dot" style="background:${categoricalColor(i)}"></span>` +
              `${esc(r.fuelType)}</td>` +
              `<td class="mono">${esc(r.typeName || '—')}</td>` +
              `<td class="mono">${
                r.segment === null || r.segment === undefined
                  ? '—'
                  : `${esc(r.segment)}${r.segmentName ? ` · ${esc(r.segmentName)}` : ''}`
              }</td>` +
              `<td class="num">${esc(fmt(r.enrichment, 4))}</td>` +
              `<td class="num">${esc(r.count)}</td>` +
              `<td class="num ${decl !== null && decl !== r.count ? 'differs' : ''}"` +
              `${decl !== null && decl !== r.count
                ? ' title="Declared count differs from the count mapped on the core — some positions carry a fuel type the listing never describes."'
                : ''}>${decl === null ? '—' : esc(fmt(decl, 0))}</td>` +
              `<td>${esc(
                r.batchLabel ||
                  (r.batchNumber !== null && r.batchNumber !== undefined ? `#${r.batchNumber}` : '—')
              )}</td>` +
              `<td>${r.fresh ? '<span class="tag tag-fresh">fresh</span>' : '—'}</td></tr>`
            );
          })
          .join('') +
        `<tr class="total-row"><td colspan="4">Total</td><td class="num">${total}</td>` +
        `<td class="num">${declaredTotal ? esc(fmt(declaredTotal, 0)) : '—'}</td><td colspan="2"></td></tr>` +
        `</tbody></table></div>` +
        (expected === undefined || expected === null
          ? ''
          : `<div class="tally">${
              total === expected
                ? `<span class="check ok">✓ ${total} assemblies — matches geometry.nAssemblies</span>`
                : `<span class="check bad">✗ inventory totals ${total}, geometry.nAssemblies is ${expected}</span>`
            }${
              declaredTotal
                ? declaredTotal === total
                  ? ` <span class="check ok">✓ agrees with the declared type totals</span>`
                  : ` <span class="check bad">✗ declared type totals give ${fmt(declaredTotal, 0)}</span>`
                : ''
            }</div>`) +
        `</section>`
    );
  }

  if (types.length) {
    out.push(
      `<section class="sub"><h3>Assembly types <span class="pill">${types.length}</span></h3>` +
        `<div class="table-wrap"><table class="data-table"><thead><tr>` +
        `<th class="num">Type</th><th>Name</th><th>Class</th><th class="num">Loading<br>(kg)</th>` +
        `<th class="num">Zones</th><th class="num">Active<br>seg</th><th class="num">In core</th>` +
        `</tr></thead><tbody>` +
        types
          .map(
            (t) =>
              `<tr><td class="num">${esc(t.fuelType)}</td><td class="mono">${esc(t.name || '—')}</td>` +
              `<td>${esc(t.class || '—')}</td>` +
              `<td class="num">${
                Number.isFinite(t.loadingGrams) ? esc(fmt(t.loadingGrams / 1000, 1)) : '—'
              }</td>` +
              `<td class="num">${esc(t.axialZones ?? '—')}</td>` +
              `<td class="num">${esc(t.activeSegment ?? '—')}</td>` +
              `<td class="num">${esc(fmt(t.countInCore, 0))}</td></tr>`
          )
          .join('') +
        `</tbody></table></div></section>`
    );
  }

  if (segs.length) {
    out.push(
      `<section class="sub"><h3>Fuelled segments <span class="pill">${segs.length}</span></h3>` +
        `<div class="table-wrap"><table class="data-table"><thead><tr>` +
        `<th class="num">#</th><th>Name</th><th class="num">Enrich<br>(w/o)</th><th class="num">Loading</th>` +
        `<th class="num">BP load</th><th class="num">BP rods</th>` +
        `<th class="num">Equivalent<br>assemblies</th>` +
        `</tr></thead><tbody>` +
        segs
          .map(
            (s) =>
              `<tr><td class="num">${esc(s.number)}</td><td class="mono">${esc(s.name || '')}</td>` +
              `<td class="num">${esc(fmt(s.enrichment, 4))}</td>` +
              `<td class="num">${esc(fmt(s.loading, 4))}</td>` +
              `<td class="num">${esc(fmt(s.bpLoading, 3))}</td>` +
              `<td class="num">${esc(s.bpRods ?? '—')}</td>` +
              `<td class="num">${esc(fmt(s.equivalentAssemblies, 3))}</td></tr>`
          )
          .join('') +
        `</tbody></table></div>` +
        `<p class="foot-note">Segment numbers are a different namespace from fuel-type numbers. ` +
        `<b>Equivalent assemblies</b> is height-weighted — an assembly whose fuel segment spans ` +
        `351 of 381 cm counts as 0.921 — so it is not an assembly count.</p>` +
        `</section>`
    );
  }

  const batches = ((p.inputDeck || {}).batches) || [];
  if (batches.length) {
    out.push(
      `<section class="sub"><h3>Input-deck batches</h3><div class="table-wrap">` +
        `<table class="data-table"><thead><tr><th>Label</th><th>Serial base</th>` +
        `<th class="num">Count</th><th class="num">Type</th><th class="num">Batch</th></tr></thead><tbody>` +
        batches
          .map(
            (b) =>
              `<tr><td class="mono">${esc(b.label)}</td><td class="mono">${esc(b.serialBase || '—')}</td>` +
              `<td class="num">${esc(b.count ?? '—')}</td><td class="num">${esc(b.fuelType ?? '—')}</td>` +
              `<td class="num">${esc(b.batchNumber ?? '—')}</td></tr>`
          )
          .join('') +
        `</tbody></table></div></section>`
    );
  }

  out.push(listingBlocks(p));
  host.innerHTML = out.join('');
}

/* Which optional edits this run actually contains. Without this, a listing
 * that never requested PRI.INP maps or BAT.EDT is indistinguishable from a
 * parse failure — the reader just sees nothing and has to guess. */
function listingBlocks(p) {
  const maps = p.maps || {};
  const hasBatch = (p.statePoints || []).some(
    (s) => s.batchEdits && Object.keys(s.batchEdits).length
  );
  const g = p.geometry || {};
  const nSym = (p.symmetryGroups || []).length;
  // [label, state, detail, explanation] — state is 'yes' | 'no' | 'ok'
  const rows = [
    ['Fuel map (FMAP)', maps.fmap ? 'yes' : 'no', maps.fmap ? cellCount(maps.fmap) : 'no PRI.INP fuel map edited',
      'Identity per position is also carried by the assembly records, which are always present, so the map itself is not required to read this run.'],
    ['Core map (CMAP)', maps.cmap ? 'yes' : 'no', maps.cmap ? cellCount(maps.cmap) : 'no PRI.INP core map edited',
      'Optional PRI.INP core map edit.'],
    ['Batch edits (BAT.EDT)', hasBatch ? 'yes' : 'no', hasBatch ? 'one per state point' : 'no BAT.EDT block',
      'Per-batch maxima with the limiting assembly. Shown in the Inspector.'],
    ['Axial edits', g.is3d ? 'yes' : 'no', g.is3d ? `${g.fuelNodes} fuel nodes` : '2D run — one axial fuel node',
      g.is3d ? 'Axial distributions per state point, plotted on the Plots view.'
             : 'A single axial node means there is no axial shape to edit — this is the geometry, not a missing block.'],
    ['Symmetry check', nSym ? 'no' : 'ok', nSym ? `${nSym} group${nSym === 1 ? '' : 's'} flagged` : 'ran, every group passed',
      nSym ? 'Failing groups are listed under Diagnostics.' : 'The check was performed and nothing failed.'],
  ];
  const LABEL = { yes: 'present', no: 'not in this run', ok: 'clean' };
  return (
    `<section class="sub"><h3>Listing blocks</h3>` +
    `<table class="kv blocks"><tbody>` +
    rows
      .map(
        ([k, stateName, detail, why]) =>
          `<tr><th>${esc(k)}</th><td>` +
          `<span class="blk ${esc(stateName)}">${esc(LABEL[stateName])}</span> ` +
          `<span class="muted">${esc(detail)}</span>` +
          `<div class="blk-why">${esc(why)}</div></td></tr>`
      )
      .join('') +
    `</tbody></table>` +
    `<p class="foot-note">These blocks are optional in a SIMULATE-3 run. “Not in this run” ` +
    `means the listing never contained them — it is not a parse failure.</p>` +
    `</section>`
  );
}

function cellCount(map) {
  const n = Array.isArray(map.cells) ? map.cells.length : 0;
  const f = Array.isArray(map.fieldNames) && map.fieldNames.length ? ` · ${map.fieldNames.join(', ')}` : '';
  return `${n} position${n === 1 ? '' : 's'}${f}`;
}

/* --------------------------------------------------------- listing navigator */

export function renderNavTree() {
  const host = $('#nav-tree');
  const p = state.payload;
  if (!p) { host.innerHTML = ''; return; }

  const tree = p.navTree || [];
  const filter = state.treeFilter.trim().toLowerCase();
  const stepInfo = new Map();
  for (const sp of p.statePoints || []) stepInfo.set(`${sp.case}:${sp.step}`, sp);
  const unit = exposureUnit(p);

  let shown = 0;
  const out = [];

  for (const c of tree) {
    const caseKey = `case:${c.case}`;
    const steps = c.steps || [];
    const secTotal = steps.reduce((a, s) => a + (s.sections || []).length, 0);

    const stepNodes = [];
    for (const s of steps) {
      const stepKey = `step:${c.case}:${s.step}`;
      const secs = (s.sections || []).filter(
        (sec) =>
          !filter ||
          `${sec.name || ''} ${sec.label || ''} ${sec.kind || ''}`.toLowerCase().includes(filter)
      );
      if (filter && !secs.length) continue;
      shown += secs.length;

      const sp = stepInfo.get(`${c.case}:${s.step}`);
      const open = filter ? true : state.openNodes.has(stepKey);
      const secHtml = secs
        .map((sec) => {
          const active = state.section && String(state.section.id) === String(sec.id);
          return (
            `<li><button type="button" class="tree-leaf${active ? ' is-active' : ''}" ` +
            `data-section='${esc(JSON.stringify({ id: sec.id, start: sec.start, end: sec.end, label: sec.label, name: sec.name, kind: sec.kind, page: sec.page }))}'>` +
            `<span class="kind kind-${esc(String(sec.kind || '').replace(/\W/g, '-'))}">${esc(sec.kind || '')}</span>` +
            `<span class="leaf-name">${esc(sec.name || sec.label || sec.id)}</span>` +
            `<span class="leaf-lines">${sec.start}–${sec.end}</span></button></li>`
          );
        })
        .join('');

      stepNodes.push(
        `<li class="tree-step"><button type="button" class="tree-node" data-toggle="${esc(stepKey)}" ` +
          `aria-expanded="${open}"><span class="caret" aria-hidden="true">${open ? '▾' : '▸'}</span>` +
          `<span>Step ${s.step}</span>` +
          (sp ? `<span class="tree-note">${esc(fmt(sp.exposure, 3))} ${esc(unit)}</span>` : '') +
          `<span class="pill pill-mini">${secs.length}</span></button>` +
          (open ? `<ul class="tree-leaves">${secHtml}</ul>` : '') +
          `</li>`
      );
    }

    if (filter && !stepNodes.length) continue;
    const openCase = filter ? true : state.openNodes.has(caseKey);
    out.push(
      `<div class="tree-case"><button type="button" class="tree-node tree-node-case" ` +
        `data-toggle="${esc(caseKey)}" aria-expanded="${openCase}">` +
        `<span class="caret" aria-hidden="true">${openCase ? '▾' : '▸'}</span>` +
        `<span>Case ${c.case}</span><span class="tree-note">${steps.length} step${steps.length === 1 ? '' : 's'}</span>` +
        `<span class="pill pill-mini">${secTotal}</span></button>` +
        (openCase ? `<ul class="tree-steps">${stepNodes.join('')}</ul>` : '') +
        `</div>`
    );
  }

  host.innerHTML = out.join('') || `<div class="empty-note">No sections match “${esc(state.treeFilter)}”.</div>`;
  const pill = $('#nav-count');
  if (pill) pill.textContent = filter ? `${shown} match` : `${(p.sections || []).length} sections`;
}

/* ------------------------------------------------------------ section viewer */

export async function openSection(sec, opts = {}) {
  const runId = state.runId;
  if (!runId) return;
  const context = opts.context === undefined ? 2 : opts.context;
  const offset = Math.max(0, sec.start - context);
  update(
    { section: { ...sec, text: null, loading: true, error: null, offset, highlight: opts.highlight ?? null } },
    'section'
  );
  try {
    const text = await fetchSection(runId, sec.start, sec.end, context);
    update(
      { section: { ...sec, text, loading: false, error: null, offset, highlight: opts.highlight ?? null } },
      'section'
    );
  } catch (err) {
    update(
      { section: { ...sec, text: null, loading: false, error: err.message, offset, highlight: null } },
      'section'
    );
  }
}

export function renderSectionViewer() {
  const host = $('#section-view');
  const note = $('#section-note');
  const copy = $('#section-copy');
  const sec = state.section;

  if (!sec) {
    host.innerHTML =
      `<div class="empty-note">Pick a section in the listing navigator to read the raw ` +
      `SIMULATE-3 output for it — or search the listing and click a text hit to jump ` +
      `straight to that line.</div>`;
    note.textContent = 'Nothing open';
    copy.hidden = true;
    return;
  }

  note.textContent = `${sec.kind ? `${sec.kind} · ` : ''}lines ${sec.start}–${sec.end}${
    sec.page ? ` · page ${sec.page}` : ''
  }`;

  if (sec.loading) {
    host.innerHTML = `<div class="empty-note">Loading lines ${sec.start}–${sec.end}…</div>`;
    copy.hidden = true;
    return;
  }
  if (sec.error) {
    host.innerHTML = `<div class="error-note">${esc(sec.error)}</div>`;
    copy.hidden = true;
    return;
  }

  const lines = String(sec.text ?? '').split('\n');
  const width = String(sec.offset + lines.length).length;
  const body = lines
    .map((ln, i) => {
      const no = sec.offset + i;
      const hot = sec.highlight !== null && sec.highlight !== undefined && no === sec.highlight;
      const inRange = no >= sec.start && no < sec.end;
      return (
        `<div class="lst-line${hot ? ' is-hit' : ''}${inRange ? '' : ' is-context'}"${hot ? ' id="lst-hit"' : ''}>` +
        `<span class="lst-no">${String(no).padStart(width, ' ')}</span>` +
        `<span class="lst-text">${esc(ln) || '&nbsp;'}</span></div>`
      );
    })
    .join('');

  host.innerHTML =
    `<div class="lst-head"><span class="lst-title">${esc(sec.label || sec.name || sec.id)}</span></div>` +
    `<div class="lst-body" tabindex="0" role="region" aria-label="Raw listing text">${body}</div>`;
  copy.hidden = false;

  const hit = host.querySelector('#lst-hit');
  if (hit) hit.scrollIntoView({ block: 'center' });
}

/* ------------------------------------------------------------- text results */

/* Sections & Search hands the text hits their own column — but only once there
 * are hits to put in it, otherwise the view would carry an empty gutter. */
function showHitsColumn(on) {
  document.body.classList.toggle('has-hits', !!on);
}

export function renderSearchResults() {
  const card = $('#search-card');
  const host = $('#search-results');
  const pill = $('#search-count');
  const r = state.hits;

  if (state.searching) {
    card.hidden = false;
    showHitsColumn(true);
    pill.textContent = '…';
    host.innerHTML = `<div class="empty-note">Searching the listing…</div>`;
    return;
  }
  if (!r) { card.hidden = true; showHitsColumn(false); host.innerHTML = ''; return; }

  card.hidden = false;
  showHitsColumn(true);
  pill.textContent = `${r.count}${r.truncated ? '+' : ''}`;
  if (!r.hits.length) {
    host.innerHTML = `<div class="empty-note">No raw-text hits for “${esc(r.query || state.query)}”.</div>`;
    return;
  }
  host.innerHTML =
    (r.truncated ? `<div class="hint">Showing the first ${r.hits.length} hits.</div>` : '') +
    r.hits
      .map(
        (h) =>
          `<button type="button" class="hit" data-hit-line="${h.line}">` +
          `<span class="hit-meta">line ${h.line}${h.case !== null && h.case !== undefined ? ` · case ${h.case}` : ''}` +
          `${h.step !== null && h.step !== undefined ? ` · step ${h.step}` : ''}` +
          `${h.page ? ` · p${h.page}` : ''}</span>` +
          `<span class="hit-text">${esc(h.text)}</span></button>`
      )
      .join('');
}

/* -------------------------------------------------------------- load panel */

export function buildLoadPanel(host, handlers) {
  host.innerHTML =
    `<div class="load-panel">` +
    `<div class="dropzone" id="${host.id}-dz" tabindex="0" role="button" ` +
    `aria-label="Drop a SIMULATE-3 listing here or press Enter to browse">` +
    `<div class="dz-mark" aria-hidden="true">⇪</div>` +
    `<div class="dz-title">Drop a SIMULATE-3 listing here</div>` +
    `<div class="dz-sub">or <span class="linkish">browse for a file</span> — .out listings up to 256 MB</div>` +
    `<input type="file" class="dz-input" accept=".out,.txt,.lis,.prt,text/plain" hidden />` +
    `</div>` +
    `<div class="samples"><div class="samples-head">Bundled examples</div>` +
    `<div class="sample-list">Loading samples…</div></div>` +
    `<div class="load-status" role="status" aria-live="polite"></div>` +
    `</div>`;

  const dz = host.querySelector('.dropzone');
  const input = host.querySelector('.dz-input');

  dz.addEventListener('click', () => input.click());
  dz.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
  });
  input.addEventListener('change', () => {
    if (input.files && input.files[0]) handlers.onFile(input.files[0]);
    input.value = '';
  });
  ['dragenter', 'dragover'].forEach((t) =>
    dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.add('is-over'); })
  );
  ['dragleave', 'drop'].forEach((t) =>
    dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.remove('is-over'); })
  );
  dz.addEventListener('drop', (e) => {
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) handlers.onFile(f);
  });

  return {
    setSamples(samples) {
      const list = host.querySelector('.sample-list');
      if (!samples.length) {
        list.innerHTML = `<span class="muted">No bundled samples on this server.</span>`;
        return;
      }
      list.innerHTML = samples
        .map(
          (s) =>
            `<button type="button" class="sample-btn" data-sample="${esc(s.name)}" ` +
            `aria-label="Parse the bundled sample ${esc(s.name)}, ${esc(s.sizeKb)} kilobytes">` +
            `<span class="sample-name">${esc(s.name)}</span>` +
            `<span class="sample-size">${esc(s.sizeKb)} kB</span></button>`
        )
        .join('');
      list.querySelectorAll('[data-sample]').forEach((b) =>
        b.addEventListener('click', () => handlers.onSample(b.dataset.sample))
      );
    },
    setStatus(html, kind = '') {
      const el = host.querySelector('.load-status');
      el.className = `load-status ${kind}`;
      el.innerHTML = html;
    },
  };
}

/* --------------------------------------------------------------- clipboard */

export async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (_) { /* fall through */ }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
  document.body.removeChild(ta);
  return ok;
}
