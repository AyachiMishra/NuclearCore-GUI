"""Tests for the browser adapter -- the same operations app.py exposes over
HTTP, called directly as they will be from inside Pyodide."""

from __future__ import annotations

import base64
import json

import pytest

from s3dash.web import browser
from tests.conftest import SAMPLES, samples_available

needs_listings = pytest.mark.skipif(
    not samples_available(), reason="reference listing not present (see README)"
)


@pytest.fixture
def run_id():
    raw = (SAMPLES / "case_002495.out").read_bytes()
    result = json.loads(browser.parse(raw, "case_002495.out"))
    assert result["ok"] is True
    return result["runId"]


class TestParse:
    @needs_listings
    def test_parses_a_real_listing(self):
        raw = (SAMPLES / "9074.out").read_bytes()
        result = json.loads(browser.parse(raw, "9074.out"))
        assert result["ok"] is True
        assert result["geometry"]["iafull"] == 15
        assert len(result["assemblies"]) == 193
        assert result["runId"]

    def test_empty_file_is_reported_not_raised(self):
        result = json.loads(browser.parse(b"", "empty.out"))
        assert result["ok"] is False
        assert "empty" in result["detail"].lower()

    def test_non_simulate_file_is_reported_with_a_useful_message(self):
        blob = (b"just some text that is not a listing\n" * 10)
        result = json.loads(browser.parse(blob, "junk.txt"))
        assert result["ok"] is False
        assert "SIMULATE-3" in result["detail"]

    @needs_listings
    def test_accepts_a_memoryview_like_pyodide_hands_through(self, run_id):
        # Pyodide converts a JS Uint8Array argument into a buffer-like object,
        # not a plain `bytes` -- browser.parse must accept that too.
        raw = memoryview((SAMPLES / "case_002495.out").read_bytes())
        result = json.loads(browser.parse(raw, "case_002495.out"))
        assert result["ok"] is True


class TestSectionAndSearch:
    @needs_listings
    def test_section_text_returns_raw_listing(self, run_id):
        parsed = json.loads(browser.parse((SAMPLES / "case_002495.out").read_bytes(), "case_002495.out"))
        sec = next(s for s in parsed["sections"] if s["name"] == "2RPF")
        result = json.loads(browser.section_text(parsed["runId"], sec["start"], sec["end"]))
        assert result["ok"] is True
        assert "PRI.STA 2RPF" in result["text"]

    @needs_listings
    def test_search_finds_lines(self, run_id):
        result = json.loads(browser.search(run_id, "SYMGRP"))
        assert result["ok"] is True
        assert result["count"] > 0
        assert "SYMGRP" in result["hits"][0]["text"]

    def test_unknown_run_is_reported_not_raised(self):
        result = json.loads(browser.search("deadbeef", "x"))
        assert result["ok"] is False


class TestExports:
    @needs_listings
    def test_export_json_round_trips_the_payload(self, run_id):
        parsed = json.loads(browser.parse((SAMPLES / "case_002495.out").read_bytes(), "case_002495.out"))
        result = json.loads(browser.export_json(parsed["runId"]))
        assert result["ok"] is True
        assert result["payload"]["geometry"]["iafull"] == 17

    @needs_listings
    def test_export_csv_has_one_row_per_assembly(self, run_id):
        result = json.loads(browser.export_csv(run_id, step=0))
        assert result["ok"] is True
        rows = result["csv"].strip().split("\n")
        assert len(rows) == 242
        assert "site" in rows[0] and "2RPF" in rows[0]

    @needs_listings
    def test_report_pdf_returns_base64_pdf_bytes(self, run_id):
        result = json.loads(browser.report_pdf(run_id, step=0))
        assert result["ok"] is True
        pdf_bytes = base64.b64decode(result["pdfBase64"])
        assert pdf_bytes.startswith(b"%PDF-")

    def test_export_on_unknown_run_is_reported_not_raised(self):
        result = json.loads(browser.export_csv("deadbeef", step=0))
        assert result["ok"] is False


class TestLoadingPattern:
    @needs_listings
    def test_supported_run_returns_full_entries(self, run_id):
        result = json.loads(browser.loading_pattern(run_id))
        assert result["ok"] is True
        assert result["supported"] is True
        assert len(result["entries"]) > 0

    def test_unknown_run_is_reported_not_raised(self):
        result = json.loads(browser.loading_pattern("deadbeef"))
        assert result["ok"] is True
        assert result["supported"] is False

    @needs_listings
    def test_apply_a_valid_swap(self, run_id):
        original = json.loads(browser.loading_pattern(run_id))
        reused = [e for e in original["entries"] if e["kind"] == "reused"]
        a, b = reused[0], reused[1]
        changes = json.dumps([
            {"fromRow": a["row"], "fromCol": a["col"], "toRow": b["row"], "toCol": b["col"]}
        ])
        result = json.loads(browser.apply_loading_pattern(run_id, changes))
        assert result["ok"] is True
        assert result["valid"] is True
        assert result["problems"] == []

    @needs_listings
    def test_apply_an_invalid_move_is_reported_not_raised(self, run_id):
        changes = json.dumps([{"fromRow": 1, "fromCol": 1, "toRow": 2, "toCol": 2}])
        result = json.loads(browser.apply_loading_pattern(run_id, changes))
        assert result["ok"] is False
        assert "No assembly" in result["detail"]

    @needs_listings
    def test_generate_returns_inp_text_reflecting_the_change(self, run_id):
        original = json.loads(browser.loading_pattern(run_id))
        reused = [e for e in original["entries"] if e["kind"] == "reused"]
        a, b = reused[0], reused[1]
        changes = json.dumps([
            {"fromRow": a["row"], "fromCol": a["col"], "toRow": b["row"], "toCol": b["col"]}
        ])
        result = json.loads(
            browser.generate_loading_pattern(run_id, changes, "placeholder.res", "0.0", None)
        )
        assert result["ok"] is True
        assert "'RES' 'placeholder.res' 0.0/" in result["text"]
        assert b["token"] in result["text"]
        assert isinstance(result["flaggedCards"], list)
        assert result["filename"].endswith("_cycle_next.inp")
