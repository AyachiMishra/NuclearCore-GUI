# UX review — SIMULATE-3 core analysis dashboard

Reviewed at commit prior to the UX pass, against all three bundled samples
(`case_002495.out`, `apr1400.c02.out`, `9074.out`), light and dark themes,
viewports 600 / 900 / 1440 px.

Colour claims in this document are **measured, not eyeballed**: OKLab lightness,
WCAG contrast, printed-greyscale ordering and Machado–Oliveira–Fernandes (2009,
severity 1.0) protanopia / deuteranopia / tritanopia simulation were computed for
every ramp step. The categorical palette was run through the `dataviz` skill's
`validate_palette.js`.

---

## Verdict

The tool is already *substantially* correct where most dashboards are wrong: it
drives the grid off `geometry.iafull`, builds the layer list from
`variableOrder`, excludes `2PLO` from colour scales, labels `2EXP` `GWD/T` from
the payload, distinguishes withdrawn rods from inserted-by-zero-steps, and
labels `equivalentAssemblies` as height-weighted with a footnote. The 2D and
ARO empty states are genuinely good — they *explain themselves with evidence*
(`geometry.fuelNodes = 1 · kd = 1 · axialState.nodes is empty for every step`)
rather than showing a blank chart. No `undefined` / `null` / `NaN` leaks into
the DOM on any sample.

The real problems are elsewhere: **measurable accessibility failures in text
colour**, **a colour-to-ink rule that is provably wrong in the middle of the
ramp**, **ragged numeric precision**, **an input handler that misses frame
budget**, and — the largest — **three whole payload blocks that the UI never
renders at all**. For a tool whose product is numbers, silently dropping 25
labelled physics values per state point is the most serious finding here.

---

## Superseded by direct user instruction

The user issued four direct instructions mid-review. Where my own findings
conflicted, theirs win. Dropped or changed as a result:

| My finding | Status |
|---|---|
| The single-scroll layout puts the map, three charts and the section viewer in one column; the map dominates and the charts are below the fold. I was going to propose collapsing the chart grid and making the section viewer a drawer. | **Superseded** — replaced by the three-view split (Core map / Plots / Sections) the user specified. Better answer than mine. |
| I judged the *direction* of the existing viridis ramp (dark = low, light = high) acceptable, since viridis is monotonic and CVD-safe as-is; my planned change was hue, not direction. | **Superseded** — user requires light = low, dark = high. Implemented, and it is the better default: it matches `report.py`, so screen and print now agree. |
| Considered a **diverging** scale centred on 1.0 for `2RPF`. | **Rejected, with reasoning** (below). |
| I proposed keeping the metadata strip in the header but letting it wrap to two rows. | **Superseded** — moved to the left column, which also fixes the truncation bug properly rather than papering over it. |

### Why not a diverging scale for `2RPF`

`2RPF` really is polar data — relative power fraction is centred on 1.0 by
construction, and a diverging ramp would make over/under-powered assemblies pop
instantly. I decided against it, for three reasons that hold independently of
the user's instruction:

1. A diverging ramp is **light in the middle and dark at both ends**. It is
   therefore *not* monotonic in lightness, so it does not survive greyscale
   printing (0.7 and 1.3 print as the same grey) and it breaks "darker always
   means more". The user's instruction #2 requires exactly the opposite.
2. It would apply to `2RPF` only. `2EXP`, `2PIN`, `2KIN`, `2RR1` are not
   centred on anything, so the map's encoding would change meaning depending on
   which layer is selected — the worst possible property for an instrument.
3. Auto-detecting "is this centred on 1.0?" is fragile and would silently
   change the encoding as the data changed.

The over/under-1.0 reading is preserved a different way: the histogram carries a
mean marker, and the legend states the true numeric domain.

---

## Critical

### C1. Cell-label ink is chosen by a threshold that is provably in the wrong place

`coremap.js:79` — `return L > 0.42 ? '#10161d' : '#f4f8fb';`

The crossover between the two inks should sit where they contrast equally with
the fill. For this ink pair that is at relative luminance **0.188**, not 0.42.
Every fill with relative luminance between 0.19 and 0.42 therefore gets *white*
text where black was the better choice, and at the top of that band white text
lands at **2.09:1** — less than half the 4.5:1 AA floor.

