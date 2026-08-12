# Interactive Core Loading Editor + Next-Cycle .inp Generator

Status: approved. Date: 2026-08-12.

## Goal

Let the user rearrange the *currently loaded* core's assemblies on the core
map, then generate a SIMULATE-3 input deck for the next cycle reflecting
that rearrangement. The researcher runs the generated `.inp` through their
own SIMULATE-3 installation. This tool never performs reactor-physics
calculations and never claims the edited core is a computed result.

## Investigation findings this design depends on

These were established empirically against two real, independent decks
(`apr1400.c02.out`, `case_002495.out`) before any design work — see the
conversation record for the verification scripts and full evidence. They
are load-bearing facts, not assumptions:

1. **`assemblies[].printed` is not the axis this feature needs.** It tracks
   which *state-point value* cells (RPF, exposure, ...) SIMULATE-3 actually
   computed and printed, versus which are display-only mirror images filled
   in by `expand_to_full_core`. It says nothing about whether a position's
   *loading* was independently specified.

2. **The `FUE.LAB` card's grid is not parsed anywhere in this codebase.**
   `inputcards.py` captures the `'FUE.LAB' 4/` card line itself into
   `deck.cards`, then skips every row that follows it — the loop only
   matches lines starting with a quoted card name.

3. **The `FUE.LAB` grid format, decoded and verified:** each row is
   `<row> <format> <token> <token> ...`. `<row>` is the real core row
   directly, no offset. Column is recovered from the token's **absolute
   character position** within the row (not its ordinal position among
   tokens): `col = char_offset // 5 + 1`, measured from the first
   character after the two leading numbers. This was verified two ways on
   `apr1400.c02.out` — the predicted set of 241 (row, col) positions
   matches the true occupied set exactly (zero phantom, zero missing), and
   all 121 fresh-batch tokens (`TP01`/`TP02`) land on positions whose
   resolved fuel type matches what `FUE.NEW` declared — then re-verified
   unmodified against the independent `case_002495.out` deck (241/241
   exact match again). No manual exists anywhere in this repository
   (checked); this is empirical, cross-validated on two decks, not
   confirmed against an official spec.

4. **For a reused assembly, the printed token is a shuffle reference, not
   a label.** `N-03` at a slot does not mean "this position is called
   N-03" — cross-checked against `assemblies[].label` (which always equals
   current site — 0 exceptions across 241 assemblies in both files) it
   never matches. It means "load whichever assembly was at site N-03 in
   the *previous* cycle's restart file here." **The shuffle history is not
   missing from the `.out` after all** — it was un-decoded. (This corrects
   what was told to the user two turns earlier in the conversation.)

5. **Both verified decks give every position an explicit `FUE.LAB` entry**
   (241 tokens for 241 assemblies) — there is no reduced-quarter-with-
   auto-fill happening for *loading*, only for *computed-value display*.
   So for these geometries, every displayed assembly is independently,
   safely editable — the printed-vs-symmetry-expanded ambiguity the spec
   raised does not apply to the loading pattern itself, on the two decks
   tested.

6. **Both verified decks are quarter-core with rotational symmetry**
   (`ihave=2`, `symmetry=ROTATIONAL`, `iafull=17`). BEAVRS (the third
   sample) is full-core with `restartFile: None` — a first cycle with no
   `FUE.LAB` card at all, since there is nothing to shuffle. There is
   **no verified example** of a half-core, octant, or full-core-with-
   shuffle deck's `FUE.LAB` layout.

7. **`WRE` is captured verbatim** in `deck.cards` (e.g.
   `'s3.apr1400_PPF.uo2.c02.depl.res'`) — exactly the restart file the
   *next* cycle's `RES` card should reference. This is a direct copy
   across card types, not a naming-convention inference.

## Scope decision (confirmed with the user)

**Quarter-core, rotational symmetry only for v1.** At parse time, the
loading-pattern decoder counts its recovered entries against total
assembly count. If they don't match — or the geometry isn't
quarter-core/rotational — the tool refuses to enter edit mode and states
why, rather than guessing an unverified layout or symmetry rule.

Also out of scope, per direct instruction not to guess: any deck that
uses non-default `rotation`/`subType` values (both are constant/blank in
every deck checked — real syntax for writing them is unknown). If the
editor encounters one, it blocks editing that position and reports why,
rather than silently discarding or resetting the value.

## The symmetry-group insight

Section 5 of the request asked whether a displayed position is
independently printed or a symmetry-expanded image of another, and asked
that this be handled explicitly rather than guessed.

