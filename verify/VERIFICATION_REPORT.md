# SIMULATE-3 parser — numerical verification report

**Verdict: PASS, after seven defects were found and fixed.**

Every value the parser publishes for the three reference listings has been
re-extracted from the raw bytes by an independent implementation and compared.
**147,151 comparisons, 0 remaining discrepancies.** Seven parser defects were
proved against the raw files during the sweep and are all fixed; each is
described below with file-and-line evidence.

| | `case_002495.out` | `apr1400.c02.out` | `9074.out` |
|---|---:|---:|---:|
| Values compared | 46,104 | 41,560 | 59,487 |
| Discrepancies remaining | 0 | 0 | 0 |

Regenerate at any time:

```
python verify/check_all.py            # console summary, exit 1 on any mismatch
python verify/check_all.py --report   # also rewrites verify/RESULTS.md
python -m pytest tests/test_verification.py -q
```

---

## Method

The rule was: **never validate the parser using the parser.** For every
category, the expected value is recovered from the listing by `verify/raw.py`
using a *deliberately different* technique from `s3dash/parser`, so a shared
mistake cannot cancel out:

| Data | Parser's technique | This report's technique |
|---|---|---|
| Core maps | midpoint cuts between column-ruler tokens | fixed-pitch character windows anchored on each ruler token's **right edge**, pitch derived from the ruler |
| Output Summary | one regex per dot-leader entry | split the line on the dot run, read the tail of each segment |
| Depletion table | one anchored full-row regex | whitespace tokenisation with positional field indices, after splitting the `AX/K` slash apart |
| Diagnostics | column slicing on the dash rule | same rule, independently located, plus a whole-table sweep for echoed rows |
| `PRI.INP` grids | slice on `+` positions of the rule line | same `+` positions found independently, with `:`-delimited cell text |
| Symmetry expansion | `expand_to_full_core` | 90° orbit `(r,c) → (c, n+1−r)` derived from the geometry here, in the checker |
| Fuel types (BEAVRS) | `FUE.TYP` matrix via the input-deck parser | `FUE.TYP` matrix re-read straight from the echoed card |

Map cells are compared **exactly** (`float` equality via a 1e-12 relative
tolerance, and byte-exact string equality for `2PLO`). Nothing is sampled —
all 53,340 printed map cells across all 91 state points are compared.

---

## What was checked, and how much

Counts are comparisons performed, per category per file. Full machine output:
`verify/RESULTS.md`.

| Category | `case_002495` | `apr1400.c02` | `9074` |
|---|---:|---:|---:|
| 1. Core maps — every cell, every state point | 8,556 | 7,728 | 37,056 |
| 2. Ragged rows / null placement | 1,116 | 1,008 | 2,880 |
| 3. Symmetry expansion | 30,009 | 27,105 | n/a (full core) |
| 4. Non-numeric map round-trip (`2PLO`) | 2,139 | 1,932 | 6,176 |
| 5. Per-state-point scalars | 776 | 701 | 801 |
| 6. Depletion table | 590 | 533 | 609 |
| 7. Axial distributions | 992 | 896 | 11,360 |
| 8. Diagnostics roll-up | 90 | 74 | 46 |
| 9. Symmetry groups | 306 | 78 | 2 |
| 10. Assembly identity | 1,305 | 1,301 | 387 |
| 11. Cross-source consistency | 219 | 198 | 162 |
| 12. Units | 6 | 6 | 8 |
| **Total** | **46,104** | **41,560** | **59,487** |

### 1. Core maps — the headline check

Every `PRI.STA` / `PIN.EDT` map block was located independently (124 / 112 /
192 blocks), its cells read as fixed-width character windows, and every cell
compared against `statePoints[i].values[code][assemblyIndex["r,c"]]`.

* `case_002495` — 4 codes × 31 steps × 69 printed cells = **8,556** cells.
* `apr1400.c02` — 4 codes × 28 steps × 69 cells = **7,728**.
* `9074` — 6 codes (`2RPF 2KIN 2EXP 2PIN 2PLO 2RR1`) × 32 steps × 193 cells =
  **37,056**.

**Zero mismatches.** The banded-map primitive is correct on both a 9-column
quarter-core layout and a 15-column full-core one, and no map block, code or
state point is missing from the payload.

### 2. Ragged rows and nulls

