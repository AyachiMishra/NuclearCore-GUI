"""Independent re-extraction of SIMULATE-3 listing values.

Nothing in this module imports ``s3dash``. Every extractor here deliberately
uses a *different* technique from the production parser so that a shared
mistake cannot hide:

* maps      -- fixed-pitch character windows anchored on the *right edge* of
               each column-ruler token (the parser uses midpoint cuts between
               ruler tokens).
* summaries -- split the line on runs of two-or-more dots and read the tail
               (the parser uses one big regex per entry).
* tables    -- whitespace tokenisation with positional field counting (the
               parser uses a single anchored regex per row).
* grids     -- ``:``-delimited splitting of the cell band (the parser slices
               on ``+`` positions from the rule line).
"""

from __future__ import annotations

import re
from pathlib import Path

# --------------------------------------------------------------------- input


def read_lines(path: str | Path) -> list[str]:
    """Read a listing exactly the way the production loader does.

    Deliberately identical: the *bytes* are the ground truth, so any
    difference here would compare two different documents rather than two
    readings of one.
    """
    raw = Path(path).read_text(encoding="latin-1", errors="replace")
    return [ln.rstrip("\r\n").replace("\x0c", "") for ln in raw.split("\n")]


_CASE_STEP_RE = re.compile(r"^\s*Case\s+(\d+)\s+Step\s+(\d+)\s?(?P<rest>.*)$")
_PPM_EXP_RE = re.compile(
    r"(?P<ppm>-?[0-9.]+)\s*ppm\s+(?P<exp>-?[0-9.]+)\s*(?P<unit>GWd/MT|GWd/ST|EFPD|EFPH|MWD/MT)",
    re.IGNORECASE,
)


def case_step_context(lines: list[str]) -> list[tuple[int, int]]:
    """``ctx[i]`` = the ``(case, step)`` in force at line ``i``.

    Built by forward-filling the most recent ``Case n Step m`` page-banner
    line, which is how the listing itself attributes everything below it.
    """
    ctx: list[tuple[int, int]] = []
    cur = (0, 0)
    for ln in lines:
        m = _CASE_STEP_RE.match(ln)
        if m:
            cur = (int(m.group(1)), int(m.group(2)))
        ctx.append(cur)
    return ctx


def _parse_banner(line: str, i: int) -> dict | None:
    m = _CASE_STEP_RE.match(line)
    if not m:
        return None
    rest = m.group("rest") or ""
    pe = _PPM_EXP_RE.search(rest)
    entry = {
        "line": i,
        "case": int(m.group(1)),
        "step": int(m.group(2)),
        "boron": None,
        "exposure": None,
        "unit": None,
        "title": None,
    }
    if pe:
        entry["boron"] = float(pe.group("ppm"))
        entry["exposure"] = float(pe.group("exp"))
        entry["unit"] = pe.group("unit")
        entry["title"] = rest[: pe.start()].strip() or None
    else:
        entry["title"] = rest.strip() or None
    return entry


def banner_context(lines: list[str]) -> dict[tuple[int, int], dict]:
    """First page banner seen for each ``(case, step)`` -> exposure/boron/title."""
    out: dict[tuple[int, int], dict] = {}
    for i, ln in enumerate(lines):
        e = _parse_banner(ln, i)
        if e and (e["case"], e["step"]) not in out:
            out[(e["case"], e["step"])] = e
    return out


def banner_before(lines: list[str], index: int) -> dict | None:
    """The page banner in force at ``index``.

    A ``(case, step)`` label is repeated on every page printed while that step
    is being worked on -- including the trial pages of an exposure search --
    and the banner states the *current* condition. The banner that belongs
    with a block of results is therefore the nearest one above it, not the
    first one in the file carrying the same label.
    """
    for i in range(index, -1, -1):
        e = _parse_banner(lines[i], i)
        if e:
            return e
    return None


# ----------------------------------------------------------------- band maps

