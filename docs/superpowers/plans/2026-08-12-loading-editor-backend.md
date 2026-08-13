# Core Loading Editor — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decode the `FUE.LAB` loading-pattern card (unparsed anywhere in this codebase today), let a caller apply symmetry-consistent moves/swaps to it, validate the result, and generate a next-cycle `.inp` text that changes only what the loading-pattern edit requires.

**Architecture:** Two new parser-layer modules alongside the existing ones in `s3dash/parser/`: `loadingpattern.py` (decode + geometry guardrail) and `nextcycle.py` (orbit-aware apply, validate, encode, generate). One small addition to the existing `geometry.py` to expose symmetry-orbit computation as a public function, reusing the exact rotation math `expand_to_full_core` already relies on rather than duplicating it. No frontend, no HTTP/browser-adapter wiring — this plan produces backend logic only, fully exercised by `pytest`; a second plan wires it into `app.py`/`browser.py` and the UI.

**Tech Stack:** Pure Python, stdlib only (`re`, `dataclasses`) — matches every other parser module.

## Global Constraints

- Verified formula (do not deviate): in the `FUE.LAB` grid, each row is `<row> <format> <token> <token> ...`. `row` is the real core row directly, no offset. `col = char_offset // 5 + 1`, where `char_offset` is the token's 0-indexed character position measured from the first character after the two leading numbers.
- Scope is quarter-core (`geom.ihave == 2`) with rotational symmetry (`geom.symmetry` starts with `"ROT"`) only. Any other geometry raises `LoadingPatternError` rather than being processed.
- A `FUE.LAB` card with a decoded entry count that does not equal the run's assembly count raises `LoadingPatternError` — never silently falls back to guessing a symmetry-expansion rule for the loading pattern itself.
- The closed model: moves and swaps only. Total assembly count, every serial, and every fresh-batch tag's occurrence count must be identical before and after any sequence of edits.
- Test command: `python -m pytest -q`, run from the repo root. 229 passing before this plan.
- Sample fixtures already present locally: `sample_data/case_002495.out`, `sample_data/apr1400.c02.out` — gated by the existing `samples_available()`/`needs_listings` pattern (see `tests/test_browser.py`), since they are gitignored and not guaranteed present in every checkout.

---

## Task 1: `geometry.symmetry_orbit()`

**Files:**
- Modify: `s3dash/parser/geometry.py`
- Test: `tests/test_geometry_orbit.py`

**Interfaces:**
- Consumes: the existing private `_images(r, c, n, symmetry, ihave)` function already in `geometry.py`.
- Produces: `symmetry_orbit(r: int, c: int, geom: Geometry) -> list[tuple[int, int]]` — the full orbit (the position itself plus every symmetric image), sorted, deduplicated. Length 4 for a general quarter-core rotational position; can be shorter only at a fixed point of the rotation (e.g. the exact core centre on an odd-width grid). Every later task in this plan calls this function; no other task recomputes rotation math.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_geometry_orbit.py
"""symmetry_orbit() is the one place this feature computes rotation math --
it must reuse geometry.py's existing, already-correct _images(), not
duplicate it."""

from __future__ import annotations

from s3dash.parser.geometry import Geometry, symmetry_orbit


def _quarter_rotational(iafull: int) -> Geometry:
    g = Geometry()
    g.iafull = iafull
    g.ihave = 2
    g.symmetry = "ROTATIONAL"
    return g


def test_general_position_has_four_member_orbit():
    geom = _quarter_rotational(17)
    orbit = symmetry_orbit(2, 5, geom)
    assert len(orbit) == 4
    assert (2, 5) in orbit


def test_orbit_is_self_consistent_for_every_member():
    # Every member of an orbit must produce the identical orbit set --
    # otherwise "the atomic unit a drag affects" would depend on which
    # member the user happened to grab.
    geom = _quarter_rotational(17)
    orbit = symmetry_orbit(2, 5, geom)
    for (r, c) in orbit:
        assert set(symmetry_orbit(r, c, geom)) == set(orbit)


def test_core_centre_is_a_fixed_point_on_odd_width_grid():
    geom = _quarter_rotational(17)
    centre = (9, 9)
    assert symmetry_orbit(*centre, geom) == [centre]


def test_orbit_matches_expand_to_full_core_images():
    # symmetry_orbit must describe exactly the same symmetry the existing,
    # already-relied-upon expand_to_full_core uses for value maps -- two
    # different notions of symmetry in one codebase would be a real bug.
    from s3dash.parser.geometry import expand_to_full_core

    geom = _quarter_rotational(17)
    expanded = expand_to_full_core({(2, 5): 1.0}, geom)
    assert set(expanded) == set(symmetry_orbit(2, 5, geom))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_geometry_orbit.py -v`
Expected: FAIL — `ImportError: cannot import name 'symmetry_orbit'`

- [ ] **Step 3: Add `symmetry_orbit` to `geometry.py`**

In `s3dash/parser/geometry.py`, add immediately after the existing `_images` function (after line 216, before `def quarter_origin`):

```python
def symmetry_orbit(r: int, c: int, geom: Geometry) -> list[tuple[int, int]]:
    """The full symmetry orbit of (r, c): itself plus every symmetric
    image, sorted. Length is 4 for a general quarter-core rotational
    position; shorter only at a fixed point of the rotation (e.g. the
    exact core centre on an odd-width grid).

    This is the single source of truth for "which positions must move
    together to keep a loading pattern symmetric" -- it calls the same
    _images() that expand_to_full_core already uses for value maps, so
    the two never disagree about what "symmetric" means.
    """
    images = _images(r, c, geom.iafull, geom.symmetry, geom.ihave)
    return sorted({(r, c), *images})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_geometry_orbit.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: `233 passed`

- [ ] **Step 6: Commit**

```bash
git add s3dash/parser/geometry.py tests/test_geometry_orbit.py
git commit -m "feat(loading-editor): expose symmetry_orbit(), reusing the existing rotation math"
```

---

## Task 2: `loadingpattern.py` — decode the `FUE.LAB` grid

**Files:**
- Create: `s3dash/parser/loadingpattern.py`
- Test: `tests/test_loadingpattern.py`