BEAVRS rows are ragged: row 1 prints seven values that belong to **columns
5–11**, not 1–7. Verified for every ragged row of every map that

* the printed columns are exactly the contiguous run the geometry requires
  (no holes, no off-by-one shift), and
* positions with no printed value are absent from `assemblyIndex` entirely
  (`"1,4"` and `"1,12"` do not exist) rather than being zero-filled.

Across all 91 state points × all codes, **not one `null` appears in any value
array** — every fuelled position has a value in every map, which is what these
runs print. No position is ever zero-filled.

### 3. Symmetry expansion (quarter → full core)

For `case_002495` and `apr1400.c02` the 90° rotational orbit was derived from
the geometry inside the checker and applied to every printed cell. Verified:

* every printed value appears **unchanged** at its printed coordinate
  (never overwritten by an image) — including the genuine asymmetries the
  SYMGRP check exists to report, e.g. `2EXP` at line 2572/2573 prints
  `29.911` at (13,14) and `29.910` at (14,13), and both survive;
* every expanded position equals its correct rotational image;
* the expanded footprint equals the assembly list **exactly**, and the count
  matches the listing's own `Fuel Assemblies . . . 241.0000` in the Input
  Summary;
* the expansion is never *ambiguous*: positions on the centre row and centre
  column are printed twice within one orbit, and in these files the two
  prints always agree exactly, so no expanded cell had to choose between two
  candidate values. (The checker counts and reports such cases; the count is
  zero for both files.)

### 4. Non-numeric maps (`2PLO`)

10,247 pin-location cells across the three files round-trip **byte for byte**,
including the internal space in `10, 9` / `1, 1` and the 3,966 BEAVRS cells
containing `*`. Every one is a `str` in the payload, never coerced to a
number, and the symmetry expansion carries the exact string.

### 5–6. Scalars and the depletion table

`keff`, `coreExposure`, `peakNodal`, `axialOffset`, `boron`, `exposure` and
`exposureUnit` checked for all 91 state points against their own Output
Summary block and page banner, plus every dot-leader entry re-read
independently. Every row × every one of 17 columns of the end-of-run
`Summary of Steady-State` table checked (91 rows, 1,547 field comparisons).
The table is echoed line-for-line in all three files; the echoed copies were
confirmed **byte-identical** before accepting the de-duplication, and the
de-duplicated row count exactly equals the state-point count (31 / 28 / 32) —
no step dropped, none duplicated.

### 7. Axial distributions

For `9074`, all 12 nodes × all columns of both blocks for all 32 state points.
Confirmed the file prints **top node first** (node 12) and the payload is
ordered node 1 → 12 with each node's values still attached to its own node
number — normalised, not silently reversed (`nodes[0]["RPF"] == 0.57392`,
the value printed on the *last* line of the block, line 1334). The `Ave` row
agrees with the unweighted mean of the nodes to within 0.5 % for every column.

### 8–9. Diagnostics and symmetry groups

Every row of the `Summary of Errors/Warnings/Cautions and Notes` table
compared field by field, including `times`. The doubled/echoed table did not
double the counts: 34 printed rows → 21 distinct in `case_002495`, and the
summed `times` reproduce `status` exactly (71 warnings / 33 cautions /
40 notes). All 8 + 2 `ERR.CHK - SYMGRP` blocks compared member by member —
row, col, label, fuel type, rotation, average exposure and all four quadrant
exposures.

### 10. Assembly identity

Site labels checked against the column footers the listing prints under every
map (`** J- H- G- ... **`) and against the site names embedded in the CMAP
rule (`+J-09--+`). `FMAP` labels, serials and rotations compared for all 289
grid cells; `CMAP` fuel type and batch for all 69. For BEAVRS (no `FMAP`,
no `CMAP`) every one of the 193 fuel types was compared against the echoed
`'FUE.TYP'` matrix, offset by `NREF`. Per-type counts equal the `Fueled
Segments` equivalent-assembly column where the two numbering schemes coincide,
and the column total accounts for every assembly in all three files.

### 11–12. Cross-source consistency and units

Where the listing states a quantity twice, both statements were checked
against the payload: k-eff (Output Summary vs depletion table), cycle and core
exposure (page banner vs Output Summary vs table), and the assembly count
(Input Summary vs `BAT.EDT` `CORE` row vs the maps — 118 `CORE` rows).
Units are read, never assumed: `2EXP` is labelled from its own heading
(`GWD/T`), and the cycle exposure unit is `GWd/MT` for the APR1400 files and
`EFPD` for BEAVRS.

