# Vision: Nuclear Core Analysis

Load a SIMULATE-3 output listing (Eg: run192832.out) and understand it without reading eleven
thousand lines of fixed-width Fortran print.

Upload a `.out` file and get an interactive core map, per-assembly inspection,
depletion and axial charts, a symmetry/diagnostics review, and a navigable
index of every section in the file with its original text one click away.

Three views — **Core map**, **Plots**, and **Sections & Search** — sharing one
loaded run, with exports to JSON, CSV, PNG and a formatted PDF report.

![Core map](docs/img/core-map.svg)

<p align="center">
  <img src="docs/img/depletion.svg" alt="Depletion progression" width="62%">
  <img src="docs/img/axial.svg" alt="Axial power profile" width="34%">
</p>

<sub>Rendered from a SIMULATE-3 run of
[BEAVRS](https://crpg.mit.edu/research/benchmark-for-evaluation-and-validation-of-reactor-simulations),
MIT's openly published benchmark: a 15×15 full-core 3D PWR. Regenerate with
`python tools/make_readme_assets.py your_run.out`.</sub>

---

## Running it

```bash
python -m pip install -r requirements.txt
```

```bash
python -m s3dash
```

That starts the server on <http://127.0.0.1:8000> and opens a browser. Drop any
`.out` file on the load panel — it parses server-side in well under a second
for a typical 1 MB listing. Or run uvicorn directly:

```bash
python -m uvicorn s3dash.web.app:app --port 8000
```

**No build step, no npm, no network.** The front end is vanilla ES modules and
hand-written SVG; nothing is fetched from a CDN. It runs on an air-gapped
machine exactly as it runs on a connected one.

### Bringing your own listings

**No `.out` files are committed here.** They are SIMULATE-3 output for specific
plant models and are not ours to redistribute. Anything you drop into
`sample_data/` appears as a one-click button on the load panel:

```
sample_data/
  your_cycle1.out
  your_cycle2.out
```

You never need to do that to use the tool — the upload button reads any file
you point it at, whatever it is named.

### Exports

| Format | What it is |
|---|---|
| **PDF report** | Eight pages: cover, linked contents with page numbers, run summary, core map, every depletion step tabulated, axial distribution (3D runs), inventory and segments, diagnostics with the symmetry breakdown, provenance. Sections that do not apply are omitted rather than left empty. |
| **PNG** | Any chart or the core map, rendered at 2× |
| **CSV** | The assembly table for the current step |
| **JSON** | The complete parsed payload |
| **Print** | Every view as one document |

The PDF is also available directly:
`GET /api/run/{runId}/report.pdf?step=N`

### Sharing a result

To hand someone a finished analysis without asking them to install anything:

```bash
python -m s3dash.bundle your_run.out -o your_run.html
```

That writes one self-contained HTML file — the whole dashboard with the parsed
results baked in, opening on a double-click with no Python and no network. It
carries results, not the parser, so it cannot open *other* listings; for that,
run the server.

---

## Why the parser generalises

SIMULATE-3 can emit around thirty state variables (`RPF`, `EXP`, `KINF`,
`TFU`, `XEN`, …) each on eight different bases (`2`, `3`, `Z`, `Q`, `N`, `P`,
`S`, `X`), which is a couple of hundred possible edit names — before counting
`PIN.EDT`, `BAT.EDT` and `DET.EDT`. Enumerating them would guarantee the
parser breaks on the first file that uses one it had not met.

It does not enumerate them. The listing is built from a small number of
recurring *physical layouts*, and the parser reads those:

| Primitive | Used by |
|---|---|
| Page/banner segmentation | everything — gives every value its case/step context |
| Banded 2D map | **every** `PRI.STA` and `PIN.EDT` variable, control-rod map |
| Bordered cell grid | `PRI.INP` FMAP / CMAP / QMAP / BMAP |
| Dashed-rule table | segments, batch edits, library parameters, diagnostics, depletion |
| Dot-leader key/value | Input Summary, Output Summary, dimensions |
| Framed card cluster | `ERR.CHK - SYMGRP` violation groups |

A variable this parser has never seen still comes through, because its
*shape* is already known. `9074.out` exercises exactly this: it contains
`2KIN` and `2RR1`, which neither APR1400 file has, and both parse with no
code specific to them.

Geometry is likewise read, never assumed. `IAFULL`, `KD`, `IHAVE`, `IF2X2`,
`NREF` and the symmetry mode come out of the echoed dimensions block, and
everything downstream — grid size, quarter/octant expansion, whether axial
data exists — follows from those.

### Verified generality

It was developed against three listings that disagree on every axis that
matters. They are not committed here (see *Bringing your own listings*), but
they are what every claim below was checked against:

| | `case_002495` | `apr1400.c02` | `9074` |
|---|---|---|---|
| Plant | APR1400 C2 | APR1400 C2 | BEAVRS C1 |
| Core width | 17 | 17 | **15** |
| Fraction | quarter | quarter | **full** |
| Axial | 2D (1 node) | 2D | **3D (12 nodes)** |
| Exposure unit | GWd/MT | GWd/MT | **EFPD** |
| Extra variables | — | — | **2KIN, 2RR1** |
| `PRI.INP` maps | 4 | 4 | **none** |
| `BAT.EDT` | yes | yes | **none** |
| `ERR.CHK` | SYMGRP | SYMGRP + SYMROT | **none** |
| Loading card | `FUE.LAB` | `FUE.LAB` | **`FUE.TYP`** |
| Steps | 31 | 28 | 32 |

Missing sections degrade rather than fail: BEAVRS has no `FMAP` and no batch
edits, and still produces a complete 193-assembly core map. Anything the
parser skipped is reported in `parseNotes` and surfaced in the UI, so a
partial parse is visible rather than silent.

---

## Correctness

The parser is checked against facts the listing states about *itself*, not
against previously-parsed output:

- Quarter-core expansion yields exactly the assembly count the Input Summary
  reports — 241, 241 and 193.
- Per-fuel-type counts match the `Assembly Physical Descriptions` block, and
  the height-weighted totals reproduce the `Fueled Segments` equivalent-
  assembly column (56 assemblies × 351/381 cm = 51.591).
- Generated site labels match all 241 `FMAP` labels.
- k-eff from the Output Summary agrees with the independently printed
  depletion table at every step.
- Depletion rows equal state-point counts (31 / 28 / 32).
- Rod positions equal `total withdrawn ÷ steps per rod` (289 / 289 / 225).

### Independent verification

`verify/` re-extracts values straight from the raw bytes using a separate
implementation, deliberately written with a different technique per layout so
a shared bug cannot hide. It compared **147,151 values** across the three
files and now reports **zero discrepancies**:

| File | Values compared |
|---|---:|
| `case_002495.out` | 46,104 |
| `apr1400.c02.out` | 41,560 |
| `9074.out` | 59,487 |

That includes all 53,340 printed map cells across 91 state points and 428 map
blocks, plus ~57,000 rotational-image checks on the expanded quarter cores.

Getting there took **twelve** parser fixes. Every one was invisible in the
original file and only surfaced because a second and third file, or an
independent extractor, disagreed. The most consequential:

- **Cycle length was overstated by 0.94 GWd/MT.** An `ITE.SRC 'EOLEXP'`
  search prints trial pages whose banner exposure is not the converged
  answer; `case_002495` step 30 published 25.050 instead of 24.112. The
  listing states the right value five lines later and again in the depletion
  table.
- **`FUE.TYP` numbers were being read as segment numbers.** They coincide in
  the APR1400 decks and do not in BEAVRS, where it gave most of the core the
  wrong enrichment (3.10 w/o read as 2.40).
- **Exposure unit was inferred from the wrong page**, labelling an EFPD run
  as GWd/MT.
- **Segments with no burnable poison print `------`**; requiring digits there
  silently dropped 107 of BEAVRS's 193 assemblies.
- **`P**2` axial values landed under the wrong column** — a wrong number
  under a plausible name, the worst failure mode for a diagnostic tool.

Full findings in `verify/VERIFICATION_REPORT.md`.

### Running the tests

```bash
python -m pytest tests/ -q
```

Tests that need a real listing skip when none is present, so a fresh clone
runs **68 tests** covering the layout primitives, the column arithmetic,
geometry resolution, symmetry expansion (rotational, mirror and octant) and
report escaping — the parts that fail silently rather than loudly. Put listings
in `sample_data/` to unlock the other 126, which check parsed values against
figures each file states about itself.

### Checking a file the parser has never seen

Point the self-check at any listing to find out whether it was understood.
Every check compares the parser against a number the file states about
itself, so it needs no known-good reference:

```bash
python -m s3dash.check path/to/run.out
```

```
   ok   Assembly count vs Input Summary        241 parsed vs 241 declared
   ok   Height-weighted counts vs Fueled Segments  4 segment(s) match
   ok   k-eff agrees across two sources        Output Summary matches depletion table
   ok   Rod positions vs listing total         289 positions vs 289 implied by total/steps
```

It exits non-zero on failure, so it can gate a batch conversion. Where it
cannot decide something it says so rather than guessing — BEAVRS references
eight fuel types the listing never describes, and the check reports that
instead of silently misattributing them.

This command found three real defects during development, including one where
`FUE.TYP` numbers were being treated as segment numbers — harmless in the
APR1400 decks, where they coincide, and wrong for most of the BEAVRS core.

`verify/` holds an independent re-extraction of values straight from the raw
text — deliberately written with different techniques than the parser uses, so
a shared bug cannot hide — with its findings in
`verify/VERIFICATION_REPORT.md`.

---

## Layout

```
s3dash/
  parser/
    textutil.py     column arithmetic, Fortran number parsing, heading despacing
    document.py     pages, state-point context, section index
    geometry.py     DIM/COR resolution, fractional-core expansion
    primitives.py   the layout primitives above
    sections.py     bespoke layouts (SYMGRP, diagnostics, depletion, axial, batch)
    inputcards.py   echoed input deck, fuel definitions, segment table
    build.py        assembles the JSON payload
  web/
    app.py          FastAPI endpoints
    static/         the dashboard (vanilla ES modules + SVG)
docs/
  API_CONTRACT.md   payload shape, endpoints, and the rules the UI must honour
  sample_payload_*.json
tests/              parser, integration and API tests
verify/             independent numerical verification
sample_data/        the three reference listings
```

---

## Adding support for another section

Most additions need no parser code at all — a new `PRI.STA` variable is
already handled. For a genuinely new layout:

1. Add an anchor row to `_ANCHORS` in `document.py` (regex → kind + name).
2. If it reuses an existing shape, point the dispatch in `build.py` at the
   matching primitive. If the shape is new, add a primitive.
3. Add a fixture to `tests/test_primitives.py` copied verbatim from a real
   listing, and an assertion in `tests/test_integration.py` tied to something
   the file states about itself.

Unrecognised regions are never dropped silently — they remain reachable
through the navigation tree and the raw section viewer.

---

## Known limits

Stated plainly, because a diagnostic tool that overstates its own coverage is
worse than one that admits gaps.

- **One file at a time**; there is no run-to-run comparison view.
- **No real-file coverage for octant or mirror symmetry.** Both paths are
  implemented and unit-tested against synthetic cores, but all three sample
  files are rotational — quarter or full. Check any octant or mirror listing
  with `python -m s3dash.check` before trusting its core map.
- **No BWR file was available.** BWR listings should parse structurally, since
  the geometry resolution and layout primitives are shared, but this is
  untested against real output.
- **No file with maps split across a page break.** Wide cores can force a map
  to continue on the next page; the stitching code exists but no sample
  exercises it.
- **Rods are fully withdrawn in every sample.** The partially-inserted branch
  is unit-tested only.
- 3D runs give the core-average axial profile; per-assembly axial detail needs
  the run to have edited `3RPF`-class maps.
- `QMAP` and `BMAP` are parsed but not published in the payload.
- The `*` that appears in some `PIN.EDT 2PLO` cells (e.g. `14*13`) is
  preserved byte-for-byte but its meaning is not documented in the manual, so
  it is not interpreted.