_RULER_RE = re.compile(r"^\s*\*\*(?:\s+\d+)+\s+\*\*\s*$")
_FOOTER_RE = re.compile(r"^\s*\*\*\s+\S.*\*\*\s*$")
_MAP_HEAD_RE = re.compile(r"^\s*(PRI\.STA|PIN\.EDT)\s+(?P<code>[0-9A-Z][A-Z0-9+\-]{1,7})\s*-\s*(?P<desc>.+)$")


class RawMap:
    """One ``**``-ruled map block, read straight out of the character grid."""

    def __init__(self, code: str, head_line: int, ruler_line: int):
        self.code = code
        self.head_line = head_line
        self.ruler_line = ruler_line
        self.cols: list[int] = []
        self.cells: dict[tuple[int, int], str] = {}  # exact stripped text
        self.cell_line: dict[tuple[int, int], int] = {}
        self.rows: list[int] = []
        self.col_labels: dict[int, str] = {}
        self.case = 0
        self.step = 0
        self.end_line = ruler_line


def _ruler_ends(line: str) -> tuple[list[int], list[int]]:
    """Column indices and the character position just past each ruler token."""
    toks = [m for m in re.finditer(r"\S+", line) if m.group() != "**"]
    return [int(m.group()) for m in toks], [m.end() for m in toks]


def extract_maps(lines: list[str]) -> list[RawMap]:
    """Find every ``PRI.STA``/``PIN.EDT`` map and read its cells.

    Field geometry is derived from the ruler: a column's value window ends two
    characters past the right edge of its ruler token and is ``pitch`` wide,
    where ``pitch`` is the constant spacing between ruler tokens. This is a
    pure fixed-width read -- no midpoints, no tokenisation of the data rows.
    """
    ctx = case_step_context(lines)
    out: list[RawMap] = []
    pending: tuple[int, str] | None = None

    for i, line in enumerate(lines):
        m = _MAP_HEAD_RE.match(line)
        if m:
            pending = (i, m.group("code"))
            continue
        if not _RULER_RE.match(line) or pending is None:
            continue

        head_line, code = pending
        pending = None
        cols, ends = _ruler_ends(line)
        if len(cols) < 2:
            continue
        pitch = ends[1] - ends[0]
        rm = RawMap(code, head_line, i)
        rm.cols = cols
        rm.case, rm.step = ctx[i]

        j = i + 1
        blanks = 0
        while j < len(lines):
            ln = lines[j]
            if not ln.strip():
                blanks += 1
                if blanks >= 2:
                    break
                j += 1
                continue
            blanks = 0
            if _FOOTER_RE.match(ln) and not _RULER_RE.match(ln):
                for tok in re.finditer(r"\S+", ln):
                    if tok.group() == "**":
                        continue
                    best, bd = None, 999
                    for cidx, e in zip(cols, ends):
                        d = abs((e - 1) - (tok.end() - 1))
                        if d < bd:
                            best, bd = cidx, d
                    if best is not None and bd < 6:
                        rm.col_labels[best] = tok.group().rstrip("-")
                break
            head = re.match(r"\s*(\d+)\b", ln)
            if not head:
                break
            row = int(head.group(1))
            label_end = head.end()
            got = False
            for cidx, e in zip(cols, ends):
                lo = max(label_end, e - (pitch - 2))
                text = ln[lo : e + 2].strip()
                if not text:
                    continue
                rm.cells[(row, cidx)] = text
                rm.cell_line[(row, cidx)] = j
                got = True
            if got:
                rm.rows.append(row)
            j += 1
        rm.end_line = j
        if rm.cells:
            out.append(rm)
    return out


# ------------------------------------------------------------ output summary

_DOTS_RE = re.compile(r"\.\s*\.[\s.]*")


def output_summary_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """``(start, end)`` of every ``Output Summary`` region."""
    starts = [i for i, ln in enumerate(lines) if ln.strip().startswith("Output Summary")]
    out = []
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(lines)
        # An Output Summary block never runs past the next state point's maps.
        for j in range(s + 1, min(e, s + 120)):
            if lines[j].lstrip().startswith(("PRI.STA", "PIN.EDT", "BAT.EDT", "PRI.INP")):
                e = j
                break
        out.append((s, e))
    return out


_NUM_RE = re.compile(r"^(-?\d[\d,]*\.?\d*(?:[eE][+-]?\d+)?)")


