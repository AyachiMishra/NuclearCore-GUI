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

from .document import Document, Section
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


def find_input_cards_section(doc: Document) -> Section:
    """The "Input Cards" section actually holding a FUE.LAB card.

    Some builds echo the "Listing of Input Cards" heading twice, leaving
    an empty stub section ahead of the real one -- the same issue
    build.py's own _first() exists to guard against for other sections.
    Document.find(...)[0] is therefore not safe to use directly here.

    Raises LoadingPatternError if no such section exists.
    """
    for sec in doc.find("input", "Input Cards"):
        if find_fuel_lab_card(doc.lines[sec.start:sec.end]) is not None:
            return sec
    raise LoadingPatternError(
        "No 'Input Cards' section containing a FUE.LAB card was found in this listing."
    )
