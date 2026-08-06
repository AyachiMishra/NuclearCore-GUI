# Front-end implementation report

Browser front end for the SIMULATE-3 core analysis dashboard. Vanilla ES
modules, no build step, no npm, zero network dependencies — every asset is
served from `/static`, every chart is hand-written SVG, and the only external
reference in `index.html` is `href="data:,"` for the favicon (which exists purely
to suppress a 404). A strict-offline machine renders it identically.

## Files created

| File | Lines | Role |
|---|---|---|
| `s3dash/web/static/index.html` | ~150 | Document shell, panel containers, `<dialog>` loader |
| `s3dash/web/static/css/app.css` | ~880 | Design tokens, layout, SVG styling, print sheet |
| `s3dash/web/static/js/api.js` | ~80 | Fetch wrappers; funnels backend `detail` into `Error.message` |
| `s3dash/web/static/js/state.js` | ~430 | State + pub/sub + every payload derivation |
| `s3dash/web/static/js/coremap.js` | ~570 | SVG core map, colour scales, CRD drive map, tooltips |
| `s3dash/web/static/js/charts.js` | ~520 | Depletion / axial / distribution charts, mini bars |
| `s3dash/web/static/js/panels.js` | ~700 | Header, inspector, diagnostics, inventory, navigator, section viewer |
| `s3dash/web/static/js/app.js` | ~480 | Toolbar construction, event wiring, render dispatch |

Also added `.claude/launch.json` so `preview_start` can run the server.
Nothing under `s3dash/parser/` or `s3dash/web/app.py` was touched.

## Architecture

`state.js` holds one mutable object plus a `subscribe(fn)` / `update(patch,
...changeKeys)` pair. Renderers subscribe once and receive the set of change
keys, so a step change re-renders the map, three charts and the inspector but
leaves the navigator tree and diagnostics table alone. All payload
interpretation lives in `state.js` as pure selectors (`buildLayers`,
`layerValues`, `symmetryMap`, `axisLabels`, `controlRodSummary`,
`inventoryByType`, …) — no view module reads the payload shape directly.

## How each contract rule is honoured

1. **Core size** — the grid comes from `geometry.iafull` via `gridSize()`, with a
   fall-back that scans `assemblies[]` for the max row/col. Verified 17×17 and
   15×15.
2. **Variables** — the layer selector is built from `variableOrder` plus any code
   found in `statePoints[].values`, labelled from `sections[].variable.name` +
   `unit`, falling back to the raw code. BEAVRS shows 2RR1/2KIN automatically;
   APR1400 does not.
3. **Axial data** — `!geometry.is3d` renders an explanatory empty state quoting
   `fuelNodes` and `kd`, never an empty chart. The axial selector is disabled
   with the exact tooltip "2D case — single axial node" on both the `<select>`
   and its wrapper (disabled controls swallow hover in some browsers).
4. **`maps.fmap` / `batchEdits`** — never read. Nothing in the UI assumes them.
5. **`exposureUnit`** — read from the state point first, then `meta`, and used in
   every axis label, readout and header field. Confirmed `GWd/MT` vs `EFPD`.
6. **Index alignment** — `layerValues()` maps over `assemblies[]` and indexes the
   value array positionally; `null` renders as a neutral "no data" fill.
7. **2PLO** — detected as a text layer by sampling the first non-null value.
   Rendered as cell labels with a neutral fill and a legend that says so; it is
   excluded from the colour scale and gets a category bar chart, not a histogram.
8. **`parseNotes`** — a full-width amber strip under the header when non-empty
   (hidden on all three samples, which have none).
9. **`printed === false`** — a subtle 45° hatch overlay, an "expanded" tag in the
   inspector, a legend key, and a tooltip note. 172 of 241 cells in
   case_002495; 0 in 9074.

### Later payload additions

- **`meta.timing`** — `completion` is a chip in the header: green with a check for
  "Normal Termination", red with a warning glyph otherwise, plus an explicit
  "results may be incomplete" note in the diagnostics panel when abnormal.
  `cpuSeconds` / `elapsedSeconds` / `cpuUtilisation` form the header's
  "Execution time" field, each omitted individually when absent (apr1400.c02
  has no elapsed or utilisation). The `subroutines[]` profile is a collapsed
  bar chart in the diagnostics panel.
