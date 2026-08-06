"""Regression tests derived from the adversarial verification sweep.

Each test re-extracts its expected value from the raw listing using a
technique *different* from the production parser's, so a shared mistake in
both cannot make a test pass. The full sweep lives in ``verify/`` and compares
~147,000 values; what is kept here is the subset that (a) caught a real bug or
(b) guards an invariant a future refactor could plausibly break.

Line numbers quoted in comments are 0-based indices into the file as the
parser reads it, and are stable for the bundled sample files.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "verify") not in sys.path:
    sys.path.insert(0, str(ROOT / "verify"))

import raw  # noqa: E402  (verify/ must be on sys.path first)

SAMPLES = ROOT / "sample_data"
FILES = {"apr_c2": "case_002495.out", "apr_alt": "apr1400.c02.out", "beavrs": "9074.out"}


@pytest.fixture(scope="module")
def lines() -> dict[str, list[str]]:
    return {k: raw.read_lines(SAMPLES / v) for k, v in FILES.items()}


# --------------------------------------------------------------------- maps


class TestMapsAgainstRawCharacters:
    """Every printed map cell, re-read as fixed-width character windows."""

    def test_every_cell_of_every_map_matches(self, parsed, lines):
        for key, result in parsed.items():
            payload = result.payload
            index = payload["assemblyIndex"]
            sps = {(s["case"], s["step"]): s for s in payload["statePoints"]}
            compared = 0
            for m in raw.extract_maps(lines[key]):
                arr = sps[(m.case, m.step)]["values"][m.code]
                numeric = all(_is_number(t) for t in m.cells.values())
                for (row, col), text in m.cells.items():
                    got = arr[index[f"{row},{col}"]]
                    want = float(text) if numeric else text
                    assert got == want or (
                        numeric and got == pytest.approx(want, abs=0, rel=0)
                    ), f"{key} {m.code} ({row},{col}) at line {m.cell_line[(row, col)]}"
                    compared += 1
            assert compared > 7000, f"{key} compared only {compared} cells"

    def test_beavrs_ragged_row_one_lands_on_columns_five_to_eleven(self, beavrs, lines):
        """Row 1 prints seven values; they belong to columns 5-11, not 1-7."""
        maps = [m for m in raw.extract_maps(lines["beavrs"]) if m.code == "2RPF"]
        first = maps[0]
        assert sorted(c for (r, c) in first.cells if r == 1) == list(range(5, 12))
        index = beavrs.payload["assemblyIndex"]
        sp = beavrs.payload["statePoints"][0]
        assert sp["values"]["2RPF"][index["1,5"]] == 0.448
        assert sp["values"]["2RPF"][index["1,11"]] == 0.446
        assert "1,4" not in index and "1,12" not in index

    def test_pin_location_map_round_trips_byte_for_byte(self, parsed, lines):
        """``2PLO`` cells such as ``10, 9`` keep their internal space."""
        for key in ("apr_c2", "beavrs"):
            payload = parsed[key].payload
            index = payload["assemblyIndex"]
            sps = {(s["case"], s["step"]): s for s in payload["statePoints"]}
            seen_space = False
            for m in raw.extract_maps(lines[key]):
                if m.code != "2PLO":
                    continue
                arr = sps[(m.case, m.step)]["values"]["2PLO"]
                for (row, col), text in m.cells.items():
                    assert arr[index[f"{row},{col}"]] == text
                    seen_space |= " " in text
            assert seen_space, f"{key}: expected space-containing 2PLO cells"


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


# --------------------------------------------------------- symmetry expansion


class TestSymmetryExpansion:
    def test_quarter_core_expands_to_the_stated_assembly_count(self, parsed, lines):
        for key in ("apr_c2", "apr_alt"):
            stated = raw.input_summary_value(lines[key], "Fuel Assemblies")
            assert len(parsed[key].payload["assemblies"]) == int(stated)

    def test_expanded_cells_equal_their_rotational_image(self, apr, lines):
        """Derive the 90-degree orbit independently and check every image."""
        payload = apr.payload
        n = payload["geometry"]["iafull"]
        index = payload["assemblyIndex"]
        sp = payload["statePoints"][0]
        maps = {m.code: m for m in raw.extract_maps(lines["apr_c2"]) if m.case == 1 and m.step == 0}
        m = maps["2RPF"]
        checked = 0
        for (row, col), text in m.cells.items():
            r, c = row, col
            for _ in range(3):
                r, c = c, n + 1 - r
                if (r, c) in m.cells:
                    continue  # printed itself; covered by the map test
                assert sp["values"]["2RPF"][index[f"{r},{c}"]] == float(text), (
                    f"({r},{c}) should mirror printed ({row},{col})"
                )
                checked += 1
        assert checked > 100

    def test_printed_values_are_never_overwritten_by_an_image(self, apr, lines):
        """The asymmetries SYMGRP reports must survive expansion."""
        payload = apr.payload
        index = payload["assemblyIndex"]
        sp = payload["statePoints"][0]
        for m in raw.extract_maps(lines["apr_c2"]):
            if m.code != "2EXP" or (m.case, m.step) != (1, 0):
                continue
            # (13,14) and (14,13) are printed and differ: 29.911 vs 29.910.
            assert sp["values"]["2EXP"][index["13,14"]] == 29.911
            assert sp["values"]["2EXP"][index["14,13"]] == 29.910
            break


# ------------------------------------------------------------------ scalars


class TestStatePointScalars:
    def test_peak_nodal_power_is_captured(self, parsed):
        """Printed without a dot leader, so a generic key/value scan misses it."""
        expected = {"apr_c2": 1.424, "apr_alt": 1.439, "beavrs": 2.712}
        for key, want in expected.items():
            sp = parsed[key].payload["statePoints"][0]
            assert sp["peakNodal"] == want
            assert all(s["peakNodal"] is not None for s in parsed[key].payload["statePoints"])

    def test_scalars_match_their_own_output_summary_block(self, parsed, lines):
        for key, result in parsed.items():
            payload = result.payload
            ctx = raw.case_step_context(lines[key])
            sps = {(s["case"], s["step"]): s for s in payload["statePoints"]}
            for start, end in raw.output_summary_blocks(lines[key]):
                sp = sps.get(ctx[start])
                if sp is None:
                    continue
                for pattern, field in (
                    (r"K-effective[\s.]*(-?[\d.]+)", "keff"),
                    (r"Core Average Exposure[\s.]*EBAR\s+(-?[\d.]+)", "coreExposure"),
                    (r"Peak Nodal Power \(Location\)\s+(-?[\d.]+)", "peakNodal"),
                    (r"Axial Offset[\s.]*A-O\s+(-?[\d.]+)", "axialOffset"),
                ):
                    want = raw.summary_scalar(lines[key], start, end, pattern)
                    if want is not None:
                        assert sp[field] == want, f"{key} {ctx[start]} {field}"

    def test_exposure_comes_from_the_state_points_own_page(self, apr, apr_alt):
        """An exposure search retries a step; only the converged page counts.

        ``case_002495`` step 30 is first printed at a trial exposure of 25.050
        GWd/MT and converges at 24.112, which is what its Output Summary, its
        maps and the end-of-run table all report.
        """
        last = apr.payload["statePoints"][-1]
        assert last["step"] == 30
        assert last["exposure"] == 24.112
        assert apr.payload["meta"]["cycleEnd"] == 24.112
        assert apr_alt.payload["statePoints"][-1]["exposure"] == 21.685

    def test_beavrs_exposure_unit_is_efpd_everywhere(self, beavrs):
        """The pre-run page says GWd/MT; the run's actual unit is EFPD."""
        units = {sp["exposureUnit"] for sp in beavrs.payload["statePoints"]}
        assert units == {"EFPD"}
        assert beavrs.payload["meta"]["exposureUnit"] == "EFPD"

    def test_exposure_unit_is_never_hard_coded(self, parsed):
        assert parsed["apr_c2"].payload["meta"]["exposureUnit"] == "GWd/MT"
        assert parsed["beavrs"].payload["meta"]["exposureUnit"] == "EFPD"


