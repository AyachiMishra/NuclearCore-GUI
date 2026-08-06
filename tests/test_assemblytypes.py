"""Assembly type descriptions and the FUE.TYP -> segment mapping."""

from __future__ import annotations

import pytest

from s3dash.parser.assemblytypes import (
    count_for_type,
    parse_assembly_types,
    segment_for_type,
)

# Two records side by side, each with a short end region and a tall fuel zone.
# This is the APR1400 shape: the fuel segment is not the only one present.
BLOCK = [
    " Assembly Physical Descriptions",
    " ------------------------------",
    "",
    " Assm. Name    : RADIALREF           |   Assm. Name    : ASSMBLYH1",
    " Assm. Sub Type:    1     1          |   Assm. Sub Type:    4     4",
    " Assm. Class   : Reflector           |   Assm. Class   : Fuel",
    " Fuel  Type    : 1                   |   Fuel  Type    : 4",
    " Mech. Design  : 1                   |   Mech. Design  : 1",
    " Loading (gram): 0.                  |   Loading (gram): 433533.",
    " # Axial Zone  : 1                   |   # Axial Zone  : 2",
    " # Assm        : 30.000              |   # Assm in Core: 56.000",
    "                                     |",
    "                                     |   **********************  381.000 cm",
    "                                     |   *     Segment:4      *",
    "                                     |   *         H1         *",
    "                                     |   *     351.000 cm     *",
    " **********************  381.000 cm  |   **********************   30.000 cm",
    " *     Segment:1      *              |   *     Segment:10     *",
    " *       RADREF       *              |   *        ACB         *",
    " *     381.000 cm     *              |   *     30.000 cm      *",
    " **********************    0.000 cm  |   **********************    0.000 cm",
    "",
    " Control Rod Descriptions",
    " **********************  365.760 cm",
    " *     Segment:99     *",
]


class TestParsing:
    def test_reads_both_side_by_side_records(self):
        types = parse_assembly_types(BLOCK, 0, len(BLOCK))
        assert [t.fuel_type for t in types] == [1, 4]

    def test_reads_names_class_and_counts(self):
        types = {t.fuel_type: t for t in parse_assembly_types(BLOCK, 0, len(BLOCK))}
        assert types[4].name == "ASSMBLYH1"
        assert types[4].assembly_class == "Fuel"
        assert types[4].is_fuel is True
        assert types[1].is_fuel is False
        assert types[4].count_in_core == 56.0
        assert types[4].loading_grams == 433533.0
        assert types[4].axial_zones == 2

    def test_hash_prefixed_fields_are_read(self):
        """'# Assm in Core' and '# Axial Zone' start with '#', not a letter."""
        types = {t.fuel_type: t for t in parse_assembly_types(BLOCK, 0, len(BLOCK))}
        assert types[4].count_in_core is not None
        assert types[4].axial_zones is not None

    def test_stops_before_the_next_block(self):
        """The section extends past the assemblies; segment 99 belongs to the
        control rod descriptions and must not leak in."""
        types = {t.fuel_type: t for t in parse_assembly_types(BLOCK, 0, len(BLOCK))}
        assert 99 not in types[4].segments
        assert types[4].segment_heights == {4: 351.0, 10: 30.0}


class TestActiveSegment:
    def test_picks_the_tallest_segment_not_the_last(self):
        """A short axial cutback sits below the fuel; picking by position or
        frequency would choose the cutback."""
        types = {t.fuel_type: t for t in parse_assembly_types(BLOCK, 0, len(BLOCK))}
        assert types[4].active_segment == 4

    def test_mapping_excludes_reflectors(self):
        types = parse_assembly_types(BLOCK, 0, len(BLOCK))
        assert segment_for_type(types) == {4: 4}
        assert count_for_type(types) == {4: 56.0}


class TestAgainstRealFiles:
    def test_apr1400_mapping_is_identity(self, apr):
        specs = {t["fuelType"]: t for t in apr.payload["assemblyTypes"]}
        for ftype in (4, 5, 8, 9):
            assert specs[ftype]["activeSegment"] == ftype

    def test_beavrs_mapping_is_not_identity(self, beavrs):
        """Assuming FUE.TYP == segment number would attribute the wrong
        enrichment to most of the BEAVRS core."""
        specs = {t["fuelType"]: t for t in beavrs.payload["assemblyTypes"]}
        assert specs[7]["activeSegment"] == 12
        assert specs[10]["activeSegment"] == 9
        assert specs[2]["activeSegment"] == 4

    def test_enrichment_follows_the_stated_segment(self, beavrs):
        """Type 7 is PWRU310W16 at 3.10 w/o. Segment 7 is PWRU240W16 at 2.40,
        which is what the identity assumption would have produced."""
        row = next(r for r in beavrs.payload["inventory"] if r["fuelType"] == 7)
        assert row["segmentName"] == "PWRU310W16"
        assert row["enrichment"] == pytest.approx(3.10)

    def test_type_names_match_their_segment_names(self, beavrs):
        """An independent confirmation that the mapping is right."""
        for row in beavrs.payload["inventory"]:
            if row["typeName"] and row["segmentName"]:
                assert row["typeName"] == row["segmentName"]

    def test_declared_counts_total_the_core(self, parsed):
        for key, result in parsed.items():
            payload = result.payload
            stated = sum(
                t["countInCore"]
                for t in payload["assemblyTypes"]
                if t["isFuel"] and t["countInCore"]
            )
            assert stated == pytest.approx(len(payload["assemblies"]), abs=0.5), key


class TestSegmentTable:
    def test_segments_without_burnable_poison_are_not_dropped(self, beavrs):
        """Columns that do not apply print as '------'; requiring digits there
        silently discarded 107 of BEAVRS's 193 assemblies."""
        numbers = {s["number"] for s in beavrs.payload["segments"]}
        assert {4, 5, 8}.issubset(numbers)
        no_bp = next(s for s in beavrs.payload["segments"] if s["number"] == 4)
        assert no_bp["bpLoading"] is None
        assert no_bp["enrichment"] == pytest.approx(1.61)

    def test_segment_equivalents_total_the_core(self, parsed):
        for key, result in parsed.items():
            payload = result.payload
            total = sum(
                s["equivalentAssemblies"]
                for s in payload["segments"]
                if s["equivalentAssemblies"]
            )
            assert total == pytest.approx(len(payload["assemblies"]), abs=1.0), key
