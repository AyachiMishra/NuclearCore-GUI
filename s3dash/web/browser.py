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
from pathlib import Path

from ..parser import BuildResult, parse_text
from ..parser.loadingpattern import LoadingPatternError, find_input_cards_section, parse_loading_pattern
from ..parser.nextcycle import PositionChange, generate_inp, replay_changes, suggest_generation_inputs, validate
from ..parser.nextcycle import ValidationError as LoadingValidationError
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
        "suggested": suggest_generation_inputs(
            result.payload["inputDeck"]["cards"], result.payload["meta"].get("cycleEnd")
        ),
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