# ---------------------------------------------------------------- depletion


class TestDepletionTable:
    def test_every_row_and_column_matches_the_raw_table(self, parsed, lines):
        columns = [
            ("cycleExposure", 2),
            ("keff", 3),
            ("nq", 4),
            ("boron", 5),
            ("axialPeak", 6),
            ("axialPeakNode", 7),
            ("axialOffset", 8),
            ("peakRadial", 9),
            ("peakNodal", 10),
            ("peak3pin", 11),
            ("density", 12),
            ("power", 13),
            ("flow", 14),
            ("crdPosition", 15),
            ("pressure", 16),
            ("inletTemp", 17),
            ("coreExposure", 18),
        ]
        for key, result in parsed.items():
            rows = raw.depletion_rows(lines[key])
            by_key = {}
            for toks in rows:
                by_key.setdefault((int(toks[0]), int(toks[1])), []).append(toks)
            dep = {(d["case"], d["step"]): d for d in result.payload["depletion"]}
            assert len(dep) == len(by_key), f"{key}: dedup changed the row count"
            for step_key, group in by_key.items():
                # The block is echoed; the copies must be identical, otherwise
                # collapsing them would be discarding a distinct row.
                assert len({tuple(g[:-1]) for g in group}) == 1
                for field, col in columns:
                    assert dep[step_key][field] == float(group[0][col]), (
                        f"{key} {step_key} {field}"
                    )

    def test_depletion_keff_agrees_with_the_output_summary(self, parsed):
        for key, result in parsed.items():
            payload = result.payload
            dep = {(d["case"], d["step"]): d["keff"] for d in payload["depletion"]}
            for sp in payload["statePoints"]:
                if sp["keff"] is not None and (sp["case"], sp["step"]) in dep:
                    assert sp["keff"] == pytest.approx(
                        dep[(sp["case"], sp["step"])], abs=1e-5
                    ), f"{key} step {sp['step']}"


