# SIMULATE-3 Core Analysis Dashboard

Load a SIMULATE-3 output listing and understand it without reading eleven
thousand lines of fixed-width Fortran print.

Upload a `.out` file and get an interactive core map, per-assembly inspection,
depletion and axial charts, a symmetry/diagnostics review, and a navigable
index of every section in the file with its original text one click away.

---

## Running it

```bash
python -m pip install -r requirements.txt
```

```bash
python -m s3dash
```

That starts the server on <http://127.0.0.1:8000> and opens a browser. Or run
uvicorn directly:

```bash
python -m uvicorn s3dash.web.app:app --port 8000
```

Three example listings ship in `sample_data/` and load with one click, so the
dashboard is usable before you upload anything.

**No build step, no npm, no network.** The front end is vanilla ES modules and
hand-written SVG; nothing is fetched from a CDN. It runs on an air-gapped
machine exactly as it runs on a connected one.

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

The three bundled files disagree on every axis that matters, which is why all
three are kept as fixtures:

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
- Per-fuel-type inventory matches the `Fueled Segments` equivalent-assembly
  column exactly (56 + 64 + 56 + 65 = 241).
- Generated site labels match all 241 `FMAP` labels.
- k-eff from the Output Summary agrees with the independently printed
  depletion table at every step.
- Depletion rows equal state-point counts (31 / 28 / 32).

```bash
python -m pytest tests/ -q
```

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

- One file at a time; there is no run-to-run comparison view.
- 3D runs are read per axial node for the core-average axial profile;
  per-assembly axial detail requires the run to have edited `3RPF`-class maps.
- BWR listings parse structurally (the geometry and primitives are shared),
  but only PWR files were available to verify against.
