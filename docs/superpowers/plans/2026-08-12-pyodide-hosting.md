# Pyodide-Hosted Public Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anyone can visit a GitHub Pages URL, upload their own SIMULATE-3 `.out` listing (or try the bundled BEAVRS sample), and get the real, live-parsed dashboard — entirely client-side, no server, no account.

**Architecture:** Package the existing parser + report generators (`s3dash.parser`, `s3dash.web.report`, `s3dash.web.pdfreport` — all pure Python, verified zero non-stdlib imports except `reportlab`, which is a confirmed pure-Python wheel) as an installable wheel. A new adapter module, `s3dash/web/browser.py`, exposes the same operations `s3dash/web/app.py` exposes over HTTP, as plain functions returning JSON strings. A new static site (`webdemo/`) boots Pyodide, installs that wheel via micropip, and calls those functions directly in the visitor's browser instead of over `fetch()`. The existing frontend (`state.js`, `coremap.js`, `panels.js`, `charts.js`, `views.js`, `app.js`) is reused unmodified via a CI copy step — only `api.js` differs between the two builds, because it's the only file that talks to a backend.

**Tech Stack:** Pyodide (CPython-on-WASM, loaded from the jsdelivr CDN), micropip, GitHub Actions (`actions/deploy-pages`), setuptools wheel packaging. No new runtime dependencies added to `requirements.txt` — the demo installs `reportlab` itself via micropip.

## Global Constraints