# -------------------------------------------------------------------- axial


class TestAxialDistributions:
    def test_all_twelve_nodes_and_every_column_are_present(self, beavrs, lines):
        blocks = raw.axial_blocks(lines["beavrs"])
        first = next(b for b in blocks if b["kind"] == "state")
        ax = beavrs.payload["statePoints"][0]["axialState"]
        assert [n["node"] for n in ax["nodes"]] == list(range(1, 13))
        by_node = {n["node"]: n for n in ax["nodes"]}
        sub = first["subtables"][0]
        for node_id, values in sub["nodes"].items():
            for col, token in zip(sub["columns"], values):
                assert by_node[node_id][col] == float(token), f"node {node_id} {col}"

    def test_node_one_is_the_bottom_node_not_the_first_printed(self, beavrs, lines):
        """The listing prints node 12 first; ordering must not be reversed."""
        block = next(b for b in raw.axial_blocks(lines["beavrs"]) if b["kind"] == "state")
        printed_order = list(block["subtables"][0]["nodes"])
        assert printed_order[0] == 12, "fixture assumption: file prints top node first"
        ax = beavrs.payload["statePoints"][0]["axialState"]
        assert ax["nodes"][0]["node"] == 1
        assert ax["nodes"][0]["RPF"] == 0.57392  # the bottom node's value

    def test_average_row_equals_the_mean_of_the_nodes(self, beavrs):
        ax = beavrs.payload["statePoints"][0]["axialState"]
        for col in ("RPF", "KINF", "DEN"):
            mean = sum(n[col] for n in ax["nodes"]) / len(ax["nodes"])
            assert mean == pytest.approx(ax["summary"]["Ave"][col], rel=5e-3), col

    def test_sparse_summary_row_lands_in_its_own_column(self, beavrs):
        """``P**2`` prints one number, under EXPO -- not under the first column."""
        for sp in beavrs.payload["statePoints"]:
            p2 = sp["axialState"]["summary"].get("P**2")
            if p2 is None:
                continue
            assert set(p2) == {"EXPO"}, f"step {sp['step']}: {p2}"
        step2 = beavrs.payload["statePoints"][2]["axialState"]["summary"]["P**2"]
        assert step2["EXPO"] == 1.27916

    def test_page_width_continuation_subtables_are_not_dropped(self, parsed, lines):
        """The depletion block repeats its header with further columns."""
        for key in FILES:
            block = next(
                b for b in raw.axial_blocks(lines[key]) if b["kind"] == "depletion"
            )
            expected: list[str] = []
            for sub in block["subtables"]:
                for col in sub["columns"]:
                    if col not in expected:
                        expected.append(col)
            assert len(block["subtables"]) > 1, f"{key}: fixture assumption"
            got = parsed[key].payload["statePoints"][0]["axialDepletion"]["columns"]
            assert got == expected, f"{key}: {len(got)} columns, expected {len(expected)}"


# -------------------------------------------------------------- diagnostics