Measured on the ramp actually shipping: `#35b779` (viridis step 6, a mid-power
cell) renders white text at **2.4:1**. Visible in the core-map screenshot as the
washed-out `0.984` / `0.913` cells in row 1.

**Fix:** choose whichever ink actually contrasts more, and widen the ink pair to
pure black/white on data tiles. Measured worst case after the fix: **4.98:1**
(light ramp), **4.67:1** (dark ramp), **4.85:1** (categorical) — AA on every
step of every scale.

### C2. `--text-faint` fails WCAG AA in both themes

Measured in-browser against the computed surface colours:

| Token | Light on `--panel` | Dark on `--panel` | Dark on `--panel-3` |
|---|---|---|---|
| `--text-faint` (was `#8593a3` / `#6d7d8e`) | **3.13:1** | **4.07:1** | **3.80:1** |

Required: 4.5:1 — every consumer of this token renders at 9.5–11 px, so the
large-text relief does not apply. It is not decorative text either; it carries
the core-map subtitle (`17×17 lattice · 241 fuelled positions · step 19`), the
legend footer, every `.meta-k`, per-step exposures in the navigator, `.hint`,
`.foot-note`, `.sample-size` and `.muted`.

**Fix:** re-solved in OKLCH holding hue and chroma, minimum lightness that
clears 4.5:1 on `--panel`, `--panel-2` **and** `--panel-3`:
`#616e7d` (light) → 5.19 / 4.83 / 4.50; `#8191a3` (dark) → 5.32 / 4.97 / 4.51.

### C3. Three payload blocks are parsed, documented, and never rendered

`grep` over `js/` for `batchEdits`, `\.summary`, `maps\.` returns **nothing**
outside `axialState.summary`.

| Block | Content | Sample |
|---|---|---|
| `statePoints[].summary` | **25 labelled values per step**, each with a unit and its SIMULATE code — Thermal Power 3983.8 MWt, Core Flow 131093 MT/hr, Inlet 563.71 K, Coolant Average 573.67 K, Depletion Step Length 6.288 Hours … | all three |
| `statePoints[].batchEdits` | per-batch peaking (`NPIN`, `NXPO`) **with the limiting assembly** — batch 3, 121 assemblies, 1.589, label `H-16`, serial `F-149`, location `(14, 3, 1)` | APR1400 only |
| `maps.fmap` / `maps.cmap` | PRI.INP loading maps | APR1400 only |

This is the biggest single gap. The brief asks whether BEAVRS's *absence* of
FMAP and batch edits "reads as not-present or as a bug" — neither: there is no
panel at all, so BEAVRS's absence is invisible **and** APR1400's presence is
lost data.

**Fix:** render `summary` and `batchEdits`, each with an explicit
"not present in this run" state. `maps.fmap`/`cmap` are near-duplicates of
`assemblies[]` (label / serial / type+rotation, already in the tooltip and
inspector) — I surface their *presence* rather than re-drawing the grid, so the
BEAVRS case reads as a deliberate "not edited in this run".

---

## Important

### I1. `fmt()` produces ragged precision — in the same sentence

```js
value.toFixed(digits).replace(/\.?0+$/, (m) => (m.includes('.') ? '' : m))
```

The regex strips trailing zeros **only when the whole fractional part is zero**,
so `0.43 → "0.4300"` but `1.0 → "1"`. Observed side by side:

- legend: `0.4300  0.8870  1.3440` — but the axial reference line in the same
  view reads `core ave 1`
- header: `0–24.112 GWd/MT` (0 dp and 3 dp in one range) and `0–601 EFPD`

For an instrument whose product is numbers, ragged decimals read as sloppiness.
**Fix:** fixed decimals, always. Additionally, the core map now derives **one
precision for the whole layer** from its extent, so every cell in a layer has
the same number of decimals — which is what an engineering table does.

### I2. The step slider misses frame budget

Measured: one `input` event costs **19–27 ms** and rebuilds **1260 SVG nodes**
plus three charts and the inspector, synchronously. The frame budget is 16.7 ms,
so dragging across 31–32 steps stutters — exactly the symptom the brief asks
about. **Fix:** coalesce renders into one `requestAnimationFrame`; repeated
`input` events inside a frame collapse to a single render.

