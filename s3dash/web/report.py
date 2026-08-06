"""Standalone HTML report generation.

Produces one self-contained file -- no scripts, no external assets, printable
straight to PDF -- summarising a parsed run. This is the artefact you attach
to an email; the dashboard is the artefact you explore in.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

# Perceptually ordered ramp: lightness decreases monotonically, so it stays
# readable for the common colour-vision deficiencies and survives greyscale
# printing -- which matters because this report is made to be printed.
_RAMP = [
    "#f7f4ec", "#f4e2bd", "#eecb8d", "#e6ad66", "#dc8f52",
    "#c9713f", "#ad5636", "#8a3f30", "#632c26",
]


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _fmt(value, digits: int = 3) -> str:
    if value is None:
        return "&mdash;"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    return _esc(value)


def _colour(value: float | None, lo: float, hi: float) -> str:
    if value is None:
        return "#e9e9ec"
    if hi <= lo:
        return _RAMP[len(_RAMP) // 2]
    t = min(1.0, max(0.0, (value - lo) / (hi - lo)))
    return _RAMP[min(len(_RAMP) - 1, int(t * len(_RAMP)))]


def _core_map_svg(payload: dict, sp: dict, code: str) -> str:
    """Render one state point's core map as inline SVG."""
    assemblies = payload["assemblies"]
    values = sp["values"].get(code) or []
    numeric = [v for v in values if isinstance(v, (int, float))]
    if not numeric:
        return "<p class='muted'>No numeric data for this layer.</p>"

    lo, hi = min(numeric), max(numeric)
    n = payload["geometry"]["iafull"]
    cell, pad = 34, 30
    width = n * cell + pad * 2
    height = n * cell + pad * 2

    parts = [
        f"<svg viewBox='0 0 {width} {height}' role='img' "
        f"aria-label='Core map of {_esc(code)}' class='coremap'>"
    ]
    for i in range(1, n + 1):
        x = pad + (i - 0.5) * cell
        parts.append(
            f"<text class='axis' x='{x:.1f}' y='{pad - 10}' text-anchor='middle'>{i}</text>"
        )
        y = pad + (i - 0.5) * cell
        parts.append(
            f"<text class='axis' x='{pad - 8}' y='{y + 3:.1f}' text-anchor='end'>{i}</text>"
        )

    flagged = {
        (m["row"], m["col"])
        for g in payload.get("symmetryGroups", [])
        for m in g["members"]
    }

    for idx, a in enumerate(assemblies):
        v = values[idx] if idx < len(values) else None
        x = pad + (a["col"] - 1) * cell
        y = pad + (a["row"] - 1) * cell
        fill = _colour(v if isinstance(v, (int, float)) else None, lo, hi)
        # Keep label contrast readable against the darker end of the ramp.
        dark = isinstance(v, (int, float)) and (v - lo) / (hi - lo or 1) > 0.62
        parts.append(
            f"<rect x='{x + 1}' y='{y + 1}' width='{cell - 2}' height='{cell - 2}' "
            f"fill='{fill}' stroke='#00000018'/>"
        )
        parts.append(
            f"<text class='cell {'on-dark' if dark else ''}' x='{x + cell / 2:.1f}' "
            f"y='{y + cell / 2 - 2:.1f}' text-anchor='middle'>{_esc(a['site'])}</text>"
        )
        label = _fmt(v, 3) if isinstance(v, (int, float)) else _esc(v)
        parts.append(
            f"<text class='val {'on-dark' if dark else ''}' x='{x + cell / 2:.1f}' "
            f"y='{y + cell - 6:.1f}' text-anchor='middle'>{label}</text>"
        )
        if (a["row"], a["col"]) in flagged:
            parts.append(
                f"<path d='M{x + cell - 10} {y + 2} L{x + cell - 2} {y + 2} "
                f"L{x + cell - 2} {y + 10} Z' fill='#c0392b'/>"
            )
    parts.append("</svg>")

    legend = ["<div class='legend'><span>", _fmt(lo), "</span>"]
    for colour in _RAMP:
        legend.append(f"<i style='background:{colour}'></i>")
    legend.append(f"<span>{_fmt(hi)}</span></div>")
    return "".join(parts) + "".join(legend)


