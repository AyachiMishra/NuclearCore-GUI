"""Document layer: pages, state-point context, and the section index.

A SIMULATE-3 listing is a sequence of printer pages. Every page carries a
three-line banner that states which case and depletion step produced the text
below it. Recovering that banner is what lets every parsed number be
attributed to the right state point -- so this module runs before any
section-specific parsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .textutil import despace_heading

# ``1`` in column 1 is the Fortran form-feed carriage control that starts a page.
_PAGE_RE = re.compile(r"^.?S\s?I\s?M\s?U\s?L\s?A\s?T\s?E\s?-\s?3\b")
_PAGE_NO_RE = re.compile(r"\bPage\s+(\d+)\s*$")
_VERSION_RE = re.compile(r"\*\*\s*([0-9]+\.[0-9]+\.[0-9]+)\s")
_RUN_RE = re.compile(
    r"Run:\s*(?P<run>.*?)\s*\*\*\s*Project:\s*(?P<project>.*?)\s*\*\*"
    r"\s*Run Time:\s*(?P<time>[0-9.:]+)\.?\*\*\s*Date:\s*(?P<date>[0-9/]+)"
)
_PCT_RE = re.compile(r"([0-9.]+)%\s*Flow\s+([0-9.]+)%\s*Power")
_CASE_RE = re.compile(r"^\s*Case\s+(\d+)\s+Step\s+(\d+)\s?(?P<rest>.*)$")
_PPM_EXP_RE = re.compile(
    r"(?P<ppm>-?[0-9.]+)\s*ppm\s+(?P<exp>-?[0-9.]+)\s*(?P<unit>GWd/MT|GWd/ST|EFPD|EFPH|MWD/MT)",
    re.IGNORECASE,
)


@dataclass
class RunInfo:
    """Global metadata that identifies the run, taken from the page banner."""

    code: str = "SIMULATE-3"
    version: str | None = None
    run_name: str | None = None
    project: str | None = None
    run_time: str | None = None
    run_date: str | None = None
    percent_flow: float | None = None
    percent_power: float | None = None
    title: str | None = None
    source_file: str | None = None
    page_count: int = 0


@dataclass
class Page:
    """One printer page, with the state-point context declared in its banner."""

    index: int
    page_no: int | None
    start: int  # first line index of the banner
    body_start: int  # first line index after the banner
    end: int  # exclusive
    case: int | None = None
    step: int | None = None
    exposure: float | None = None
    exposure_unit: str | None = None
    boron_ppm: float | None = None
    title: str | None = None


@dataclass
class Section:
    """A contiguous, named region of the listing."""

    kind: str  # e.g. "pri.sta", "pri.inp", "pin.edt", "summary"
    name: str  # e.g. "2RPF", "FMAP", "Output Summary"
    label: str  # human-readable heading text
    start: int  # line index of the heading
    end: int  # exclusive
    case: int | None = None
    step: int | None = None
    page_no: int | None = None
    meta: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.name}"


# Anchor table. Each entry maps a regex over a *normalized* line to a
# (kind, name-extractor) pair. Adding support for a new edit is one row here --
# the layout primitives already know how to read the body.
_ANCHORS: list[tuple[str, re.Pattern[str], str]] = [
    ("pri.sta", re.compile(r"^PRI\.STA\s+(?P<name>[0-9A-Z][A-Z0-9+\-]{1,7})\s*-\s*(?P<desc>.+)$"), "name"),
    ("pri.inp", re.compile(r"^PRI\.INP\s*-\s*(?P<name>[A-Z]{3,5})\s*-\s*(?P<desc>.+)$"), "name"),
    ("pin.edt", re.compile(r"^PIN\.EDT\s+(?P<name>[0-9A-Z][A-Z0-9]{1,7})\s*-\s*(?P<desc>.+)$"), "name"),
    ("bat.edt", re.compile(r"^BAT\.EDT\s*-\s*ON\s*-\s*(?P<desc>Batch Edits.*)$"), "const:BAT.EDT"),
    ("err.chk", re.compile(r"^ERR\.CHK\s*-\s*(?P<name>[A-Z]+)\s*-\s*(?P<desc>.+)$"), "name"),
    ("err.chk", re.compile(r"^ERR\.CHK\s*-\s*(?P<desc>(?:Exposure|Sub-Assembly|Assembly)\b.+)$"), "const:EXPOSURES"),
    ("summary", re.compile(r"^(?P<desc>Output Summary\b.*)$"), "const:Output Summary"),
    ("summary", re.compile(r"^(?P<desc>Input Summary)\s*$"), "const:Input Summary"),
    ("summary", re.compile(r"^(?P<desc>Option Summary)\s*$"), "const:Option Summary"),
    ("summary", re.compile(r"^(?P<desc>Summary of Library Parameters)\s*$"), "const:Library Parameters"),
    ("summary", re.compile(r"^(?P<desc>Fueled Segments:?)\s*$"), "const:Fueled Segments"),
    ("summary", re.compile(r"^(?P<desc>Installed Dimension Limits:?)\s*$"), "const:Dimension Limits"),
    ("summary", re.compile(r"^(?P<desc>Assembly Physical Descriptions)\s*$"), "const:Assembly Descriptions"),
    ("axial", re.compile(r"^(?P<desc>Average Axial Distributions for State Point Variables)\s*$"), "const:Axial State"),
    ("axial", re.compile(r"^(?P<desc>Average Axial Distributions for Depletion Arguments)\s*$"), "const:Axial Depletion"),
    ("crd", re.compile(r"^(?P<desc>Control Rod Withdrawal Map.*)$"), "const:Control Rod Map"),
    ("input", re.compile(r"^-*(?P<desc>Listing of Input Cards.*)$"), "const:Input Cards"),
    ("diag", re.compile(r"^(?P<desc>Summary of Errors/Warnings/Cautions and Notes)\s*$"), "const:Diagnostics"),
    ("depletion", re.compile(r"^(?P<desc>[PB]WR\s+Summary of Steady-State.*)$"), "const:Depletion Table"),
    ("files", re.compile(r"^(?P<desc>Summary of File Activity)\s*$"), "const:File Activity"),
    ("timing", re.compile(r"^(?P<desc>Report on CPU Time.*)$"), "const:CPU Time"),
    ("ite", re.compile(r"^(?P<desc>ITE\s*-\s*QPANDA Flux solution.*)$"), "const:Flux Solution"),
]


class Document:
    """Parsed page/section structure of one SIMULATE-3 output file."""

    def __init__(self, lines: list[str], source_file: str | None = None):
        self.lines = lines
        self.run = RunInfo(source_file=source_file)
        self.pages: list[Page] = []
        self.sections: list[Section] = []
        self._page_of_line: list[int] = []
        self._segment_pages()
        self._index_sections()

    # ------------------------------------------------------------------ pages

    def _segment_pages(self) -> None:
        starts = [i for i, ln in enumerate(self.lines) if _PAGE_RE.match(ln.lstrip("\x0c"))]
        if not starts:
            # A file with no page banners is still usable as a single page.
            self.pages = [Page(index=0, page_no=None, start=0, body_start=0, end=len(self.lines))]
            self._build_line_map()
            return

        # Text before the first banner is preamble (the input-card listing).
        if starts[0] > 0:
            self.pages.append(
                Page(index=0, page_no=None, start=0, body_start=0, end=starts[0])
            )

        for n, s in enumerate(starts):
            end = starts[n + 1] if n + 1 < len(starts) else len(self.lines)
            page = Page(
                index=len(self.pages),
                page_no=self._page_no(self.lines[s]),
                start=s,
                body_start=min(s + 1, end),
                end=end,
            )
            self._read_banner(page)
            self.pages.append(page)

        self.run.page_count = sum(1 for p in self.pages if p.page_no is not None)
        self._build_line_map()
        self._forward_fill_context()

    @staticmethod
    def _page_no(line: str) -> int | None:
        m = _PAGE_NO_RE.search(line.rstrip())
        return int(m.group(1)) if m else None

    def _read_banner(self, page: Page) -> None:
        """Read the 2-3 banner lines that follow the page marker."""
        head = self.lines[page.start]
        if self.run.version is None:
            m = _VERSION_RE.search(head)
            if m:
                self.run.version = m.group(1)

        cursor = page.start + 1
        limit = min(page.start + 4, page.end)

        while cursor < limit:
            line = self.lines[cursor]
            if self.run.run_name is None:
                m = _RUN_RE.search(line)
                if m:
                    self.run.run_name = m.group("run").strip() or None
                    self.run.project = m.group("project").strip() or None
                    self.run.run_time = m.group("time").strip() or None
                    self.run.run_date = m.group("date").strip() or None
            if self.run.percent_flow is None:
                m = _PCT_RE.search(line)
                if m:
                    self.run.percent_flow = float(m.group(1))
                    self.run.percent_power = float(m.group(2))

            m = _CASE_RE.match(line)
            if m:
                page.case = int(m.group(1))
                page.step = int(m.group(2))
                rest = m.group("rest") or ""
                pe = _PPM_EXP_RE.search(rest)
                if pe:
                    page.boron_ppm = float(pe.group("ppm"))
                    page.exposure = float(pe.group("exp"))
                    page.exposure_unit = pe.group("unit")
                    title = rest[: pe.start()].strip()
                else:
                    title = rest.strip()
                page.title = title or None
                # The first substantive page title doubles as the case title.
                if title and self.run.title is None and len(title) > 8:
                    self.run.title = title
                page.body_start = cursor + 1
                return
            cursor += 1

        page.body_start = min(page.start + 3, page.end)

    def _build_line_map(self) -> None:
        self._page_of_line = [0] * len(self.lines)
        for p in self.pages:
            for i in range(p.start, p.end):
                self._page_of_line[i] = p.index

    def _forward_fill_context(self) -> None:
        """Pages without a Case/Step banner inherit the previous page's context."""
        last: tuple[int | None, int | None, float | None, str | None] = (None, None, None, None)
        for p in self.pages:
            if p.case is not None:
                last = (p.case, p.step, p.exposure, p.exposure_unit)
            else:
                p.case, p.step, p.exposure, p.exposure_unit = last

    def page_for_line(self, idx: int) -> Page:
        return self.pages[self._page_of_line[idx]] if self._page_of_line else self.pages[0]

    # --------------------------------------------------------------- sections

    def _index_sections(self) -> None:
        hits: list[Section] = []
        for i, raw in enumerate(self.lines):
            norm = despace_heading(raw).strip()
            if not norm:
                continue
            for kind, pattern, name_rule in _ANCHORS:
                m = pattern.match(norm)
                if not m:
                    continue
                if name_rule.startswith("const:"):
                    name = name_rule.split(":", 1)[1]
                else:
                    name = m.groupdict().get(name_rule) or name_rule
                page = self.page_for_line(i)
                desc = (m.groupdict().get("desc") or "").strip()
                hits.append(
                    Section(
                        kind=kind,
                        name=name,
                        label=desc or name,
                        start=i,
                        end=i + 1,
                        case=page.case,
                        step=page.step,
                        page_no=page.page_no,
                    )
                )
                break

        # A section runs until the next section heading. Page banners are not
        # terminators: wide maps legitimately continue across a page break.
        for n, sec in enumerate(hits):
            sec.end = hits[n + 1].start if n + 1 < len(hits) else len(self.lines)
        self.sections = hits

    def find(self, kind: str | None = None, name: str | None = None) -> list[Section]:
        return [
            s
            for s in self.sections
            if (kind is None or s.kind == kind) and (name is None or s.name == name)
        ]

    def text(self, sec: Section, max_lines: int | None = None) -> str:
        stop = sec.end if max_lines is None else min(sec.end, sec.start + max_lines)
        return "\n".join(self.lines[sec.start : stop])


def load(path: str | Path) -> Document:
    """Read a SIMULATE-3 listing from disk and build its Document."""
    p = Path(path)
    raw = p.read_text(encoding="latin-1", errors="replace")
    lines = [ln.rstrip("\r\n").replace("\x0c", "") for ln in raw.split("\n")]
    return Document(lines, source_file=p.name)


def load_text(raw: str, source_file: str | None = None) -> Document:
    """Build a Document from already-loaded text (used by the upload path)."""
    lines = [ln.rstrip("\r\n").replace("\x0c", "") for ln in raw.split("\n")]
    return Document(lines, source_file=source_file)