For a quarter-core rotational deck, **every one of the 4 rotational
images of a position has its own independent `FUE.LAB` entry** (finding
5, above) — but SIMULATE-3 only *solves* one quarter and assumes the
other three mirror it (`ihave=2`). If a user moved one assembly without
moving its three rotational partners identically, the resulting deck
would be syntactically valid but describe a loading pattern that is no
longer actually symmetric — SIMULATE-3 would still solve it as a
symmetric quarter-core case, silently producing physics for a pattern
that doesn't match what's actually loaded. That's exactly the class of
silent, dangerous mistake this feature must not produce.

**Resolution:** the editor's atomic unit of drag/swap is a position's full
symmetry orbit (itself plus its rotational images — 4 for a general
position, fewer only at a fixed point of the rotation, e.g. the exact
core centre on an odd-width grid), computed via `geometry._images()` —
the exact function the parser already uses for value-map expansion.
Dragging one visible assembly moves all of its symmetry partners
together, by construction. The loading pattern is symmetric before an
edit and stays symmetric after every edit — never validated-after-the-
fact and rejected, guaranteed correct by how the interaction is built.

## Architecture (confirmed with the user)

- `s3dash/parser/loadingpattern.py` (new): decodes the `FUE.LAB` grid via
  the verified formula; classifies each entry as `fresh` (matches a
  `FUE.NEW` label) or `reused` (site-style pattern); runs the entry-count
  guardrail. Exposed as `payload.loadingPattern`.
- `s3dash/parser/nextcycle.py` (new): given the payload and a list of
  position changes, validates them and returns a generated `.inp` text +
  change summary, or a structured failure. Called from both
  `s3dash/web/app.py` (new endpoint) and `s3dash/web/browser.py` (new
  function) — the same sharing pattern `pdfreport.build_pdf` already
  uses across the server and Pyodide builds.
- `s3dash/web/static/js/loadingeditor.js` (new): owns editor-mode state
  (`originalCore` / `modifiedCore`, change list, undo/redo stack),
  following `state.js`'s existing plain-object-plus-`update()` pattern.
- Modified: `app.js` (mode switch + wiring), `coremap.js` (drag
  interaction, editing-mode visual treatment — the map is already a pure
  function of an assembly array via `renderCoreMap()`, so rendering
  `modifiedCore` instead of `state.payload` reuses the existing renderer
  almost unchanged), `panels.js` (validation + change-summary display),
  `app.py` / `browser.py` (one thin endpoint/function each).

The original parsed run (`state.payload`) is never mutated. Nothing about
the existing analysis path changes.

## Drag interaction

The core map is a hand-built SVG, fully re-rendered from state on every
`renderCoreMap()` call (string-built `innerHTML`, not incremental DOM
patching), with one delegated listener set on the host container rather
than per-cell listeners. The drag interaction follows the same pattern
rather than native HTML5 drag-and-drop (which has known cross-browser
inconsistencies for arbitrary SVG elements, not just `<img>`): pointer
events (`pointerdown` on a cell, `pointermove`/`pointerup` on the
document) tracked in `loadingeditor.js`, with `renderCoreMap()` given an
edit-mode flag that swaps its data source and draws drag-affordance /
drop-target highlighting.

