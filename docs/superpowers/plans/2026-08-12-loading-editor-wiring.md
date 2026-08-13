# Core Loading Editor — Backend Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the already-built, already-tested loading-pattern logic (`s3dash/parser/loadingpattern.py`, `s3dash/parser/nextcycle.py`) to HTTP (`app.py`) and Pyodide (`browser.py`) callers, so a frontend can get a run's loading pattern, apply a list of moves/swaps, and generate the next-cycle `.inp` — with zero new frontend code.

**Architecture:** Two small additions to the parser layer first (`nextcycle.replay_changes`, `loadingpattern.find_input_cards_section`), then one route/function set per existing web surface, each a thin wrapper reusing that shared logic — the same split `pdfreport.build_pdf` already has across both surfaces. **Stateless replay**: no new server-side mutable per-run state. Every request carries the *full* current list of changes; the server always starts from the run's own immutable original parse and replays. This makes undo/redo/reset a pure frontend concern (truncate/resend a local array) and makes server/client state desync structurally impossible — the cost is redoing a cheap, linear decode+fold on every request, an explicit tradeoff, not an oversight.

**Tech Stack:** FastAPI + Pydantic (already a transitive dependency of FastAPI, not a new one) for `app.py`; plain Python + the existing `_ok`/`_err` JSON-envelope convention for `browser.py`.

## Global Constraints