**Interfaces:**
- Consumes: `Geometry` (from `.geometry`), a document's `lines: list[str]`, the set of fresh-batch labels from `InputDeck.batches` (each a `FuelBatch` with `.label`, from `.inputcards`).
- Produces: `LoadingEntry` (dataclass: `row`, `col`, `token`, `kind` — `kind` is `"fresh"` or `"reused"`), `LoadingPatternError` (exception), `find_fuel_lab_card(lines) -> int | None`, `decode_loading_pattern(lines, fuel_lab_line, fresh_labels) -> dict[tuple[int,int], LoadingEntry]`, `parse_loading_pattern(lines, geom, fresh_labels, assembly_count) -> dict[tuple[int,int], LoadingEntry] | None` (the composed entry point later tasks and the frontend-wiring plan call). Task 3 onward consumes `LoadingEntry` and `parse_loading_pattern`'s return type directly.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_loadingpattern.py
"""Decoding the FUE.LAB grid -- verified against two independent real
decks. See docs/superpowers/specs/2026-08-12-loading-editor-design.md for
the reverse-engineering evidence this formula is built from."""

from __future__ import annotations

import re

import pytest

from s3dash.parser import parse_file
from s3dash.parser.loadingpattern import (
    LoadingPatternError,
    decode_loading_pattern,
    find_fuel_lab_card,
    parse_loading_pattern,
)
from tests.conftest import SAMPLES, samples_available

needs_listings = pytest.mark.skipif(
    not samples_available(), reason="reference listing not present (see README)"
)


@needs_listings
@pytest.mark.parametrize("filename", ["apr1400.c02.out", "case_002495.out"])
def test_decoded_positions_exactly_match_occupied_assemblies(filename):
    result = parse_file(SAMPLES / filename)
    payload = result.payload
    lines = result.document.lines

    fresh_labels = {b["label"] for b in payload["inputDeck"]["batches"]}
    fuel_lab_line = find_fuel_lab_card(lines)
    assert fuel_lab_line is not None

    entries = decode_loading_pattern(lines, fuel_lab_line, fresh_labels)
    occupied = {(a["row"], a["col"]) for a in payload["assemblies"]}

    assert set(entries) == occupied
    assert len(entries) == len(payload["assemblies"])


@needs_listings
def test_fresh_tokens_match_declared_fuel_new_type(filename="apr1400.c02.out"):
    result = parse_file(SAMPLES / filename)
    payload = result.payload
    lines = result.document.lines
    by_rc = {(a["row"], a["col"]): a for a in payload["assemblies"]}

    fresh_by_label = {b["label"]: b["fuelType"] for b in payload["inputDeck"]["batches"]}
    fuel_lab_line = find_fuel_lab_card(lines)
    entries = decode_loading_pattern(lines, fuel_lab_line, set(fresh_by_label))

    checked = 0
    for (r, c), entry in entries.items():
        if entry.kind == "fresh":
            checked += 1
            assert by_rc[(r, c)]["fuelType"] == fresh_by_label[entry.token]
    assert checked == 121  # 56 TP01 + 65 TP02 in this specific deck


@needs_listings
def test_reused_tokens_are_site_style_and_never_match_current_site(filename="apr1400.c02.out"):
    # A reused token references the PREVIOUS cycle's site, not this run's
    # current site -- this is the shuffle-history finding the design spec
    # documents. If this regresses to matching current site, the encode/
    # decode round trip would silently corrupt shuffle references.
    result = parse_file(SAMPLES / filename)
    payload = result.payload
    lines = result.document.lines
    by_rc = {(a["row"], a["col"]): a for a in payload["assemblies"]}

    fresh_labels = {b["label"] for b in payload["inputDeck"]["batches"]}
    fuel_lab_line = find_fuel_lab_card(lines)
    entries = decode_loading_pattern(lines, fuel_lab_line, fresh_labels)

    reused = [e for e in entries.values() if e.kind == "reused"]
    assert len(reused) == 120
    for e in reused:
        assert re.fullmatch(r"[A-Z]-\d\d", e.token)
        assert by_rc[(e.row, e.col)]["label"] != e.token


def test_geometry_guardrail_rejects_non_quarter_core():
    from s3dash.parser.geometry import Geometry

    geom = Geometry()
    geom.ihave = 4  # full core
    geom.symmetry = "ROTATIONAL"
    with pytest.raises(LoadingPatternError, match="quarter-core"):
        parse_loading_pattern(["'FUE.LAB' 4/", "  0  0"], geom, set(), assembly_count=1)


def test_geometry_guardrail_rejects_non_rotational_symmetry():
    from s3dash.parser.geometry import Geometry

    geom = Geometry()
    geom.ihave = 2
    geom.symmetry = "MIRROR"
    with pytest.raises(LoadingPatternError, match="rotational"):
        parse_loading_pattern(["'FUE.LAB' 4/", "  0  0"], geom, set(), assembly_count=1)


@needs_listings
def test_beavrs_has_no_fuel_lab_card_and_returns_none():
    # BEAVRS is a first-cycle deck with no restart -- nothing to shuffle,
    # so it has no FUE.LAB card at all. That's a normal case, not an error.
    result = parse_file(SAMPLES / "9074.out")
    entries = parse_loading_pattern(
        result.document.lines, result.geometry, set(), assembly_count=193
    )
    assert entries is None