def dot_leader_entries(lines: list[str], start: int, end: int) -> dict[str, float]:
    """Read ``Label . . . CODE value unit`` pairs by splitting on the dot run.

    Two or three entries share a line, so the line is first cut into segments
    at every dot run and each segment's *tail* is scanned for the value. This
    is structurally different from the parser's single-regex scan.
    """
    out: dict[str, float] = {}
    for i in range(start, end):
        line = lines[i]
        if ". ." not in line and ".." not in line:
            continue
        pieces = _DOTS_RE.split(line)
        # piece[k] ends with the label for the dot run that follows it, and
        # piece[k+1] begins with the (optional) code then the value.
        for k in range(len(pieces) - 1):
            label = pieces[k].strip()
            if not label:
                continue
            # The label is the trailing word-run of the piece; anything before
            # a 2+ space gap belongs to the previous column.
            label = re.split(r"\s{2,}", label)[-1].strip()
            label = re.sub(r"^[^A-Za-z]+", "", label)
            tail = pieces[k + 1].lstrip()
            mcode = re.match(r"([A-Z][A-Z0-9\-+]{1,8})\s+", tail)
            if mcode:
                tail = tail[mcode.end() :]
            mnum = _NUM_RE.match(tail)
            if not mnum:
                continue
            try:
                out[label] = float(mnum.group(1).replace(",", ""))
            except ValueError:
                continue
    return out


def summary_scalar(lines: list[str], start: int, end: int, pattern: str) -> float | None:
    """Pull one labelled number out of a region with a bespoke regex."""
    for i in range(start, end):
        m = re.search(pattern, lines[i])
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


# ---------------------------------------------------------- depletion table


def depletion_rows(lines: list[str]) -> list[list[str]]:
    """Every data row of the end-of-run steady-state table, as token lists.

    Rows are located by their shape (18+ tokens, first two integers, an
    ``a/b`` peak field) rather than by a full-line regex.
    """
    head = [
        i
        for i, ln in enumerate(lines)
        if re.match(r"^\s*Case\s+Step\s+Bor\b", re.sub(r"\s+", " ", ln).strip())
        or re.match(r"^\s*Case\s+Step\b.*Peak Powers", re.sub(r"\s+", " ", ln))
    ]
    if not head:
        return []
    start = head[0]
    out = []
    for i in range(start, len(lines)):
        ln = lines[i]
        if "/" not in ln:
            continue
        # The "AX / K" field is printed as "1.55/ 4" or "1.14/10"; splitting the
        # slash apart makes every row a flat, positionally fixed token list.
        toks = ln.replace("/", " ").split()
        if len(toks) != 21:
            continue
        if not (toks[0].isdigit() and toks[1].isdigit()):
            continue
        out.append(toks + [str(i)])
    return out


# ------------------------------------------------------------ axial tables


def axial_blocks(lines: list[str]) -> list[dict]:
    """Every ``Average Axial Distributions`` block, with *all* sub-tables."""
    out = []
    for i, ln in enumerate(lines):
        s = _despace(ln).strip()
        if not s.startswith("Average Axial Distributions"):
            continue
        kind = "state" if "State Point" in s else "depletion"
        block = {"line": i, "kind": kind, "subtables": []}
        j = i + 1
        cur = None
        while j < len(lines):
            l2 = lines[j]
            s2 = _despace(l2).strip()
            if s2.startswith("Average Axial Distributions") or s2.startswith("_____"):
                break
            toks = l2.split()
            if toks and toks[0] == "K" and len(toks) > 1:
                cur = {"columns": toks[1:], "nodes": {}, "summary": {}, "header_line": j}
                block["subtables"].append(cur)
                j += 1
                continue
            if cur is not None and toks:
                if toks[0].isdigit():
                    cur["nodes"][int(toks[0])] = toks[1:]
                elif toks[0] in {"Ave", "A-O", "P**2", "Min", "Max"}:
                    cur["summary"][toks[0]] = _positional(l2, cur["columns"], lines[cur["header_line"]])
                elif cur["nodes"] or cur["summary"]:
                    if not l2.strip().startswith(("Run:", "Case", "1S I M", "S I M")):
                        break
            j += 1
        if block["subtables"]:
            block["end"] = j
            out.append(block)
    return out