---

## Defects found and fixed

All seven were proved against the raw listing before any code changed.
13 of the 32 tests in `tests/test_verification.py` fail against the pre-fix
parser (verified in a throwaway worktree) and pass after.

### D1 — `peakNodal` was `null` on every state point *(all 3 files, 91 values)*

`Peak Nodal Power (Location)     1.424 (16,10, 1)` (`case_002495` line 2622)
is the only Output Summary entry printed **without a dot leader**, so the
generic key/value scan never saw it. `statePoints[i].peakNodal` was `null`
everywhere, contradicting the documented contract (`"peakNodal": 1.424`).

*Fix:* `sections.parse_summary_peaks()` reads the peak block by name
(`Peak Nodal Power`, `F-delta-H`, `Max-Fxy`, `Max-3PIN`, `Max-4PIN`) and
`build` merges it into `summary` without displacing a real dot-leader entry.

### D2 — a state point could take another step's exposure and unit *(all 3 files)*

`page_ctx.setdefault((case, step), page)` bound each state point to the
**first** page bearing its `Case n Step m` label. But SIMULATE-3 repeats that
label on every page it prints while working on the step — including the trial
pages of an exposure search — and the banner reports the *current* trial, not
the result.

* `case_002495` step 30: banner at line 10450 says `25.050 GWd/MT`; the step's
  own Output Summary (line 10733: `Cycle Exp. 631.8 EFPD ... 24.112 GWd/MT`),
  its maps (line 10671) and the depletion table (line 10964) all say
  **24.112**. The payload published 25.050, and `meta.cycleEnd` with it.
* `apr1400.c02` step 27: 22.05 published vs 21.685 actual.
* `9074`: the pre-run page for step 0 (line 221) reads `0.000 GWd/MT`, so
  `statePoints[0].exposureUnit` and therefore **`meta.exposureUnit` for the
  whole file** came out `GWd/MT` — for a run whose cycle exposure is in
  `EFPD`. A dashboard would have mislabelled every depletion axis.

*Fix:* `build._state_page()` anchors on the page carrying the state point's
own report (its Output Summary), falling back to its maps, then to any page
with the label.

### D3 — sparse axial summary rows landed in the wrong column *(9074, 64 values)*

`P**2` prints a single number under `EXPO` (`9074` line 1337, characters
27–34). `dict(zip(columns, vals))` assigned it to `RPF`, so
`axialState.summary["P**2"]["RPF"]` held the exposure-squared metric and
`["EXPO"]` was missing — a wrong number under a plausible name, in every one
of the 32 state points.

*Fix:* rows whose value count differs from the column count are placed by
character position (nearest column-heading right edge); full rows are still
zipped, which is exact.

### D4 — two thirds of the axial depletion arguments were dropped *(all 3 files)*

The depletion block prints more variables than fit the page width, so it
repeats its `K ...` header with further columns (`9074` line 1368;
`case_002495` lines 2651 and 2655). The parser stopped at the second header,
publishing 9 of 18 columns for BEAVRS and 9 of 20 for the APR1400 files.
`HVO HCR EY- EX+ EY+ EX- HIS HY- HX+ HY+ HX-` were silently absent.

*Fix:* every sub-table is merged into the same node rows and summary rows.
`axialDepletion.columns` is now 18–20 long. Documented in the contract.

### D5 — side-by-side symmetry cards were lost *(case_002495, 4 of 24 members)*

`SYMGRP` cards are placed at the page column mirroring the assembly's core
position, so two cards routinely share the same lines:

```
                      F1                                F2
               |( 9, 4)=C-03  |                  |( 9,14)=R-15  |
```

Only the first `|...|` on each line was read, so groups D, E, F and G each
lost their second card, and D1/F1 were reported with tag `?`. Group D
publishes `[('?',9,5), ('D0',13,9)]` instead of `D1 (9,5)`, `D2 (9,13)`,
`D0 (13,9)` — a symmetry-violation report missing a third of its evidence.

*Fix:* every box on a line is collected with its column centre and routed to
the card occupying that column; tag lines are matched the same way.

### D6 — the diagnostics `Where` column was split in half *(2 files, 10 rows)*