def test_entry_count_mismatch_raises():
    from s3dash.parser.geometry import Geometry

    geom = Geometry()
    geom.iafull = 4
    geom.ihave = 2
    geom.symmetry = "ROTATIONAL"
    lines = [
        "'FUE.LAB' 4/",
        "  1  1 TP01",
        "  0  0",
    ]
    with pytest.raises(LoadingPatternError, match="assemblies"):
        parse_loading_pattern(lines, geom, {"TP01"}, assembly_count=99)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_loadingpattern.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 's3dash.parser.loadingpattern'`

- [ ] **Step 3: Write `loadingpattern.py`**

```python
# s3dash/parser/loadingpattern.py
"""Decodes the FUE.LAB loading-pattern card -- not parsed anywhere else in
this codebase. inputcards.py captures the card's own line into deck.cards
but skips every grid row that follows it.

Format, reverse-engineered and verified against two independent real
decks (apr1400.c02.out, case_002495.out) -- see
docs/superpowers/specs/2026-08-12-loading-editor-design.md for the
evidence. Each grid row is ``<row> <format> <token> <token> ...``. ``row``
is the real core row directly, no offset. Column comes from the token's
absolute character position within the row, not its ordinal position
among tokens -- rows can have gaps in the middle, not just trimmed edges,
which is exactly why ordinal counting fails and character position does
not: ``col = char_offset // 5 + 1``, measured from the first character
after the two leading numbers.

Only verified for quarter-core, rotational-symmetry decks -- the one
geometry class both real examples share. LoadingPatternError is raised
for anything else rather than guessing an unverified layout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .geometry import Geometry

_FIELD_WIDTH = 5
_PREFIX_RE = re.compile(r"^\s*\d+\s+\d+")


class LoadingPatternError(Exception):
    """Raised when the loading pattern can't be safely decoded: an
    unverified geometry, or a FUE.LAB entry count that doesn't match the
    run's assembly count. Callers must not fall back to guessing when
    this is raised -- report it and stop."""


@dataclass
class LoadingEntry:
    """One FUE.LAB grid token, resolved to a core position."""

    row: int
    col: int
    token: str
    kind: str  # "fresh" | "reused"

    def to_json(self) -> dict:
        return {"row": self.row, "col": self.col, "token": self.token, "kind": self.kind}


def check_geometry_supported(geom: Geometry) -> None:
    """Raises LoadingPatternError if this geometry is outside what's
    verified: quarter-core (ihave == 2) with rotational symmetry."""
    if geom.ihave != 2:
        raise LoadingPatternError(
            f"Loading pattern editing is only verified for quarter-core decks "
            f"(ihave=2); this deck is {geom.fraction_name} (ihave={geom.ihave})."
        )
    if not geom.symmetry.startswith("ROT"):
        raise LoadingPatternError(
            f"Loading pattern editing is only verified for rotational symmetry; "
            f"this deck declares symmetry={geom.symmetry!r}."
        )


def find_fuel_lab_card(lines: list[str]) -> int | None:
    """Line index of the 'FUE.LAB' card, or None if the deck has none --
    a normal case for a first-cycle deck with no restart file, since
    there is nothing to shuffle."""
    for i, line in enumerate(lines):
        if "'FUE.LAB'" in line:
            return i
    return None


def decode_loading_pattern(
    lines: list[str],
    fuel_lab_line: int,
    fresh_labels: set[str],
) -> dict[tuple[int, int], LoadingEntry]:
    """Decode the grid that follows `fuel_lab_line`.

    `fresh_labels` are the labels FUE.NEW declared (e.g. {"TP01", "TP02"});
    any other token is classified "reused". The grid ends at the first
    row whose leading token is "0" -- the terminator both verified decks
    use.
    """
    out: dict[tuple[int, int], LoadingEntry] = {}
    i = fuel_lab_line + 1
    while i < len(lines):
        line = lines[i]
        toks = line.split()
        if not toks or toks[0] == "0":
            break
        row = int(toks[0])
        m = _PREFIX_RE.match(line)
        rest = line[m.end():] if m else line
        for tok_m in re.finditer(r"\S+", rest):
            col = tok_m.start() // _FIELD_WIDTH + 1
            token = tok_m.group(0)
            kind = "fresh" if token in fresh_labels else "reused"
            out[(row, col)] = LoadingEntry(row=row, col=col, token=token, kind=kind)
        i += 1
    return out


def check_entry_count(entries: dict[tuple[int, int], LoadingEntry], assembly_count: int) -> None:
    """Raises LoadingPatternError if the decoded entry count doesn't
    match the run's assembly count -- signals a deck that relies on
    loading-pattern symmetry expansion, which this formula does not
    handle (both verified decks give every position its own explicit
    entry)."""
    if len(entries) != assembly_count:
        raise LoadingPatternError(
            f"Decoded {len(entries)} FUE.LAB entries but the run has "
            f"{assembly_count} assemblies -- this deck may rely on "
            f"loading-pattern symmetry expansion, which is not supported."
        )


def parse_loading_pattern(
    lines: list[str],
    geom: Geometry,
    fresh_labels: set[str],
    assembly_count: int,
) -> dict[tuple[int, int], LoadingEntry] | None:
    """Full pipeline: locate FUE.LAB, verify the geometry is trustworthy,
    decode it, verify the entry count.

    Returns None (not an error) when the deck has no FUE.LAB card at all
    -- a normal, valid first-cycle case, not a failure.

    Raises LoadingPatternError when a FUE.LAB card exists but this deck's
    geometry isn't verified, or the decoded entry count doesn't match the
    assembly count.
    """
    fuel_lab_line = find_fuel_lab_card(lines)
    if fuel_lab_line is None:
        return None
    check_geometry_supported(geom)
    entries = decode_loading_pattern(lines, fuel_lab_line, fresh_labels)
    check_entry_count(entries, assembly_count)
    return entries
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_loadingpattern.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: `241 passed`

- [ ] **Step 6: Commit**

```bash
git add s3dash/parser/loadingpattern.py tests/test_loadingpattern.py
git commit -m "feat(loading-editor): decode the FUE.LAB grid, verified on two real decks"
```

---

## Task 3: `nextcycle.py` — orbit-aware apply

**Files:**
- Create: `s3dash/parser/nextcycle.py`
- Test: `tests/test_nextcycle.py`

**Interfaces:**
- Consumes: `LoadingEntry` (from `.loadingpattern`), `Geometry` + `symmetry_orbit` (from `.geometry`).
- Produces: `PositionChange` (dataclass: `from_row`, `from_col`, `to_row`, `to_col`), `AppliedOperation` (dataclass: `operation` (`"move"`/`"swap"`), `from_site`, `to_site`, `from_token`, `to_token: str | None`, plus `.to_json()`), `ValidationError` (exception), `apply_change(entries, change, geom) -> tuple[dict[tuple[int,int], LoadingEntry], AppliedOperation]`. Task 4 consumes `ValidationError` and the same `entries` type. Task 6 consumes `AppliedOperation` objects directly (threading them through into `GenerationResult.operations` unchanged); `.to_json()` itself is for the frontend-wiring plan's audit-summary serialization, not called anywhere in this backend-only plan.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_nextcycle.py
"""Applying, validating, encoding, and generating from a modified loading
pattern."""

from __future__ import annotations

import pytest

from s3dash.parser.geometry import Geometry
from s3dash.parser.loadingpattern import LoadingEntry
from s3dash.parser.nextcycle import PositionChange, ValidationError, apply_change


def _quarter_rotational(iafull: int) -> Geometry:
    g = Geometry()
    g.iafull = iafull
    g.ihave = 2
    g.symmetry = "ROTATIONAL"
    return g


def _entry(row, col, token, kind="reused"):
    return LoadingEntry(row=row, col=col, token=token, kind=kind)


class TestApplyChange:
    def test_noop_move_to_its_own_position(self):
        geom = _quarter_rotational(17)
        entries = {(1, 2): _entry(1, 2, "N-03")}
        change = PositionChange(from_row=1, from_col=2, to_row=1, to_col=2)
        new_entries, op = apply_change(entries, change, geom)
        assert new_entries == entries
        assert op.operation == "move"

    def test_swap_moves_every_symmetry_partner_together(self):
        geom = _quarter_rotational(17)
        from s3dash.parser.geometry import symmetry_orbit

        src_orbit = symmetry_orbit(2, 5, geom)
        dst_orbit = symmetry_orbit(3, 3, geom)
        assert len(src_orbit) == len(dst_orbit) == 4

        entries = {}
        for i, (r, c) in enumerate(src_orbit):
            entries[(r, c)] = _entry(r, c, f"SRC{i}")
        for i, (r, c) in enumerate(dst_orbit):
            entries[(r, c)] = _entry(r, c, f"DST{i}")

        change = PositionChange(from_row=2, from_col=5, to_row=3, to_col=3)
        new_entries, op = apply_change(entries, change, geom)

        assert op.operation == "swap"
        assert set(new_entries) == set(entries)  # position set unchanged
        # every source-orbit position now holds a token that used to be a
        # destination-orbit token, and vice versa
        assert {new_entries[pos].token for pos in src_orbit} == {f"DST{i}" for i in range(4)}
        assert {new_entries[pos].token for pos in dst_orbit} == {f"SRC{i}" for i in range(4)}

    def test_original_entries_never_mutated(self):
        geom = _quarter_rotational(17)
        from s3dash.parser.geometry import symmetry_orbit

        src_orbit = symmetry_orbit(2, 5, geom)
        dst_orbit = symmetry_orbit(3, 3, geom)
        entries = {(r, c): _entry(r, c, "A") for (r, c) in src_orbit}
        entries.update({(r, c): _entry(r, c, "B") for (r, c) in dst_orbit})
        snapshot = dict(entries)

        apply_change(entries, PositionChange(2, 5, 3, 3), geom)
        assert entries == snapshot

    def test_moving_from_empty_position_raises(self):
        geom = _quarter_rotational(17)
        with pytest.raises(ValidationError, match="No assembly"):
            apply_change({}, PositionChange(2, 5, 3, 3), geom)

    def test_mismatched_orbit_sizes_raise(self):
        # (9,9) is the fixed-point centre of a 17-wide grid (orbit size 1);
        # (2,5) has a 4-member orbit. Swapping them cannot preserve
        # symmetry, so it must be rejected, not silently truncated.
        geom = _quarter_rotational(17)
        entries = {(9, 9): _entry(9, 9, "CENTRE"), (2, 5): _entry(2, 5, "A")}
        with pytest.raises(ValidationError, match="symmetry orbit"):
            apply_change(entries, PositionChange(2, 5, 9, 9), geom)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_nextcycle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 's3dash.parser.nextcycle'`

- [ ] **Step 3: Write the `apply_change` portion of `nextcycle.py`**

```python
# s3dash/parser/nextcycle.py
"""Generate a next-cycle SIMULATE-3 input deck from a modified loading
pattern.

