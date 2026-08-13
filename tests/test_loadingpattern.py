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