`(?P<where>\S+)` cannot hold a two-word column. `SYMGRP A 1 WARNING RES STEP
not quarter rotational` (line 10818) parsed as `where="RES"`,
`info="STEP   not quarter rotational"` — contradicting the documented contract
(`"where":"RES STEP","info":"not quarter rotational"`).

*Fix:* fields are cut on the table's own `----- ----- ...` rule (field *k*
spans dash-group *k* start → dash-group *k+1* start), with the old regex kept
as a fallback when no rule is present. The de-duplication key now includes
`info`, so two rows differing only in their message cannot be collapsed.

### D7 — symmetric positions described the same assembly differently *(2 files, 139 positions)*

`FMAP` prints the fuel type only inside the calculated quadrant, so
`if a.fuel_type is None:` used CMAP for the *expanded* positions and not for
the printed ones. The result was that an assembly and its own rotational image
carried different metadata:

| position | printed | fuelType | batch | enrichment |
|---|---|---:|---:|---:|
| (9,10) | yes | 5 | `null` | 3.76667 |
| (9,8) — its image | no | 5 | 1 | 3.77 |

*Fix:* CMAP is consulted for every position (batch and, as a fallback, fuel
type); enrichment always prefers the 5-decimal `Fueled Segments` value over
CMAP's 2-decimal print, so all four orbit members now agree exactly.

### Also changed — variable units are read, not tabulated

`describe_variable()` returned a unit from a table keyed on the edit code, so
`2EXP` was labelled `GWd/MT` while its own heading says
`Assembly 2D EXPOSURE  - GWD/T`. It now takes the unit from the section
heading when the heading names one (a unit token carries a solidus, which
distinguishes it from a trailing descriptive word such as `- K-infinity`), and
falls back to the table only when the heading is silent.

---

## Disagreements *in the source itself*

Not parser bugs; recorded because a reader of the dashboard may notice them.

1. **`case_002495` step 30 is printed at two different exposures** — 25.050 on
   its first pages (lines 10450, 10484) and 24.112 after the EOL search
   converges (lines 10617 onward, `NQ = 13`). Same for `apr1400.c02` step 27
   (22.05 → 21.685). The payload now reports the converged value, which is
   what the maps on those pages and the end-of-run table both use.
2. **`9074` labels its pre-run page `GWd/MT`** (line 221) in a run whose cycle
   exposure is otherwise in `EFPD` throughout.
3. **`apr1400.c02` `Fueled Segments` equivalent assemblies sum to 241.001**,
   not 241 — the segments are axially zoned so the per-segment equivalents are
   fractional and printed to 3 dp. Accepted within 0.01.
4. **`case_002495` prints eight quarter-core symmetry violations** (`2EXP`
   differences of 0.001 GWd/T between rotational images). These are real and
   are preserved rather than smoothed over by the expansion.

---

## What could not be verified

* **`2PLO` `*` cells.** 3,966 BEAVRS pin-location cells contain `*`
  (e.g. `14*13`). They round-trip byte for byte, which is all the payload
  promises. What SIMULATE-3 means by the `*` is not stated anywhere in these
  listings, so no *semantic* check was possible.
* **Peak-power locations.** `Peak Nodal Power (Location) 1.424 (16,10, 1)` —
  the value is now published; the `(16,10, 1)` coordinate is not a payload
  field, so it was checked as text only, not cross-referenced against the
  `2PIN` map.
* **`QMAP` / `BMAP`.** Parsed into `doc.sections` but not published in the
  payload (only `fmap` and `cmap` are), so there is nothing to compare.
* **Non-echoed input.** Anything the listing never restates (e.g. library
  cross-sections) cannot be checked against itself by definition.
* **Only three files.** Everything here is verified for one 15×15 full-core
  3D BEAVRS run and two 17×17 quarter-core 2D APR1400 runs. Octant symmetry
  (`IHAVE=1`), mirror symmetry, BWRs, and maps wide enough to be split across
  a page break have **no coverage** in the sample set; the code paths exist
  and are unexercised. `python -m s3dash.check <file>` is the right first
  move on a listing from any other plant.

---

## Note on concurrency

Another agent was modifying `s3dash/parser/` during this sweep and its commits
swept in some of the changes above before they were finished. The state
verified here is the working tree as of this report: `python -m pytest tests/
-q` → **177 passed**, `python verify/check_all.py` → **0 problems**.
