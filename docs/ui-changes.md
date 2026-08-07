# UI change set

Fourteen requested changes to the dashboard front end. Everything lives in
`s3dash/web/static/` — no build step, no dependencies, no network references.

## What changed

| # | Change | Where |
|---|---|---|
| 1 | App renamed **Vision: Nuclear Core Analysis** | `index.html` (`<title>`, `.brand-title`) |
| 2 | `Sections` tab renamed **Sections & Search** | `index.html`, `views.js` (`VIEW_LABEL`) |
| 3 | RUN metadata card removed from the Sections view | `views.js` (`applyView` hides `#meta-card`) |
| 4 | Section viewer moved directly under the Listing navigator | `index.html`, `app.css` |
| 5 | Core map 20 % larger — cap 500 → 600 px, column 560 → 672 px | `app.css` |
| 6 | `Flagged only` moved from the toolbar into the core map card header | `index.html` |
| 7 | `Export` moved from the toolbar into the header, beside `Load listing` | `index.html` |
| 8 | Export collapsed to one button with a hover / click / keyboard menu, plus a new **PDF Report** item | `index.html`, `app.js`, `api.js` |
| 9 | `Layer distribution` and `Depletion progression` swapped | `index.html` |
| 10 | `Layer` dropdown moved into the Layer-distribution card header; the map keeps its own | `index.html`, `app.js` |
| 11 | Every chart and the core map gained **Export PNG** | `charts.js`, `app.js`, `index.html` |
| 12 | Diagnostics counters filter the list, in the header badge and in the panel | `panels.js`, `app.js`, `state.js` |
| 13 | Every shadow re-aimed: light from the left, so shadows fall right and down | `app.css` |
| 14 | Cards and panels are user-resizable above 900 px | `app.css`, `app.js`, `coremap.js` |

## Notes on the trickier ones

**Sections & Search layout (3, 4).** The view now owns its two cards: navigator
on top, raw-text viewer directly beneath it, both in the main column. Text hits
take a second column, but only once a search has returned something — a body
class drives the grid so the view never carries an empty gutter. The RUN card
still appears on Core map and Plots.

**Export menu (8).** A `<details>` menu: click and Space/Enter toggle it, a
keyboard focus opens it (guarded by `:focus-visible`, or a mouse click would
open and immediately close it), hover opens with a close delay so crossing the
gap to the panel does not dismiss it, and Escape closes and returns focus. The
PDF item fetches `GET /api/run/{id}/report.pdf?step=N` rather than navigating
to it, so the wait can be shown on the item and a backend `{"detail": …}` comes
back as the same error toast every other failure uses. In the standalone
bundle, where there is no server, the item is not offered.

**PNG export (11).** The figures are hand-built SVG painted entirely by CSS, so
the exporter copies each node's computed painting properties onto a clone,
serialises it, and draws it through an `Image` and a canvas at 2×, on an opaque
background. `<title>`/`<desc>` are skipped — never painted, and a sixth of the
nodes on a full-core map. A 15×15 full-core map exports 1200 × 1194 px in about
0.8 s; the charts are far quicker. Nothing is fetched: `XMLSerializer` emits the
SVG namespace itself, which is why the static tree still contains no URLs.

**Diagnostics filters (12).** `state.diagFilter` holds one severity or the
`SYMMETRY` category. A severity narrows the table and drops the symmetry cards;
`SYMMETRY` does the reverse; the pressed counter clears it. A "showing X of Y"
line names the active filter and carries a **Show all** button. The header badge
is now a group of buttons rather than one — each counter applies its own filter
and jumps to the panel.

**Resizable cards (14).** CSS `resize: both` with `overflow: auto`, capped at
`max-width: 100%` so a drag cannot push a card out of its grid column, with
`min-width: 220px` / `min-height: 120px` floors. A `ResizeObserver` marks a
dragged card `is-sized` — which hands its inner scroller the height instead of
leaving a hole — and redraws anything measured in pixels once the width has
actually moved. Resizing is switched off below 901 px and any dragged size is
dropped there, so the 900 px and 600 px layouts are untouched. The core map's
label thresholds now consider the host's height as well as its width, because a
card dragged short scales the map by height.

Not resizable: the header, the toolbar, the view tabs and the load dialog —
they are chrome, not content.

## Verified

- All three bundled listings load and every view works: `case_002495.out`
  (17×17 quarter-core 2D), `apr1400.c02.out` (same shape), `9074.out` (BEAVRS
  15×15 full-core 3D, 12 axial nodes, extra `2KIN`/`2RR1`, no FMAP/BAT.EDT).
- Console clean; no horizontal scroll at 1440 / 900 / 600 px; light and dark.
- `grep -rn "http\|cdn\|unpkg\|jsdelivr" s3dash/web/static/` returns nothing.
- `python -m pytest tests/ -q` passes, including the bundle's `node --check`
  and its no-external-references assertion.
