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

SHARED_JS = ["state.js", "coremap.js", "panels.js", "charts.js", "views.js", "app.js", "loadingeditor.js"]


def build(outdir: Path) -> None:
    if outdir.exists():
        shutil.rmtree(outdir)
    shutil.copytree(ROOT / "webdemo", outdir)

    static_js = ROOT / "s3dash" / "web" / "static" / "js"
    for name in SHARED_JS:
        shutil.copy2(static_js / name, outdir / "js" / name)

    (outdir / "css").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "s3dash" / "web" / "static" / "css" / "app.css", outdir / "css" / "app.css")

    # app.css's @font-face rules resolve "../fonts/*.woff2" relative to
    # css/app.css, so this must land as a sibling of the css/ dir above.
    shutil.copytree(ROOT / "s3dash" / "web" / "static" / "fonts", outdir / "fonts")

    (outdir / "sample_data").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "sample_data" / "9074.out", outdir / "sample_data" / "9074.out")

    wheels = sorted((ROOT / "dist").glob("s3dash-*-py3-none-any.whl"))
    if not wheels:
        raise SystemExit(
            "No wheel found in dist/ -- run `python -m build --wheel` first (see Task 2)."
        )
    # Renamed to a fixed filename so pyodide-bridge.js never has to change
    # when pyproject.toml's version bumps -- but it must still be a
    # syntactically valid wheel filename (5 dash-separated parts), because
    # micropip parses name/version/tags *from the filename itself* before
    # it will install a local wheel. "0" is a placeholder version, never
    # read for anything: we install by direct file reference, never by
    # resolving a version constraint.
    shutil.copy2(wheels[-1], outdir / "s3dash-0-py3-none-any.whl")

    print(f"Assembled {outdir.relative_to(ROOT)}/ from webdemo/ + shared static files")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--outdir", type=Path, default=ROOT / "site")
    args = ap.parse_args(argv)
    build(args.outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