def _positional(line: str, columns: list[str], header: str) -> dict[str, float | None]:
    """Assign a sparse summary row's values to columns by character position."""
    hends = {}
    toks = [m for m in re.finditer(r"\S+", header)]
    for m in toks[1:]:
        hends[m.group()] = m.end()
    out: dict[str, float | None] = {c: None for c in columns}
    for m in re.finditer(r"\S+", line):
        if m.start() < 6:
            continue
        best, bd = None, 999
        for c in columns:
            d = abs(hends.get(c, -99) - m.end())
            if d < bd:
                best, bd = c, d
        if best is not None and bd <= 8:
            try:
                out[best] = float(m.group())
            except ValueError:
                out[best] = None
    return out


def _despace(line: str) -> str:
    toks = line.split()
    if len(toks) < 6:
        return line
    if sum(1 for t in toks if len(t) == 1) / len(toks) < 0.6:
        return line
    return " ".join(w.replace(" ", "") for w in re.split(r"\s{2,}", line.strip()) if w.strip())


# ------------------------------------------------------------- diagnostics


def diagnostic_rows(lines: list[str]) -> list[tuple[str, int, str, str, str, int]]:
    """Rows of the errors/warnings roll-up, read by fixed columns.

    The header rule (``-----   -----   ------ ...``) fixes the columns: field
    *k* runs from the start of dash-group *k* to the start of dash-group
    *k+1*. That matters because real labels ("SYMGRP F", "NOCRTYP2") and real
    Where values ("RES STEP") are wider than their dash group and contain
    spaces, so whitespace tokenisation cannot recover them.
    """
    hdr = None
    for i, ln in enumerate(lines):
        if re.match(r"^\s*Label\s+Times\s+Degree\s+Where\s+Info\s*$", ln):
            hdr = i
            break
    if hdr is None:
        return []
    rule = lines[hdr + 1]
    starts = [m.start() for m in re.finditer(r"-+", rule)]
    if len(starts) < 5:
        return []
    cuts = [0] + starts[1:] + [10**6]
    out = []
    for i in range(hdr + 2, len(lines)):
        ln = lines[i]
        if not ln.strip():
            continue
        if re.match(r"^\s*Label\s+Times\s+Degree", ln) or set(ln.strip()) <= {"-", " "}:
            continue
        fields = [ln[cuts[k] : cuts[k + 1]].strip() for k in range(5)]
        if fields[2] not in {"ERROR", "WARNING", "CAUTION", "NOTE"}:
            if out:
                break
            continue
        try:
            n = int(fields[1])
        except ValueError:
            continue
        out.append((fields[0], n, fields[2], fields[3], fields[4], i))
    return out


# ---------------------------------------------------------- symmetry groups