The source deck's own echoed "Listing of Input Cards" text is the
template: only the FUE.LAB grid is regenerated, RES/WRE are substituted,
DEP.CYC/DEP.STA get an advisory comment ahead of them, and every other
card is preserved character-for-character. See
docs/superpowers/specs/2026-08-12-loading-editor-design.md for why each
card gets the treatment it gets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .geometry import Geometry, symmetry_orbit
from .loadingpattern import LoadingEntry

_FIELD_WIDTH = 5


class ValidationError(Exception):
    """One violated invariant of the closed loading-pattern model. The
    message names the exact rule broken and is shown to the user
    verbatim -- it must always be specific enough to act on."""


@dataclass
class PositionChange:
    """One user drag: move (or, if occupied, swap) whatever is at
    (from_row, from_col) to (to_row, to_col). Symmetry partners are
    derived here via geometry.symmetry_orbit, never supplied by the
    caller -- this is what keeps an edited pattern symmetric by
    construction rather than by after-the-fact rejection."""

    from_row: int
    from_col: int
    to_row: int
    to_col: int


@dataclass
class AppliedOperation:
    """One completed orbit-level move or swap, for the audit summary --
    one entry per drag the user made, not one per individual
    symmetry-partner position."""

    operation: str  # "move" | "swap"
    from_site: str
    to_site: str
    from_token: str
    to_token: str | None  # None for a move onto a previously-empty position

    def to_json(self) -> dict:
        return {
            "operation": self.operation,
            "from": self.from_site,
            "to": self.to_site,
            "fromToken": self.from_token,
            "toToken": self.to_token,
        }


def apply_change(
    entries: dict[tuple[int, int], LoadingEntry],
    change: PositionChange,
    geom: Geometry,
) -> tuple[dict[tuple[int, int], LoadingEntry], AppliedOperation]:
    """Apply one drag to `entries`, expanding it to the full symmetry
    orbit. Returns a new dict (the input is never mutated) and a record
    of what happened, with the i-th image of the source orbit exchanged
    against the i-th image of the destination orbit.

    Raises ValidationError if the source position is empty, or the two
    orbits have different sizes (a partial-symmetry drag, which cannot be
    applied without breaking symmetry).
    """
    if (change.from_row, change.from_col) not in entries:
        raise ValidationError(
            f"No assembly at ({change.from_row}, {change.from_col}) to move."
        )

    from_orbit = symmetry_orbit(change.from_row, change.from_col, geom)
    to_orbit = symmetry_orbit(change.to_row, change.to_col, geom)
    if len(from_orbit) != len(to_orbit):
        raise ValidationError(
            f"({change.from_row}, {change.from_col}) has a symmetry orbit of "
            f"{len(from_orbit)} position(s) but the destination has "
            f"{len(to_orbit)} -- these cannot be exchanged without breaking "
            f"symmetry."
        )

    out = dict(entries)
    from_entry = entries[(change.from_row, change.from_col)]
    to_entry = entries.get((change.to_row, change.to_col))

    for (fr, fc), (tr, tc) in zip(from_orbit, to_orbit):
        moving = entries.get((fr, fc))
        landing = entries.get((tr, tc))
        if moving is not None:
            out[(tr, tc)] = LoadingEntry(row=tr, col=tc, token=moving.token, kind=moving.kind)
        elif (tr, tc) in out:
            del out[(tr, tc)]
        if landing is not None:
            out[(fr, fc)] = LoadingEntry(row=fr, col=fc, token=landing.token, kind=landing.kind)
        elif (fr, fc) in out:
            del out[(fr, fc)]

    same_position = (change.from_row, change.from_col) == (change.to_row, change.to_col)
    op = AppliedOperation(
        operation="swap" if (to_entry is not None and not same_position) else "move",
        from_site=geom.site_label(change.from_row, change.from_col),
        to_site=geom.site_label(change.to_row, change.to_col),
        from_token=from_entry.token,
        to_token=to_entry.token if (to_entry is not None and not same_position) else None,
    )
    return out, op
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_nextcycle.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: `246 passed`

- [ ] **Step 6: Commit**

```bash
git add s3dash/parser/nextcycle.py tests/test_nextcycle.py
git commit -m "feat(loading-editor): apply moves/swaps as whole symmetry orbits"
```