class TestDiagnostics:
    def test_every_rollup_row_matches_including_multiword_fields(self, parsed, lines):
        for key, result in parsed.items():
            rows = raw.diagnostic_rows(lines[key])
            uniq = {}
            for label, times, sev, where, info, line in rows:
                uniq.setdefault((label, times, sev, where, info), line)
            diag = {d["label"]: d for d in result.payload["diagnostics"]}
            assert len(diag) == len(uniq), f"{key}: echoed rows mis-collapsed"
            for (label, times, sev, where, info) in uniq:
                got = diag[label]
                assert (got["times"], got["severity"], got["where"], got["info"]) == (
                    times,
                    sev,
                    where,
                    info,
                ), f"{key} {label}"

    def test_symgrp_where_field_keeps_both_words(self, apr):
        """``RES STEP`` is one column; splitting it moves half into Info."""
        row = next(d for d in apr.payload["diagnostics"] if d["label"] == "SYMGRP A")
        assert row["where"] == "RES STEP"
        assert row["info"] == "not quarter rotational"

    def test_status_counts_are_the_summed_times(self, parsed, lines):
        for key, result in parsed.items():
            uniq = {r[:5] for r in raw.diagnostic_rows(lines[key])}
            totals: dict[str, int] = {}
            for label, times, sev, where, info in uniq:
                totals[sev] = totals.get(sev, 0) + times
            status = result.payload["status"]
            assert status["errors"] == totals.get("ERROR", 0)
            assert status["warnings"] == totals.get("WARNING", 0)
            assert status["cautions"] == totals.get("CAUTION", 0)
            assert status["notes"] == totals.get("NOTE", 0)
            assert status["distinctLabels"] == len(uniq)

    def test_apr1400_counts_are_the_documented_ones(self, apr):
        status = apr.payload["status"]
        assert (status["warnings"], status["cautions"], status["notes"]) == (71, 33, 40)


# ---------------------------------------------------------- symmetry groups


class TestSymmetryGroups:
    def test_side_by_side_cards_are_all_captured(self, apr, lines):
        """Two cards share a line when both sit on the same core row."""
        groups = {g["group"]: g for g in apr.payload["symmetryGroups"]}
        assert len(groups) == 8
        for g in raw.symmetry_blocks(lines["apr_c2"]):
            got = groups[g["group"]]
            assert len(got["members"]) == len(g["members"]), (
                f"group {g['group']}: {len(g['members'])} cards printed at "
                f"line {g['line']}, payload has {len(got['members'])}"
            )
            for mine, theirs in zip(g["members"], got["members"]):
                assert (theirs["tag"], theirs["row"], theirs["col"], theirs["label"]) == (
                    mine["tag"],
                    mine["row"],
                    mine["col"],
                    mine["label"],
                )
                assert theirs["fuelType"] == int(mine["typ"])
                assert theirs["rotation"] == int(mine["rot"])
                assert theirs["aveExp"] == mine["ave"]
                assert theirs["quadrantExp"] == mine["quad"]

    def test_group_d_has_three_members_with_real_tags(self, apr):
        d = next(g for g in apr.payload["symmetryGroups"] if g["group"] == "D")
        assert [m["tag"] for m in d["members"]] == ["D1", "D2", "D0"]
        assert [(m["row"], m["col"]) for m in d["members"]] == [(9, 5), (9, 13), (13, 9)]


# ------------------------------------------------------- assembly identity