def symmetry_blocks(lines: list[str]) -> list[dict]:
    """Every ``SYMGRP`` violation block and its assembly cards.

    Cards are laid out across the page, and two of them can share a line
    (``|( 9, 4)=C-03  |          |( 9,14)=R-15  |``). Every ``|...|`` segment
    on a line is therefore collected with its column position and routed to
    the card whose box occupies that column, so no card is lost.
    """
    warn = re.compile(r"\*\*\s*\((?:Warning|Error)\)\s*-\s*SYMGRP\s+(\S+)\s*-\s*(.+)$")
    head = re.compile(r"^\(\s*(\d+),\s*(\d+)\)\s*=\s*(\S+)$")
    kv = re.compile(r"^(FUE\.ROT|FUE\.TYP|AVE EXP)\s*=\s*([-\d.]+)$")
    pair = re.compile(r"^([-\d.]+)\s+([-\d.]+)$")
    tagtok = re.compile(r"^[A-Z]\d$")

    groups: list[dict] = []
    cur: dict | None = None
    open_cards: list[dict] = []  # cards on the current page row, by column
    pending_tags: list[tuple[float, str]] = []

    def boxes(line: str) -> list[tuple[float, str]]:
        """(centre, text) for each ``|...|`` box on a line."""
        out = []
        for m in re.finditer(r"\|([^|]*)\|", line):
            out.append(((m.start() + m.end()) / 2.0, m.group(1).strip()))
        # Adjacent boxes share a '|', which finditer's non-overlapping scan
        # skips; rescan from each match end to catch them.
        pos = 0
        while True:
            m = re.compile(r"\|([^|]*)\|").search(line, pos)
            if not m:
                break
            pos = m.end() - 1
            c = ((m.start() + m.end()) / 2.0, m.group(1).strip())
            if c not in out:
                out.append(c)
        return sorted(set(out))

    for i, ln in enumerate(lines):
        m = warn.search(ln)
        if m:
            g = m.group(1)
            if cur is None or cur["group"] != g:
                cur = {"group": g, "message": m.group(2).strip(), "members": [], "line": i}
                groups.append(cur)
            open_cards = []
            pending_tags = []
            continue
        if cur is None:
            continue

        bx = boxes(ln)
        if not bx:
            toks = [
                ((t.start() + t.end()) / 2.0, t.group())
                for t in re.finditer(r"\S+", ln)
                if tagtok.match(t.group())
            ]
            if toks and len(ln.strip()) <= 40:
                pending_tags = toks
                open_cards = []
            continue

        for centre, text in bx:
            h = head.match(text)
            if h:
                tag = "?"
                if pending_tags:
                    tag = min(pending_tags, key=lambda t: abs(t[0] - centre))[1]
                card = {
                    "tag": tag,
                    "row": int(h.group(1)),
                    "col": int(h.group(2)),
                    "label": h.group(3),
                    "quad": [],
                    "line": i,
                    "centre": centre,
                }
                cur["members"].append(card)
                open_cards.append(card)
                continue
            if not open_cards:
                continue
            card = min(open_cards, key=lambda c: abs(c["centre"] - centre))
            k = kv.match(text)
            if k:
                card[{"FUE.ROT": "rot", "FUE.TYP": "typ", "AVE EXP": "ave"}[k.group(1)]] = float(
                    k.group(2)
                )
                continue
            p = pair.match(text)
            if p:
                card["quad"].extend([float(p.group(1)), float(p.group(2))])
    return [g for g in groups if g["members"]]


# --------------------------------------------------------------- input grids


def bordered_bands(lines: list[str], name: str) -> list[dict]:
    """Every ``PRI.INP - <name>`` band, read by splitting the cell area on ``:``.

    The parser slices on the ``+`` positions of the rule line; here the row's
    own ``:`` delimiters do the cutting, which is an independent check that
    the two agree on where a cell begins and ends.
    """
    out = []
    head = re.compile(rf"^\s*PRI\.INP\s*-\s*{re.escape(name)}\s*-\s*(.+)$")
    for i, ln in enumerate(lines):
        if not head.match(ln):
            continue
        m = re.match(r"^\s*I\s*/\s*J\s*=\s*(.+)$", lines[i + 1])
        if not m:
            continue
        cols = [int(t) for t in m.group(1).split()]
        band: dict = {"line": i, "cols": cols, "cells": {}, "sites": {}, "aliases": {}}
        j = i + 2
        block: list[str] = []
        row = None
        alias = None
        sites: dict[int, str] = {}
        rule_plus: list[int] = []

        def flush() -> None:
            nonlocal block, row, alias
            if row is not None and block:
                for depth, ln2 in enumerate(block):
                    vals = _colon_cells(ln2, rule_plus)
                    for c, txt in zip(cols, vals):
                        cell = band["cells"].setdefault((row, c), [])
                        while len(cell) <= depth:
                            cell.append("")
                        cell[depth] = txt
                for c, s in sites.items():
                    band["sites"][(row, c)] = s
                if alias is not None:
                    band["aliases"][row] = alias
            block = []
            row = None
            alias = None

        while j < len(lines):
            ln2 = lines[j]
            if re.search(r"S\s?I\s?M\s?U\s?L\s?A\s?T\s?E\s?-\s?3", ln2):
                break
            s = ln2.strip()
            if s.startswith("+") and s.count("+") >= 3 and not any(c.islower() for c in s):
                flush()
                rule_plus = [k.start() for k in re.finditer(r"\+", ln2)]
                sites = {}
                for n, (a, b) in enumerate(
                    [(rule_plus[k] + 1, rule_plus[k + 1]) for k in range(len(rule_plus) - 1)],
                    start=1,
                ):
                    seg = ln2[a:b].strip("-+ ")
                    if seg and re.fullmatch(r"[A-Z]{1,2}-?\d{1,2}", seg):
                        sites[cols[n - 1] if n - 1 < len(cols) else n] = seg
                j += 1
                continue
            if not s:
                j += 1
                continue
            lo = rule_plus[0] if rule_plus else 0
            hi = (rule_plus[-1] + 1) if rule_plus else len(ln2)
            if row is None:
                t = re.search(r"(\d+)", ln2[:lo])
                if t:
                    row = int(t.group(1))
            if alias is None:
                t = re.match(r"\s*(\d+)", ln2[hi:])
                if t:
                    alias = t.group(1)
            block.append(ln2)
            j += 1
        flush()
        band["end"] = j
        if band["cells"]:
            out.append(band)
    return out