- Every `s3dash.web.browser` function returns a JSON **string** with the shape `{"ok": true, ...fields}` on success or `{"ok": false, "detail": "<message>"}` on failure — never raises for user-facing errors, never returns a bare value. This is deliberate: Pyodide marshals plain Python `str` returns losslessly and automatically, while raised exceptions surface to JS as a multi-line traceback string that is unpleasant to parse cleanly. One uniform envelope, one place (`webdemo/js/pyodide-bridge.js`'s `call()`) that unwraps it.
- Only BEAVRS (`sample_data/9074.out`) ships with the public demo — matches the example-data policy already decided for this project. No other `sample_data/*.out` file is ever copied into `webdemo/` or the deployed site.
- `s3dash/web/app.py` (FastAPI) and `s3dash/__main__.py` (uvicorn entry point) are never imported by anything the browser build touches. Verified: both `s3dash/__init__.py` and `s3dash/web/__init__.py` are empty, so importing `s3dash.parser`, `s3dash.web.report`, `s3dash.web.pdfreport`, or `s3dash.web.browser` cannot transitively import FastAPI.
- Existing test command stays `python -m pytest -q`, run from the repo root, currently 218 passing. Every task that touches Python must leave this passing.
- The wheel is always installed by direct relative URL (`./s3dash.whl`), never by bare package name — so its exact version string never needs to match anything JS references.

---

## Task 1: Browser adapter module

**Files:**
- Create: `s3dash/web/browser.py`
- Test: `tests/test_browser.py`

**Interfaces:**
- Consumes: `s3dash.parser.parse_text(text: str, source_file: str | None) -> BuildResult` (existing), `s3dash.web.pdfreport.build_pdf(payload: dict, step: int) -> bytes` (existing), `s3dash.web.report.render_report` (existing, not used by this module directly but co-packaged).
- Produces (all return JSON strings per the Global Constraints envelope): `parse(raw, filename: str) -> str`, `section_text(run_id: str, start: int, end: int, context: int = 0) -> str`, `search(run_id: str, q: str, limit: int = 200) -> str`, `export_json(run_id: str) -> str`, `export_csv(run_id: str, step: int = 0) -> str`, `report_pdf(run_id: str, step: int = 0) -> str` (envelope carries `pdfBase64`, a base64-encoded string — Pyodide marshals `str` cleanly, and PDF bytes can't go directly inside a JSON string).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_browser.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_browser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 's3dash.web.browser'`

- [ ] **Step 3: Write the implementation**

```python
# s3dash/web/browser.py
"""Browser adapter: the same operations app.py exposes over HTTP, as plain
Python functions a Pyodide-hosted page can call directly.

Every function returns a JSON string shaped `{"ok": true, ...}` on success
or `{"ok": false, "detail": "..."}` on failure -- see the plan's Global
Constraints for why. State lives in this module's globals (mirroring
app.py's `_RUNS`/`_store`/`_get`) for as long as the browser tab does; there
is no server process here to hold it instead.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import uuid

from ..parser import BuildResult, parse_text
from .pdfreport import build_pdf

_RUNS: dict[str, BuildResult] = {}
_ORDER: list[str] = []
_MAX_RUNS = 8


def _store(result: BuildResult) -> str:
    run_id = uuid.uuid4().hex[:12]
    _RUNS[run_id] = result
    _ORDER.append(run_id)
    while len(_ORDER) > _MAX_RUNS:
        _RUNS.pop(_ORDER.pop(0), None)
    return run_id


def _get(run_id: str) -> BuildResult | None:
    return _RUNS.get(run_id)


def _ok(fields: dict) -> str:
    return json.dumps({"ok": True, **fields})


def _err(detail: str) -> str:
    return json.dumps({"ok": False, "detail": detail})


def parse(raw, filename: str) -> str:
    """Parse an uploaded or sample file.

    `raw` is anything `bytes()`-able -- Pyodide hands a JS Uint8Array
    through as a buffer-like object, not a plain `bytes`.
    """
    data = bytes(raw)
    if not data:
        return _err("Uploaded file is empty.")
    text = data.decode("latin-1", errors="replace")
    try:
        result = parse_text(text, source_file=filename or "upload.out")
    except Exception as exc:  # noqa: BLE001 -- reported to the UI, not a crash
        return _err(f"Could not parse file: {exc}")
    if not result.payload["sections"]:
        return _err(
            "No SIMULATE-3 sections were recognised. Is this a SIMULATE-3 output listing?"
        )
    run_id = _store(result)
    return _ok({"runId": run_id, **result.payload})


def section_text(run_id: str, start: int, end: int, context: int = 0) -> str:
    result = _get(run_id)
    if result is None:
        return _err("Run not found; re-upload the file.")
    lines = result.document.lines
    lo = max(0, start - context)
    hi = min(len(lines), end + context)
    if lo >= hi:
        return _err("Empty line range.")
    return _ok({"text": "\n".join(lines[lo:hi])})


def search(run_id: str, q: str, limit: int = 200) -> str:
    result = _get(run_id)
    if result is None:
        return _err("Run not found; re-upload the file.")
    needle = q.lower()
    hits = []
    for i, line in enumerate(result.document.lines):
        if needle in line.lower():
            page = result.document.page_for_line(i)
            hits.append(
                {
                    "line": i,
                    "text": line.rstrip()[:220],
                    "case": page.case,
                    "step": page.step,
                    "page": page.page_no,
                }
            )
            if len(hits) >= limit:
                break
    return _ok(
        {"query": q, "count": len(hits), "hits": hits, "truncated": len(hits) >= limit}
    )


def export_json(run_id: str) -> str:
    result = _get(run_id)
    if result is None:
        return _err("Run not found; re-upload the file.")
    return _ok({"payload": result.payload})


def export_csv(run_id: str, step: int = 0) -> str:
    result = _get(run_id)
    if result is None:
        return _err("Run not found; re-upload the file.")
    payload = result.payload
    points = payload["statePoints"]
    if not points:
        return _err("No state points in this run.")
    sp = next((p for p in points if p["step"] == step), points[0])

    codes = list(sp["values"].keys())
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        ["row", "col", "site", "label", "serial", "fuelType", "batch", "enrichment", *codes]
    )
    for i, a in enumerate(payload["assemblies"]):
        writer.writerow(
            [
                a["row"], a["col"], a["site"], a["label"], a["serial"],
                a["fuelType"], a["batch"], a["enrichment"],
                *[sp["values"][c][i] for c in codes],
            ]
        )
    return _ok({"csv": buf.getvalue()})


def report_pdf(run_id: str, step: int = 0) -> str:
    result = _get(run_id)
    if result is None:
        return _err("Run not found; re-upload the file.")
    try:
        pdf_bytes = build_pdf(result.payload, step=step)
    except Exception as exc:  # noqa: BLE001 -- a layout failure must not crash the page
        return _err(f"Could not render the PDF report: {exc}")
    return _ok({"pdfBase64": base64.b64encode(pdf_bytes).decode("ascii")})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_browser.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: `227 passed` (218 existing + 9 new)

- [ ] **Step 6: Commit**

```bash
git add s3dash/web/browser.py tests/test_browser.py
git commit -m "feat(hosting): add browser adapter mirroring app.py's routes as plain functions"
```

---

## Task 2: Package `s3dash` as an installable wheel

**Files:**
- Create: `pyproject.toml`

**Interfaces:**
- Consumes: the `s3dash` package as it exists on disk (parser + web, including Task 1's `browser.py`).
- Produces: a wheel file `dist/s3dash-1.0.0-py3-none-any.whl`, importable as `s3dash.parser`, `s3dash.web.report`, `s3dash.web.pdfreport`, `s3dash.web.browser`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "s3dash"
version = "1.0.0"
description = "SIMULATE-3 listing parser and report generators"
requires-python = ">=3.10"
# Deliberately empty: app.py/__main__.py (the only modules needing fastapi,
# uvicorn) are never imported by the browser build, and reportlab is
# installed as a separate, explicit micropip step -- declaring it here too
# would have micropip re-resolve it a second time for no benefit.
dependencies = []

[tool.setuptools.packages.find]
include = ["s3dash*"]
```

- [ ] **Step 2: Build the wheel**

Run:
```bash
python -m pip install --upgrade build
python -m build --wheel
```
Expected: `Successfully built s3dash-1.0.0-py3-none-any.whl` and the file exists at `dist/s3dash-1.0.0-py3-none-any.whl`.

- [ ] **Step 3: Verify it installs cleanly and imports the right things in isolation**

Run (adjust `python -m venv` invocation for your shell; this is the POSIX form):
```bash
python -m venv /tmp/s3dash-wheel-check
/tmp/s3dash-wheel-check/bin/pip install dist/s3dash-1.0.0-py3-none-any.whl
/tmp/s3dash-wheel-check/bin/python -c "import s3dash.parser, s3dash.web.report, s3dash.web.pdfreport" 2>&1
```
Expected: the third command fails with `ModuleNotFoundError: No module named 'reportlab'` (expected -- that venv never installed reportlab; this only proves the wheel's own modules import without pulling in fastapi/uvicorn). Then:
```bash
/tmp/s3dash-wheel-check/bin/pip install reportlab
/tmp/s3dash-wheel-check/bin/python -c "import s3dash.parser, s3dash.web.report, s3dash.web.pdfreport, s3dash.web.browser; print('ok')"
```
Expected: `ok`, no `fastapi`/`uvicorn` installed in this venv at any point.

- [ ] **Step 4: Confirm the existing suite still passes from the repo root (unaffected by the new packaging file)**

Run: `python -m pytest -q`
Expected: `227 passed`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore(hosting): package s3dash as an installable wheel"
```

---

## Task 3: Unify JSON/CSV export to the blob pattern PDF export already uses

**Why this is in scope:** the Pyodide build has no server, so `exportJsonUrl`/`exportCsvUrl` — which today return a URL for the browser to navigate to — have nothing to point at. Rather than special-case Pyodide, this task changes both exports to the `{blob, filename}` pattern `fetchReportPdf` already uses, in the one shared `api.js`/`app.js` the local-server build keeps using unmodified. Same fix, one place, benefits both builds (failed exports now toast an error instead of silently opening a 404 page).

**Files:**
- Modify: `s3dash/web/static/js/api.js`
- Modify: `s3dash/web/static/js/app.js:34,479-489`
- Test: `tests/test_api.py` (existing backend tests are unaffected — this is a frontend-only change; verify manually per Step 4)

**Interfaces:**
- Produces: `api.js` now exports `exportJson(runId): Promise<{blob: Blob, filename: string|null}>` and `exportCsv(runId, step): Promise<{blob: Blob, filename: string|null}>`, replacing the old `exportJsonUrl(runId): string` / `exportCsvUrl(runId, step): string`. `webdemo/js/api.js` (Task 6) must export the identical two names with the identical shape.

- [ ] **Step 1: Replace the URL-builders with blob-fetchers in `api.js`**

In `s3dash/web/static/js/api.js`, replace:

```javascript
export function exportJsonUrl(runId) {
  return `/api/run/${encodeURIComponent(runId)}/export.json`;
}

export function exportCsvUrl(runId, step) {
  return `/api/run/${encodeURIComponent(runId)}/export.csv?step=${encodeURIComponent(step)}`;
}
```

with:

```javascript
function filenameFromDisposition(res) {
  const disposition = res.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  return match ? decodeURIComponent(match[1]) : null;
}

/** GET /api/run/{id}/export.json -> {blob, filename} */
export async function exportJson(runId) {
  const res = await check(await fetch(`/api/run/${encodeURIComponent(runId)}/export.json`));
  return { blob: await res.blob(), filename: filenameFromDisposition(res) };
}

/** GET /api/run/{id}/export.csv -> {blob, filename} */
export async function exportCsv(runId, step) {
  const url = `/api/run/${encodeURIComponent(runId)}/export.csv?step=${encodeURIComponent(step)}`;
  const res = await check(await fetch(url));
  return { blob: await res.blob(), filename: filenameFromDisposition(res) };
}
```

Also replace `fetchReportPdf`'s own inline Content-Disposition parsing with a call to the new shared helper, so there is exactly one regex for it:

```javascript
export async function fetchReportPdf(runId, step) {
  const q = new URLSearchParams({ step: String(Number.isFinite(step) ? step | 0 : 0) });
  const res = await check(
    await fetch(`/api/run/${encodeURIComponent(runId)}/report.pdf?${q}`)
  );
  return { blob: await res.blob(), filename: filenameFromDisposition(res) || 'report.pdf' };
}
```

- [ ] **Step 2: Update `app.js`'s import and the two export handlers**

In `s3dash/web/static/js/app.js:29-37`, change the import:

```javascript
import {
  listSamples,
  parseSample,
  parseUpload,
  searchText,
  exportJson,
  exportCsv,
  fetchReportPdf,
} from './api.js';
```

In `s3dash/web/static/js/app.js:479-489`, replace:

```javascript
  $('#exp-json').addEventListener('click', () => {
    if (!state.runId) return;
    download(exportJsonUrl(state.runId));
    closeMenu($('#export-menu'));
  });
  $('#exp-csv').addEventListener('click', () => {
    const sp = statePoint();
    if (!state.runId || !sp) return;
    download(exportCsvUrl(state.runId, sp.step));
    closeMenu($('#export-menu'));
  });
```

with:

```javascript
  $('#exp-json').addEventListener('click', async () => {
    if (!state.runId) return;
    try {
      const { blob, filename } = await exportJson(state.runId);
      saveBlob(blob, filename || `${fileStem()}.parsed.json`);
    } catch (err) {
      toast(err.message || 'The JSON export failed.', 'error');
    }
    closeMenu($('#export-menu'));
  });
  $('#exp-csv').addEventListener('click', async () => {
    const sp = statePoint();
    if (!state.runId || !sp) return;
    try {
      const { blob, filename } = await exportCsv(state.runId, sp.step);
      saveBlob(blob, filename || `${fileStem()}.step${sp.step}.csv`);
    } catch (err) {
      toast(err.message || 'The CSV export failed.', 'error');
    }
    closeMenu($('#export-menu'));
  });
```

`saveBlob` and `fileStem` are already defined earlier in `app.js` (used by `exportPdf`) — no new helpers needed. The now-unused `download()` helper (`app.js:604-611`) stays: nothing else calls it after this change, but it is harmless, and removing it is out of scope for this task (a separate cleanup, not required by this feature).

- [ ] **Step 3: Run the backend test suite (this change is frontend-only, but confirms nothing else broke)**

Run: `python -m pytest -q`
Expected: `227 passed`

- [ ] **Step 4: Manually verify in a real browser**

```bash
python -m s3dash
```
In the Browser pane: load the BEAVRS sample, open the Export menu, click **JSON** — confirm a `.parsed.json` file downloads and a success toast is not required (no toast on success today, matching existing PDF behavior) but no error toast appears. Click **CSV** — confirm a `.step0.csv` file downloads. Both should behave exactly as before this change from the user's perspective.

- [ ] **Step 5: Commit**

```bash
git add s3dash/web/static/js/api.js s3dash/web/static/js/app.js
git commit -m "refactor(ui): unify JSON/CSV export to the blob pattern PDF export already uses"
```

---

## Task 4: `webdemo/` static site skeleton

**Files:**
- Create: `webdemo/index.html`

**Interfaces:**
- Consumes: `./js/pyodide-bridge.js`'s `boot()` export (Task 5 — this task can be written and committed first; it just won't do anything until Task 5 exists, which is fine, these are sequential commits in one feature).
- Produces: the page shell every later task's script gets loaded into.

- [ ] **Step 1: Write `webdemo/index.html`**

Start from `s3dash/web/static/index.html` verbatim, with exactly two kinds of change: (a) absolute `/static/...` paths become relative `./...` paths, because a GitHub Pages project site is served from a subpath (`https://<user>.github.io/<repo>/`), not the domain root; (b) the closing `<script type="module" src="/static/js/app.js"></script>` is replaced with an inline boot sequence that starts Pyodide first and only then loads `app.js`.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Vision: Nuclear Core Analysis</title>
<link rel="icon" href="data:," />
<link rel="stylesheet" href="./css/app.css" />
<style>
  /* Only used before Pyodide has finished booting -- app.css's own tokens
     aren't guaranteed loaded-and-parsed at the same instant this runs, so
     this stays deliberately self-contained rather than assuming its vars. */
  .boot-status {
    display: flex; align-items: center; gap: 0.6em;
    max-width: 40em; margin: 4em auto; padding: 1em 1.25em;
    font: 15px/1.5 ui-sans-serif, Segoe UI, system-ui, sans-serif;
    border: 1px solid #dcdfe4; border-radius: 8px; color: #33363b;
  }
  .boot-status.is-error { border-color: #c0392b; color: #c0392b; }
  .boot-status a { color: inherit; }
</style>
</head>
<body>

<a class="skip-link" href="#view-map">Skip to core map</a>

<header class="app-header">
  <div class="brand">
    <span class="brand-mark" aria-hidden="true">S3</span>
    <span class="brand-text">
      <span class="brand-title">Vision: Nuclear Core Analysis</span>
      <span class="brand-sub" id="hdr-file">No listing loaded</span>
    </span>
  </div>

  <nav class="view-nav" id="view-nav" aria-label="Views" hidden>
    <a class="viewtab" href="#/map"      data-view="map">Core map</a>
    <a class="viewtab" href="#/plots"    data-view="plots">Plots</a>
    <a class="viewtab" href="#/sections" data-view="sections">Sections &amp; Search</a>
  </nav>

  <div class="header-actions">
    <span id="completion-chip" class="completion-chip" hidden></span>
    <div id="status-badge" class="status-badge" role="group" aria-label="Run diagnostics summary" hidden></div>

    <details class="menu menu-export" id="export-menu" hidden>
      <summary class="btn" role="button" aria-haspopup="menu" aria-label="Export this run">Export <span class="menu-caret" aria-hidden="true">▾</span></summary>
      <div class="menu-body menu-list" role="menu" aria-label="Export">
        <button type="button" class="menu-item" role="menuitem" id="exp-json"
                aria-label="Export JSON — the full parsed payload">
          <span class="menu-item-name">JSON</span>
          <span class="menu-item-note">full parsed payload</span>
        </button>
        <button type="button" class="menu-item" role="menuitem" id="exp-csv"
                aria-label="Export CSV — the assembly table for the current step">
          <span class="menu-item-name">CSV</span>
          <span class="menu-item-note">assembly table, current step</span>
        </button>
        <button type="button" class="menu-item" role="menuitem" id="exp-pdf"
                aria-label="Export a PDF report for the current step">
          <span class="menu-item-name">PDF Report</span>
          <span class="menu-item-note">formatted report, current step</span>
        </button>
        <button type="button" class="menu-item" role="menuitem" id="exp-print"
                aria-label="Print every view as one document">
          <span class="menu-item-name">Print</span>
          <span class="menu-item-note">every view, one document</span>
        </button>
      </div>
    </details>

    <button type="button" id="btn-load" class="btn">Load listing</button>
    <button type="button" id="btn-theme" class="btn btn-icon" aria-label="Toggle colour theme" title="Toggle colour theme (light / dark / auto)">
      <span id="theme-glyph" aria-hidden="true">◐</span>
    </button>
  </div>
</header>

<div class="notice-strip" id="parse-notes" hidden></div>

<div class="toolbar" id="toolbar" hidden>
  <div class="tool-group tool-step" data-views="map plots">
    <span class="tool-label">Step</span>
    <button type="button" class="btn btn-step" id="step-prev" title="Previous step (←)" aria-label="Previous step">◀</button>
    <input type="range" id="step-slider" min="0" max="0" value="0" step="1" aria-label="Depletion step" />
    <button type="button" class="btn btn-step" id="step-next" title="Next step (→)" aria-label="Next step">▶</button>
    <output id="step-readout" class="step-readout" for="step-slider">—</output>
  </div>

  <div class="tool-group" data-views="map plots">
    <label for="axial-select">Axial</label>
    <select id="axial-select" disabled></select>
  </div>

  <div class="tool-group tool-search" data-views="map sections">
    <label for="search-input">Search</label>
    <input type="search" id="search-input" placeholder="serial, site, or raw text…" />
    <button type="button" class="btn" id="search-go">Find</button>
  </div>

  <div class="tool-group" data-views="map">
    <details class="menu" id="filter-menu">
      <summary class="btn" role="button" aria-haspopup="true">Filter <span id="filter-count" class="pill pill-mini" hidden></span></summary>
      <div class="menu-body" id="filter-body"></div>
    </details>
  </div>
</div>

<section class="hero" id="hero" aria-label="Load a listing"></section>

<main class="layout" id="layout" hidden>

  <aside class="rail rail-left" aria-label="Run metadata and text hits">
    <section class="card" id="meta-card" data-resizable>
      <header class="card-head">
        <h2>Run</h2>
      </header>
      <div id="meta-strip" class="meta-strip"></div>
    </section>

    <section class="card card-flush" id="search-card" data-resizable hidden>
      <header class="card-head">
        <h2>Text hits</h2>
        <span class="pill" id="search-count"></span>
      </header>
      <div class="hits-scroll"><div id="search-results"></div></div>
    </section>
  </aside>

  <div class="col-center">

    <!-- ------------------------------------------------------------ map -->
    <section class="card view" id="view-map" data-resizable aria-label="Core map">
      <header class="card-head card-head-stack">
        <div class="card-head-row">
          <h2 id="coremap-title">Core map</h2>
          <span class="card-head-note" id="coremap-note"></span>
        </div>
        <div class="card-head-row card-head-tools">
          <label class="tool-label" for="layer-select">Layer</label>
          <select id="layer-select" aria-label="Core map layer"></select>
          <label class="switch"><input type="checkbox" id="flagged-only" /><span>Flagged only</span></label>
          <button type="button" class="btn btn-mini btn-png" data-png="coremap" data-png-name="core-map">Export PNG</button>
        </div>
      </header>
      <div class="coremap-wrap">
        <div id="coremap" class="coremap"></div>
        <div id="coremap-legend" class="legend"></div>
      </div>
    </section>

    <!-- ---------------------------------------------------------- plots -->
    <div class="view" id="view-plots" hidden>
      <div class="chart-grid">
        <section class="card" id="chart-hist-card" data-resizable>
          <header class="card-head">
            <h2>Layer distribution</h2>
            <label class="sr-only" for="layer-select-hist">Layer</label>
            <select id="layer-select-hist" aria-label="Layer distribution variable"></select>
            <button type="button" class="btn btn-mini btn-png" data-png="chart-hist" data-png-name="layer-distribution">Export PNG</button>
          </header>
          <span class="card-head-note card-sub-note" id="hist-note"></span>
          <div id="chart-hist" class="chart-host"></div>
        </section>

        <section class="card" id="chart-axial-card" data-resizable>
          <header class="card-head">
            <h2>Axial profile</h2>
            <select id="axial-column" aria-label="Axial chart variable"></select>
            <button type="button" class="btn btn-mini btn-png" data-png="chart-axial" data-png-name="axial-profile">Export PNG</button>
          </header>
          <div id="chart-axial" class="chart-host"></div>
        </section>

        <section class="card" id="chart-depletion-card" data-resizable>
          <header class="card-head">
            <h2>Depletion progression</h2>
            <select id="depl-metric" aria-label="Depletion chart Y axis"></select>
            <button type="button" class="btn btn-mini btn-png" data-png="chart-depletion" data-png-name="depletion-progression">Export PNG</button>
          </header>
          <div id="chart-depletion" class="chart-host"></div>
        </section>

        <section class="card" id="chart-inventory-card" data-resizable>
          <header class="card-head">
            <h2>Assembly count by fuel type</h2>
            <button type="button" class="btn btn-mini btn-png" data-png="chart-inventory" data-png-name="fuel-type-count">Export PNG</button>
          </header>
          <div id="chart-inventory" class="chart-host"></div>
        </section>

        <section class="card" id="chart-cpu-card" data-resizable>
          <header class="card-head">
            <h2>CPU by subroutine</h2>
            <button type="button" class="btn btn-mini btn-png" data-png="chart-cpu" data-png-name="cpu-by-subroutine">Export PNG</button>
          </header>
          <div id="chart-cpu" class="chart-host"></div>
        </section>
      </div>
    </div>

    <!-- -------------------------------------------------------- sections -->
    <div class="view" id="view-sections" hidden>
      <section class="card card-flush" id="nav-card" data-resizable>
        <header class="card-head">
          <h2>Listing navigator</h2>
          <span class="pill" id="nav-count"></span>
        </header>
        <div class="card-tools">
          <input type="search" id="tree-filter" placeholder="Filter sections…" aria-label="Filter sections" />
        </div>
        <div class="tree-scroll"><div id="nav-tree" class="tree"></div></div>
      </section>

      <section class="card" id="section-card" data-resizable aria-label="Section viewer">
        <header class="card-head">
          <h2>Section viewer</h2>
          <span class="card-head-note" id="section-note">Pick a section in the navigator</span>
          <button type="button" class="btn btn-mini" id="section-copy" hidden>Copy</button>
        </header>
        <div id="section-view" class="section-view"></div>
      </section>
    </div>

  </div>

  <aside class="rail rail-right" id="rail-right" aria-label="Detail panels">
    <div class="tabs" role="tablist" aria-label="Detail panels">
      <button type="button" class="tab" role="tab" id="tab-inspector"   aria-controls="panel-inspector"   aria-selected="true">Inspector</button>
      <button type="button" class="tab" role="tab" id="tab-diagnostics" aria-controls="panel-diagnostics" aria-selected="false">Diagnostics <span class="pill pill-mini" id="tab-diag-count"></span></button>
      <button type="button" class="tab" role="tab" id="tab-inventory"   aria-controls="panel-inventory"   aria-selected="false">Inventory</button>
    </div>
    <div class="panel" role="tabpanel" id="panel-inspector"   aria-labelledby="tab-inspector" data-resizable></div>
    <div class="panel" role="tabpanel" id="panel-diagnostics" aria-labelledby="tab-diagnostics" data-resizable hidden></div>
    <div class="panel" role="tabpanel" id="panel-inventory"   aria-labelledby="tab-inventory" data-resizable hidden></div>
  </aside>

</main>

<dialog id="load-dialog" aria-label="Load a SIMULATE-3 listing">
  <div class="dialog-head">
    <h2>Load a listing</h2>
    <button type="button" class="btn btn-icon" id="load-close" aria-label="Close">✕</button>
  </div>
  <div id="load-dialog-host"></div>
</dialog>

<div id="tooltip" class="tooltip" role="tooltip" aria-hidden="true" hidden></div>
<div id="toast" class="toast" role="status" aria-live="polite" hidden></div>

<div id="boot-status" class="boot-status" role="status">
  <span class="spinner" aria-hidden="true"></span>
  <span>Starting up — loading the Python runtime in your browser (a few seconds, once).</span>
</div>
<script type="module">
  import { boot } from './js/pyodide-bridge.js';
  const el = document.getElementById('boot-status');
  boot()
    .then(() => {
      el.remove();
      import('./js/app.js');
    })
    .catch((err) => {
      el.className = 'boot-status is-error';
      el.innerHTML =
        '<strong>Could not start the in-browser runtime.</strong> ' +
        (err && err.message ? err.message : String(err)) +
        ' You can still run this locally — see the ' +
        '<a href="https://github.com/AyachiMishra/NuclearCore-GUI#quick-start">quick-start</a>.';
    });
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add webdemo/index.html
git commit -m "feat(hosting): add the webdemo static site shell"
```

---

## Task 5: `pyodide-bridge.js`

**Files:**
- Create: `webdemo/js/pyodide-bridge.js`

**Interfaces:**
- Consumes: nothing from this repo (loads Pyodide itself from the jsdelivr CDN at `PYODIDE_CDN`, and `./s3dash.whl` relative to the page, produced by Task 7's assembly step).
- Produces: `boot(): Promise<void>` (idempotent — safe to call more than once, only boots once), `call(fn: string, ...args): Promise<object>` (awaits `boot()`, invokes `s3dash.web.browser[fn](...args)`, parses its JSON-string return, throws `Error(detail)` if `ok` is false, otherwise returns the parsed object). Task 6's `webdemo/js/api.js` is the only consumer of `call`.

- [ ] **Step 1: Write `pyodide-bridge.js`**

```javascript
/* pyodide-bridge.js — boots Pyodide and exposes the same call surface
 * api.js normally gets from the FastAPI backend, backed by s3dash.web.browser
 * running in-process instead of over the network. Nothing downstream of
 * api.js knows the difference.
 */

// Check https://pyodide.org for the current stable release before deploying
// -- this is pinned deliberately (an unpinned CDN path would mean a Pyodide
// upstream release could silently change the demo's behaviour underneath
// this repo with no corresponding commit here).
const PYODIDE_VERSION = 'v0.26.4';
const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/${PYODIDE_VERSION}/full/`;

let pyodideReady = null;
let browserModule = null;

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error(`Could not load ${src}`));
    document.head.appendChild(s);
  });
}

/** Boots Pyodide, installs reportlab + our wheel, imports the adapter
 *  module. Safe to call more than once -- later calls await the same
 *  in-flight (or already-settled) boot rather than booting twice. */
export function boot() {
  if (pyodideReady) return pyodideReady;
  pyodideReady = (async () => {
    await loadScript(`${PYODIDE_CDN}pyodide.js`);
    const pyodide = await self.loadPyodide({ indexURL: PYODIDE_CDN });
    await pyodide.loadPackage('micropip');
    const micropip = pyodide.pyimport('micropip');
    await micropip.install('reportlab');
    await micropip.install('./s3dash.whl');
    browserModule = pyodide.pyimport('s3dash.web.browser');
  })();
  return pyodideReady;
}

/** Calls a `s3dash.web.browser` function and unwraps its
 *  {ok, detail?, ...fields} envelope into a plain object, or throws
 *  Error(detail) -- the same contract api.js's check() already gives the
 *  rest of the app for HTTP responses. */
export async function call(fn, ...args) {
  await boot();
  const raw = browserModule[fn](...args);
  const result = JSON.parse(raw);
  if (!result.ok) throw new Error(result.detail || `${fn} failed`);
  return result;
}
```

- [ ] **Step 2: Commit**

```bash
git add webdemo/js/pyodide-bridge.js
git commit -m "feat(hosting): add the Pyodide boot sequence and Python call bridge"
```

---

## Task 6: `webdemo/js/api.js` (Pyodide-backed)

**Files:**
- Create: `webdemo/js/api.js`

**Interfaces:**
- Consumes: `./pyodide-bridge.js`'s `call(fn, ...args)` (Task 5).
- Produces: the exact same eight names Task 3 left `s3dash/web/static/js/api.js` exporting — `listSamples()`, `parseSample(name)`, `parseUpload(file)`, `fetchSection(runId, start, end, context)`, `searchText(runId, query)`, `exportJson(runId)`, `exportCsv(runId, step)`, `fetchReportPdf(runId, step)` — with identical shapes, so `app.js` (copied in unmodified by Task 7) imports this file exactly as it imports the server-backed one.

- [ ] **Step 1: Write `webdemo/js/api.js`**

```javascript
/* api.js (Pyodide build) — same export surface as the server-backed api.js
 * in s3dash/web/static/js/, backed by s3dash.web.browser running inside
 * Pyodide instead of fetch(). app.js imports this file by the same relative
 * path ('./api.js') either way and cannot tell the two apart.
 */

import { call } from './pyodide-bridge.js';

let sampleBytes = null; // Uint8Array, fetched once and cached

const BEAVRS_SAMPLE = { name: '9074.out', sizeKb: null };

/** Static stand-in for GET /api/samples -- this demo ships exactly one
 *  bundled sample (BEAVRS), matching the project's example-data policy. */
export async function listSamples() {
  if (sampleBytes === null) {
    const res = await fetch('./sample_data/9074.out');
    if (!res.ok) return [];
    sampleBytes = new Uint8Array(await res.arrayBuffer());
    BEAVRS_SAMPLE.sizeKb = Math.round(sampleBytes.length / 1024);
  }
  return [{ name: BEAVRS_SAMPLE.name, sizeKb: BEAVRS_SAMPLE.sizeKb }];
}

export async function parseSample(name) {
  await listSamples(); // ensures sampleBytes is populated
  if (name !== BEAVRS_SAMPLE.name || sampleBytes === null) {
    throw new Error(`Unknown sample: ${name}`);
  }
  const r = await call('parse', sampleBytes, name);
  const { ok, ...payload } = r;
  return payload;
}

export async function parseUpload(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const r = await call('parse', bytes, file.name);
  const { ok, ...payload } = r;
  return payload;
}

export async function fetchSection(runId, start, end, context = 2) {
  const r = await call(
    'section_text', runId,
    Math.max(0, start | 0), Math.max(0, end | 0), Math.min(200, Math.max(0, context | 0))
  );
  return r.text;
}

export async function searchText(runId, query) {
  const r = await call('search', runId, query, 200);
  const { ok, ...body } = r;
  return body;
}

export async function exportJson(runId) {
  const r = await call('export_json', runId);
  const text = JSON.stringify(r.payload, null, 2);
  return { blob: new Blob([text], { type: 'application/json' }), filename: null };
}

export async function exportCsv(runId, step) {
  const r = await call('export_csv', runId, step);
  return { blob: new Blob([r.csv], { type: 'text/csv' }), filename: null };
}

export async function fetchReportPdf(runId, step) {
  const r = await call('report_pdf', runId, step);
  const binary = atob(r.pdfBase64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return { blob: new Blob([bytes], { type: 'application/pdf' }), filename: null };
}
```

`filename: null` in the last three functions is intentional, not a placeholder: `app.js`'s three export handlers (after Task 3) already fall back to `` `${fileStem()}...` `` whenever `filename` is falsy — exactly the existing behavior for `fetchReportPdf` today. Returning `null` here reuses that fallback instead of duplicating filename construction in Python.

- [ ] **Step 2: Commit**

```bash
git add webdemo/js/api.js
git commit -m "feat(hosting): add the Pyodide-backed api.js implementation"
```

---

## Task 7: Site assembly script

**Files:**
- Create: `tools/build_webdemo.py`

**Interfaces:**
- Consumes: `webdemo/` (Tasks 4-6), `s3dash/web/static/js/{state,coremap,panels,charts,views,app}.js`, `s3dash/web/static/css/app.css`, `sample_data/9074.out`, `dist/*.whl` (Task 2's build output).
- Produces: an assembled, servable site directory (default `site/`). Used identically by CI (Task 8) and by a developer testing locally (Task 9), so the two never drift apart.

- [ ] **Step 1: Write `tools/build_webdemo.py`**

```python
"""Assemble the Pyodide-hosted demo site.

Copies webdemo/ (the Pyodide-specific files) together with the shared
frontend JS/CSS, the BEAVRS sample, and the built s3dash wheel into one
servable directory. Run this the same way locally (to test before pushing)
and in CI (to build what actually gets deployed) -- there is exactly one
place that decides what ships.

    python tools/build_webdemo.py
    python -m http.server --directory site 8080
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SHARED_JS = ["state.js", "coremap.js", "panels.js", "charts.js", "views.js", "app.js"]


def build(outdir: Path) -> None:
    if outdir.exists():
        shutil.rmtree(outdir)
    shutil.copytree(ROOT / "webdemo", outdir)

    static_js = ROOT / "s3dash" / "web" / "static" / "js"
    for name in SHARED_JS:
        shutil.copy2(static_js / name, outdir / "js" / name)

    (outdir / "css").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "s3dash" / "web" / "static" / "css" / "app.css", outdir / "css" / "app.css")

    (outdir / "sample_data").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "sample_data" / "9074.out", outdir / "sample_data" / "9074.out")

    wheels = sorted((ROOT / "dist").glob("s3dash-*-py3-none-any.whl"))
    if not wheels:
        raise SystemExit(
            "No wheel found in dist/ -- run `python -m build --wheel` first (see Task 2)."
        )
    shutil.copy2(wheels[-1], outdir / "s3dash.whl")

    print(f"Assembled {outdir.relative_to(ROOT)}/ from webdemo/ + shared static files")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--outdir", type=Path, default=ROOT / "site")
    args = ap.parse_args(argv)
    build(args.outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it and confirm the assembled site looks right**

Run:
```bash
python -m build --wheel
python tools/build_webdemo.py
```
Expected output ends with `Assembled site/ from webdemo/ + shared static files`, and `site/` now contains: `index.html`, `js/pyodide-bridge.js`, `js/api.js`, `js/{state,coremap,panels,charts,views,app}.js`, `css/app.css`, `sample_data/9074.out`, `s3dash.whl`.

- [ ] **Step 3: Commit**

```bash
git add tools/build_webdemo.py
git commit -m "feat(hosting): add the site assembly script shared by CI and local testing"
```

(`site/` itself is a build product — add `site/` to `.gitignore` in this same commit if a repo-root `.gitignore` exists and doesn't already ignore it; check with `git status` after Step 2 to confirm it isn't showing up as untracked noise.)

---

## Task 8: GitHub Actions deploy workflow

**Files:**
- Create: `.github/workflows/deploy-pages.yml`

**Interfaces:**
- Consumes: Task 7's `tools/build_webdemo.py`.
- Produces: a deployed GitHub Pages site on every push to `main` that touches relevant paths.

- [ ] **Step 1: Write the workflow**

```yaml
name: Deploy Pages demo

on:
  push:
    branches: [main]
    paths:
      - 's3dash/parser/**'
      - 's3dash/web/report.py'
      - 's3dash/web/pdfreport.py'
      - 's3dash/web/browser.py'
      - 'webdemo/**'
      - 's3dash/web/static/**'
      - 'pyproject.toml'
      - 'sample_data/9074.out'
      - 'tools/build_webdemo.py'
      - '.github/workflows/deploy-pages.yml'
  workflow_dispatch: {}

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Build the s3dash wheel
        run: |
          python -m pip install --upgrade pip build
          python -m build --wheel
      - name: Assemble the site
        run: python tools/build_webdemo.py
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Enable Pages-from-Actions in the repository (manual, one-time — cannot be done from a commit)**

In the GitHub web UI: **Settings → Pages → Build and deployment → Source → GitHub Actions**. Nothing to configure beyond selecting that source; the workflow above handles the rest.

- [ ] **Step 3: Commit and push**

```bash
git add .github/workflows/deploy-pages.yml
git commit -m "feat(hosting): add the GitHub Pages deploy workflow"
git push origin main
```

- [ ] **Step 4: Watch the run and confirm it deploys**

In the GitHub web UI: **Actions** tab → the "Deploy Pages demo" run → confirm both jobs (`build`, `deploy`) finish green, then open the URL the `deploy` job reports (`https://<user>.github.io/<repo>/`).

---

## Task 9: End-to-end verification

**Files:** none (verification only).

**Interfaces:** none — this task exercises everything built in Tasks 1-8 together.

- [ ] **Step 1: Assemble and serve the site locally**

```bash
python -m build --wheel
python tools/build_webdemo.py
python -m http.server --directory site 8080
```

- [ ] **Step 2: Open it in the Browser pane and confirm the boot sequence**

Navigate to `http://localhost:8080/`. Confirm the "Starting up — loading the Python runtime…" message appears immediately, then disappears once Pyodide finishes (a few seconds). Check `read_console_messages` for errors during boot — a failed `micropip.install('./s3dash.whl')` is the most likely failure mode (wrong relative path, or the wheel wasn't copied) and will show up here first.

- [ ] **Step 3: Confirm the BEAVRS sample loads and renders real data**

Click **Load listing** → the BEAVRS sample button. Confirm the core map renders with real Relative Power Fraction values (not blank cells), matching what `docs/img/core-map.svg` already shows for this same file.

- [ ] **Step 4: Confirm upload works with a second listing**

Upload `sample_data/case_002495.out` through the same dialog. Confirm it parses and the core map updates to a different (17×17 vs BEAVRS's 15×15) layout.

- [ ] **Step 5: Confirm every export works**

Open the Export menu on the BEAVRS run: click **JSON** (confirm a `.parsed.json` downloads with real payload content, not an error), **CSV** (confirm a `.step0.csv` downloads with 242 rows), **PDF Report** (confirm a `.report.pdf` downloads and its first bytes are `%PDF-` — open it and confirm it renders a real report, not a blank or corrupt file).

- [ ] **Step 6: Confirm search and the section viewer work**

Search for `SYMGRP` in the search box; confirm hits appear. Click one; confirm it navigates to the Sections view and shows the surrounding raw listing text.

- [ ] **Step 7: Confirm the failure path is honest, not silent**

Temporarily rename `site/s3dash.whl` to force a boot failure, reload the page, and confirm the boot-status element shows the error message and the local-quick-start link — not a blank page or a stuck spinner. Rename it back afterward.

- [ ] **Step 8: Update the README with the live link**

Once Task 8's deploy is confirmed live, add one line near the top of `README.md` (immediately under the title, before "A web dashboard that turns..."): `**[Try it now →](https://<user>.github.io/<repo>/)** — runs entirely in your browser; nothing you upload leaves your machine.` Commit this on its own:

```bash
git add README.md
git commit -m "docs: link the live hosted demo from the README"
git push origin main
```
