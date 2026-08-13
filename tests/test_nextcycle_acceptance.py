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
    # naming inference). case_002495.out itself has no WRE card -- not
    # every deck sets up a restart chain (it may be a single sensitivity
    # case rather than part of an ongoing depletion sequence) -- so this
    # falls back to a placeholder rather than crashing; the RES/WRE
    # substitution mechanics are exercised for real against apr1400's own
    # data in TestGenerateInp instead. The loading-pattern move/generate/
    # reparse round trip below -- this test's actual acceptance bar -- is
    # unaffected either way.
    wre_card = next(
        (c for c in payload["inputDeck"]["cards"] if c["card"] == "WRE"), None
    )
    current_wre_filename = (
        _QUOTED_RE.search(wre_card["args"]).group(1) if wre_card else "placeholder.depl.res"
    )
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