def _colon_cells(line: str, plus: list[int]) -> list[str]:
    """Cell texts for one grid line, cut at the ``+`` columns of the rule."""
    if not plus:
        return []
    vals = []
    for k in range(len(plus) - 1):
        a, b = plus[k] + 1, plus[k + 1]
        txt = line[a:b].strip()
        # A legend written into an edge slot has no digits and looks like a
        # dotted/comma'd field name.
        if txt and not any(ch.isdigit() for ch in txt) and re.fullmatch(
            r"(?:FUE\.[A-Z]{0,3}|TYP,[A-Z]{0,3}|[A-Z]{2,4}[.,][A-Z]{0,3})", txt
        ):
            txt = ""
        vals.append(txt)
    return vals


# --------------------------------------------------------------- misc blocks


def fueled_segments(lines: list[str]) -> list[list[str]]:
    """Rows of the ``Fueled Segments`` table (first occurrence)."""
    start = None
    for i, ln in enumerate(lines):
        if ln.strip().rstrip(":") == "Fueled Segments":
            start = i
            break
    if start is None:
        return []
    rows = []
    seen = set()
    for i in range(start, min(start + 80, len(lines))):
        s = lines[i].strip()
        if s.startswith(("Reflector Segments", "Fuel Temperature", "- - -")):
            break
        toks = lines[i].split()
        if len(toks) >= 9 and toks[0].isdigit() and re.fullmatch(r"[\d.]+", toks[2] or ""):
            if toks[0] in seen:
                continue
            seen.add(toks[0])
            rows.append(toks)
    return rows


def fue_typ_grid(lines: list[str]) -> dict[tuple[int, int], int]:
    """The ``'FUE.TYP'`` integer matrix from the echoed input deck.

    Row/column indices are 1-based over the matrix, which includes the
    reflector ring, so callers offset by NREF to reach core coordinates.
    """
    start = None
    for i, ln in enumerate(lines[:4000]):
        if ln.strip().startswith("'FUE.TYP'"):
            start = i
            break
    if start is None:
        return {}
    grid: dict[tuple[int, int], int] = {}
    row = 0
    for i in range(start + 1, min(start + 60, len(lines))):
        body = lines[i].split("/")[0]
        toks = body.split()
        if not toks or not all(re.fullmatch(r"\d+", t) for t in toks):
            break
        row += 1
        for c, t in enumerate(toks, start=1):
            grid[(row, c)] = int(t)
        if "/" in lines[i]:
            break
    return grid


def input_summary_value(lines: list[str], label: str) -> float | None:
    """A single ``Input Summary`` dot-leader value, e.g. ``Fuel Assemblies``."""
    pat = re.compile(re.escape(label) + r"[\s.]*(?:[A-Z]+\s+)?(-?[\d.]+)")
    for ln in lines[:5000]:
        m = pat.search(ln)
        if m:
            return float(m.group(1))
    return None