---

## Task 4: `nextcycle.py` — validation

**Files:**
- Modify: `s3dash/parser/nextcycle.py`
- Test: `tests/test_nextcycle.py`

**Interfaces:**
- Consumes: the same `entries` dict shape as Task 3, `symmetry_orbit`.
- Produces: `validate(entries, original_entries, geom) -> list[str]` (empty list means valid). Task 6 calls this before generating.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_nextcycle.py`:

```python
from s3dash.parser.nextcycle import apply_change, validate


class TestValidate:
    def _base(self):
        geom = _quarter_rotational(17)
        from s3dash.parser.geometry import symmetry_orbit

        a_orbit = symmetry_orbit(2, 5, geom)
        b_orbit = symmetry_orbit(3, 3, geom)
        entries = {(r, c): _entry(r, c, f"A{i}") for i, (r, c) in enumerate(a_orbit)}
        entries.update({(r, c): _entry(r, c, f"B{i}") for i, (r, c) in enumerate(b_orbit)})
        return geom, entries

    def test_unchanged_pattern_is_valid(self):
        geom, entries = self._base()
        assert validate(entries, entries, geom) == []

    def test_valid_swap_via_apply_change_stays_valid(self):
        geom, entries = self._base()
        new_entries, _ = apply_change(entries, PositionChange(2, 5, 3, 3), geom)
        assert validate(new_entries, entries, geom) == []

    def test_duplicate_serial_detected(self):
        geom, entries = self._base()
        (r, c) = next(iter(entries))
        broken = dict(entries)
        other = next(k for k in broken if k != (r, c))
        broken[other] = LoadingEntry(row=other[0], col=other[1], token=broken[(r, c)].token, kind="reused")
        problems = validate(broken, entries, geom)
        assert any("appears at" in p for p in problems)

    def test_vanished_position_detected(self):
        geom, entries = self._base()
        (r, c) = next(iter(entries))
        broken = dict(entries)
        del broken[(r, c)]
        problems = validate(broken, entries, geom)
        assert any("emptied" in p for p in problems)

    def test_partial_orbit_detected(self):
        # Directly construct a broken state (not reachable via apply_change,
        # which always moves whole orbits) to prove validate() catches it
        # independently, not just by trusting the caller used apply_change.
        geom, entries = self._base()
        (r, c) = next(iter(entries))
        broken = dict(entries)
        del broken[(r, c)]
        broken[(50, 50)] = LoadingEntry(row=50, col=50, token=broken.get((r, c), _entry(r, c, "X")).token if False else "X", kind="reused")
        problems = validate(broken, entries, geom)
        assert any("symmetric" in p or "emptied" in p or "occupied" in p for p in problems)

    def test_fresh_count_change_detected(self):
        geom, entries = self._base()
        (r, c) = next(iter(entries))
        broken = dict(entries)
        broken[(r, c)] = LoadingEntry(row=r, col=c, token=broken[(r, c)].token, kind="fresh")
        problems = validate(broken, entries, geom)
        assert any("fresh-batch" in p for p in problems)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_nextcycle.py -v`
Expected: FAIL — `ImportError: cannot import name 'validate'`

- [ ] **Step 3: Add `validate` to `nextcycle.py`**

Append to `s3dash/parser/nextcycle.py`:

```python
def validate(
    entries: dict[tuple[int, int], LoadingEntry],
    original_entries: dict[tuple[int, int], LoadingEntry],
    geom: Geometry,
) -> list[str]:
    """Every invariant of the closed loading-pattern model. Returns a
    list of violated-rule messages -- empty means valid. Never raises;
    this collects every problem for display rather than stopping at the
    first, so the user sees the whole picture at once."""
    problems: list[str] = []

    added = sorted(set(entries) - set(original_entries))
    removed = sorted(set(original_entries) - set(entries))
    if added:
        problems.append(f"{len(added)} position(s) now occupied that weren't: {added[:5]}")
    if removed:
        problems.append(f"{len(removed)} position(s) emptied that were occupied: {removed[:5]}")

    seen: dict[str, list[tuple[int, int]]] = {}
    for (r, c), e in entries.items():
        if e.kind == "reused":
            seen.setdefault(e.token, []).append((r, c))
    for token, positions in seen.items():
        if len(positions) > 1:
            problems.append(f"{token} appears at {len(positions)} positions: {sorted(positions)}")

    original_reused = {e.token for e in original_entries.values() if e.kind == "reused"}
    now_reused = set(seen)
    missing = original_reused - now_reused
    if missing:
        problems.append(f"{len(missing)} reused assembly reference(s) vanished: {sorted(missing)}")

    fresh_before = sum(1 for e in original_entries.values() if e.kind == "fresh")
    fresh_after = sum(1 for e in entries.values() if e.kind == "fresh")
    if fresh_before != fresh_after:
        problems.append(
            f"fresh-batch position count changed ({fresh_before} -> {fresh_after}) -- "
            f"moves and swaps must not create or remove assemblies"
        )

    checked_orbits: set[tuple[tuple[int, int], ...]] = set()
    for (r, c) in entries:
        orbit = tuple(symmetry_orbit(r, c, geom))
        if orbit in checked_orbits:
            continue
        checked_orbits.add(orbit)
        missing_partners = [pos for pos in orbit if pos not in entries]
        if missing_partners:
            problems.append(
                f"{geom.site_label(r, c)} is occupied but its symmetry "
                f"partner(s) at {sorted(missing_partners)} are not -- the "
                f"loading pattern is no longer rotationally symmetric"
            )

    return problems
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_nextcycle.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: `252 passed`

- [ ] **Step 6: Commit**

```bash
git add s3dash/parser/nextcycle.py tests/test_nextcycle.py
git commit -m "feat(loading-editor): validate the closed loading-pattern model"
```

---

## Task 5: `nextcycle.py` — encode (inverse of decode)

**Files:**
- Modify: `s3dash/parser/nextcycle.py`
- Test: `tests/test_nextcycle.py`

**Interfaces:**
- Consumes: `entries` (same shape), `Geometry`.
- Produces: `encode_loading_pattern(entries, geom) -> str` (the `FUE.LAB` grid text, decodable by `loadingpattern.decode_loading_pattern` back to the same `entries`). Task 6 calls this to build the regenerated card.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_nextcycle.py`:

```python
from s3dash.parser.loadingpattern import decode_loading_pattern, find_fuel_lab_card
from s3dash.parser.nextcycle import encode_loading_pattern