class TestAssemblyIdentity:
    def test_site_labels_match_the_map_column_footers(self, parsed, lines):
        for key, result in parsed.items():
            payload = result.payload
            letters: dict[int, str] = {}
            for m in raw.extract_maps(lines[key]):
                letters.update(m.col_labels)
            assert letters, f"{key}: no column footers found"
            for pos, i in payload["assemblyIndex"].items():
                row, col = (int(x) for x in pos.split(","))
                if col in letters:
                    assert payload["assemblies"][i]["site"] == f"{letters[col]}-{row:02d}"

    def test_fmap_labels_and_serials_match_the_printed_grid(self, apr, lines):
        cells: dict[tuple[int, int], list[str]] = {}
        for band in raw.bordered_bands(lines["apr_c2"], "FMAP"):
            cells.update(band["cells"])
        assert len(cells) > 250
        payload = apr.payload
        index = payload["assemblyIndex"]
        for (row, col), fields in cells.items():
            if not any(fields):
                continue
            a = payload["assemblies"][index[f"{row},{col}"]]
            assert a["label"] == fields[0]
            assert a["serial"] == fields[1]

    def test_beavrs_fuel_types_match_the_fue_typ_matrix(self, beavrs, lines):
        grid = raw.fue_typ_grid(lines["beavrs"])
        assert grid, "FUE.TYP matrix not found"
        nref = beavrs.payload["geometry"]["nref"]
        payload = beavrs.payload
        for pos, i in payload["assemblyIndex"].items():
            row, col = (int(x) for x in pos.split(","))
            assert payload["assemblies"][i]["fuelType"] == grid[(row + nref, col + nref)]

    def test_symmetric_positions_describe_the_same_assembly(self, parsed):
        """An expanded position and its printed original must not disagree."""
        for key in ("apr_c2", "apr_alt"):
            payload = parsed[key].payload
            n = payload["geometry"]["iafull"]
            index = payload["assemblyIndex"]
            for pos, i in index.items():
                row, col = (int(x) for x in pos.split(","))
                a = payload["assemblies"][i]
                r, c = row, col
                for _ in range(3):
                    r, c = c, n + 1 - r
                    b = payload["assemblies"][index[f"{r},{c}"]]
                    assert (a["fuelType"], a["batch"], a["enrichment"], a["bpRods"]) == (
                        b["fuelType"],
                        b["batch"],
                        b["enrichment"],
                        b["bpRods"],
                    ), f"{key}: {a['site']} vs {b['site']}"

    def test_segment_equivalents_account_for_every_assembly(self, parsed, lines):
        for key, result in parsed.items():
            total = sum(float(t[8]) for t in raw.fueled_segments(lines[key]))
            # Axially zoned cores print fractional equivalents to 3dp.
            assert total == pytest.approx(len(result.payload["assemblies"]), abs=0.01)


# ------------------------------------------------------------- cross-source


class TestCrossSourceConsistency:
    def test_assembly_count_agrees_across_three_independent_statements(
        self, parsed, lines
    ):
        for key, result in parsed.items():
            payload = result.payload
            stated = int(raw.input_summary_value(lines[key], "Fuel Assemblies"))
            assert payload["geometry"]["nAssemblies"] == stated
            assert len(payload["assemblies"]) == stated
            for sp in payload["statePoints"]:
                for rows in (sp.get("batchEdits") or {}).values():
                    for row in rows:
                        if row["batch"] == "CORE":
                            assert row["assemblies"] == stated

    def test_state_point_exposure_agrees_with_the_depletion_table(self, parsed):
        for key, result in parsed.items():
            payload = result.payload
            dep = {(d["case"], d["step"]): d for d in payload["depletion"]}
            for sp in payload["statePoints"]:
                row = dep.get((sp["case"], sp["step"]))
                if row is None or sp["exposure"] is None:
                    continue
                assert sp["exposure"] == pytest.approx(
                    row["cycleExposure"], abs=1e-3
                ), f"{key} step {sp['step']}"
                assert sp["coreExposure"] == pytest.approx(
                    row["coreExposure"], abs=1e-3
                ), f"{key} step {sp['step']}"

    def test_2exp_unit_comes_from_the_listing_not_a_constant(self, parsed, lines):
        """``2EXP`` is headed ``GWD/T``; the cycle unit is a separate thing."""
        for key, result in parsed.items():
            heading = next(
                ln for ln in lines[key] if re.match(r"^\s*PRI\.STA 2EXP\s+-", ln)
            )
            unit = heading.rstrip().rsplit("-", 1)[1].strip()
            assert unit == "GWD/T", f"{key}: fixture assumption ({heading!r})"
            section = next(
                s
                for s in result.payload["sections"]
                if s.get("variable") and s["variable"]["code"] == "2EXP"
            )
            assert section["variable"]["unit"] == unit, (
                f"{key}: 2EXP unit must be the heading's, not a table constant"
            )
            # ... and the cycle exposure unit is independent of it.
            assert result.payload["meta"]["exposureUnit"] in {"GWd/MT", "EFPD"}

    def test_variable_unit_falls_back_when_the_heading_is_silent(self, apr):
        """A heading with no unit must not have a descriptive word read as one."""
        by_code = {
            s["variable"]["code"]: s["variable"]
            for s in apr.payload["sections"]
            if s.get("variable")
        }
        assert by_code["2RPF"]["unit"] == ""
        assert by_code["2PLO"]["unit"] == ""