- **`statePoints[].controlRods`** — a **"Control rods"** view layer under a "Core
  state" option group. It renders from `rows`/`cols` on its own coordinate
  space with numeric drive headers — deliberately *not* the assembly index
  space, and not the site letters, so it cannot be mistaken for the fuel map.
  Withdrawn drives read **`OUT`** in a distinct neutral fill; inserted drives
  show their step value on a colour ramp. Since all three samples are
  `anyInserted: false`, the common path shows a prominent **ARO** banner ("All
  rods withdrawn — every one of the 289 drive positions is fully out"), the
  distribution chart shows a matching ARO empty state, and the inspector
  carries an ARO block for every step. It never looks blank or broken.
- **`inventory[]` new fields** — enrichment is taken from `inventory[].enrichment`
  directly; `segments[]` is never indexed by `fuelType`. `typeName`, `segment`,
  `segmentName` and `enrichment` all render as "—" when null (BEAVRS types
  13–20). The inspector falls back to the type-level enrichment, labelled
  "(type)", when an assembly has no enrichment of its own — 147 of 193 BEAVRS
  assemblies.
- **`assemblyTypes[]`** — `countInCore` appears as a "Decl." column beside the
  mapped count, and both totals are checked against `geometry.nAssemblies`
  (both ✓ on all three files). Rows where the two disagree — BEAVRS type 6
  reads 32 mapped vs 38 declared, because 16 positions carry types the listing
  never describes — get a muted `≠` marker with an explanatory tooltip rather
  than being silently reconciled. A separate assembly-types table lists class,
  loading, axial zones and active segment.
- **`segments[].equivalentAssemblies`** is labelled "Equivalent assemblies" with
  a footnote stating it is height-weighted and not an assembly count.

## Features

**Header** — file name, code + version, plant/case title, geometry summary
("PWR · 17×17 · quarter-core rotational · 2D · 241 assemblies"), run date/time,
step count with cycle-exposure span and unit, execution time, the completion
chip, and a status badge driven by `status.level` reading e.g. "WARNINGS ·
8 symmetry violations · 71 warnings". Clicking the badge opens the diagnostics
panel and moves focus to it; its `title` carries the full severity breakdown.

**Load panel** — drag-and-drop zone plus a file picker posting to `/api/parse`,
and one-click buttons for every entry in `/api/samples`. Busy state with a
spinner; backend `detail` strings are rendered verbatim in a red strip. The
same panel is mounted both as the landing hero and inside a `<dialog>` reached
from the header.

**Toolbar** — layer selector (three option groups), step slider with prev/next
and a readout ("Step 16 / 31 · 10.050 GWd/MT · k-eff 1.07444 · 0 ppm"), axial
node selector, search box, a filter dropdown with fuel-type and batch
checkboxes, a flagged-only toggle, and JSON / CSV / Print exports. ← and →
step through the run when focus is not in a field or on the map.

**Core map** — SVG grid sized from `iafull`, row numbers left and site column
letters across the top, both derived from `assemblies[].site` (T…A for the
17-wide APR1400, R…A for the 15-wide BEAVRS). Sequential layers use viridis —
perceptually ordered and colour-vision-deficiency safe, with no red/green
pairing; categorical layers use an Okabe-Ito-derived palette. Cell text colour
is chosen per-cell by relative luminance. Legend always states the numeric
range or the category counts (with fuel-type names) plus the flag and hatch
keys. Red corner badge for symmetry-group members, hatch for
`printed === false`, dimming for filtered-out cells, a strong ring for the
selection.

**Accessibility** — the map is a `role="grid"` with roving tabindex: arrow keys
move between occupied positions, Home/End jump along a row, Enter/Space
selects, and focus survives re-render. Focus rings are visible on every
control. Charts are `role="img"` with `<title>`/`<desc>`, a caption that states
the reading in words, and a collapsed data table. There is a skip link.

**Inspector** — state-point summary, the control-rod block, full assembly
identity (site, coords, serial, label, fuel type + type name, segment, batch,
rotation, enrichment, BP rods, loading, source), every code's value at the
current step with the active layer highlighted, and — for flagged assemblies —
the full symmetry-group breakdown with each member's position, fuel type,
average exposure and 2×2 quadrant exposures, so the disagreeing position is
visible at a glance. Member names are buttons that select that assembly.

**Diagnostics** — severity chips, a sortable table (click or Enter on any
header) with severity colouring and per-row "line N" links into the section
viewer, one card per symmetry group, and the execution block.

**Inventory** — the enriched inventory table with the totals check, a bar
chart, the assembly-types table and the segments table with its footnote.

**Charts** — depletion progression (X = `cycleExposure` labelled with the
payload unit, Y switchable between k-eff / peak radial / peak nodal / peak
3-pin / boron / axial offset, dashed reference line at k = 1.0, marker and
cursor on the current step, points clickable to jump); axial profile drawn
bottom-to-top with a core-average reference line and a column selector, or the
2D empty state; and a distribution histogram with mean and max annotated,
degrading to a category bar chart for categorical and text layers.

**Navigator and section viewer** — `navTree` as a collapsible Case → Step →
section tree with counts, exposures on step nodes and a filter box. Clicking a
section fetches `/api/run/{id}/section?context=2` and shows the raw listing in
a monospace pane with real line numbers, dimmed context lines, the section
heading and a copy button. Text search hits open the same viewer at the hit
line, highlighted and scrolled into view.

**Theming** — light and dark via `prefers-color-scheme`, plus a header toggle
cycling auto → light → dark that writes `data-theme` on `<html>` and persists
to `localStorage`. The `[data-theme]` rules follow the media query in source
order, so a manual choice always wins.

**Print** — `@media print` hides the toolbar, navigator, tabs and dialogs,
forces the meta strip and all three panels visible, switches to a white
palette, and sets `break-inside: avoid` on cards.

## Verified in the browser (screenshots taken)

Server run with `python -m uvicorn s3dash.web.app:app --port 8000`.

- All three samples load from the sample buttons and render fully.
- **case_002495**: 241 cells on a 17×17 grid, columns T…A, legend range
  0.3950–1.3890, 8 symmetry groups flagged with corner badges, 172 hatched
  cells.
- **9074**: 193 cells on a **15×15** grid, columns R…A, unit **EFPD**, layers
  include 2RR1 and 2KIN, no Batch layer (all batches null), no flags, no hatch.
- **apr1400.c02**: 241 cells, 28 steps, 2 symmetry violations, execution time
  showing CPU only.
- Step slider and prev/next re-render map, legend range, histogram, depletion
  marker and inspector (checked step 0 → 20 → 21 → 19 on case_002495).
- Axial chart: **12 bars for 9074**, node 1 at the bottom (y = 239) and node 12
  at the top (y = 21), peak at node 4 — and the **2D empty state** for both
  APR1400 files.
- Clicking a cell populates the inspector; so does Enter on a focused cell
  after arrow-key navigation.
- Section viewer renders 292 raw lines with line numbers for the SYMGRP
  section; search for "H226" selects site M-01 and returns 3 text hits, and
  clicking one jumps the viewer to line 253 highlighted.
- Every layer on every sample exercised, including Control rods (289 OUT cells,
  ARO banner) and 2PLO (text).
- Filters dim non-matching cells (128 of 193 dimmed for one BEAVRS fuel type);
  flagged-only leaves exactly the 20 flagged members.
- Theme toggle cycles auto → light → dark; dark theme screenshotted.
- Upload errors surface the backend `detail` verbatim ("No SIMULATE-3 sections
  were recognised…", "Uploaded file is empty.") without discarding the loaded
  run.
- `document.documentElement.scrollWidth === clientWidth` on all three samples —
  no horizontal page scroll.
- `read_console_messages` reports **no logs and no errors** after the full pass.

## Notes and limitations

- **Per-assembly axial data does not exist in these listings.** Every variable
  carries the `2` prefix ("2D assembly" basis) and `axialState` is core-average
  only, so the axial chart plots the core average and says so in its caption.
  If a future payload adds a 3D per-assembly edit, `renderAxialChart` is the
  single place to overlay it.
- The axial node selector highlights the node in the profile chart and shows
  its full row of values in the inspector. It cannot re-colour the core map,
  because no per-assembly axial values are available to colour it with.
- BEAVRS fuel-type counts differ per type between the map and
  `assemblyTypes[].countInCore` (32 vs 38 for type 6) because 16 positions use
  types 13–20 that the listing never describes. Totals agree at 193; the UI
  shows both and marks the per-row difference rather than hiding it.
- The step slider re-renders the map and all three charts synchronously on
  every `input` event. At 241–289 cells this is imperceptible; a much larger
  core would want a rAF coalesce in `onChange`.
