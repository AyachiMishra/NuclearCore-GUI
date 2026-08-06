"""FastAPI application: upload a listing, serve its parsed payload.

State is deliberately per-session and in-memory. The dashboard analyses one
file at a time, and holding parsed runs in a process dictionary keeps the
deployment to a single command with no database or disk cache to manage.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..parser import BuildResult, parse_text
from .report import render_report

STATIC_DIR = Path(__file__).parent / "static"
SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"
MAX_UPLOAD_BYTES = 256 * 1024 * 1024

app = FastAPI(title="SIMULATE-3 Dashboard", version="1.0.0")

# run_id -> parsed result. Bounded so a long session cannot grow without limit.
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


def _get(run_id: str) -> BuildResult:
    result = _RUNS.get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found; re-upload the file.")
    return result


@app.post("/api/parse")
async def parse_upload(file: UploadFile) -> JSONResponse:
    """Parse an uploaded SIMULATE-3 listing and return its full payload."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 256 MB limit.")

    text = raw.decode("latin-1", errors="replace")
    try:
        result = parse_text(text, source_file=file.filename or "upload.out")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse file: {exc}") from exc

    if not result.payload["sections"]:
        raise HTTPException(
            status_code=422,
            detail="No SIMULATE-3 sections were recognised. Is this a SIMULATE-3 output listing?",
        )

    run_id = _store(result)
    return JSONResponse({"runId": run_id, **result.payload})


@app.get("/api/samples")
async def list_samples() -> dict:
    """List the bundled example listings, so the UI works with no upload."""
    if not SAMPLE_DIR.is_dir():
        return {"samples": []}
    return {
        "samples": [
            {"name": p.name, "sizeKb": round(p.stat().st_size / 1024)}
            for p in sorted(SAMPLE_DIR.glob("*.out"))
        ]
    }


@app.post("/api/samples/{name}")
async def parse_sample(name: str) -> JSONResponse:
    """Parse one of the bundled samples by name."""
    path = (SAMPLE_DIR / name).resolve()
    if not path.is_file() or path.parent != SAMPLE_DIR.resolve():
        raise HTTPException(status_code=404, detail="Sample not found.")
    result = parse_text(path.read_text(encoding="latin-1", errors="replace"), source_file=path.name)
    run_id = _store(result)
    return JSONResponse({"runId": run_id, **result.payload})


@app.get("/api/run/{run_id}/section", response_class=PlainTextResponse)
async def section_text(
    run_id: str,
    start: int = Query(..., ge=0),
    end: int = Query(..., ge=0),
    context: int = Query(0, ge=0, le=200),
) -> str:
    """Return the raw listing text for a line range, for the section viewer."""
    result = _get(run_id)
    lines = result.document.lines
    lo = max(0, start - context)
    hi = min(len(lines), end + context)
    if lo >= hi:
        raise HTTPException(status_code=400, detail="Empty line range.")
    return "\n".join(lines[lo:hi])


@app.get("/api/run/{run_id}/search")
async def search(run_id: str, q: str = Query(..., min_length=1), limit: int = 200) -> dict:
    """Full-text search over the raw listing, returning line hits."""
    result = _get(run_id)
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
    return {"query": q, "count": len(hits), "hits": hits, "truncated": len(hits) >= limit}


@app.get("/api/run/{run_id}/export.json")
async def export_json(run_id: str) -> StreamingResponse:
    """Download the complete parsed payload as JSON."""
    result = _get(run_id)
    blob = json.dumps(result.payload, indent=2).encode("utf-8")
    name = Path(result.payload["meta"]["fileName"] or "run").stem
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}.parsed.json"'},
    )


@app.get("/api/run/{run_id}/export.csv")
async def export_csv(run_id: str, step: int = Query(0, ge=0)) -> StreamingResponse:
    """Download one state point's assembly table as CSV."""
    result = _get(run_id)
    payload = result.payload
    points = payload["statePoints"]
    if not points:
        raise HTTPException(status_code=404, detail="No state points in this run.")
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
    name = Path(payload["meta"]["fileName"] or "run").stem
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}.step{sp["step"]}.csv"'},
    )


@app.get("/api/run/{run_id}/report.html")
async def export_report(run_id: str, step: int = Query(0, ge=0), download: bool = True):
    """Standalone, self-contained HTML report -- printable straight to PDF."""
    result = _get(run_id)
    html_doc = render_report(result.payload, step=step)
    name = Path(result.payload["meta"]["fileName"] or "run").stem
    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{name}.report.html"'
    return HTMLResponse(html_doc, headers=headers)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    page = STATIC_DIR / "index.html"
    if not page.is_file():
        raise HTTPException(status_code=500, detail="Front end assets are missing.")
    return HTMLResponse(page.read_text(encoding="utf-8"))


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
