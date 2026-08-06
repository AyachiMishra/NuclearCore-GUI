"""Generate the README images from a real listing.

Run from the project root with any SIMULATE-3 output::

    python tools/make_readme_assets.py path/to/run.out

Writes SVG (vector, small, crisp at any zoom) into ``docs/img/``. Committing
generated images rather than a browser screenshot keeps them reproducible and
keeps the repository free of binary blobs that churn on every UI tweak.

The bundled examples use BEAVRS, MIT's openly published benchmark, so nothing
plant-proprietary ends up in the repository.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from s3dash.parser import parse_file  # noqa: E402

# Light -> dark, monotonic in lightness: higher value carries more visual
# weight, and the ramp survives greyscale printing. Matches the dashboard.
RAMP = [
    "#f7f4ec", "#f4e2bd", "#eecb8d", "#e6ad66", "#dc8f52",
    "#c9713f", "#ad5636", "#8a3f30", "#632c26",
]
INK_LIGHT, INK_DARK = "#33363b", "#ffffff"
MUTED, LINE, PANEL = "#6b7280", "#dcdfe4", "#f8f9fb"


def _colour(value: float | None, lo: float, hi: float) -> tuple[str, bool]:
    if value is None:
        return "#eceef1", False
    t = 0.0 if hi <= lo else min(1.0, max(0.0, (value - lo) / (hi - lo)))
    idx = min(len(RAMP) - 1, int(t * len(RAMP)))
    return RAMP[idx], t > 0.62


def core_map_svg(payload: dict, code: str = "2RPF", step: int = 0) -> str:
    geom = payload["geometry"]
    sp = next((p for p in payload["statePoints"] if p["step"] == step), payload["statePoints"][0])
    values = sp["values"].get(code) or []
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums:
        raise SystemExit(f"{code} has no numeric values in this listing")
    lo, hi = min(nums), max(nums)

    n = geom["iafull"]
    cell, pad, top = 46, 34, 74
    w, h = n * cell + pad * 2, n * cell + pad + top + 60

    letters: dict[int, str] = {}
    for a in payload["assemblies"]:
        letters.setdefault(a["col"], a["site"].split("-")[0])

    unit = next(
        (s["variable"]["unit"] for s in payload["sections"]
         if s.get("variable") and s["variable"]["code"] == code and s["variable"].get("unit")),
        "",
    )
    name = next(
        (s["variable"]["name"] for s in payload["sections"]
         if s.get("variable") and s["variable"]["code"] == code),
        code,
    )

    o: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
        f'height="{h}" font-family="ui-sans-serif,Segoe UI,system-ui,sans-serif" '
        f'role="img" aria-label="{name} core map">',
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        f'<text x="{pad}" y="30" font-size="19" font-weight="600" fill="#1b1d21">'
        f'{name}{" (" + unit + ")" if unit else ""}</text>',
        f'<text x="{pad}" y="52" font-size="13" fill="{MUTED}">'
        f'{payload["meta"].get("plant") or "core"} &#183; {n}&#215;{n} &#183; '
        f'{geom["fraction"]}-core {geom["symmetry"].lower()} &#183; '
        f'{len(payload["assemblies"])} fuelled positions &#183; step {sp["step"]}</text>',
    ]

    for c in range(1, n + 1):
        x = pad + (c - 0.5) * cell
        o.append(
            f'<text x="{x:.1f}" y="{top - 10}" text-anchor="middle" font-size="12" '
            f'fill="{MUTED}">{letters.get(c, c)}</text>'
        )
    for r in range(1, n + 1):
        y = top + (r - 0.5) * cell
        o.append(
            f'<text x="{pad - 10}" y="{y + 4:.1f}" text-anchor="end" font-size="12" '
            f'fill="{MUTED}">{r}</text>'
        )

    flagged = {
        (m["row"], m["col"])
        for g in payload.get("symmetryGroups", []) for m in g["members"]
    }

    for i, a in enumerate(payload["assemblies"]):
        v = values[i] if i < len(values) else None
        fill, dark = _colour(v if isinstance(v, (int, float)) else None, lo, hi)
        ink = INK_DARK if dark else INK_LIGHT
        x, y = pad + (a["col"] - 1) * cell, top + (a["row"] - 1) * cell
        o.append(
            f'<rect x="{x + 1}" y="{y + 1}" width="{cell - 2}" height="{cell - 2}" rx="4" '
            f'fill="{fill}" stroke="#00000014"/>'
        )
        o.append(
            f'<text x="{x + cell / 2:.1f}" y="{y + cell / 2 - 3:.1f}" text-anchor="middle" '
            f'font-size="10" fill="{ink}" opacity="0.75">{a["site"]}</text>'
        )
        if isinstance(v, (int, float)):
            o.append(
                f'<text x="{x + cell / 2:.1f}" y="{y + cell - 9:.1f}" text-anchor="middle" '
                f'font-size="12" font-weight="600" fill="{ink}">{v:.3f}</text>'
            )
        if (a["row"], a["col"]) in flagged:
            o.append(
                f'<path d="M{x + cell - 13} {y + 3} L{x + cell - 3} {y + 3} '
                f'L{x + cell - 3} {y + 13} Z" fill="#c0392b"/>'
            )

    ly = top + n * cell + 26
    o.append(f'<text x="{pad}" y="{ly - 4}" font-size="11" fill="{MUTED}">'
             f'LIGHT = LOW &#183; DARK = HIGH</text>')
    sw = 30
    for k, colour in enumerate(RAMP):
        o.append(f'<rect x="{pad + 150 + k * sw}" y="{ly - 14}" width="{sw}" height="11" '
                 f'fill="{colour}"/>')
    o.append(f'<text x="{pad + 144}" y="{ly - 4}" text-anchor="end" font-size="11" '
             f'fill="{MUTED}">{lo:.3f}</text>')
    o.append(f'<text x="{pad + 156 + len(RAMP) * sw}" y="{ly - 4}" font-size="11" '
             f'fill="{MUTED}">{hi:.3f}</text>')
    o.append("</svg>")
    return "".join(o)


def depletion_svg(payload: dict) -> str:
    rows = payload.get("depletion") or []
    pts = [(r["cycleExposure"], r["keff"]) for r in rows if r.get("keff") is not None]
    if len(pts) < 2:
        raise SystemExit("not enough depletion steps to plot")

    w, h, m = 900, 320, 62
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys + [1.0]), max(ys + [1.0])
    span = (y1 - y0) or 1
    y0, y1 = y0 - span * 0.10, y1 + span * 0.10

    px = lambda x: m + (x - x0) / ((x1 - x0) or 1) * (w - m - 22)  # noqa: E731
    py = lambda y: h - m - (y - y0) / ((y1 - y0) or 1) * (h - m - 30)  # noqa: E731

    unit = payload["meta"].get("exposureUnit") or ""
    o = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
        f'height="{h}" font-family="ui-sans-serif,Segoe UI,system-ui,sans-serif" '
        f'role="img" aria-label="Core k-effective versus cycle exposure">',
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        f'<text x="{m}" y="26" font-size="15" font-weight="600" fill="#1b1d21">'
        f'Depletion progression &#8212; k-effective vs cycle exposure</text>',
    ]
    for frac in (0, 0.25, 0.5, 0.75, 1):
        tick = y0 + frac * (y1 - y0)
        y = py(tick)
        o.append(f'<line x1="{m}" y1="{y:.1f}" x2="{w - 22}" y2="{y:.1f}" stroke="{LINE}"/>')
        o.append(f'<text x="{m - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="11" '
                 f'fill="{MUTED}">{tick:.3f}</text>')
    if y0 < 1.0 < y1:
        o.append(f'<line x1="{m}" y1="{py(1.0):.1f}" x2="{w - 22}" y2="{py(1.0):.1f}" '
                 f'stroke="#b3261e" stroke-dasharray="5 4"/>')
        o.append(f'<text x="{w - 26}" y="{py(1.0) - 6:.1f}" text-anchor="end" font-size="11" '
                 f'fill="#b3261e">k = 1.000 (critical)</text>')
    path = " ".join(
        f'{"M" if i == 0 else "L"}{px(x):.1f} {py(y):.1f}' for i, (x, y) in enumerate(pts)
    )
    o.append(f'<path d="{path}" fill="none" stroke="#2f5d9e" stroke-width="2"/>')
    for x, y in pts:
        o.append(f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="2.8" fill="#2f5d9e"/>')
    for frac in (0, 0.5, 1):
        xv = x0 + frac * (x1 - x0)
        o.append(f'<text x="{px(xv):.1f}" y="{h - m + 20}" text-anchor="middle" font-size="11" '
                 f'fill="{MUTED}">{xv:.0f}</text>')
    o.append(f'<text x="{(w + m) / 2:.0f}" y="{h - 10}" text-anchor="middle" font-size="12" '
             f'fill="{MUTED}">Cycle exposure ({unit})</text>')
    o.append("</svg>")
    return "".join(o)


def axial_svg(payload: dict) -> str | None:
    sp = payload["statePoints"][0]
    ax = (sp.get("axialState") or {})
    nodes = ax.get("nodes") or []
    if len(nodes) < 2:
        return None

    w, h, m = 420, 360, 58
    vals = [n.get("RPF") for n in nodes if n.get("RPF") is not None]
    lo, hi = min(vals), max(vals)
    lo, hi = 0.0, hi * 1.08
    n_max = max(n["node"] for n in nodes)

    px = lambda v: m + (v - lo) / ((hi - lo) or 1) * (w - m - 24)  # noqa: E731
    py = lambda k: h - m - (k - 1) / ((n_max - 1) or 1) * (h - m - 34)  # noqa: E731

    o = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
        f'height="{h}" font-family="ui-sans-serif,Segoe UI,system-ui,sans-serif" '
        f'role="img" aria-label="Axial power profile">',
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        f'<text x="{m - 34}" y="26" font-size="15" font-weight="600" fill="#1b1d21">'
        f'Axial power profile ({len(nodes)} nodes)</text>',
    ]
    for k in range(1, n_max + 1):
        y = py(k)
        o.append(f'<line x1="{m}" y1="{y:.1f}" x2="{w - 24}" y2="{y:.1f}" stroke="{LINE}"/>')
        o.append(f'<text x="{m - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="10" '
                 f'fill="{MUTED}">{k}</text>')
    pts = sorted(((n["node"], n["RPF"]) for n in nodes if n.get("RPF") is not None))
    path = " ".join(
        f'{"M" if i == 0 else "L"}{px(v):.1f} {py(k):.1f}' for i, (k, v) in enumerate(pts)
    )
    o.append(f'<path d="{path}" fill="none" stroke="#c9713f" stroke-width="2.2"/>')
    for k, v in pts:
        o.append(f'<circle cx="{px(v):.1f}" cy="{py(k):.1f}" r="3" fill="#c9713f"/>')
    o.append(f'<text x="{(w + m) / 2:.0f}" y="{h - 10}" text-anchor="middle" font-size="12" '
             f'fill="{MUTED}">Relative power fraction</text>')
    o.append(f'<text x="{m - 40}" y="{h / 2:.0f}" font-size="11" fill="{MUTED}" '
             f'transform="rotate(-90 {m - 40} {h / 2:.0f})" text-anchor="middle">'
             f'Axial node (bottom &#8594; top)</text>')
    o.append("</svg>")
    return "".join(o)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate README images from a listing.")
    ap.add_argument("listing", type=Path)
    ap.add_argument("-o", "--outdir", type=Path, default=ROOT / "docs" / "img")
    args = ap.parse_args(argv)

    payload = parse_file(args.listing).payload
    args.outdir.mkdir(parents=True, exist_ok=True)

    assets = {"core-map.svg": core_map_svg(payload), "depletion.svg": depletion_svg(payload)}
    axial = axial_svg(payload)
    if axial:
        assets["axial.svg"] = axial

    for name, svg in assets.items():
        path = args.outdir / name
        path.write_text(svg, encoding="utf-8")
        print(f"{path.relative_to(ROOT)}  ({len(svg) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