### I3. The "symmetry-expanded" hatch covers three quarters of the map

`API_CONTRACT.md` calls for this to be indicated "subtly". On a quarter-core
case ~75 % of positions are expanded, so the hatch is drawn over most of the
map, striping the numbers. Because it is the *majority* state it also carries no
discriminating information in that form. **Fix:** far lighter hatch, and invert
the mark when expanded positions are the majority so the ink lands on the
minority — the calculated quadrant is what the reader actually wants to find.

### I4. In the ARO state the control-rod map is 225 identical tiles

All three samples are ARO at **every** step (`inserted` is empty for all 31/28/32
state points), so this is the *only* rod view a user of these files will ever
see: a 15×15 or 17×17 grid of the word "OUT". It is a screenful of zero
information. **Fix:** when ARO, collapse to a compact drive-position schematic
plus the statement, keeping the layout of the drive grid visible.

### I5. Symmetry violations don't show *by how much* a position disagrees

The brief asks explicitly. The group card lists members with `aveExp` and the
four quadrant exposures, but the reader has to do the subtraction. **Fix:** show
each member's signed deviation from the group mean and flag the extreme member;
show the max quadrant spread per member.

### I6. The hover tooltip is a 347 px wall

Measured 291 × 347 px — 39 % of a 900 px viewport — and it duplicates the
Inspector panel almost exactly. A hover card should answer "what is this?" in
one glance; the full breakdown is what click-to-select is for, and that already
works. **Fix:** compact hover card (identity, the active layer's value, flags);
full detail stays in the Inspector. Also added a `max-height` + scroll guard,
since with six value codes on BEAVRS plus a short viewport the card could exceed
the screen with no way to see the bottom.

### I7. `scrollIntoView({behavior:'smooth'})` ignores `prefers-reduced-motion`

Four call sites in `app.js` (`gotoLine`, nav-tree leaf, `data-select-rc`,
status badge). The CSS honours the preference for the spinner but the JS does
not. **Fix:** read the media query and fall back to `'auto'`.

### I8. Metadata strip truncation (user-reported — confirmed)

Measured at 1440 px: three of six values are clipped.

| Field | Shown | Needed |
|---|---|---|
| Plant / case | 173 px | **434 px** |
| Geometry | 173 px | **320 px** |
| Execution time | 173 px | **200 px** |

`grid-template-columns: repeat(3, minmax(0,1fr))` plus
`.meta-v { white-space: nowrap; text-overflow: ellipsis }` guarantees this for
any case title of normal length. Below 980 px the strip is `display:none`, so
on a narrow screen the run identity vanishes entirely. **Fix:** per instruction
#3, moved to the left column and allowed to wrap.

---

### I9. The header overflows off-screen below ~1120 px

Found while implementing. `.app-header` was `flex-wrap: nowrap`; at a 900 px
viewport its three children measured brand 204 + view nav 236 + actions 566 =
**1056 px against 885 px of space**. The overflow was invisible only because
`html, body { overflow-x: hidden }` clipped it — which means the theme toggle
and part of the Load button were *unreachable*, not just ugly. The old header
had the same failure mode with the metadata strip absorbing the slack.

**Fix:** the header wraps, and below 1120 px the view nav takes its own row.

### I10. The filter dropdown ran off the viewport

`.menu-body` was `left: 0; min-width: 220px` inside a `position: relative`
wrapper. At 600 px the panel measured left 421 → right **641** against a 600 px
viewport, so a third of the fuel-type checkboxes sat in the clipped region.
**Fix:** anchored to its right edge with a viewport clamp, and below 1000 px —
where the toolbar wraps and the control can land anywhere on the row — it spans
the toolbar instead of guessing an edge.

## Polish

- **P1.** Axial-profile bars are filled from the sequential ramp by their own
  value — colour re-encoding what bar length already shows, for no gain (the
  axial chart shares no encoding with anything else). Single hue instead, with
  the selected node highlighted. *(The histogram keeps the ramp: there it is
  a shared encoding with the core map, not decoration.)*
- **P2.** The symmetry flag triangle is `--err` (`#a32218`) with no outline; on
  the dark end of the new ramp (`#642d27`) that is 1.6:1. Given a contrasting
  outline.
- **P3.** `meta.restartExposure` is printed with no unit.
- **P4.** `segments[].loading` and `bpLoading` columns carry no unit — see
  *Data observations*.
- **P5.** Legend numbers now use the layer's derived precision, so the legend
  and the cells agree digit for digit.
- **P6.** Theme switching did not re-render the core map; with per-theme ramps
  it must. The OS flipping the theme while in `auto` has the same problem, so
  that is watched too.
- **P7.** *(consequence of C2)* Darkening `--text-faint` for AA left it only
  0.4 of a ratio point from `--text-dim`, collapsing the three ink levels into
  two. `--text-dim` was re-solved as well, restoring a legible ramp:
  16.5 / 7.4 / 5.2 (light), 13.5 / 8.0 / 5.3 (dark).
- **P8.** *(consequence of I1)* With `fmt` no longer stripping zeros, chart axes
  inherited the caller's 4 decimals and printed `0.0000  5.0000  10.0000`. Tick
  precision is now derived from the tick step, so a step of 5 prints `0 5 10`
  and a step of 0.02 prints `1.14`.
- **P9.** Filters dimmed cells with no statement of what was withheld — a dim
  cell reads as "no data". The card head now says
  *filtered to 20 of 241, 221 dimmed* in warning ink whenever a filter is on.

---

## Verified as already correct — deliberately left alone

- **The categorical palette.** Okabe–Ito-derived. `validate_palette.js --mode
  light`: lightness band PASS, chroma floor PASS, normal-vision floor PASS
  (20.0), CVD separation WARN at ΔE 7.6 for `#cc79a7 ↔ #009e73`, contrast WARN
  on four slots. Both WARNs are *legal with secondary encoding*, and the
  secondary encoding is present and unavoidable here: every categorical cell
  prints its own value, and the legend lists value + name + count. Re-stepping
  Okabe–Ito to chase ΔE 8 would trade a recognised CVD-safe standard for a
  marginal number. **No change.**
- **Grid sizing, layer building, `2PLO` exclusion, `exposureUnit` handling.**
  All read from the payload; BEAVRS correctly gains `2RR1`/`2KIN`, correctly
  loses the Batch layer (`batch` is null for all 193 assemblies), and correctly
  labels `2EXP` as `GWD/T`.
- **The 2D and ARO empty states.** Already excellent — they cite the evidence.
  Left as they are.
- **`equivalentAssemblies`.** Already labelled "Equivalent assemblies" with the
  height-weighting footnote. Correct.
- **Withdrawn vs 0-steps-inserted.** Already distinct in fill, text and ARIA.
- **Null handling.** 8 BEAVRS fuel types with no description already render
  `—`. Zero `undefined`/`null`/`NaN` in the rendered DOM on all three samples.
- **`parseNotes`.** Already surfaced in a notice strip when non-empty. Empty on
  all three samples, so the strip is correctly hidden; the code path is sound.
- **Control-rod ramp direction.** The CRD layer deliberately inverts (`1 - t`)
  so that *darker = more deeply inserted*, because the plotted number is the
  withdrawal position — a rod that is fully out is the null state and must not
  be the heaviest mark. This is a semantic inversion of an already-inverted
  quantity, not a violation of "darker = more"; the legend now says so
  explicitly.

---

## Data observations — reported, not fixed

Per the brief these are **not** changed; the parser is verified.

1. **`segments[].loading` and `segments[].bpLoading` carry no unit anywhere in
   the payload.** `assemblyTypes[].loadingGrams` does (grams, rendered as kg),
   but the segment table's `loading` (e.g. `2.63569`) has no declared unit, so
   the UI cannot label it without inventing one. The column is therefore
   rendered unitless. If the listing states a unit for these, exposing it on
   `segments[]` would let the UI label the column.
2. **`statePoints[].summary` contains a key `'D-ACTUAL)'`** with a stray closing
   parenthesis (value `8.2e-05`, unit `CM-2`) in every sample. Looks like a
   label-capture artefact from a parenthesised source line. Harmless — it is
   rendered verbatim as a row label — but worth a look.
3. **`assemblies[].subType` and `previousLocation` are null for 100 % of
   assemblies in all three samples**, and BEAVRS additionally has `batch`,
   `serial` and `rotation` null for all 193. Consistent with the listings; noted
   only so it is not mistaken for a UI bug when those rows are absent.
4. `inventory[]` for BEAVRS has 8 rows (types 13, 14, 15 and others) with null
   `typeName` and null `segment` but a non-zero count — positions carrying a
   fuel type the listing never describes. The UI shows `—`; the tally still
   reconciles to 193.

---

## Changes made

| # | Change | Driver |
|---|---|---|
| 1 | Three views (`#/map`, `#/plots`, `#/sections`) with hash routing, ARIA tablist, keyboard nav, state preserved across switches | user #1 |
| 2 | Sequential ramp inverted to light = low / dark = high; separate validated light and dark anchor sets | user #2 |
| 3 | Metadata moved to a stacked card at the top of the left column, values wrap | user #3 |
| 4 | Core map capped to ~0.7× with adaptive cell text and per-layer precision | user #4 |
| 5 | Best-of-two ink selection for cell labels | C1 |
| 6 | `--text-faint` re-solved for AA in both themes | C2 |
| 7 | Output summary + batch edits rendered, with explicit not-present states; FMAP/CMAP presence surfaced | C3 |
| 8 | `fmt()` fixed decimals; per-layer precision on the map and legend | I1 |
| 9 | rAF-coalesced re-render | I2 |
| 10 | Hatch weight reduced and inverted when expansion is the majority | I3 |
| 11 | Compact ARO rod schematic | I4 |
| 12 | Per-member symmetry deviation and quadrant spread | I5 |
| 13 | Compact hover card + max-height guard | I6 |
| 14 | `prefers-reduced-motion` honoured in JS scrolling, plus a global CSS guard | I7 |
| 15 | Header wraps instead of overflowing; filter popup clamped to the viewport | I9, I10 |
| 16 | Axial bars single-hue; flag outline; restart-exposure unit; theme re-render | P1–P6 |
| 17 | `--text-dim` re-solved; axis tick precision from tick step; filter withholding stated | P7–P9 |
| 18 | Only the visible view renders; entering a view redraws it from state | I2 |
| 19 | Print stylesheet reworked for the three views — all of them print, in order | §7 |

### Verification

| Check | Result |
|---|---|
| `python -m pytest tests/ -q` | **177 passed** (no Python touched) |
| Console errors, 3 samples × 2 themes × 3 views | **none** |
| Horizontal scroll at 1440 / 900 / 600 px, all views | **none** |
| `undefined` / `null` / `NaN` / `[object Object]` in the DOM | **none**, all samples |
| Network references (`http`, `cdn`, `unpkg`, `jsdelivr`) under `static/` | **none** |
| Cell-label contrast, measured on the live SVG over 193 cells | worst **5.20:1** |
| `--text-faint` on panel / panel-2 / panel-3 | 5.20 / 4.84 / 4.52 light · 5.32 / 4.97 / 4.51 dark |
| Step-slider drag, 120 input events | **30 renders** (one per frame) instead of 120 |

### Ramp verification after the change

```
NEW light ramp  #f7f4ec → #642d27      NEW dark ramp   #e2dfd8 → #814942
  monotonic in OKLab L ............ PASS       PASS
  monotonic in printed greyscale .. PASS (min step 19.4/255)   PASS (14.5/255)
  protanopia ordering ............. PASS       PASS
  deuteranopia ordering ........... PASS       PASS
  tritanopia ordering ............. PASS       PASS
  darkest step vs panel ........... 10.79:1    2.42:1  (was 1.57:1 un-anchored)
  worst cell-label contrast ....... 4.98:1     4.67:1
```

The hue spine is taken from `report.py`'s ramp, so the interactive map and the
standalone HTML report now read as the same instrument. The dark-mode set keeps
the same hue path but is re-anchored in lightness (0.905 → 0.470 instead of
0.968 → 0.372) so the high-value end still separates from `--panel` — the naive
reuse of the light anchors would have put the darkest cells at 1.57:1 against
the dark panel, i.e. invisible.