class TestEncodeLoadingPattern:
    def test_round_trips_a_hand_built_pattern(self):
        geom = _quarter_rotational(17)
        from s3dash.parser.geometry import symmetry_orbit

        orbit = symmetry_orbit(2, 5, geom)
        entries = {(r, c): _entry(r, c, "N-03" if i == 0 else "TP01", "reused" if i == 0 else "fresh")
                   for i, (r, c) in enumerate(orbit)}

        text = encode_loading_pattern(entries, geom)
        lines = ["'FUE.LAB' 4/", *text.splitlines()]
        decoded = decode_loading_pattern(lines, 0, {"TP01"})
        assert decoded.keys() == entries.keys()
        for pos in entries:
            assert decoded[pos].token == entries[pos].token
            assert decoded[pos].kind == entries[pos].kind

    @pytest.mark.skipif(
        not __import__("tests.conftest", fromlist=["samples_available"]).samples_available(),
        reason="reference listing not present (see README)",
    )
    def test_round_trips_the_real_apr1400_pattern(self):
        from s3dash.parser import parse_file
        from tests.conftest import SAMPLES

        result = parse_file(SAMPLES / "apr1400.c02.out")
        payload = result.payload
        lines = result.document.lines
        fresh_labels = {b["label"] for b in payload["inputDeck"]["batches"]}
        fuel_lab_line = find_fuel_lab_card(lines)
        original = decode_loading_pattern(lines, fuel_lab_line, fresh_labels)

        text = encode_loading_pattern(original, result.geometry)
        reencoded_lines = ["'FUE.LAB' 4/", *text.splitlines()]
        roundtripped = decode_loading_pattern(reencoded_lines, 0, fresh_labels)

        assert roundtripped.keys() == original.keys()
        for pos in original:
            assert roundtripped[pos].token == original[pos].token
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_nextcycle.py -v`
Expected: FAIL — `ImportError: cannot import name 'encode_loading_pattern'`

- [ ] **Step 3: Add `encode_loading_pattern` to `nextcycle.py`**

Append to `s3dash/parser/nextcycle.py`:

```python
def encode_loading_pattern(entries: dict[tuple[int, int], LoadingEntry], geom: Geometry) -> str:
    """Render `entries` back into FUE.LAB grid text -- regenerates every
    row from the (row, col) -> token mapping rather than surgically
    patching the original text, so encoding is provably the inverse of
    loadingpattern.decode_loading_pattern rather than drifting from it
    over incremental edits. Ends with the "0  0" terminator both verified
    decks use."""
    by_row: dict[int, dict[int, str]] = {}
    for (r, c), e in entries.items():
        by_row.setdefault(r, {})[c] = e.token

    lines: list[str] = []
    for r in sorted(by_row):
        cols = by_row[r]
        max_col = max(cols)
        cells = [" " * _FIELD_WIDTH] * max_col
        for c, token in cols.items():
            cells[c - 1] = token.ljust(_FIELD_WIDTH)
        row_text = "".join(cells).rstrip()
        lines.append(f"{r:3d}  1 {row_text}")
    lines.append("  0  0")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_nextcycle.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: `254 passed`

- [ ] **Step 6: Commit**

```bash
git add s3dash/parser/nextcycle.py tests/test_nextcycle.py
git commit -m "feat(loading-editor): encode the FUE.LAB grid, verified round-trip on real data"
```

---

## Task 6: `nextcycle.py` — generate the next-cycle `.inp`

**Files:**
- Modify: `s3dash/parser/nextcycle.py`
- Test: `tests/test_nextcycle.py`