def _keff_chart_svg(payload: dict) -> str:
    """Depletion progression as an inline SVG line chart."""
    rows = payload.get("depletion") or []
    pts = [(r["cycleExposure"], r["keff"]) for r in rows if r.get("keff") is not None]
    if len(pts) < 2:
        return "<p class='muted'>Not enough depletion steps to plot.</p>"

    w, h, m = 760, 260, 46
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys + [1.0]), max(ys + [1.0])
    y0, y1 = y0 - (y1 - y0) * 0.08, y1 + (y1 - y0) * 0.08

    def px(x):
        return m + (x - x0) / (x1 - x0 or 1) * (w - m - 14)

    def py(y):
        return h - m - (y - y0) / (y1 - y0 or 1) * (h - m - 16)

    unit = _esc(payload["meta"].get("exposureUnit") or "")
    parts = [
        f"<svg viewBox='0 0 {w} {h}' role='img' "
        f"aria-label='Core k-effective versus cycle exposure' class='chart'>"
    ]
    for frac in (0, 0.25, 0.5, 0.75, 1):
        tick = y0 + frac * (y1 - y0)
        y = py(tick)
        parts.append(f"<line class='grid' x1='{m}' y1='{y:.1f}' x2='{w - 14}' y2='{y:.1f}'/>")
        parts.append(
            f"<text class='axis' x='{m - 8}' y='{y + 3:.1f}' text-anchor='end'>{tick:.3f}</text>"
        )
    if y0 < 1.0 < y1:
        parts.append(
            f"<line class='crit' x1='{m}' y1='{py(1.0):.1f}' x2='{w - 14}' y2='{py(1.0):.1f}'/>"
            f"<text class='crit-label' x='{w - 18}' y='{py(1.0) - 5:.1f}' "
            f"text-anchor='end'>k = 1.000 (critical)</text>"
        )
    path = " ".join(
        f"{'M' if i == 0 else 'L'}{px(x):.1f} {py(y):.1f}" for i, (x, y) in enumerate(pts)
    )
    parts.append(f"<path class='line' d='{path}'/>")
    for x, y in pts:
        parts.append(f"<circle class='pt' cx='{px(x):.1f}' cy='{py(y):.1f}' r='2.4'/>")
    parts.append(
        f"<text class='axis-title' x='{(w + m) / 2:.0f}' y='{h - 8}' text-anchor='middle'>"
        f"Cycle exposure ({unit})</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def _table(headers: list[str], rows: list[list], caption: str = "") -> str:
    if not rows:
        return f"<p class='muted'>No {_esc(caption or 'data')}.</p>"
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{c if isinstance(c, str) and c.startswith('<') else _esc(c)}</td>"
                         for c in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


_CSS = """
:root{--fg:#1b1d21;--muted:#6b7280;--line:#dcdfe4;--bg:#fff;--panel:#f8f9fb;
--ok:#1a7f45;--warn:#9a6a00;--err:#b3261e;}
*{box-sizing:border-box}
body{margin:0;padding:36px;font:14px/1.55 "Segoe UI",system-ui,-apple-system,sans-serif;
color:var(--fg);background:var(--bg);-webkit-print-color-adjust:exact;print-color-adjust:exact}
.wrap{max-width:1000px;margin:0 auto}
h1{font-size:23px;margin:0 0 4px}h2{font-size:16px;margin:34px 0 10px;padding-bottom:6px;
border-bottom:1px solid var(--line)}h3{font-size:13px;margin:18px 0 6px;color:var(--muted);
text-transform:uppercase;letter-spacing:.06em}
.sub{color:var(--muted);margin:0 0 18px}
.badge{display:inline-block;padding:3px 10px;border-radius:11px;font-size:12px;font-weight:600}
.badge.ok{background:#e4f4ea;color:var(--ok)}.badge.warn{background:#fdf1d8;color:var(--warn)}
.badge.err{background:#fbe4e2;color:var(--err)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:14px 0}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:10px 12px}
.kpi .k{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.kpi .v{font-size:19px;font-variant-numeric:tabular-nums;margin-top:2px}
table{border-collapse:collapse;width:100%;font-size:12.5px;margin:8px 0}
th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;
font-variant-numeric:tabular-nums}
th{background:var(--panel);font-weight:600;font-size:11px;text-transform:uppercase;
letter-spacing:.04em;color:var(--muted)}
.scroll{overflow-x:auto}
.muted{color:var(--muted);font-style:italic}
.coremap{width:100%;height:auto;max-width:660px}
.coremap .axis{font-size:9px;fill:var(--muted)}
.coremap .cell{font-size:8.5px;fill:#33363b}
.coremap .val{font-size:8px;fill:#54585f;font-variant-numeric:tabular-nums}
.coremap .on-dark{fill:#fff}
.legend{display:flex;align-items:center;gap:2px;margin-top:6px;font-size:11px;color:var(--muted)}
.legend i{width:26px;height:10px;display:inline-block}
.legend span{margin:0 6px;font-variant-numeric:tabular-nums}
.chart{width:100%;height:auto}
.chart .grid{stroke:var(--line);stroke-width:1}
.chart .line{fill:none;stroke:#2f5d9e;stroke-width:1.8}
.chart .pt{fill:#2f5d9e}
.chart .crit{stroke:#b3261e;stroke-width:1;stroke-dasharray:4 3}
.chart .crit-label{font-size:10px;fill:#b3261e}
.chart .axis,.chart .axis-title{font-size:10px;fill:var(--muted)}
.sev-ERROR{color:var(--err);font-weight:600}.sev-WARNING{color:var(--warn);font-weight:600}
.sev-CAUTION{color:#7a5a00}.sev-NOTE{color:var(--muted)}
footer{margin-top:36px;padding-top:12px;border-top:1px solid var(--line);
font-size:11px;color:var(--muted)}
@media print{body{padding:0}h2{page-break-after:avoid}table{page-break-inside:auto}
tr{page-break-inside:avoid}.coremap{max-width:100%}}
"""


def render_report(payload: dict, step: int | None = None) -> str:
    """Build a complete standalone HTML report for one parsed run."""
    meta = payload["meta"]
    geom = payload["geometry"]
    status = payload["status"]
    points = payload["statePoints"]
    sp = next((p for p in points if p["step"] == step), points[0]) if points else None

    level = status["level"]
    badge_class = {"OK": "ok", "WARNINGS": "warn", "ERRORS": "err"}.get(level, "warn")
    timing = meta.get("timing") or {}
    completion = timing.get("completion") or "unknown"

    depl = payload.get("depletion") or []
    peak_pin = max((d["peak3pin"] for d in depl), default=None)
    peak_rad = max((d["peakRadial"] for d in depl), default=None)
    exposures = [d["coreExposure"] for d in depl if d.get("coreExposure") is not None]
    burnups = [
        v for p in points for v in (p["values"].get("2EXP") or []) if isinstance(v, (int, float))
    ]

    geom_line = (
        f"{geom['reactorType']} &middot; {geom['iafull']}&times;{geom['iafull']} &middot; "
        f"{geom['fraction']}-core {geom['symmetry'].lower()} &middot; "
        f"{'3D, ' + str(geom['fuelNodes']) + ' axial nodes' if geom['is3d'] else '2D (1 axial node)'}"
    )

    kpis = [
        ("Status", f"<span class='badge {badge_class}'>{_esc(level)}</span>"),
        ("Termination", _esc(completion)),
        ("State points", _esc(meta.get("stepCount"))),
        ("Assemblies", _esc(len(payload["assemblies"]))),
        ("Cycle length", f"{_fmt(meta.get('cycleEnd'), 2)} {_esc(meta.get('exposureUnit') or '')}"),
        ("Peak burnup", f"{_fmt(max(burnups) if burnups else None, 2)} GWd/MT"),
        ("Peak pin power", _fmt(peak_pin, 3)),
        ("Peak radial power", _fmt(peak_rad, 3)),
        ("Core avg exposure", f"{_fmt(max(exposures) if exposures else None, 2)} GWd/MT"),
        ("Warnings", _esc(status["warnings"])),
        ("Symmetry violations", _esc(status["symmetryViolations"])),
        ("Execution time", f"{_fmt(timing.get('cpuSeconds'), 2)} s CPU"),
    ]
    kpi_html = "".join(
        f"<div class='kpi'><div class='k'>{_esc(k)}</div><div class='v'>{v}</div></div>"
        for k, v in kpis
    )

    sections: list[str] = []

    if sp:
        code = "2RPF" if "2RPF" in sp["values"] else next(iter(sp["values"]), None)
        sections.append(
            f"<h2>Core map &mdash; {_esc(code)} at step {sp['step']}"
            f" ({_fmt(sp.get('exposure'), 3)} {_esc(sp.get('exposureUnit') or '')})</h2>"
            + _core_map_svg(payload, sp, code)
        )

    sections.append("<h2>Depletion progression</h2>" + _keff_chart_svg(payload))
    if depl:
        sections.append(
            "<div class='scroll'>"
            + _table(
                ["Step", f"Cycle exp ({meta.get('exposureUnit') or ''})", "k-eff", "Boron (ppm)",
                 "Peak radial", "Peak nodal", "Peak 3-pin", "Core exp (GWd/MT)"],
                [
                    [d["step"], _fmt(d["cycleExposure"], 3), _fmt(d["keff"], 5),
                     _fmt(d["boron"], 0), _fmt(d["peakRadial"], 3), _fmt(d["peakNodal"], 3),
                     _fmt(d["peak3pin"], 3), _fmt(d["coreExposure"], 3)]
                    for d in depl
                ],
                "depletion data",
            )
            + "</div>"
        )

    sections.append(
        "<h2>Core inventory</h2>"
        + _table(
            ["Fuel type", "Assemblies", "Batch", "Fresh this cycle"],
            [
                [r["fuelType"], r["count"], r["batchLabel"] or "&mdash;",
                 "yes" if r["fresh"] else "no"]
                for r in payload["inventory"]
            ],
            "inventory",
        )
    )

    if payload.get("segments"):
        sections.append(
            "<h3>Fuel segments</h3>"
            + _table(
                ["Seg", "Name", "Enrichment (w/o U235)", "Loading (g/cc)",
                 "BP loading (g/cc)", "BP rods", "Equivalent assemblies"],
                [
                    [s["number"], s["name"], _fmt(s["enrichment"], 5), _fmt(s["loading"], 5),
                     _fmt(s["bpLoading"], 3), s["bpRods"], _fmt(s["equivalentAssemblies"], 1)]
                    for s in payload["segments"]
                ],
                "segments",
            )
        )

    sections.append(
        "<h2>Diagnostics</h2>"
        + _table(
            ["Label", "Times", "Severity", "Where", "Message"],
            [
                [d["label"], d["times"],
                 f"<span class='sev-{_esc(d['severity'])}'>{_esc(d['severity'])}</span>",
                 d["where"], d["info"]]
                for d in payload["diagnostics"]
            ],
            "diagnostics",
        )
    )

    groups = payload.get("symmetryGroups") or []
    if groups:
        rows = []
        for g in groups:
            for m in g["members"]:
                rows.append(
                    [g["group"], m["tag"], f"({m['row']}, {m['col']})", m["label"],
                     m["fuelType"], _fmt(m["aveExp"], 3),
                     ", ".join(_fmt(q, 3) for q in m["quadrantExp"])]
                )
        sections.append(
            "<h2>Symmetry check &mdash; failing groups</h2>"
            "<p class='sub'>Positions that should be rotationally equivalent but are not. "
            "Compare average and quadrant exposures to see which position disagrees.</p>"
            "<div class='scroll'>"
            + _table(
                ["Group", "Tag", "(row, col)", "Label", "Fuel type", "Avg exposure",
                 "2&times;2 quadrant exposures"],
                rows,
                "symmetry violations",
            )
            + "</div>"
        )

    if payload.get("parseNotes"):
        sections.append(
            "<h2>Parse notes</h2><ul>"
            + "".join(f"<li>{_esc(n)}</li>" for n in payload["parseNotes"])
            + "</ul>"
        )

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = f"SIMULATE-3 report &mdash; {_esc(meta.get('fileName'))}"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<h1>{_esc(meta.get('plant') or 'SIMULATE-3 run')} &mdash; {_esc(meta.get('caseTitle') or '')}</h1>
<p class="sub">{_esc(meta.get('fileName'))} &middot; {_esc(meta.get('code'))}
 {_esc(meta.get('version'))} &middot; run {_esc(meta.get('runDate'))}
 {_esc(meta.get('runTime'))} &middot; {geom_line}</p>
<div class="grid">{kpi_html}</div>
{''.join(sections)}
<footer>Generated {generated} from {_esc(meta.get('fileName'))}
 ({_esc(meta.get('lineCount'))} lines, {_esc(meta.get('pageCount'))} pages).
 Values are read directly from the listing; none are recomputed.</footer>
</div></body></html>"""
