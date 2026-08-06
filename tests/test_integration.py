"""End-to-end tests over the three reference listings.

These assert against facts the listing states about itself -- assembly counts,
segment tables, step counts -- so they catch a parser that produces
plausible-looking but wrong numbers, not just one that crashes.
"""

from __future__ import annotations

import re

import pytest


class TestGeometry:
    def test_apr1400_is_quarter_core_2d_17x17(self, apr):
        g = apr.payload["geometry"]
        assert g["iafull"] == 17
        assert g["ihave"] == 2 and g["fraction"] == "quarter"
        assert g["radialFraction"] == 0.25
        assert g["fuelNodes"] == 1 and g["is3d"] is False
        assert g["symmetry"] == "ROTATIONAL"
        assert g["reactorType"] == "PWR"

    def test_beavrs_is_full_core_3d_15x15(self, beavrs):
        g = beavrs.payload["geometry"]
        assert g["iafull"] == 15
        assert g["ihave"] == 4 and g["fraction"] == "full"
        assert g["radialFraction"] == 1.0
        assert g["kd"] == 14, "14 axial nodes including both reflectors"
        assert g["fuelNodes"] == 12 and g["is3d"] is True

    @pytest.mark.parametrize("key,expected", [("apr_c2", 241), ("apr_alt", 241), ("beavrs", 193)])
    def test_assembly_count_matches_the_listings_own_total(self, parsed, key, expected):
        payload = parsed[key].payload
        assert payload["geometry"]["nAssemblies"] == expected
        assert len(payload["assemblies"]) == expected


class TestSymmetryExpansion:
    def test_quarter_core_expands_to_every_assembly(self, apr):
        payload = apr.payload
        sp = payload["statePoints"][0]
        values = sp["values"]["2RPF"]
        assert sum(1 for v in values if v is not None) == 241

    def test_expansion_preserves_printed_values(self, apr, raw_lines):
        """A printed cell must never be replaced by a symmetry image."""
        payload = apr.payload
        idx = payload["assemblyIndex"]
        rpf = payload["statePoints"][0]["values"]["2RPF"]
        # Row 9 of the first 2RPF map, read straight from the file.
        for line in raw_lines["apr_c2"]:
            if re.match(r"^\s+9\s+1\.155\s+0\.831", line):
                break
        else:
            pytest.fail("reference 2RPF row not found in listing")
        assert rpf[idx["9,9"]] == 1.155
        assert rpf[idx["9,10"]] == 0.831
        assert rpf[idx["9,17"]] == 0.947

    def test_rotational_images_are_consistent(self, apr):
        """A rotationally symmetric core has equal power at imaged positions."""
        payload = apr.payload
        idx = payload["assemblyIndex"]
        rpf = payload["statePoints"][0]["values"]["2RPF"]
        n = payload["geometry"]["iafull"]
        r, c = 9, 12
        image = (c, n + 1 - r)
        assert rpf[idx[f"{r},{c}"]] == rpf[idx[f"{image[0]},{image[1]}"]]

    def test_full_core_file_is_not_expanded(self, beavrs):
        payload = beavrs.payload
        printed = [a for a in payload["assemblies"] if a["printed"]]
        assert len(printed) == len(payload["assemblies"])


class TestInventory:
    def test_type_counts_match_the_segment_table(self, apr):
        """Fueled Segments lists equivalent assemblies per segment; the map
        must produce the same per-type counts."""
        payload = apr.payload
        by_type = {r["fuelType"]: r["count"] for r in payload["inventory"]}
        by_seg = {s["number"]: s["equivalentAssemblies"] for s in payload["segments"]}
        for ftype, count in by_type.items():
            if ftype in by_seg:
                assert count == pytest.approx(by_seg[ftype], abs=1.0)

    def test_inventory_totals_the_whole_core(self, parsed):
        for key, result in parsed.items():
            payload = result.payload
            total = sum(r["count"] for r in payload["inventory"])
            assert total == len(payload["assemblies"]), key

    def test_fresh_batches_are_flagged(self, apr):
        fresh = [r for r in apr.payload["inventory"] if r["fresh"]]
        assert {r["batchLabel"] for r in fresh} == {"TP01", "TP02"}


class TestStatePoints:
    @pytest.mark.parametrize("key,steps", [("apr_c2", 31), ("apr_alt", 28), ("beavrs", 32)])
    def test_step_count(self, parsed, key, steps):
        assert len(parsed[key].payload["statePoints"]) == steps

    @pytest.mark.parametrize("key,steps", [("apr_c2", 31), ("apr_alt", 28), ("beavrs", 32)])
    def test_depletion_table_matches_state_points(self, parsed, key, steps):
        assert len(parsed[key].payload["depletion"]) == steps

    def test_keff_agrees_between_summary_and_depletion_table(self, parsed):
        """The two sources are printed independently; they must agree."""
        for key, result in parsed.items():
            payload = result.payload
            by_step = {d["step"]: d["keff"] for d in payload["depletion"]}
            for sp in payload["statePoints"]:
                if sp["keff"] is not None and sp["step"] in by_step:
                    assert sp["keff"] == pytest.approx(by_step[sp["step"]], abs=1e-5), (
                        f"{key} step {sp['step']}"
                    )

    def test_first_state_point_values(self, apr):
        sp = apr.payload["statePoints"][0]
        assert sp["case"] == 1 and sp["step"] == 0
        assert sp["exposure"] == 0.0
        assert sp["exposureUnit"] == "GWd/MT"
        assert sp["keff"] == pytest.approx(1.14074)

    def test_exposure_unit_is_read_not_assumed(self, beavrs):
        units = {sp["exposureUnit"] for sp in beavrs.payload["statePoints"]}
        assert "EFPD" in units, "BEAVRS reports cycle exposure in EFPD"

    def test_every_value_array_aligns_with_assemblies(self, parsed):
        for key, result in parsed.items():
            payload = result.payload
            n = len(payload["assemblies"])
            for sp in payload["statePoints"]:
                for code, arr in sp["values"].items():
                    assert len(arr) == n, f"{key} step {sp['step']} {code}"