- No new server-side mutable state. `app.py`'s `_RUNS` and `browser.py`'s `_RUNS` are not touched.
- Every JSON key at a request/response boundary is camelCase, matching every existing payload field in this codebase (`runId`, `fuelType`, `AppliedOperation.to_json()`'s own `from`/`to`/`fromToken`/`toToken`, etc.).
- `s3dash.parser.nextcycle.ValidationError` is imported under an alias (`as LoadingValidationError`) everywhere it's used alongside Pydantic/FastAPI code, since `pydantic.ValidationError` is a real, commonly-recognized name in the same ecosystem — avoids ambiguity for a future reader even though there is no actual import collision today.
- Test command: `python -m pytest -q`, run from the repo root. 262 passing before this plan.
- `tests/test_api.py`'s existing `run_id` fixture and `tests/test_browser.py`'s existing `run_id` fixture both already parse `sample_data/case_002495.out` — the exact file with a real, verified `FUE.LAB` card. Reuse them; do not add a new fixture.

---

## Task 1: `nextcycle.replay_changes`

**Files:**
- Modify: `s3dash/parser/nextcycle.py`
- Test: `tests/test_nextcycle.py`

**Interfaces:**
- Consumes: `apply_change`, `PositionChange`, `LoadingEntry`, `Geometry` (all already in `nextcycle.py`/`loadingpattern.py`).
- Produces: `replay_changes(original_entries, changes: list[PositionChange], geom) -> tuple[dict[tuple[int,int], LoadingEntry], list[AppliedOperation]]`. Tasks 3 and 4 both call this directly instead of each reimplementing the fold loop.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_nextcycle.py`:

```python
from s3dash.parser.nextcycle import replay_changes


class TestReplayChanges:
    def test_folds_changes_in_order_from_the_original(self):
        geom, entries = TestValidate()._base()
        from s3dash.parser.geometry import symmetry_orbit

        a_orbit = symmetry_orbit(2, 5, geom)
        b_orbit = symmetry_orbit(3, 3, geom)
        # swap out, then swap back -- net result equals the original,
        # but only if replay_changes actually applies both in order
        # rather than e.g. only the last one.
        changes = [
            PositionChange(2, 5, 3, 3),
            PositionChange(2, 5, 3, 3),
        ]
        result, operations = replay_changes(entries, changes, geom)
        assert result == entries
        assert len(operations) == 2
        assert all(op.operation == "swap" for op in operations)

    def test_empty_change_list_returns_the_original_unchanged(self):
        geom, entries = TestValidate()._base()
        result, operations = replay_changes(entries, [], geom)
        assert result == entries
        assert operations == []

    def test_propagates_validation_error_from_a_bad_change(self):
        geom, entries = TestValidate()._base()
        with pytest.raises(ValidationError, match="No assembly"):
            replay_changes(entries, [PositionChange(50, 50, 2, 5)], geom)

    def test_original_never_mutated(self):
        geom, entries = TestValidate()._base()
        snapshot = dict(entries)
        replay_changes(entries, [PositionChange(2, 5, 3, 3)], geom)
        assert entries == snapshot
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_nextcycle.py -k ReplayChanges -v`
Expected: FAIL — `ImportError: cannot import name 'replay_changes'`

- [ ] **Step 3: Add `replay_changes` to `nextcycle.py`**

Append to `s3dash/parser/nextcycle.py`:

```python
def replay_changes(
    original_entries: dict[tuple[int, int], LoadingEntry],
    changes: list[PositionChange],
    geom: Geometry,
) -> tuple[dict[tuple[int, int], LoadingEntry], list[AppliedOperation]]:
    """Fold apply_change over `changes` in order, starting from
    `original_entries`. The one place app.py and browser.py both call
    into instead of each reimplementing this loop.

    Raises ValidationError (from whichever apply_change call fails) if
    any change is invalid. The exception message already names the
    specific (row, col) involved -- more actionable for a caller than a
    bare list index would be, so this does not add one.
    """
    entries = original_entries
    operations: list[AppliedOperation] = []
    for change in changes:
        entries, op = apply_change(entries, change, geom)
        operations.append(op)
    return entries, operations
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_nextcycle.py -k ReplayChanges -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: `266 passed`

- [ ] **Step 6: Commit**

```bash
git add s3dash/parser/nextcycle.py tests/test_nextcycle.py
git commit -m "feat(loading-editor): add replay_changes so web callers share one fold loop"
```

---

## Task 2: `loadingpattern.find_input_cards_section`

**Files:**
- Modify: `s3dash/parser/loadingpattern.py`
- Test: `tests/test_loadingpattern.py`

**Interfaces:**
- Consumes: `Document` (from `.document`), `find_fuel_lab_card` (already in this module).
- Produces: `find_input_cards_section(doc: Document) -> Section`. Promotes into production code the robustness `tests/test_nextcycle_acceptance.py` currently has as test-only logic (`_input_cards_section_with_fuel_lab`). Task 3 and Task 4 both need this for the generate route/function.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_loadingpattern.py`:

```python
from s3dash.parser.loadingpattern import find_input_cards_section


class TestFindInputCardsSection:
    @needs_listings
    def test_finds_the_section_actually_holding_fuel_lab(self):
        result = parse_file(SAMPLES / "case_002495.out")
        section = find_input_cards_section(result.document)
        lines_in_section = result.document.lines[section.start:section.end]
        assert find_fuel_lab_card(lines_in_section) is not None

    def test_raises_when_no_section_has_a_fuel_lab_card(self):
        from s3dash.parser.document import load_text

        doc = load_text("'TIT.CAS' 'no fuel lab here' /\n'STA'/\n")
        with pytest.raises(LoadingPatternError, match="FUE.LAB"):
            find_input_cards_section(doc)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_loadingpattern.py -k FindInputCardsSection -v`
Expected: FAIL — `ImportError: cannot import name 'find_input_cards_section'`

- [ ] **Step 3: Add `find_input_cards_section` to `loadingpattern.py`**

In `s3dash/parser/loadingpattern.py`, add the import and function:

```python
from .document import Document, Section  # add to the existing import block
```

Append the function:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_loadingpattern.py -k FindInputCardsSection -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: `268 passed`

- [ ] **Step 6: Commit**

```bash
git add s3dash/parser/loadingpattern.py tests/test_loadingpattern.py
git commit -m "feat(loading-editor): promote input-cards-section lookup out of test-only code"
```

---

## Task 3: `app.py` routes

**Files:**
- Modify: `s3dash/web/app.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `parse_loading_pattern`, `find_input_cards_section`, `LoadingPatternError` (from `..parser.loadingpattern`); `PositionChange`, `replay_changes`, `validate`, `generate_inp`, `ValidationError as LoadingValidationError` (from `..parser.nextcycle`); the existing `_get(run_id)` helper.
- Produces: `GET /api/run/{run_id}/loading-pattern`, `POST /api/run/{run_id}/loading-pattern/apply`, `POST /api/run/{run_id}/loading-pattern/generate`. The frontend-wiring plan calls these three routes directly by URL; no other module in this plan depends on their internals.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
class TestLoadingPattern:
    def test_supported_run_returns_full_entries(self, client, run_id):
        resp = client.get(f"/api/run/{run_id}/loading-pattern")
        assert resp.status_code == 200
        body = resp.json()
        assert body["supported"] is True
        assert len(body["entries"]) == len(client.post("/api/samples/case_002495.out").json()["assemblies"])

    def test_unsupported_geometry_reports_a_reason_not_an_error(self, client):
        beavrs_run = client.post("/api/samples/9074.out")
        if beavrs_run.status_code != 200:
            pytest.skip("BEAVRS sample not bundled in this checkout")
        resp = client.get(f"/api/run/{beavrs_run.json()['runId']}/loading-pattern")
        assert resp.status_code == 200
        body = resp.json()
        assert body["supported"] is False
        assert "reason" in body

    def test_unknown_run_is_404(self, client):
        assert client.get("/api/run/deadbeef/loading-pattern").status_code == 404

    def test_apply_a_valid_swap(self, client, run_id):
        original = client.get(f"/api/run/{run_id}/loading-pattern").json()
        reused = [e for e in original["entries"] if e["kind"] == "reused"]
        # The first two reused entries, unfiltered: only one position in
        # this 17-wide core (the exact centre) is a rotational fixed
        # point, so the odds of colliding with it here are negligible --
        # and if it ever does, apply_change's own orbit-size check (unit-
        # tested directly in test_nextcycle.py) fails loudly with a clear
        # 422, not a silent wrong result.
        a, b = reused[0], reused[1]
        resp = client.post(
            f"/api/run/{run_id}/loading-pattern/apply",
            json={"changes": [
                {"fromRow": a["row"], "fromCol": a["col"], "toRow": b["row"], "toCol": b["col"]}
            ]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["problems"] == []
        assert len(body["operations"]) == 1

    def test_apply_an_invalid_move_is_422_with_a_specific_reason(self, client, run_id):
        resp = client.post(
            f"/api/run/{run_id}/loading-pattern/apply",
            json={"changes": [{"fromRow": 1, "fromCol": 1, "toRow": 2, "toCol": 2}]},
        )
        assert resp.status_code == 422
        assert "No assembly" in resp.json()["detail"]

    def test_generate_returns_inp_text_reflecting_the_change(self, client, run_id):
        original = client.get(f"/api/run/{run_id}/loading-pattern").json()
        reused = [e for e in original["entries"] if e["kind"] == "reused"]
        a, b = reused[0], reused[1]
        change = {"fromRow": a["row"], "fromCol": a["col"], "toRow": b["row"], "toCol": b["col"]}
        resp = client.post(
            f"/api/run/{run_id}/loading-pattern/generate",
            json={
                "changes": [change],
                "resFilename": "placeholder.res",
                "resExposure": "0.0",
                "wreFilename": None,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "'RES' 'placeholder.res' 0.0/" in body["text"]
        assert b["token"] in body["text"]
        assert isinstance(body["flaggedCards"], list)

    def test_generate_with_a_dirty_pattern_is_422(self, client, run_id):
        resp = client.post(
            f"/api/run/{run_id}/loading-pattern/generate",
            json={
                "changes": [{"fromRow": 1, "fromCol": 1, "toRow": 2, "toCol": 2}],
                "resFilename": "x", "resExposure": "0.0", "wreFilename": None,
            },
        )
        assert resp.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_api.py -k LoadingPattern -v`
Expected: FAIL — `404 Not Found` (routes don't exist yet)

- [ ] **Step 3: Add the routes to `app.py`**

Add to the imports at the top of `s3dash/web/app.py`:

```python
from pydantic import BaseModel

from ..parser.loadingpattern import LoadingPatternError, find_input_cards_section, parse_loading_pattern
from ..parser.nextcycle import PositionChange, generate_inp, replay_changes, validate
from ..parser.nextcycle import ValidationError as LoadingValidationError
```

Add near the other module-level helpers (after `_get`):

```python
class PositionChangeIn(BaseModel):
    fromRow: int
    fromCol: int
    toRow: int
    toCol: int


class ApplyChangesIn(BaseModel):
    changes: list[PositionChangeIn]


class GenerateInpIn(BaseModel):
    changes: list[PositionChangeIn]
    resFilename: str
    resExposure: str
    wreFilename: str | None = None


def _decode_original_pattern(result: BuildResult):
    """The run's original loading-pattern entries, or an HTTPException(422)
    with a human-readable reason if this run isn't editable."""
    payload = result.payload
    fresh_labels = {b["label"] for b in payload["inputDeck"]["batches"]}
    try:
        entries = parse_loading_pattern(
            result.document.lines,
            result.geometry,
            fresh_labels,
            assembly_count=len(payload["assemblies"]),
        )
    except LoadingPatternError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if entries is None:
        raise HTTPException(
            status_code=422,
            detail="This run has no FUE.LAB loading-pattern card to edit.",
        )
    return entries


def _replay(original, changes: list[PositionChangeIn], geom):
    position_changes = [PositionChange(c.fromRow, c.fromCol, c.toRow, c.toCol) for c in changes]
    try:
        return replay_changes(original, position_changes, geom)
    except LoadingValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

Add the three routes (near the other `/api/run/{run_id}/...` routes):

```python
@app.get("/api/run/{run_id}/loading-pattern")
async def loading_pattern(run_id: str) -> dict:
    """The run's original loading pattern, or why it can't be edited."""
    result = _get(run_id)
    payload = result.payload
    fresh_labels = {b["label"] for b in payload["inputDeck"]["batches"]}
    try:
        entries = parse_loading_pattern(
            result.document.lines,
            result.geometry,
            fresh_labels,
            assembly_count=len(payload["assemblies"]),
        )
    except LoadingPatternError as exc:
        return {"supported": False, "reason": str(exc)}
    if entries is None:
        return {
            "supported": False,
            "reason": (
                "This run has no FUE.LAB loading-pattern card -- likely a "
                "first-cycle run with no restart file to shuffle from."
            ),
        }
    return {
        "supported": True,
        "entries": [e.to_json() for e in entries.values()],
        "geometry": payload["geometry"],
    }


@app.post("/api/run/{run_id}/loading-pattern/apply")
async def apply_loading_pattern(run_id: str, body: ApplyChangesIn) -> dict:
    """Replay `body.changes` from the run's original pattern; report the
    result and every validation problem, without generating anything."""
    result = _get(run_id)
    original = _decode_original_pattern(result)
    modified, operations = _replay(original, body.changes, result.geometry)
    problems = validate(modified, original, result.geometry)
    return {
        "entries": [e.to_json() for e in modified.values()],
        "operations": [op.to_json() for op in operations],
        "problems": problems,
        "valid": not problems,
    }


@app.post("/api/run/{run_id}/loading-pattern/generate")
async def generate_loading_pattern(run_id: str, body: GenerateInpIn) -> JSONResponse:
    """Replay, validate, and generate the next-cycle .inp text. Refuses
    to generate from an invalid pattern rather than silently emitting a
    broken deck."""
    result = _get(run_id)
    original = _decode_original_pattern(result)
    modified, operations = _replay(original, body.changes, result.geometry)
    problems = validate(modified, original, result.geometry)
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
    try:
        section = find_input_cards_section(result.document)
    except LoadingPatternError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    gen = generate_inp(
        lines=result.document.lines,
        section_start=section.start,
        section_end=section.end,
        original_entries=original,
        modified_entries=modified,
        geom=result.geometry,
        operations=operations,
        res_filename=body.resFilename,
        res_exposure=body.resExposure,
        wre_filename=body.wreFilename,
    )
    name = Path(result.payload["meta"]["fileName"] or "run").stem
    return JSONResponse({
        "text": gen.text,
        "flaggedCards": gen.flagged_cards,
        "filename": f"{name}_cycle_next.inp",
    })
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_api.py -k LoadingPattern -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: `275 passed`

- [ ] **Step 6: Commit**

```bash
git add s3dash/web/app.py tests/test_api.py
git commit -m "feat(loading-editor): add HTTP routes for the loading-pattern editor"
```

---

## Task 4: `browser.py` functions

**Files:**
- Modify: `s3dash/web/browser.py`
- Test: `tests/test_browser.py`

**Interfaces:**
- Consumes: the same parser-layer functions as Task 3, plus this module's own existing `_get`, `_ok`, `_err`.
- Produces: `loading_pattern(run_id: str) -> str`, `apply_loading_pattern(run_id: str, changes_json: str) -> str`, `generate_loading_pattern(run_id: str, changes_json: str, res_filename: str, res_exposure: str, wre_filename: str | None) -> str`. All three return JSON strings via the existing `_ok`/`_err` envelope, mirroring `app.py`'s three routes field-for-field so the two web surfaces are interchangeable from a frontend's point of view.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_browser.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_browser.py -k LoadingPattern -v`
Expected: FAIL — `AttributeError: module 's3dash.web.browser' has no attribute 'loading_pattern'`

- [ ] **Step 3: Add the functions to `browser.py`**

Add to the imports at the top of `s3dash/web/browser.py`:

```python
from pathlib import Path  # not already imported in this file

from ..parser.loadingpattern import LoadingPatternError, find_input_cards_section, parse_loading_pattern
from ..parser.nextcycle import PositionChange, generate_inp, replay_changes, validate
from ..parser.nextcycle import ValidationError as LoadingValidationError
```

Append to `s3dash/web/browser.py`:

```python
def _decode_original_pattern(result: BuildResult):
    """The run's original loading-pattern entries, `None` if this run has
    none (a normal case, not an error), or raises LoadingPatternError if
    it has one but this geometry isn't supported. Callers translate both
    the None and the raised case into the same {"supported": false, ...}
    shape `loading_pattern()` returns."""
    payload = result.payload
    fresh_labels = {b["label"] for b in payload["inputDeck"]["batches"]}
    return parse_loading_pattern(
        result.document.lines,
        result.geometry,
        fresh_labels,
        assembly_count=len(payload["assemblies"]),
    )


def loading_pattern(run_id: str) -> str:
    result = _get(run_id)
    if result is None:
        return _ok({"supported": False, "reason": "Run not found; re-upload the file."})
    try:
        entries = _decode_original_pattern(result)
    except LoadingPatternError as exc:
        return _ok({"supported": False, "reason": str(exc)})
    if entries is None:
        return _ok({
            "supported": False,
            "reason": (
                "This run has no FUE.LAB loading-pattern card -- likely a "
                "first-cycle run with no restart file to shuffle from."
            ),
        })
    return _ok({
        "supported": True,
        "entries": [e.to_json() for e in entries.values()],
        "geometry": result.payload["geometry"],
    })


def _parse_changes(changes_json: str) -> list[PositionChange]:
    raw = json.loads(changes_json)
    return [PositionChange(c["fromRow"], c["fromCol"], c["toRow"], c["toCol"]) for c in raw]


def apply_loading_pattern(run_id: str, changes_json: str) -> str:
    result = _get(run_id)
    if result is None:
        return _err("Run not found; re-upload the file.")
    try:
        original = _decode_original_pattern(result)
    except LoadingPatternError as exc:
        return _err(str(exc))
    if original is None:
        return _err("This run has no FUE.LAB loading-pattern card to edit.")
    changes = _parse_changes(changes_json)
    try:
        modified, operations = replay_changes(original, changes, result.geometry)
    except LoadingValidationError as exc:
        return _err(str(exc))
    problems = validate(modified, original, result.geometry)
    return _ok({
        "entries": [e.to_json() for e in modified.values()],
        "operations": [op.to_json() for op in operations],
        "problems": problems,
        "valid": not problems,
    })


def generate_loading_pattern(
    run_id: str,
    changes_json: str,
    res_filename: str,
    res_exposure: str,
    wre_filename: str | None,
) -> str:
    result = _get(run_id)
    if result is None:
        return _err("Run not found; re-upload the file.")
    try:
        original = _decode_original_pattern(result)
    except LoadingPatternError as exc:
        return _err(str(exc))
    if original is None:
        return _err("This run has no FUE.LAB loading-pattern card to edit.")
    changes = _parse_changes(changes_json)
    try:
        modified, operations = replay_changes(original, changes, result.geometry)
    except LoadingValidationError as exc:
        return _err(str(exc))
    problems = validate(modified, original, result.geometry)
    if problems:
        return _err("; ".join(problems))
    try:
        section = find_input_cards_section(result.document)
    except LoadingPatternError as exc:
        return _err(str(exc))
    gen = generate_inp(
        lines=result.document.lines,
        section_start=section.start,
        section_end=section.end,
        original_entries=original,
        modified_entries=modified,
        geom=result.geometry,
        operations=operations,
        res_filename=res_filename,
        res_exposure=res_exposure,
        wre_filename=wre_filename,
    )
    name = Path(result.payload["meta"]["fileName"] or "run").stem
    return _ok({
        "text": gen.text,
        "flaggedCards": gen.flagged_cards,
        "filename": f"{name}_cycle_next.inp",
    })
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_browser.py -k LoadingPattern -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: `280 passed`

- [ ] **Step 6: Commit**

```bash
git add s3dash/web/browser.py tests/test_browser.py
git commit -m "feat(loading-editor): add browser adapter functions for the loading-pattern editor"
```
