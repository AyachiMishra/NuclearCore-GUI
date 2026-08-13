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


def replay_changes(
    original_entries: dict[tuple[int, int], LoadingEntry],
    changes: list[PositionChange],
    geom: Geometry,
) -> tuple[dict[tuple[int, int], LoadingEntry], list[AppliedOperation]]:
    """Fold apply_change over `changes` in order, starting from
    `original_entries`. The one place app.py and browser.py both call
    into instead of each reimplementing this loop.

    Raises ValidationError (from whichever apply_change call fails) if
    any change is invalid. The exception message already names the
    specific (row, col) involved -- more actionable for a caller than a
    bare list index would be, so this does not add one.
    """
    entries = original_entries
    operations: list[AppliedOperation] = []
    for change in changes:
        entries, op = apply_change(entries, change, geom)
        operations.append(op)
    return entries, operations