class TestVariableDiscovery:
    def test_apr1400_variables(self, apr):
        assert set(apr.payload["variableOrder"]) == {"2RPF", "2EXP", "2PIN", "2PLO"}

    def test_beavrs_has_extra_variables_without_code_changes(self, beavrs):
        """2KIN and 2RR1 appear only here; the generic dispatch must find them."""
        codes = set(beavrs.payload["variableOrder"])
        assert {"2KIN", "2RR1"}.issubset(codes)

    def test_pin_location_map_stays_textual(self, apr):
        sp = apr.payload["statePoints"][0]
        values = [v for v in sp["values"]["2PLO"] if v is not None]
        assert values and all(isinstance(v, str) for v in values)


class TestAxial:
    def test_3d_file_has_per_node_rows(self, beavrs):
        ax = beavrs.payload["statePoints"][0]["axialState"]
        assert len(ax["nodes"]) == 12
        assert [n["node"] for n in ax["nodes"]] == list(range(1, 13))
        assert "RPF" in ax["columns"]

    def test_2d_file_has_no_nodes_but_keeps_the_average(self, apr):
        ax = apr.payload["statePoints"][0]["axialState"]
        assert ax["nodes"] == []
        assert ax["summary"]["Ave"]["RPF"] == pytest.approx(1.0)

    def test_axial_rpf_averages_to_one(self, beavrs):
        ax = beavrs.payload["statePoints"][0]["axialState"]
        mean = sum(n["RPF"] for n in ax["nodes"]) / len(ax["nodes"])
        assert mean == pytest.approx(ax["summary"]["Ave"]["RPF"], abs=0.02)


class TestDiagnostics:
    def test_apr1400_reports_symmetry_warnings(self, apr):
        status = apr.payload["status"]
        assert status["level"] == "WARNINGS"
        assert status["symmetryViolations"] == 8
        labels = {d["label"] for d in apr.payload["diagnostics"]}
        assert any(lbl.startswith("SYMGRP") for lbl in labels)

    def test_symmetry_groups_carry_their_members(self, apr):
        groups = apr.payload["symmetryGroups"]
        assert groups
        first = groups[0]
        assert len(first["members"]) >= 2
        member = first["members"][0]
        assert member["row"] and member["col"] and member["label"]
        assert member["aveExp"] is not None
        assert len(member["quadrantExp"]) == 4

    def test_beavrs_has_no_symmetry_violations(self, beavrs):
        assert beavrs.payload["status"]["symmetryViolations"] == 0
        assert beavrs.payload["symmetryGroups"] == []

    def test_severity_counts_are_summed_from_the_rollup(self, apr):
        payload = apr.payload
        expected = sum(d["times"] for d in payload["diagnostics"] if d["severity"] == "WARNING")
        assert payload["status"]["warnings"] == expected


class TestGracefulDegradation:
    def test_missing_input_maps_do_not_break_the_build(self, beavrs):
        """BEAVRS edits no PRI.INP maps; the run must still parse fully."""
        payload = beavrs.payload
        assert payload["maps"]["fmap"] is None
        assert len(payload["assemblies"]) == 193
        assert payload["assemblies"][0]["fuelType"] is not None

    def test_missing_batch_edits_are_reported_as_absent(self, beavrs):
        assert all(sp["batchEdits"] in (None, {}) for sp in beavrs.payload["statePoints"])

    def test_batch_edits_present_where_the_run_had_them(self, apr):
        sp = apr.payload["statePoints"][0]
        assert set(sp["batchEdits"]) == {"NPIN", "NXPO"}
        core = [r for r in sp["batchEdits"]["NPIN"] if r["batch"] == "CORE"]
        assert core and core[0]["assemblies"] == 241

    def test_no_parse_notes_on_the_reference_files(self, parsed):
        for key, result in parsed.items():
            assert result.payload["parseNotes"] == [], key

    def test_truncated_file_still_yields_a_payload(self, raw_lines):
        from s3dash.parser import parse_text

        partial = "\n".join(raw_lines["apr_c2"][:3000])
        result = parse_text(partial, source_file="truncated.out")
        assert result.payload["geometry"]["iafull"] == 17
        assert result.payload["sections"]

    def test_garbage_input_does_not_raise(self):
        from s3dash.parser import parse_text

        result = parse_text("not a simulate file\njust some text\n", source_file="junk.txt")
        assert result.payload["sections"] == []
        assert result.payload["assemblies"] == []


class TestNavigation:
    def test_nav_tree_groups_sections_by_case_and_step(self, apr):
        tree = apr.payload["navTree"]
        assert tree
        cases = {c["case"] for c in tree}
        assert 1 in cases
        case1 = next(c for c in tree if c["case"] == 1)
        assert len(case1["steps"]) >= 31

    def test_section_index_describes_edit_variables(self, apr):
        sections = apr.payload["sections"]
        rpf = next(s for s in sections if s["name"] == "2RPF")
        assert rpf["variable"]["name"] == "Relative Power Fraction"
        assert rpf["variable"]["basis"] == "2D assembly"
        assert rpf["end"] > rpf["start"]

    def test_unknown_edit_codes_still_describe_themselves(self):
        from s3dash.parser import describe_variable

        got = describe_variable("2ZZZ")
        assert got["code"] == "2ZZZ"
        assert got["prefix"] == "2"
        assert got["name"] == "ZZZ"