On drop:
- **Empty valid destination, no occupant:** the dragged orbit's positions
  move there (their symmetric image slots move to the destination
  orbit's image slots, matched by rotation order).
- **Destination occupied:** the two orbits swap completely (every source
  position exchanges with its corresponding destination position).
- **Invalid destination** (outside `occupied`, or a partial/fixed-point
  orbit mismatch with the target's orbit size): rejected, no state
  change, inline reason shown.

Each accepted operation appends one entry to the change list in the
shape the request specified (`{from, to, assemblySerial, operation}` for
a move, `{positionA, positionB, assemblyA, assemblyB, operation}` for a
swap) — one entry per *orbit* operation, not per individual cell, so a
4-way rotational move reads as one change, matching how the user thinks
about it (matching the drag they made) rather than four.

## Validation

Runs before `.inp` generation is enabled, all against `modifiedCore`:

- Every one of the original 241 positions still holds exactly one
  assembly (closed model — moves and swaps only, no creation or deletion,
  matching the request's explicit prohibition).
- No serial appears twice; no serial has vanished.
- Every occupied position is a geometrically valid core position.
- Every symmetry orbit is internally consistent (all 4 images hold
  assemblies of a pattern that is actually symmetric — guaranteed by
  construction per above, checked anyway as a real invariant, not
  decoration).
- Fuel type, batch, and enrichment for every assembly are unchanged from
  whichever assembly occupies that serial (identity is carried with the
  assembly through a move, never re-derived from the new position).

Failure shows the exact violated rule; `GENERATE .INP` stays disabled
until every check passes.

## Generating the next-cycle `.inp`

The generator starts from the source deck's own `deck.cards` (the
verbatim input-card echo) as a template and touches only what the
loading change requires:

| Card | Treatment | Why |
|---|---|---|
| `FUE.LAB` | **Regenerated** from `modifiedCore` using the verified encode (inverse of the decode formula) | This is the loading pattern itself |
| `RES` | **Filename replaced** with the source deck's own `WRE` value (a direct copy, not a naming inference); **exposure replaced** with the source run's final exposure; both shown as editable fields before generation, per the request's explicit fallback instruction | The next cycle reads from exactly what this run wrote |
| `WRE` | **Filename pre-filled** by incrementing the cycle number the source deck's own RES→WRE pair demonstrates (e.g. `c02`→`c03`), shown as an editable field, clearly marked as inferred | Only a single within-deck example exists; not guessed silently, exposed for the user to confirm or override |
| `FUE.NEW` | **Preserved verbatim** | A move/swap never changes how many assemblies of a fresh tag exist — only where they sit — so the batch definitions themselves don't change |
| `TIT.CAS`, `BAT.LAB` | **Preserved verbatim**, flagged in the change summary as "copied from the source cycle — you may want to update this" | Cosmetic labels naming the *source* cycle; wrong-looking if silently carried into a new cycle's file, but inventing new text is worse than flagging the old text |
| `DEP.CYC`, `DEP.STA` | **Preserved verbatim**, flagged with an inserted `'COM'` advisory comment ahead of them | Almost certainly wrong for a new cycle (schedule length/state points are forward-looking decisions this tool cannot derive from past results) but there is no basis to invent replacement values either — flagging beats silently shipping a stale-but-plausible-looking schedule |
| Everything else (`DIM.PWR`, `DIM.CAL`, `ERR.CHK`, `FUE.INI`, `SEG.LIB`, `FUE.ZON`, `FUE.TYP` if present, `COM` banners, ...) | **Preserved verbatim, no flag** | Genuinely unrelated to which assembly sits where |

Output filename follows the request's own example convention:
`<source-stem>_cycle_next.inp`.

## Safety / scope framing

The edited core is never shown with any computed value — no power,
k-eff, boron, exposure, or margin for the hypothetical layout. The UI
carries a persistent, unmissable mode indicator ("HYPOTHETICAL LOADING
PATTERN — uncalculated") whenever `modifiedCore` differs from
`originalCore`, and the analysis map cannot be edited by accident — entering
edit mode is one explicit action, and the normal analysis view is a
separate mode that always renders `state.payload` untouched.

## Testing

Backend (`pytest`, following the existing test suite's conventions):

- `loadingpattern.py`: decode `apr1400.c02.out` and `case_002495.out`,
  assert the full 241-position round trip (occupancy set, fresh-token
  fuel-type cross-check) — the exact checks already run manually during
  investigation, now as permanent regression tests.
- `loadingpattern.py`: geometry guardrail rejects a non-quarter/non-
  rotational deck (BEAVRS) with a clear reason, not a crash or a guess.
- `nextcycle.py`: every validation rule, individually (duplicate serial,
  vanished assembly, broken symmetry orbit, invalid position).
- `nextcycle.py`: end-to-end round trip — take `case_002495.out`, apply
  one known move, generate the `.inp` text, **re-parse that generated
  text with the existing input-card parser**, and assert the moved
  assembly's new position holds it and the old position no longer does.
  This is the request's own core acceptance test.
- `nextcycle.py`: every preserved-verbatim card's exact text survives
  unchanged in the output.
- `nextcycle.py`: `RES`/`WRE` filename and exposure substitution.

Frontend (manual verification in the Browser pane, per this project's
established practice — there is no JS test runner in this repo):

- Move one assembly (and confirm its 3 symmetry partners moved too).
- Swap two occupied positions.
- Multiple sequential moves, then undo, redo, reset.
- Attempted invalid drop (occupied-by-partial-orbit, out-of-core)
  rejected with a visible reason.
- Validation panel reflects real state; `GENERATE .INP` only enables
  once valid.
- Preview screen shows the exact change list before download.
- Mode indicator ("HYPOTHETICAL...") visible throughout editing; normal
  analysis view unaffected and un-editable.

## Known limitations (stated explicitly, not silently dropped)

- Quarter-core, rotational-symmetry decks only. Other fractions/symmetry
  kinds are detected and refused, not guessed.
- Non-default `rotation`/`subType` values are unsupported; editing a
  position that has one is blocked with a stated reason.
- The reused-assembly reference convention (write the *current* deck's
  own site as the next cycle's reference key) is inferred from
  within-deck consistency, not verified against a real cycle-1/2/3
  triplet — stated as inferred in the tool's own audit output, not
  presented as verified fact.
- `WRE`'s inferred next-cycle filename (cycle-number increment) rests on
  a single within-deck example — exposed as an editable field precisely
  because of that, per the request's own fallback instruction.
- Not verified against an official SIMULATE-3 manual, because none
  exists in this repository — verified empirically against two
  independent real decks instead.