**Interfaces:**
- Consumes: `lines: list[str]` (the full document's lines), the "Input Cards" section's `start`/`end` (from `Document.find("input", "Input Cards")`), `original_entries`/`modified_entries`, `Geometry`, `list[AppliedOperation]`, restart fields.
- Produces: `GenerationResult` (dataclass: `text: str`, `flagged_cards: list[str]`, `operations: list[AppliedOperation]`), `generate_inp(...) -> GenerationResult`, and `infer_next_restart_filename(current_filename: str) -> str | None`. These are the plan's final deliverables — Task 7's acceptance test calls `generate_inp` directly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_nextcycle.py`:

```python
from s3dash.parser.nextcycle import GenerationResult, generate_inp


class TestGenerateInp:
    def _section(self, lines):
        from s3dash.parser.document import load_text

        doc = load_text("\n".join(lines))
        return doc

    def test_fue_lab_block_is_replaced_and_res_wre_substituted(self):
        geom = _quarter_rotational(4)
        source_lines = [
            "'TIT.CAS' 'ORIGINAL TITLE' /",
            "'RES' 's3.plant.c01.depl.res' 20000./",
            "'FUE.LAB' 4/",
            "  1  1 N-03 TP01",
            "  0  0",
            "'FUE.NEW', 'TP01', 'F-101', 2, 8, ,,3/",
            "'WRE' 's3.plant.c02.depl.res' /",
            "'STA'/",
        ]
        entries = {
            (1, 1): _entry(1, 1, "N-03"),
            (1, 2): _entry(1, 2, "TP01", "fresh"),
        }
        result = generate_inp(
            lines=source_lines,
            section_start=0,
            section_end=len(source_lines),
            original_entries=entries,
            modified_entries=entries,
            geom=geom,
            operations=[],
            res_filename="s3.plant.c02.depl.res",
            res_exposure="24.112",
            wre_filename="s3.plant.c03.depl.res",
        )
        assert isinstance(result, GenerationResult)
        assert "'RES' 's3.plant.c02.depl.res' 24.112/" in result.text
        assert "'WRE' 's3.plant.c03.depl.res' /" in result.text
        assert "s3.plant.c01.depl.res" not in result.text
        assert "N-03" in result.text and "TP01" in result.text
        # unrelated cards survive verbatim
        assert "'FUE.NEW', 'TP01', 'F-101', 2, 8, ,,3/" in result.text
        assert "'STA'/" in result.text

    def test_tit_cas_and_bat_lab_preserved_but_flagged(self):
        geom = _quarter_rotational(4)
        source_lines = [
            "'TIT.CAS' 'PWR CYCLE 2' /",
            "'BAT.LAB' 2 'CYC-2' /",
            "'RES' 's3.plant.c01.depl.res' 20000./",
            "'FUE.LAB' 4/",
            "  1  1 N-03",
            "  0  0",
            "'WRE' 's3.plant.c02.depl.res' /",
        ]
        entries = {(1, 1): _entry(1, 1, "N-03")}
        result = generate_inp(
            lines=source_lines, section_start=0, section_end=len(source_lines),
            original_entries=entries, modified_entries=entries, geom=geom, operations=[],
            res_filename="x", res_exposure="1.0", wre_filename=None,
        )
        assert "'TIT.CAS' 'PWR CYCLE 2' /" in result.text
        assert "'BAT.LAB' 2 'CYC-2' /" in result.text
        assert "TIT.CAS" in result.flagged_cards
        assert "BAT.LAB" in result.flagged_cards

    def test_dep_cyc_gets_advisory_comment(self):
        geom = _quarter_rotational(4)
        source_lines = [
            "'RES' 's3.plant.c01.depl.res' 20000./",
            "'FUE.LAB' 4/",
            "  1  1 N-03",
            "  0  0",
            "'DEP.CYC' 'CYCLE 2 ' .0 2 /",
        ]
        entries = {(1, 1): _entry(1, 1, "N-03")}
        result = generate_inp(
            lines=source_lines, section_start=0, section_end=len(source_lines),
            original_entries=entries, modified_entries=entries, geom=geom, operations=[],
            res_filename="x", res_exposure="1.0", wre_filename=None,
        )
        lines_out = result.text.splitlines()
        dep_idx = next(i for i, l in enumerate(lines_out) if "DEP.CYC" in l)
        assert "'COM'" in lines_out[dep_idx - 1]
        assert "review" in lines_out[dep_idx - 1].lower()

    def test_no_wre_filename_means_wre_card_untouched(self):
        geom = _quarter_rotational(4)
        source_lines = [
            "'RES' 's3.plant.c01.depl.res' 20000./",
            "'FUE.LAB' 4/",
            "  1  1 N-03",
            "  0  0",
            "'WRE' 's3.plant.c02.depl.res' /",
        ]
        entries = {(1, 1): _entry(1, 1, "N-03")}
        result = generate_inp(
            lines=source_lines, section_start=0, section_end=len(source_lines),
            original_entries=entries, modified_entries=entries, geom=geom, operations=[],
            res_filename="x", res_exposure="1.0", wre_filename=None,
        )
        assert "'WRE' 's3.plant.c02.depl.res' /" in result.text


class TestInferNextRestartFilename:
    def test_increments_the_cycle_number_the_source_deck_demonstrates(self):
        from s3dash.parser.nextcycle import infer_next_restart_filename

        # apr1400.c02.out's own RES reads .c01., its own WRE writes .c02. --
        # a within-deck, read-then-write pair that unambiguously increments.
        # The parallel move for a generated next-cycle deck is .c02. -> .c03.
        assert infer_next_restart_filename("s3.apr1400_PPF.uo2.c02.depl.res") == \
            "s3.apr1400_PPF.uo2.c03.depl.res"

    def test_double_digit_cycle_number(self):
        from s3dash.parser.nextcycle import infer_next_restart_filename

        assert infer_next_restart_filename("s3.plant.c09.depl.res") == "s3.plant.c10.depl.res"

    def test_no_recognisable_cycle_pattern_returns_none(self):
        # Must not guess when the filename doesn't demonstrate a pattern --
        # the caller falls back to asking the user, per the design's
        # explicit "expose as an editable field" instruction.
        from s3dash.parser.nextcycle import infer_next_restart_filename

        assert infer_next_restart_filename("restart_file.res") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_nextcycle.py -v`
Expected: FAIL — `ImportError: cannot import name 'generate_inp'`

- [ ] **Step 3: Add `generate_inp` and `infer_next_restart_filename` to `nextcycle.py`**

Append to `s3dash/parser/nextcycle.py`:

```python
_DEP_CARD_NAMES = ("'DEP.CYC'", "'DEP.STA'")
_FLAG_VERBATIM_CARDS = ("'TIT.CAS'", "'BAT.LAB'")

_RES_RE = re.compile(r"^(\s*'RES'\s*)'[^']*'\s*[\d.]+\.?\s*/(.*)$")
_WRE_RE = re.compile(r"^(\s*'WRE'\s*)'[^']*'\s*/(.*)$")


@dataclass
class GenerationResult:
    text: str
    flagged_cards: list[str]
    operations: list[AppliedOperation]


def generate_inp(
    lines: list[str],
    section_start: int,
    section_end: int,
    original_entries: dict[tuple[int, int], LoadingEntry],
    modified_entries: dict[tuple[int, int], LoadingEntry],
    geom: Geometry,
    operations: list[AppliedOperation],
    res_filename: str,
    res_exposure: str,
    wre_filename: str | None,
) -> GenerationResult:
    """Build the next-cycle .inp text from the source deck's own echoed
    "Listing of Input Cards" -- the [section_start, section_end) slice of
    `lines`. Only the FUE.LAB grid, the RES card, and (if `wre_filename`
    is given) the WRE card are rewritten; everything else survives
    character-for-character. DEP.CYC/DEP.STA get an advisory comment
    inserted immediately before the first one found; TIT.CAS/BAT.LAB are
    left untouched but named in `flagged_cards` for the caller's audit
    summary.
    """
    block = list(lines[section_start:section_end])

    fuel_lab_line = None
    for i, line in enumerate(block):
        if "'FUE.LAB'" in line:
            fuel_lab_line = i
            break

    out: list[str] = []
    flagged: list[str] = []
    dep_comment_inserted = False
    i = 0
    while i < len(block):
        line = block[i]

        if fuel_lab_line is not None and i == fuel_lab_line:
            out.append(line)
            i += 1
            while i < len(block):
                toks = block[i].split()
                if not toks or toks[0] == "0":
                    i += 1
                    break
                i += 1
            out.append(encode_loading_pattern(modified_entries, geom))
            continue

        m = _RES_RE.match(line)
        if m:
            out.append(f"{m.group(1)}'{res_filename}' {res_exposure}/{m.group(2)}")
            i += 1
            continue

        m = _WRE_RE.match(line)
        if m and wre_filename:
            out.append(f"{m.group(1)}'{wre_filename}' /{m.group(2)}")
            i += 1
            continue

        if not dep_comment_inserted and any(name in line for name in _DEP_CARD_NAMES):
            out.append(
                "'COM' *** REVIEW: depletion schedule copied from the source "
                "cycle -- update the exposure/step points for this cycle "
                "before running ***"
            )
            dep_comment_inserted = True

        for card in _FLAG_VERBATIM_CARDS:
            if card in line:
                name = card.strip("'")
                if name not in flagged:
                    flagged.append(name)

        out.append(line)
        i += 1

    return GenerationResult(text="\n".join(out), flagged_cards=flagged, operations=operations)


_CYCLE_NUM_RE = re.compile(r"(?:^|[._])[Cc](\d+)(?=[._]|$)")


def infer_next_restart_filename(current_filename: str) -> str | None:
    """Best-effort next-cycle filename, incrementing the trailing
    cycle-number token a filename like "...c02.depl.res" demonstrates.
    The "c<digits>" must be bounded by "." or "_" or the ends of the
    string, so a coincidental digit run elsewhere in the name (e.g. a
    plant name like "apr1400") is never mistaken for it.

    This rests on a single within-deck example -- one source deck's own
    RES-reads / WRE-writes pair, which is the only real evidence
    available (see the design spec). Deliberately conservative: returns
    None rather than guessing when no such bounded pattern is found, so
    the caller exposes the field for the user to fill in instead, per
    the design's explicit instruction not to invent restart-naming
    syntax silently.
    """
    matches = list(_CYCLE_NUM_RE.finditer(current_filename))
    if not matches:
        return None
    m = matches[-1]
    digits = m.group(1)
    incremented = str(int(digits) + 1).zfill(len(digits))
    start, end = m.span(1)
    return current_filename[:start] + incremented + current_filename[end:]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_nextcycle.py -v`
Expected: PASS (20 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: `261 passed`

- [ ] **Step 6: Commit**

```bash
git add s3dash/parser/nextcycle.py tests/test_nextcycle.py
git commit -m "feat(loading-editor): generate the next-cycle .inp from the source deck's own card echo"
```

---

## Task 7: End-to-end acceptance test

**Files:**
- Test: `tests/test_nextcycle_acceptance.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6, plus `s3dash.parser.parse_file` and `s3dash.parser.inputcards.parse_input_deck` (to re-parse the generated text).

This is the request's own required test, run against real data end to end:
take `case_002495.out`, apply one known move, generate the `.inp`, **re-parse
the generated text with the existing parser**, and confirm the moved
assembly's new position holds it and the old position doesn't.

- [ ] **Step 1: Write the test**

```python
# tests/test_nextcycle_acceptance.py
"""End-to-end: parse a real listing, move one assembly (with its symmetry
partners), generate the next-cycle .inp text, re-parse that generated
text with the existing parser, and confirm the change actually took."""

from __future__ import annotations

import re

import pytest

from s3dash.parser import inputcards, parse_file
from s3dash.parser.document import load_text
from s3dash.parser.geometry import symmetry_orbit
from s3dash.parser.loadingpattern import (
    decode_loading_pattern,
    find_fuel_lab_card,
    parse_loading_pattern,
)
from s3dash.parser.nextcycle import (
    PositionChange,
    apply_change,
    encode_loading_pattern,
    generate_inp,
    infer_next_restart_filename,
    validate,
)
from tests.conftest import SAMPLES, samples_available

needs_listings = pytest.mark.skipif(
    not samples_available(), reason="reference listing not present (see README)"
)

_QUOTED_RE = re.compile(r"'([^']*)'")


def _input_cards_section_with_fuel_lab(doc):
    """The "Input Cards" section actually holding the FUE.LAB card --
    some builds echo the heading twice, leaving an empty stub section
    ahead of the real one (see build.py's own _first()), so the first
    match returned by find() is not trustworthy on its own."""
    for sec in doc.find("input", "Input Cards"):
        if find_fuel_lab_card(doc.lines[sec.start:sec.end]) is not None:
            return sec
    raise AssertionError("no Input Cards section in this file contains a FUE.LAB card")


@needs_listings
def test_move_survives_a_full_generate_and_reparse_round_trip():
    result = parse_file(SAMPLES / "case_002495.out")
    payload = result.payload
    lines = result.document.lines
    geom = result.geometry

    fresh_labels = {b["label"] for b in payload["inputDeck"]["batches"]}
    original_entries = parse_loading_pattern(
        lines, geom, fresh_labels, assembly_count=len(payload["assemblies"])
    )
    assert original_entries is not None

    # Pick two reused assemblies with matching (non-degenerate) symmetry
    # orbits, neither in the other's own orbit -- the general case a real
    # drag exercises. (9, 9) is this 17-wide core's one rotational fixed
    # point; everything else has a 4-member orbit.
    reused_positions = [pos for pos, e in original_entries.items() if e.kind == "reused"]
    from_pos = reused_positions[0]
    from_orbit = symmetry_orbit(from_pos[0], from_pos[1], geom)
    to_pos = next(
        pos for pos in reused_positions[1:]
        if pos not in from_orbit and len(symmetry_orbit(pos[0], pos[1], geom)) == len(from_orbit)
    )
    from_token = original_entries[from_pos].token

    change = PositionChange(from_pos[0], from_pos[1], to_pos[0], to_pos[1])
    modified_entries, op = apply_change(original_entries, change, geom)
    problems = validate(modified_entries, original_entries, geom)
    assert problems == []

    input_section = _input_cards_section_with_fuel_lab(result.document)

    # Derive RES/WRE the way the design spec calls for: the next cycle's
    # RES is exactly this run's own WRE value (a direct copy, not a
    # naming inference); WRE's own next value is the best-effort
    # increment, demonstrating infer_next_restart_filename against real
    # data rather than a synthetic fixture.
    wre_card = next(c for c in payload["inputDeck"]["cards"] if c["card"] == "WRE")
    current_wre_filename = _QUOTED_RE.search(wre_card["args"]).group(1)
    next_wre_filename = infer_next_restart_filename(current_wre_filename)

    gen = generate_inp(
        lines=lines,
        section_start=input_section.start,
        section_end=input_section.end,
        original_entries=original_entries,
        modified_entries=modified_entries,
        geom=geom,
        operations=[op],
        res_filename=current_wre_filename,
        res_exposure=str(payload["meta"]["cycleEnd"]),
        wre_filename=next_wre_filename,
    )
    assert f"'RES' '{current_wre_filename}'" in gen.text
    if next_wre_filename:
        assert f"'WRE' '{next_wre_filename}'" in gen.text

    # Re-parse the GENERATED text with the existing input-card parser --
    # the request's own acceptance bar.
    generated_doc = load_text(gen.text)
    reparsed_deck = inputcards.parse_input_deck(
        generated_doc.lines, 0, len(generated_doc.lines)
    )
    reparsed_fresh = {b.label for b in reparsed_deck.batches}
    reparsed_line = next(
        i for i, l in enumerate(generated_doc.lines) if "'FUE.LAB'" in l
    )
    reparsed_entries = decode_loading_pattern(
        generated_doc.lines, reparsed_line, reparsed_fresh
    )

    assert reparsed_entries[to_pos].token == from_token
    assert reparsed_entries[from_pos].token != from_token
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/test_nextcycle_acceptance.py -v`
Expected: PASS (1 passed). If it fails, do not adjust the assertions to
match wrong output — the whole point of this task is that it either
proves the round trip correct or surfaces a real bug in Tasks 3-6.

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -q`
Expected: `262 passed`

- [ ] **Step 4: Commit**

```bash
git add tests/test_nextcycle_acceptance.py
git commit -m "test(loading-editor): end-to-end move -> generate -> reparse acceptance test"
```
