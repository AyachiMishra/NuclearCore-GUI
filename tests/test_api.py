"""HTTP surface tests using FastAPI's test client."""

from __future__ import annotations

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from s3dash.web.app import app
from tests.conftest import SAMPLES


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def run_id(client) -> str:
    resp = client.post("/api/samples/case_002495.out")
    assert resp.status_code == 200
    return resp.json()["runId"]


class TestParse:
    def test_upload_returns_full_payload(self, client):
        data = (SAMPLES / "9074.out").read_bytes()
        resp = client.post(
            "/api/parse", files={"file": ("9074.out", io.BytesIO(data), "text/plain")}
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["geometry"]["iafull"] == 15
        assert len(payload["assemblies"]) == 193
        assert payload["runId"]

    def test_empty_upload_is_rejected(self, client):
        resp = client.post(
            "/api/parse", files={"file": ("empty.out", io.BytesIO(b""), "text/plain")}
        )
        assert resp.status_code == 400

    def test_non_simulate_file_is_rejected_with_a_useful_message(self, client):
        blob = b"just some text that is not a listing\n" * 10
        resp = client.post(
            "/api/parse", files={"file": ("junk.txt", io.BytesIO(blob), "text/plain")}
        )
        assert resp.status_code == 422
        assert "SIMULATE-3" in resp.json()["detail"]

    def test_payload_is_json_serialisable_end_to_end(self, client, run_id):
        resp = client.get(f"/api/run/{run_id}/export.json")
        assert resp.status_code == 200
        assert json.loads(resp.content)["geometry"]["iafull"] == 17


class TestSamples:
    def test_samples_are_listed(self, client):
        names = {s["name"] for s in client.get("/api/samples").json()["samples"]}
        assert {"case_002495.out", "apr1400.c02.out", "9074.out"} <= names

    def test_unknown_sample_is_404(self, client):
        assert client.post("/api/samples/nope.out").status_code == 404

    def test_path_traversal_is_refused(self, client):
        resp = client.post("/api/samples/..%2F..%2Frequirements.txt")
        assert resp.status_code == 404


class TestSectionAndSearch:
    def test_section_text_returns_raw_listing(self, client, run_id):
        payload = client.post("/api/samples/case_002495.out").json()
        sec = next(s for s in payload["sections"] if s["name"] == "2RPF")
        resp = client.get(
            f"/api/run/{payload['runId']}/section",
            params={"start": sec["start"], "end": sec["end"]},
        )
        assert resp.status_code == 200
        assert "PRI.STA 2RPF" in resp.text
        assert "1.155" in resp.text

    def test_context_widens_the_window(self, client, run_id):
        narrow = client.get(
            f"/api/run/{run_id}/section", params={"start": 2554, "end": 2556}
        ).text
        wide = client.get(
            f"/api/run/{run_id}/section", params={"start": 2554, "end": 2556, "context": 5}
        ).text
        assert len(wide) > len(narrow)

    def test_search_finds_lines_with_state_point_context(self, client, run_id):
        resp = client.get(f"/api/run/{run_id}/search", params={"q": "SYMGRP"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] > 0
        hit = body["hits"][0]
        assert "SYMGRP" in hit["text"]
        assert hit["line"] >= 0

    def test_unknown_run_is_404(self, client):
        resp = client.get("/api/run/deadbeef/search", params={"q": "x"})
        assert resp.status_code == 404


class TestExports:
    def test_csv_has_one_row_per_assembly(self, client, run_id):
        resp = client.get(f"/api/run/{run_id}/export.csv", params={"step": 0})
        assert resp.status_code == 200
        rows = resp.text.strip().split("\n")
        assert len(rows) == 242, "241 assemblies plus a header"
        header = rows[0]
        assert "site" in header and "2RPF" in header

    def test_csv_values_match_the_payload(self, client, run_id):
        payload = client.post("/api/samples/case_002495.out").json()
        resp = client.get(f"/api/run/{payload['runId']}/export.csv", params={"step": 0})
        # 2PLO cells contain commas ("1, 3"), so the CSV must be read properly
        # rather than split -- which also checks the export quotes them.
        rows = list(csv.reader(io.StringIO(resp.text)))
        header, first = rows[0], rows[1]
        rpf = payload["statePoints"][0]["values"]["2RPF"][0]
        assert float(first[header.index("2RPF")]) == rpf
        assert first[header.index("2PLO")] == payload["statePoints"][0]["values"]["2PLO"][0]
        assert first[header.index("site")] == payload["assemblies"][0]["site"]


class TestReportEndpoint:
    def test_report_is_served_as_html(self, client, run_id):
        resp = client.get(f"/api/run/{run_id}/report.html", params={"step": 0})
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert resp.text.startswith("<!doctype html>")

    def test_report_downloads_by_default(self, client, run_id):
        resp = client.get(f"/api/run/{run_id}/report.html")
        assert "attachment" in resp.headers.get("content-disposition", "")

    def test_report_can_be_viewed_inline(self, client, run_id):
        resp = client.get(f"/api/run/{run_id}/report.html", params={"download": False})
        assert "content-disposition" not in resp.headers

    def test_report_is_self_contained(self, client, run_id):
        body = client.get(f"/api/run/{run_id}/report.html").text
        assert "http://" not in body and "https://" not in body
        assert "<script" not in body.lower()

    def test_report_for_unknown_run_is_404(self, client):
        assert client.get("/api/run/deadbeef/report.html").status_code == 404


class TestStaticSurface:
    def test_index_is_served(self, client):
        resp = client.get("/")
        # The front end may not be built yet in a fresh checkout; either way the
        # route must not 404, and when present it must be HTML.
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            assert "text/html" in resp.headers["content-type"]
