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
