"""Standalone HTML report generation."""

from __future__ import annotations

import re

import pytest

from s3dash.web.report import render_report


@pytest.fixture(scope="module")
def reports(parsed) -> dict:
    return {key: render_report(result.payload, step=0) for key, result in parsed.items()}


class TestStructure:
    def test_is_a_complete_standalone_document(self, reports):
        for key, doc in reports.items():
            assert doc.startswith("<!doctype html>"), key
            assert doc.rstrip().endswith("</html>"), key
            assert "<style>" in doc, key

    def test_has_no_external_references(self, reports):
        """The report must survive being emailed and opened offline."""
        for key, doc in reports.items():
            assert "http://" not in doc, key
            assert "https://" not in doc, key
            assert "<script" not in doc.lower(), key
            assert "<link" not in doc.lower(), key

    def test_svg_tags_are_balanced(self, reports):
        for key, doc in reports.items():
            assert doc.count("<svg") == doc.count("</svg>"), key
            assert doc.count("<table") == doc.count("</table>"), key

    def test_no_unrendered_placeholders(self, reports):
        for key, doc in reports.items():
            body = doc.split("</style>", 1)[1]
            assert ">None<" not in body, key
            assert "{" not in body.replace("&#123;", ""), key


class TestContent:
    def test_reports_the_real_geometry(self, reports):
        # Dimensions are written with the &times; entity, not a literal glyph.
        assert "17&times;17" in reports["apr_c2"]
        assert "quarter-core rotational" in reports["apr_c2"]
        assert "2D (1 axial node)" in reports["apr_c2"]
        assert "15&times;15" in reports["beavrs"]
        assert "full-core rotational" in reports["beavrs"]
        assert "3D, 12 axial nodes" in reports["beavrs"]

    def test_reports_termination_status(self, reports):
        for key, doc in reports.items():
            assert "Normal Termination" in doc, key

    def test_core_map_draws_one_cell_per_assembly(self, parsed, reports):
        for key, result in parsed.items():
            n = len(result.payload["assemblies"])
            # Each assembly contributes exactly one <rect>; the axis labels are text.
            rects = len(re.findall(r"<rect ", reports[key]))
            assert rects == n, key

    def test_symmetry_violations_are_tabulated(self, reports):
        doc = reports["apr_c2"]
        assert "Symmetry check" in doc
        # 8 groups, each with 2-3 member rows.
        assert doc.count("<tr>") > 8

    def test_clean_run_omits_the_symmetry_section(self, reports):
        assert "Symmetry check" not in reports["beavrs"]

    def test_depletion_table_has_a_row_per_step(self, parsed, reports):
        for key, result in parsed.items():
            steps = len(result.payload["depletion"])
            for row in result.payload["depletion"][:3]:
                assert f">{row['step']}<" in reports[key], key
            assert steps > 0

    def test_values_appear_verbatim_from_the_payload(self, parsed, reports):
        """A spot value must reach the report unchanged."""
        payload = parsed["apr_c2"].payload
        idx = payload["assemblyIndex"]["9,9"]
        value = payload["statePoints"][0]["values"]["2RPF"][idx]
        assert f"{value:,.3f}" in reports["apr_c2"]


class TestEscaping:
    def test_hostile_text_is_escaped(self, parsed):
        payload = dict(parsed["apr_c2"].payload)
        payload["meta"] = {**payload["meta"], "caseTitle": "<script>alert(1)</script>"}
        doc = render_report(payload, step=0)
        assert "<script>alert(1)</script>" not in doc
        assert "&lt;script&gt;" in doc


class TestDegradation:
    def test_renders_with_no_state_points(self, parsed):
        payload = dict(parsed["apr_c2"].payload)
        payload["statePoints"] = []
        payload["depletion"] = []
        doc = render_report(payload)
        assert doc.startswith("<!doctype html>")
        assert "Not enough depletion steps" in doc

    def test_renders_with_empty_diagnostics(self, parsed):
        payload = dict(parsed["beavrs"].payload)
        payload["diagnostics"] = []
        doc = render_report(payload)
        assert "No diagnostics" in doc
