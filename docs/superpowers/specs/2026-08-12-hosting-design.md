# Public hosting via Pyodide + GitHub Pages

Status: approved. Date: 2026-08-12.

## Goal

Anyone can visit a URL, upload their own SIMULATE-3 `.out` listing (or try the
bundled BEAVRS sample) and get the real, live-parsed dashboard — no install,
no account, and no server-side handling of their file.

## Approaches considered

| | Cost/maintenance | Porting work | Visitor's file |
|---|---|---|---|
| **A. Pyodide, static on GitHub Pages** | Free forever, nothing to run | Real (build a transport-layer shim) | Never leaves their browser |
| B. Real server (Render/Railway/Fly free tier) | Free, but cold starts after idling; depends on a third party's free tier | None — backend runs as-is | Leaves the browser, hits a rented server |
| C. Real server, paid always-on | Recurring bill | None | Same as B |

**Chosen: A.** It's free permanently, needs no ongoing attention, and — the
deciding factor — it's the only option that keeps the tool's existing promise
("no upload, no server, no network") true for strangers on the internet, not
just for someone running it locally. The audience for this tool works with
plant-proprietary listings; that property matters more than the convenience
of zero porting work.

## Repo structure

- `webdemo/` (new): `index.html` (adapted from
  `s3dash/web/static/index.html`), the existing CSS/JS copied over from
  `s3dash/web/static/` largely unchanged, plus one new file,
  `pyodide-bridge.js`.
- CI builds a wheel containing `s3dash.parser`, `s3dash.web.report`, and
  `s3dash.web.pdfreport` — never `s3dash.web.app` (the FastAPI layer, which
  needs `fastapi`/`uvicorn`, meaningless in a browser). Verified both
  `s3dash/__init__.py` and `s3dash/web/__init__.py` are empty, so importing
  the parser/report modules can't transitively import FastAPI.
- `.github/workflows/deploy-pages.yml`: builds that wheel, assembles
  `webdemo/` + the wheel + the BEAVRS sample (`sample_data/9074.out`,
  matching the existing "BEAVRS only" example-data policy) into a Pages
  artifact, deploys via GitHub's native Pages-from-Actions method (Settings →
  Pages → Source: GitHub Actions) on every push to `main` touching relevant
  paths. No `gh-pages` branch.
- Additive only: `python -m s3dash` (local server) and `python -m
  s3dash.bundle` (offline single-file export) are untouched and keep working
  exactly as today. This is a third way to run the tool, not a replacement
  for the other two.

## Data flow: the bridge

Today: JS `fetch()` → HTTP → a FastAPI route → a Python function → JSON →
the UI renders it.

New: JS calls a bridge function → the same Python function, called directly
in-process inside Pyodide (no network hop) → same JSON shape → the UI
renders it, unmodified. `state.js`, `coremap.js`, `panels.js`, `app.js` don't
change, because none of them know or care whether the answer came from a
real server or the same browser tab.

`pyodide-bridge.js` implements one function per endpoint the frontend
already calls, mirroring `s3dash/web/app.py`'s routes:

- parse upload (`POST /api/parse`)
- parse bundled sample (`POST /api/samples/{name}`)
- list samples (`GET /api/samples`) — statically just `["9074.out"]`
- section text (`GET /api/run/{id}/section`)
- search (`GET /api/run/{id}/search`)
- export JSON / CSV (`GET /api/run/{id}/export.json` / `.csv`)
- HTML / PDF report (`GET /api/run/{id}/report.html` / `.pdf`)

File upload: the browser's File API reads the dropped file's bytes in JS,
which are handed into Python through Pyodide's JS↔Python bridge — the same
handoff a multipart POST used to do, just with no network in between.
"Run" state (today held server-side in `app.py`'s `_RUNS` dict, keyed by a
generated run id) moves to an in-memory JS object on the page instead, since
there's no longer a server process to hold it.

Boot sequence: on page load, before any of the above can work, Pyodide
itself initializes — fetches its runtime from the jsdelivr CDN,
`micropip.install`s `reportlab` (confirmed pure-Python wheel, no compiled
extensions), installs our own wheel. This is a few seconds of one-time work,
so the page needs a visible "starting up" state, not a dead page. After
boot, every call is faster than the old server was, since there's no HTTP
round-trip at all.

The CDN fetch is for the Python runtime only — a visitor's uploaded file
never goes near it or leaves their machine. The "no upload, no server, no
network" property holds for their data specifically.

## Scope for v1

Ships: file upload, the BEAVRS sample, the core map (all existing layers —
power, fuel type, batch, control rods), the depletion/axial/histogram
charts, the diagnostics review, section search/raw-text viewer, and
CSV/JSON/PDF-report/PNG exports. ("Print" in the export menu calls the
browser's own `window.print()` on the live page — confirmed while planning
that it never touches the HTML-report endpoint, so it needs no porting at
all; the HTML-report endpoint itself has no UI entry point today and is out
of scope here.)

Unchanged: the parser, the report generators, and essentially all of the
frontend UI. This is a transport-layer port, not a rewrite — the smaller the
diff against the working local app, the less that can go wrong.

Explicitly out of scope: the offline single-file bundle exporter
(`s3dash.bundle`) stays a local-only CLI tool. Visiting the hosted page
already gives a zero-install experience, so there's nothing it needs to
replicate. No features beyond what the local app already does today.

Naming: the hosted page uses the app's current title, "Vision: Nuclear Core
Analysis," as already set in the codebase. A future rename is independent of
this work and not resolved here.

## Error handling

- Pyodide boot failure (CDN blocked, offline, slow connection): an inline
  message explaining what happened, with a link to the repo's normal local
  quick-start as a fallback that works regardless of network conditions.
- Parse errors (malformed or non-SIMULATE-3 file): the bridge relays the
  same message text the parser already produces today (e.g. "Could not
  parse file: ...", "No SIMULATE-3 sections were recognised...") without an
  HTTP-status-code wrapper, since there is no HTTP involved.
- No server-side size cap, because there's no server — a very large listing
  costs the visitor's own browser time and memory rather than a shared
  resource. A one-line note for very large files is enough; not a hard
  block.

## Testing

- The existing pytest suite (218 tests) keeps validating parser/report
  correctness unchanged — nothing about hosting touches that code path's
  logic, only how its inputs/outputs travel.
- A manual browser smoke check after each deploy: page loads, Pyodide
  boots, the BEAVRS sample parses, the core map renders with real data.
  Follows this project's existing practice of verifying UI changes in a
  real browser before calling them done. Not adding new CI infrastructure
  for this in v1 — the project has one existing workflow (`tests.yml`); a
  second, heavier one for browser automation isn't justified yet.

## Known implementation risks (for the plan to resolve, not decided here)

- Exact packaging mechanism for the wheel (build backend, version pinning)
  and the precise Pyodide/micropip API calls — mechanical detail for
  `writing-plans` / the implementer, not a design-level decision.
- Whether any frontend JS makes assumptions specific to running over real
  HTTP (e.g. relative URL construction, response streaming) that the bridge
  needs to account for — to be found by reading `app.js`/`state.js` closely
  during implementation, not enumerated speculatively here.
