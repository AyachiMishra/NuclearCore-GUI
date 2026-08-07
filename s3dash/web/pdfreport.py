"""Formatted PDF report for one parsed run.

Built with ReportLab's platypus flowables so pagination, table splitting and
repeat headers are handled by the layout engine rather than by hand. The
report carries a real table of contents: entries are clickable, page numbers
are resolved on a second layout pass, and the PDF outline (the sidebar
bookmark tree every viewer shows) mirrors it.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

PAGE = A4
MARGIN = 18 * mm

INK = colors.HexColor("#1b1d21")
MUTED = colors.HexColor("#6b7280")
LINE = colors.HexColor("#d9dce1")
PANEL = colors.HexColor("#f4f6f8")
ACCENT = colors.HexColor("#2f5d9e")
SEV = {
    "ERROR": colors.HexColor("#b3261e"),
    "WARNING": colors.HexColor("#9a6a00"),
    "CAUTION": colors.HexColor("#7a5a00"),
    "NOTE": MUTED,
}

# Light -> dark, monotonic in lightness so the core map stays readable in
# greyscale print, which is how these reports usually end up being read.
RAMP = [
    colors.HexColor(h) for h in (
        "#f7f4ec", "#f4e2bd", "#eecb8d", "#e6ad66", "#dc8f52",
        "#c9713f", "#ad5636", "#8a3f30", "#632c26",
    )
]


def _styles() -> dict:
    base = getSampleStyleSheet()
    s = {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=23, leading=27, textColor=INK, alignment=TA_LEFT, spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontSize=11, leading=15,
            textColor=MUTED, spaceAfter=2,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=15,
            leading=19, textColor=INK, spaceBefore=16, spaceAfter=7,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11.5,
            leading=15, textColor=INK, spaceBefore=11, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontSize=9.5, leading=13.5, textColor=INK,
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "small", parent=base["Normal"], fontSize=8, leading=11, textColor=MUTED,
        ),
        "cell": ParagraphStyle(
            "cell", parent=base["Normal"], fontSize=8, leading=10.5, textColor=INK,
        ),
        "kpiVal": ParagraphStyle(
            "kpiVal", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=13,
            leading=15, textColor=INK, alignment=TA_CENTER,
        ),
        "kpiKey": ParagraphStyle(
            "kpiKey", parent=base["Normal"], fontSize=6.8, leading=9, textColor=MUTED,
            alignment=TA_CENTER,
        ),
    }
    return s


class _Doc(BaseDocTemplate):
    """Document that numbers pages, draws furniture, and records TOC entries."""

    def __init__(self, buf, payload: dict, **kw):
        super().__init__(buf, pagesize=PAGE, leftMargin=MARGIN, rightMargin=MARGIN,
                         topMargin=MARGIN, bottomMargin=MARGIN + 6 * mm, **kw)
        self.payload = payload
        self._toc_seq = 0
        frame = Frame(
            self.leftMargin, self.bottomMargin,
            PAGE[0] - 2 * MARGIN, PAGE[1] - MARGIN - self.bottomMargin,
            id="body", showBoundary=0,
        )
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[frame], onPage=self._blank),
            PageTemplate(id="body", frames=[frame], onPage=self._furniture),
        ])

    def handle_documentBegin(self) -> None:
        """Reset the bookmark counter at the start of every layout pass.

        multiBuild lays the document out repeatedly until page numbers settle.
        Letting the counter run across passes gives each pass different
        bookmark keys, so the table of contents never compares equal and the
        build fails with "Index entries not resolved".
        """
        self._toc_seq = 0
        super().handle_documentBegin()

    def _blank(self, canvas, doc) -> None:
        canvas.saveState()
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(MARGIN, MARGIN * 0.6, self._footer_left())
        canvas.restoreState()

    def _footer_left(self) -> str:
        meta = self.payload["meta"]
        return f"{meta.get('fileName') or 'listing'} — SIMULATE-3 {meta.get('version') or ''}".strip()

    def _furniture(self, canvas, doc) -> None:
        canvas.saveState()
        meta = self.payload["meta"]
        # Running head
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(MARGIN, PAGE[1] - MARGIN + 4 * mm,
                          (meta.get("plant") or "SIMULATE-3 run")[:60])
        canvas.drawRightString(PAGE[0] - MARGIN, PAGE[1] - MARGIN + 4 * mm,
                               (meta.get("caseTitle") or "")[:70])
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, PAGE[1] - MARGIN + 2.4 * mm,
                    PAGE[0] - MARGIN, PAGE[1] - MARGIN + 2.4 * mm)
        # Footer with page number
        canvas.line(MARGIN, MARGIN * 0.6 + 4 * mm, PAGE[0] - MARGIN, MARGIN * 0.6 + 4 * mm)
        canvas.drawString(MARGIN, MARGIN * 0.6, self._footer_left())
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(INK)
        canvas.drawRightString(PAGE[0] - MARGIN, MARGIN * 0.6, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    def afterFlowable(self, flowable) -> None:
        """Feed headings to the TOC and to the PDF outline."""
        if not isinstance(flowable, Paragraph):
            return
        style = flowable.style.name
        if style not in ("h1", "h2"):
            return
        level = 0 if style == "h1" else 1
        text = flowable.getPlainText()
        key = f"toc{self._toc_seq}"
        self._toc_seq += 1
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=level, closed=False)
        self.notify("TOCEntry", (level, text, self.page, key))


# ------------------------------------------------------------------ helpers


def _fmt(v, digits: int = 3, dash: str = "—") -> str:
    if v is None:
        return dash
    if isinstance(v, float):
        return f"{v:,.{digits}f}"
    return str(v)


def _esc(v) -> str:
    return (
        str("" if v is None else v)
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _table(data, widths, style_extra=None, header=True, font=8):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    cmds = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), font),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        cmds += [
            ("BACKGROUND", (0, 0), (-1, 0), PANEL),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
            ("FONTSIZE", (0, 0), (-1, 0), font - 0.7),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
        ]
    t.setStyle(TableStyle(cmds + (style_extra or [])))
    return t


def _cell_colour(v, lo, hi):
    if v is None:
        return colors.HexColor("#eceef1"), False
    t = 0.0 if hi <= lo else min(1.0, max(0.0, (v - lo) / (hi - lo)))
    idx = min(len(RAMP) - 1, int(t * len(RAMP)))
    return RAMP[idx], t > 0.62


# ------------------------------------------------------------------ sections


def _cover(payload, st) -> list:
    meta, geom, status = payload["meta"], payload["geometry"], payload["status"]
    timing = meta.get("timing") or {}
    out = [Spacer(1, 26 * mm)]
    out.append(Paragraph("Nuclear Core Analysis Report", st["title"]))
    out.append(Paragraph(
        f'{_esc(meta.get("plant") or "SIMULATE-3 run")} &nbsp;&middot;&nbsp; '
        f'{_esc(meta.get("caseTitle") or "")}', st["subtitle"]))
    out.append(Spacer(1, 8 * mm))

    level = status["level"]
    badge = {"OK": ("No issues", colors.HexColor("#1a7f45")),
             "WARNINGS": (f'{status["warnings"]} warnings', SEV["WARNING"]),
             "ERRORS": (f'{status["errors"]} errors', SEV["ERROR"])}.get(
        level, (level, MUTED))
    facts = [
        ("Source listing", meta.get("fileName")),
        ("Simulator", f'SIMULATE-3 {meta.get("version") or ""}'.strip()),
        ("Run date", f'{meta.get("runDate") or ""} {meta.get("runTime") or ""}'.strip()),
        ("Geometry", f'{geom["reactorType"]} · {geom["iafull"]}×{geom["iafull"]} · '
                     f'{geom["fraction"]}-core {geom["symmetry"].lower()} · '
                     f'{"3D, " + str(geom["fuelNodes"]) + " axial nodes" if geom["is3d"] else "2D (1 axial node)"}'),
        ("Fuel assemblies", f'{len(payload["assemblies"])}'),
        ("Depletion", f'{meta.get("stepCount")} steps · {_fmt(meta.get("cycleStart"), 3)}'
                      f'–{_fmt(meta.get("cycleEnd"), 3)} {meta.get("exposureUnit") or ""}'),
        ("Termination", timing.get("completion") or "unknown"),
        ("Execution", f'{_fmt(timing.get("cpuSeconds"), 2)} s CPU · '
                      f'{_fmt(timing.get("elapsedSeconds"), 2)} s elapsed'),
        ("Diagnostics", f'{badge[0]} · {status["symmetryViolations"]} symmetry violations'),
        ("Restart file", meta.get("restartFile") or "—"),
    ]
    rows = [[Paragraph(f"<b>{_esc(k)}</b>", st["cell"]), Paragraph(_esc(v), st["cell"])]
            for k, v in facts]
    out.append(_table(rows, [45 * mm, 115 * mm], header=False, font=9))

    out.append(Spacer(1, 10 * mm))
    out.append(Paragraph(
        "Every figure in this report is read directly from the SIMULATE-3 output "
        "listing. Nothing is recomputed, interpolated or estimated.", st["small"]))
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out.append(Paragraph(
        f"Generated {generated} · {meta.get('lineCount')} lines, "
        f"{meta.get('pageCount')} listing pages", st["small"]))
    return out


def _toc(st) -> list:
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("toc0", fontName="Helvetica-Bold", fontSize=10, leading=17,
                       textColor=INK),
        ParagraphStyle("toc1", fontName="Helvetica", fontSize=9, leading=14,
                       leftIndent=12, textColor=MUTED),
    ]
    # Styled as a heading but deliberately NOT style "h1": afterFlowable keys
    # off the style name, so using h1 here would list "Contents" inside its own
    # table of contents.
    head = ParagraphStyle("tocHead", parent=st["h1"])
    return [Paragraph("Contents", head), Spacer(1, 3 * mm), toc]


def _core_map(payload, sp, code, st) -> list:
    values = sp["values"].get(code) or []
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums:
        return []
    lo, hi = min(nums), max(nums)
    n = payload["geometry"]["iafull"]

    index = {(a["row"], a["col"]): i for i, a in enumerate(payload["assemblies"])}
    letters: dict[int, str] = {}
    for a in payload["assemblies"]:
        letters.setdefault(a["col"], a["site"].split("-")[0])

    flagged = {(m["row"], m["col"]) for g in payload.get("symmetryGroups", [])
               for m in g["members"]}

    avail = PAGE[0] - 2 * MARGIN
    cw = min(11.2 * mm, (avail - 8 * mm) / n)
    head = [""] + [letters.get(c, str(c)) for c in range(1, n + 1)]
    data = [head]
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 5.2),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("FONTNAME", (1, 1), (-1, -1), "Helvetica-Bold"),
        ("GRID", (1, 1), (-1, -1), 0.2, colors.white),
    ]
    for r in range(1, n + 1):
        row = [str(r)]
        for c in range(1, n + 1):
            i = index.get((r, c))
            v = values[i] if i is not None and i < len(values) else None
            if i is None:
                row.append("")
                continue
            row.append(_fmt(v, 3) if isinstance(v, (int, float)) else _esc(v))
            fill, dark = _cell_colour(v if isinstance(v, (int, float)) else None, lo, hi)
            style.append(("BACKGROUND", (c, r), (c, r), fill))
            style.append(("TEXTCOLOR", (c, r), (c, r),
                          colors.white if dark else INK))
            if (r, c) in flagged:
                style.append(("BOX", (c, r), (c, r), 0.9, SEV["ERROR"]))
        data.append(row)

    t = Table(data, colWidths=[7 * mm] + [cw] * n,
              rowHeights=[5 * mm] + [cw * 0.62] * n, hAlign="LEFT")
    t.setStyle(TableStyle(style))

    legend = Table(
        [[""] * len(RAMP)], colWidths=[9 * mm] * len(RAMP), rowHeights=[3.2 * mm],
        hAlign="LEFT",
    )
    legend.setStyle(TableStyle(
        [("BACKGROUND", (i, 0), (i, 0), c) for i, c in enumerate(RAMP)]
        + [("BOX", (0, 0), (-1, -1), 0.25, LINE)]
    ))
    strip = Table(
        [[Paragraph(f'<font size=7 color="#6b7280">{_fmt(lo)}</font>', st["small"]),
          legend,
          Paragraph(f'<font size=7 color="#6b7280">{_fmt(hi)}</font>', st["small"])]],
        colWidths=[16 * mm, 9 * mm * len(RAMP) + 3 * mm, 24 * mm], hAlign="LEFT",
    )
    strip.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (1, 0), (1, 0), 3 * mm),  # keep the max label off the swatches
        ("LEFTPADDING", (2, 0), (2, 0), 0),
    ]))
    return [
        t,
        Spacer(1, 2.5 * mm),
        strip,
        Spacer(1, 1.5 * mm),
        Paragraph("Lighter is lower, darker is higher. Red outline marks an assembly "
                  "named in a symmetry-check violation.", st["small"]),
    ]


def _depletion_chart(payload, st, width, height=52 * mm):
    """Depletion progression drawn as a ReportLab Drawing."""
    from reportlab.graphics.shapes import Drawing, Line, PolyLine, String, Circle

    rows = payload.get("depletion") or []
    pts = [(r["cycleExposure"], r["keff"]) for r in rows if r.get("keff") is not None]
    if len(pts) < 2:
        return None

    ml, mb, mt, mr = 17 * mm, 9 * mm, 4 * mm, 3 * mm
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys + [1.0]), max(ys + [1.0])
    span = (y1 - y0) or 1
    y0, y1 = y0 - span * 0.12, y1 + span * 0.12

    def px(x):
        return ml + (x - x0) / ((x1 - x0) or 1) * (width - ml - mr)

    def py(y):
        return mb + (y - y0) / ((y1 - y0) or 1) * (height - mb - mt)

    d = Drawing(width, height)
    for frac in (0, 0.25, 0.5, 0.75, 1):
        tick = y0 + frac * (y1 - y0)
        y = py(tick)
        d.add(Line(ml, y, width - mr, y, strokeColor=LINE, strokeWidth=0.35))
        d.add(String(ml - 3, y - 2.2, f"{tick:.3f}", fontSize=5.6, fillColor=MUTED,
                     textAnchor="end"))
    if y0 < 1.0 < y1:
        d.add(Line(ml, py(1.0), width - mr, py(1.0), strokeColor=SEV["ERROR"],
                   strokeWidth=0.7, strokeDashArray=[3, 2]))
        d.add(String(width - mr, py(1.0) + 2, "k = 1.000", fontSize=5.6,
                     fillColor=SEV["ERROR"], textAnchor="end"))
    d.add(PolyLine([c for x, y in pts for c in (px(x), py(y))],
                   strokeColor=ACCENT, strokeWidth=1.1))
    for x, y in pts:
        d.add(Circle(px(x), py(y), 1.0, fillColor=ACCENT, strokeColor=None))
    for frac in (0, 0.5, 1):
        xv = x0 + frac * (x1 - x0)
        d.add(String(px(xv), mb - 6, f"{xv:.1f}", fontSize=5.6, fillColor=MUTED,
                     textAnchor="middle"))
    d.add(String(width / 2, 1.5, f'Cycle exposure ({payload["meta"].get("exposureUnit") or ""})',
                 fontSize=6, fillColor=MUTED, textAnchor="middle"))
    return d


def _axial_chart(sp, st, width, height=52 * mm):
    from reportlab.graphics.shapes import Drawing, Line, PolyLine, String, Circle

    nodes = ((sp.get("axialState") or {}).get("nodes")) or []
    pts = sorted((n["node"], n.get("RPF")) for n in nodes if n.get("RPF") is not None)
    if len(pts) < 2:
        return None
    ml, mb, mt, mr = 12 * mm, 9 * mm, 4 * mm, 4 * mm
    hi = max(v for _, v in pts) * 1.08
    kmax = max(k for k, _ in pts)

    def px(v):
        return ml + v / (hi or 1) * (width - ml - mr)

    def py(k):
        return mb + (k - 1) / ((kmax - 1) or 1) * (height - mb - mt)

    d = Drawing(width, height)
    for k, _ in pts:
        d.add(Line(ml, py(k), width - mr, py(k), strokeColor=LINE, strokeWidth=0.3))
        d.add(String(ml - 3, py(k) - 2, str(k), fontSize=5.4, fillColor=MUTED,
                     textAnchor="end"))
    d.add(PolyLine([c for k, v in pts for c in (px(v), py(k))],
                   strokeColor=colors.HexColor("#c9713f"), strokeWidth=1.2))
    for k, v in pts:
        d.add(Circle(px(v), py(k), 1.1, fillColor=colors.HexColor("#c9713f"),
                     strokeColor=None))
    d.add(String(width / 2, 1.5, "Relative power fraction (bottom → top)",
                 fontSize=6, fillColor=MUTED, textAnchor="middle"))
    return d


def build_pdf(payload: dict, step: int | None = None) -> bytes:
    """Render the full report and return the PDF bytes."""
    st = _styles()
    points = payload["statePoints"]
    sp = next((p for p in points if p["step"] == step), points[0]) if points else None
    meta, geom, status = payload["meta"], payload["geometry"], payload["status"]
    unit = meta.get("exposureUnit") or ""
    avail = PAGE[0] - 2 * MARGIN

    story: list = []
    story += _cover(payload, st)
    story.append(NextPageTemplate("body"))
    story.append(PageBreak())
    story += _toc(st)
    story.append(PageBreak())

    # ---- 1 Run summary
    story.append(Paragraph("1. Run summary", st["h1"]))
    depl = payload.get("depletion") or []
    burnups = [v for p in points for v in (p["values"].get("2EXP") or [])
               if isinstance(v, (int, float))]
    kpis = [
        ("State points", str(meta.get("stepCount"))),
        ("Assemblies", str(len(payload["assemblies"]))),
        ("Cycle length", f'{_fmt(meta.get("cycleEnd"), 2)} {unit}'),
        ("Peak burnup", f'{_fmt(max(burnups) if burnups else None, 2)}'),
        ("Peak pin power", _fmt(max((d["peak3pin"] for d in depl), default=None))),
        ("Peak radial", _fmt(max((d["peakRadial"] for d in depl), default=None))),
        ("Warnings", str(status["warnings"])),
        ("Symmetry viol.", str(status["symmetryViolations"])),
    ]
    kw = avail / 4
    kpi_rows = []
    for i in range(0, len(kpis), 4):
        chunk = kpis[i:i + 4]
        kpi_rows.append([Paragraph(v, st["kpiVal"]) for _, v in chunk]
                        + [""] * (4 - len(chunk)))
        kpi_rows.append([Paragraph(k.upper(), st["kpiKey"]) for k, _ in chunk]
                        + [""] * (4 - len(chunk)))
    kt = Table(kpi_rows, colWidths=[kw] * 4, hAlign="LEFT")
    kt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.4, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(kt)
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(
        f'The run terminated as <b>{_esc((meta.get("timing") or {}).get("completion") or "unknown")}</b>. '
        f'Core geometry is {geom["reactorType"]} {geom["iafull"]}×{geom["iafull"]}, '
        f'{geom["fraction"]}-core with {geom["symmetry"].lower()} symmetry, '
        f'{"3D over " + str(geom["fuelNodes"]) + " axial fuel nodes" if geom["is3d"] else "2D (single axial node)"}. '
        f'Values quoted below are taken verbatim from the listing.', st["body"]))

    # ---- 2 Core map
    if sp:
        code = "2RPF" if "2RPF" in sp["values"] else next(iter(sp["values"]), None)
        name = next((s["variable"]["name"] for s in payload["sections"]
                     if s.get("variable") and s["variable"]["code"] == code), code)
        story.append(Paragraph("2. Core map", st["h1"]))
        story.append(Paragraph(
            f'{_esc(name)} ({_esc(code)}) at step {sp["step"]} — '
            f'{_fmt(sp.get("exposure"), 3)} {_esc(sp.get("exposureUnit") or "")}, '
            f'k-effective {_fmt(sp.get("keff"), 5)}', st["h2"]))
        story += _core_map(payload, sp, code, st)

    # ---- 3 Depletion
    story.append(PageBreak())
    story.append(Paragraph("3. Depletion progression", st["h1"]))
    chart = _depletion_chart(payload, st, avail)
    if chart:
        story.append(chart)
        story.append(Spacer(1, 4 * mm))
    if depl:
        story.append(Paragraph("3.1 All state points", st["h2"]))
        head = ["Step", f"Cycle exp ({unit})", "k-eff", "Boron (ppm)", "Peak radial",
                "Peak nodal", "Peak 3-pin", "A-O", "Core exp (GWd/MT)"]
        rows = [head] + [[
            str(d["step"]), _fmt(d["cycleExposure"], 3), _fmt(d["keff"], 5),
            _fmt(d["boron"], 0), _fmt(d["peakRadial"], 3), _fmt(d["peakNodal"], 3),
            _fmt(d["peak3pin"], 3), _fmt(d["axialOffset"], 3),
            _fmt(d["coreExposure"], 3),
        ] for d in depl]
        w = avail / 9
        story.append(_table(rows, [w * 0.7] + [w * 1.2] + [w * 1.05] * 7,
                            [("ALIGN", (1, 1), (-1, -1), "RIGHT")]))

    # ---- 4 Axial
    if sp and geom["is3d"]:
        story.append(PageBreak())
        story.append(Paragraph("4. Axial distribution", st["h1"]))
        ax = _axial_chart(sp, st, avail * 0.55)
        if ax:
            story.append(ax)
            story.append(Spacer(1, 3 * mm))
        nodes = (sp.get("axialState") or {}).get("nodes") or []
        cols = (sp.get("axialState") or {}).get("columns") or []
        if nodes and cols:
            head = ["Node"] + cols
            rows = [head] + [[str(n["node"])] + [_fmt(n.get(c), 4) for c in cols]
                             for n in nodes]
            w = avail / (len(cols) + 1)
            story.append(_table(rows, [w] * (len(cols) + 1),
                                [("ALIGN", (1, 1), (-1, -1), "RIGHT")], font=7.2))

    # ---- 5 Inventory
    story.append(PageBreak())
    story.append(Paragraph("5. Core inventory", st["h1"]))
    inv = payload["inventory"]
    head = ["Fuel type", "Name", "Segment", "Enrichment (w/o U235)", "Assemblies",
            "Batch", "Fresh"]
    rows = [head] + [[
        _fmt(r["fuelType"], 0), _esc(r.get("typeName") or "—"),
        _fmt(r.get("segment"), 0), _fmt(r.get("enrichment"), 5),
        str(r["count"]), _esc(r.get("batchLabel") or "—"),
        "yes" if r["fresh"] else "no",
    ] for r in inv]
    rows.append(["", "", "", "TOTAL", str(sum(r["count"] for r in inv)), "", ""])
    w = avail / 7
    story.append(_table(rows, [w * 0.8, w * 1.3, w * 0.8, w * 1.3, w, w, w * 0.8],
                        [("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                         ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                         ("LINEABOVE", (0, -1), (-1, -1), 0.6, LINE)]))

    if payload.get("segments"):
        story.append(Paragraph("5.1 Fuel segments", st["h2"]))
        head = ["Seg", "Name", "Loading (g/cc)", "Enrichment (w/o)", "BP loading (g/cc)",
                "BP rods", "Equivalent assemblies"]
        rows = [head] + [[
            str(s["number"]), _esc(s["name"]), _fmt(s["loading"], 5),
            _fmt(s["enrichment"], 5), _fmt(s["bpLoading"], 3),
            _fmt(s["bpRods"], 0), _fmt(s["equivalentAssemblies"], 3),
        ] for s in payload["segments"]]
        w = avail / 7
        story.append(_table(rows, [w * 0.6, w * 1.4, w, w, w * 1.1, w * 0.8, w * 1.1],
                            [("ALIGN", (2, 1), (-1, -1), "RIGHT")]))
        story.append(Paragraph(
            "Equivalent assemblies is height-weighted: an assembly whose fuel segment "
            "spans 351 of 381 cm counts as 351/381 of an assembly, not as one.",
            st["small"]))

    # ---- 6 Diagnostics
    story.append(PageBreak())
    story.append(Paragraph("6. Diagnostics", st["h1"]))
    story.append(Paragraph(
        f'{status["errors"]} errors · {status["warnings"]} warnings · '
        f'{status["cautions"]} cautions · {status["notes"]} notes, '
        f'across {status["distinctLabels"]} distinct labels.', st["body"]))
    diags = payload["diagnostics"]
    if diags:
        head = ["Label", "Times", "Severity", "Where", "Message"]
        rows = [head]
        extra = []
        for i, d in enumerate(diags, start=1):
            rows.append([_esc(d["label"]), str(d["times"]), d["severity"],
                         _esc(d["where"]), Paragraph(_esc(d["info"]), st["cell"])])
            extra.append(("TEXTCOLOR", (2, i), (2, i), SEV.get(d["severity"], MUTED)))
        w = avail / 10
        story.append(_table(rows, [w * 1.5, w * 0.8, w * 1.3, w * 1.4, w * 5], extra))
    else:
        story.append(Paragraph("No diagnostics were reported.", st["small"]))

    groups = payload.get("symmetryGroups") or []
    if groups:
        story.append(Paragraph("6.1 Symmetry check — failing groups", st["h2"]))
        story.append(Paragraph(
            "Positions that should be equivalent under the declared core symmetry but "
            "are not. Compare the average and 2×2 quadrant exposures to see which "
            "position disagrees and by how much.", st["body"]))
        head = ["Group", "Tag", "(row, col)", "Label", "Fuel type", "Avg exposure",
                "2×2 quadrant exposures"]
        rows = [head]
        for g in groups:
            for m in g["members"]:
                rows.append([
                    _esc(g["group"]), _esc(m["tag"]), f'({m["row"]}, {m["col"]})',
                    _esc(m["label"]), _fmt(m["fuelType"], 0), _fmt(m["aveExp"], 3),
                    ", ".join(_fmt(q, 3) for q in m["quadrantExp"]),
                ])
        w = avail / 9
        story.append(_table(rows, [w * 0.8, w * 0.7, w * 1.2, w, w, w * 1.3, w * 3],
                            [("ALIGN", (4, 1), (-1, -1), "RIGHT")]))

    if payload.get("parseNotes"):
        story.append(Paragraph("6.2 Parse notes", st["h2"]))
        for note in payload["parseNotes"]:
            story.append(Paragraph(f"• {_esc(note)}", st["small"]))

    # ---- 7 Provenance
    story.append(Paragraph("7. Provenance", st["h1"]))
    timing = meta.get("timing") or {}
    facts = [
        ("Source file", meta.get("fileName")),
        ("Lines / listing pages", f'{meta.get("lineCount")} / {meta.get("pageCount")}'),
        ("Simulator version", meta.get("version")),
        ("Run started", f'{timing.get("startDate") or ""} {timing.get("startTime") or ""}'.strip()),
        ("Run ended", f'{timing.get("endDate") or ""} {timing.get("endTime") or ""}'.strip()),
        ("CPU / elapsed", f'{_fmt(timing.get("cpuSeconds"), 3)} s / '
                          f'{_fmt(timing.get("elapsedSeconds"), 3)} s'),
        ("Termination", timing.get("completion")),
        ("Restart file", meta.get("restartFile") or "—"),
    ]
    rows = [[Paragraph(f"<b>{_esc(k)}</b>", st["cell"]), Paragraph(_esc(v), st["cell"])]
            for k, v in facts]
    story.append(_table(rows, [50 * mm, avail - 50 * mm], header=False))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "This report was produced by an independent reader of SIMULATE-3 text output. "
        "Values are transcribed from the listing without recomputation.", st["small"]))

    buf = io.BytesIO()
    doc = _Doc(buf, payload,
               title=f'Core analysis — {meta.get("fileName") or "run"}',
               author="Vision: Nuclear Core Analysis",
               subject=meta.get("caseTitle") or "SIMULATE-3 core analysis")
    # multiBuild lays out twice so the table of contents can resolve page numbers.
    doc.multiBuild(story)
    return buf.getvalue()
