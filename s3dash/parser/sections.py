"""Section handlers: the thin layer that names what the primitives return.

Most edits need no code at all -- ``PRI.STA``, ``PIN.EDT`` and ``PRI.INP``
are dispatched generically by shape, so a variable this parser has never seen
still comes through. Only genuinely bespoke layouts (the symmetry-group
cards, the diagnostics roll-up, the depletion table, the input-card echo) get
a handler here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .textutil import as_float, tokenize

# --------------------------------------------------------------- diagnostics

_SEVERITY_ORDER = {"ERROR": 3, "WARNING": 2, "CAUTION": 1, "NOTE": 0}


@dataclass
class Diagnostic:
    label: str
    times: int
    severity: str
    where: str
    info: str
    line: int

    def to_json(self) -> dict:
        return {
            "label": self.label,
            "times": self.times,
            "severity": self.severity,
            "where": self.where,
            "info": self.info,
            "line": self.line,
        }


_DIAG_RE = re.compile(
    r"^\s*(?P<label>\S+(?:\s\S)?)\s+(?P<times>\d+)\s+"
    r"(?P<sev>ERROR|WARNING|CAUTION|NOTE)\s+(?P<where>\S+)\s+(?P<info>.*)$"
)
_DIAG_HDR_RE = re.compile(r"^\s*Label\s+Times\s+Degree\s+Where\s+Info\s*$")
_SEVERITIES = {"ERROR", "WARNING", "CAUTION", "NOTE"}


def parse_diagnostics(lines: list[str], start: int, end: int) -> list[Diagnostic]:
    """Parse the ``Summary of Errors/Warnings/Cautions and Notes`` table.

    This roll-up is the authoritative count for the whole run -- individual
    messages are printed many times, but each appears here once with its
    occurrence count. Duplicate rows (some builds echo the block twice) are
    collapsed on the full row identity.

    Columns are taken from the dashed rule under the heading rather than from
    whitespace, because both the label and the *Where* field legitimately
    contain a space (``SYMGRP F``, ``RES STEP``) and are wider than the dash
    group above them. Splitting on whitespace silently moves half of *Where*
    into *Info*.
    """
    cuts = _diag_columns(lines, start, end)
    seen: set[tuple] = set()
    out: list[Diagnostic] = []
    for i in range(start, end):
        fields = _diag_fields(lines[i], cuts)
        if fields is None:
            continue
        label, times, sev, where, info = fields
        key = (label, times, sev, where, info)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Diagnostic(label=label, times=times, severity=sev, where=where, info=info, line=i)
        )
    out.sort(key=lambda d: (-_SEVERITY_ORDER.get(d.severity, 0), d.label))
    return out


def _diag_columns(lines: list[str], start: int, end: int) -> list[int] | None:
    """Column start positions from the ``----- ----- ...`` rule, if present."""
    for i in range(start, end):
        if not _DIAG_HDR_RE.match(lines[i]) or i + 1 >= end:
            continue
        starts = [m.start() for m in re.finditer(r"-+", lines[i + 1])]
        if len(starts) >= 5:
            return [0] + starts[1:5]
    return None


def _diag_fields(line: str, cuts: list[int] | None) -> tuple[str, int, str, str, str] | None:
    """Split one roll-up row, preferring fixed columns over whitespace."""
    if cuts:
        edges = cuts + [len(line)]
        parts = [line[edges[k] : edges[k + 1]].strip() for k in range(5)]
        if parts[2] in _SEVERITIES and parts[1].isdigit() and parts[0]:
            return parts[0], int(parts[1]), parts[2], parts[3], parts[4]
        return None
    m = _DIAG_RE.match(line)
    if not m:
        return None
    return (
        m.group("label").strip(),
        int(m.group("times")),
        m.group("sev"),
        m.group("where").strip(),
        m.group("info").strip(),
    )


def overall_status(diags: list[Diagnostic]) -> str:
    """Reduce the diagnostics roll-up to one badge."""
    if any(d.severity == "ERROR" for d in diags):
        return "ERRORS"
    if any(d.severity == "WARNING" for d in diags):
        return "WARNINGS"
    return "OK"


# ---------------------------------------------------------- symmetry groups


@dataclass
class SymmetryMember:
    """One assembly card inside a ``SYMGRP`` violation block."""

    tag: str  # A0, A1, A2 ...
    row: int
    col: int
    label: str
    fue_typ: int | None = None
    fue_rot: int | None = None
    ave_exp: float | None = None
    quadrant_exp: list[float] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "tag": self.tag,
            "row": self.row,
            "col": self.col,
            "label": self.label,
            "fuelType": self.fue_typ,
            "rotation": self.fue_rot,
            "aveExp": self.ave_exp,
            "quadrantExp": self.quadrant_exp,
        }


@dataclass
class SymmetryGroup:
    group: str
    message: str
    members: list[SymmetryMember] = field(default_factory=list)
    line: int = 0

    def exp_spread(self) -> float | None:
        vals = [m.ave_exp for m in self.members if m.ave_exp is not None]
        return max(vals) - min(vals) if len(vals) > 1 else None

    def type_mismatch(self) -> bool:
        types = {m.fue_typ for m in self.members if m.fue_typ is not None}
        return len(types) > 1

    def to_json(self) -> dict:
        return {
            "group": self.group,
            "message": self.message,
            "members": [m.to_json() for m in self.members],
            "expSpread": self.exp_spread(),
            "typeMismatch": self.type_mismatch(),
            "line": self.line,
        }


_SYM_WARN_RE = re.compile(r"\*\*\s*\((?:Warning|Error)\)\s*-\s*SYMGRP\s+(?P<grp>\S+)\s*-\s*(?P<msg>.+)$")
_SYM_BOX_RE = re.compile(r"\|([^|]*)\|")
_SYM_HEAD_RE = re.compile(r"^\(\s*(?P<row>\d+),\s*(?P<col>\d+)\)\s*=\s*(?P<label>\S+)$")
_SYM_KV_RE = re.compile(r"^(?P<key>FUE\.ROT|FUE\.TYP|AVE EXP)\s*=\s*(?P<val>[-\d.]+)$")
_SYM_PAIR_RE = re.compile(r"^(?P<a>[-\d.]+)\s+(?P<b>[-\d.]+)$")
_SYM_TAG_RE = re.compile(r"^[A-Z]\d$")


def parse_symmetry_groups(lines: list[str], start: int, end: int) -> list[SymmetryGroup]:
    """Parse ``ERR.CHK - SYMGRP`` violation blocks.

    Each block prints two or three assembly "cards", one per symmetric
    position, carrying the 2x2 sub-assembly exposures, fuel type, rotation and
    average exposure. The cards are placed at the page column that mirrors the
    assembly's position in the core, so **two cards routinely share the same
    lines**::

        F1                                F2
        |( 9, 4)=C-03  |                  |( 9,14)=R-15  |
        |12.778   7.901|                  |12.778  17.735|

    Reading only the first ``|...|`` on each line loses the right-hand card
    entirely. Every box on a line is therefore collected with its column
    centre and routed to the card that occupies that column; the tag line
    above is matched to its card the same way.
    """
    groups: list[SymmetryGroup] = []
    current: SymmetryGroup | None = None
    open_cards: list[tuple[float, SymmetryMember]] = []
    pending_tags: list[tuple[float, str]] = []

    for i in range(start, end):
        line = lines[i]

        m = _SYM_WARN_RE.search(line)
        if m:
            grp = m.group("grp")
            if current is None or current.group != grp:
                current = SymmetryGroup(group=grp, message=m.group("msg").strip(), line=i)
                groups.append(current)
            open_cards = []
            pending_tags = []
            continue

        if current is None:
            continue

        boxes = _sym_boxes(line)
        if not boxes:
            # A bare tag line (one or more tags) introduces the next row of
            # cards; anything else with no box is not part of a card.
            tags = [(t.center, t.text) for t in tokenize(line) if _SYM_TAG_RE.match(t.text)]
            if tags and len(line.strip()) <= 40:
                pending_tags = tags
                open_cards = []
            continue

        for centre, text in boxes:
            head = _SYM_HEAD_RE.match(text)
            if head:
                tag = "?"
                if pending_tags:
                    tag = min(pending_tags, key=lambda t: abs(t[0] - centre))[1]
                member = SymmetryMember(
                    tag=tag,
                    row=int(head.group("row")),
                    col=int(head.group("col")),
                    label=head.group("label"),
                )
                current.members.append(member)
                open_cards.append((centre, member))
                continue
            if not open_cards:
                continue
            member = min(open_cards, key=lambda c: abs(c[0] - centre))[1]
            kv = _SYM_KV_RE.match(text)
            if kv:
                key, val = kv.group("key"), kv.group("val")
                if key == "FUE.ROT":
                    member.fue_rot = int(float(val))
                elif key == "FUE.TYP":
                    member.fue_typ = int(float(val))
                else:
                    member.ave_exp = as_float(val)
                continue
            pair = _SYM_PAIR_RE.match(text)
            if pair:
                for g in ("a", "b"):
                    v = as_float(pair.group(g))
                    if v is not None:
                        member.quadrant_exp.append(v)

    return [g for g in groups if g.members]


def _sym_boxes(line: str) -> list[tuple[float, str]]:
    """``(column centre, contents)`` for every ``|...|`` box on a line.

    Adjacent boxes share a ``|``, which a non-overlapping scan would skip, so
    the scan restarts on each closing bar.
    """
    out: list[tuple[float, str]] = []
    pos = 0
    while True:
        m = _SYM_BOX_RE.search(line, pos)
        if not m:
            break
        pos = m.end() - 1
        entry = ((m.start() + m.end()) / 2.0, m.group(1).strip())
        if entry not in out:
            out.append(entry)
    return out


# ------------------------------------------------------------ depletion table

_DEPL_ROW_RE = re.compile(
    r"^\s*(?P<case>\d+)\s+(?P<step>\d+)\s+(?P<exp>-?\d+\.\d+)\s+(?P<keff>\d+\.\d+)\s+"
    r"(?P<nq>\d+)\s+(?P<bor>-?\d+)\s+(?P<ax>[\d.]+)/\s*(?P<k>\d+)\s+"
    r"(?P<ao>-?[\d.]+)\s+(?P<rad>[\d.]+)\s+(?P<node>[\d.]+)\s+(?P<pin3>[\d.]+)\s+"
    r"(?P<dens>[\d.]+)\s+(?P<power>[\d.]+)\s+(?P<flow>[\d.]+)\s+(?P<crd>-?\d+)\s+"
    r"(?P<pres>\d+)\s+(?P<tin>[\d.]+)\s+(?P<coreexp>-?[\d.]+)"
)


def parse_depletion_table(lines: list[str], start: int, end: int) -> list[dict]:
    """Parse the end-of-run ``Summary of Steady-State`` depletion table.

    One row per state point with k-eff, boron, peak powers and exposures --
    the cleanest source for the depletion progression chart. Rows are
    deduplicated on ``(case, step)`` because some builds echo the block.
    """
    seen: set[tuple[int, int]] = set()
    rows: list[dict] = []
    for i in range(start, end):
        m = _DEPL_ROW_RE.match(lines[i])
        if not m:
            continue
        g = m.groupdict()
        key = (int(g["case"]), int(g["step"]))
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "case": key[0],
                "step": key[1],
                "cycleExposure": float(g["exp"]),
                "keff": float(g["keff"]),
                "nq": int(g["nq"]),
                "boron": float(g["bor"]),
                "axialPeak": float(g["ax"]),
                "axialPeakNode": int(g["k"]),
                "axialOffset": float(g["ao"]),
                "peakRadial": float(g["rad"]),
                "peakNodal": float(g["node"]),
                "peak3pin": float(g["pin3"]),
                "density": float(g["dens"]),
                "power": float(g["power"]),
                "flow": float(g["flow"]),
                "crdPosition": float(g["crd"]),
                "pressure": float(g["pres"]),
                "inletTemp": float(g["tin"]),
                "coreExposure": float(g["coreexp"]),
                "line": i,
            }
        )
    rows.sort(key=lambda r: (r["case"], r["step"]))
    return rows


# ------------------------------------------------------- axial distributions


# ------------------------------------------------- output-summary peak block

# The peak-power lines are the only Output Summary entries printed WITHOUT a
# dot leader, so the generic key/value scan never sees them and `peakNodal`
# comes out null on every state point. They are read here by name instead.
_PEAK_RE = re.compile(
    r"(?P<label>Peak Nodal Power|F-delta-H|Max-Fxy|Max-3PIN|Max-4PIN)"
    r"(?:\s*\(Location\))?\s+(?P<value>-?\d+\.\d+)\b"
)


def parse_summary_peaks(lines: list[str], start: int, end: int) -> dict[str, dict]:
    """Peak power entries from an ``Output Summary`` block.

    Returned in the same shape as the dot-leader entries so the caller can
    merge them into one ``summary`` mapping.
    """
    out: dict[str, dict] = {}
    for i in range(start, end):
        for m in _PEAK_RE.finditer(lines[i]):
            label = m.group("label")
            if label in out:
                continue
            val = as_float(m.group("value"))
            if val is None:
                continue
            out[label] = {"value": val, "code": None, "unit": None, "line": i}
    return out


# ------------------------------------------------------- axial distributions

_AXIAL_SUMMARY_ROWS = {"Ave", "A-O", "P**2", "Min", "Max"}


def parse_axial_table(lines: list[str], start: int, end: int) -> dict:
    """Parse an ``Average Axial Distributions`` block.

    Layout is a node index followed by one column per variable, printed top
    node first, with trailing ``Ave`` / ``A-O`` / ``P**2`` summary rows. In a
    2D case only the summary rows exist, which the caller renders as "no
    axial detail" rather than an empty chart.

    Two details make a naive read wrong:

    * The depletion block prints **more variables than fit the page width**,
      so it repeats the ``K ...`` header two or three times with further
      columns. Every sub-table is merged into one node row, otherwise two
      thirds of the depletion arguments are silently dropped.
    * Summary rows can be **sparse** -- ``P**2`` prints a single number under
      ``EXPO``, not under the first column. Rows whose value count differs
      from the column count are therefore placed by character position
      instead of being zipped left-to-right.
    """
    nodes: dict[int, dict] = {}
    summary: dict[str, dict[str, float | None]] = {}
    columns: list[str] = []

    header_idx: int | None = None
    sub_cols: list[str] = []
    sub_toks: list = []
    saw_data = False

    for i in range(start, end):
        line = lines[i]
        toks = tokenize(line)
        if not toks:
            continue
        if toks[0].text == "K" and len(toks) > 1 and _looks_like_axial_header(toks):
            # A new sub-table: same rows, further columns.
            if header_idx is not None and not saw_data:
                break
            header_idx = i
            sub_toks = toks[1:]
            sub_cols = [t.text for t in sub_toks]
            for c in sub_cols:
                if c not in columns:
                    columns.append(c)
            continue
        if header_idx is None:
            continue

        head = toks[0].text
        if head.isdigit():
            saw_data = True
            row = nodes.setdefault(int(head), {"node": int(head)})
            row.update(_axial_row(toks[1:], sub_cols, sub_toks))
        elif head in _AXIAL_SUMMARY_ROWS:
            saw_data = True
            summary.setdefault(head, {}).update(_axial_row(toks[1:], sub_cols, sub_toks))
        elif saw_data and not _is_page_furniture(line):
            break

    if header_idx is None:
        return {"columns": [], "nodes": [], "summary": {}}
    return {
        "columns": columns,
        "nodes": [nodes[k] for k in sorted(nodes)],
        "summary": summary,
    }


def _looks_like_axial_header(toks: list) -> bool:
    """True when a ``K ...`` line names variables rather than holding data."""
    return all(as_float(t.text) is None for t in toks[1:])


def _axial_row(value_toks: list, columns: list[str], header_toks: list) -> dict:
    """Map one row's values onto column names.

    A full row is zipped left-to-right, which is exact. A short row is placed
    by matching each value's right edge to the nearest column heading's right
    edge, because SIMULATE-3 leaves the missing columns blank rather than
    shifting the printed ones left.
    """
    vals = [as_float(t.text) for t in value_toks]
    if len(vals) == len(columns):
        return dict(zip(columns, vals))
    out: dict[str, float | None] = {}
    for tok, val in zip(value_toks, vals):
        best, best_d = None, 1e9
        for name, htok in zip(columns, header_toks):
            d = abs(htok.end - tok.end)
            if d < best_d:
                best, best_d = name, d
        if best is not None and best_d <= 6:
            out[best] = val
    return out


def _is_page_furniture(line: str) -> bool:
    """Page banners split a block in two; they are not the end of it."""
    s = line.strip()
    return bool(
        re.match(r"^\d?S\s?I\s?M\s?U\s?L\s?A\s?T\s?E", s)
        or s.startswith(("Run:", "Case ", "Cycle exposure"))
    )


# ------------------------------------------------------------- batch inventory

_BATCH_HDR_RE = re.compile(r"^\s*(?P<edit>[A-Z0-9]{3,5})\s+-\s+(?P<desc>.+?)\s{2,}SCALE")


def parse_batch_edits(lines: list[str], start: int, end: int) -> dict[str, list[dict]]:
    """Parse ``BAT.EDT`` blocks into ``{edit_name: [rows]}``.

    Each block reports, per batch, the assembly count and the maximum of one
    quantity with the assembly that attains it. ``CORE`` is the whole-core
    roll-up row and is kept so the UI can show it as a total.
    """
    out: dict[str, list[dict]] = {}
    edit: str | None = None
    for i in range(start, end):
        line = lines[i]
        m = _BATCH_HDR_RE.match(line)
        if m:
            edit = m.group("edit")
            out.setdefault(edit, [])
            continue
        if edit is None:
            continue
        toks = tokenize(line)
        if not toks:
            continue
        first = toks[0].text
        if not (first.isdigit() or first == "CORE"):
            continue
        nums = [t.text for t in toks]
        # Layout: number [name] assemblies value label serial (i, j, k)
        loc = re.search(r"\(\s*[\d,\s]+\)\s*$", line)
        try:
            if first == "CORE":
                assemblies, value = int(nums[1]), as_float(nums[2])
                name, label, serial = "CORE", nums[3], nums[4]
            elif len(nums) >= 7 and not nums[1].replace(".", "").isdigit():
                name = nums[1]
                assemblies, value = int(nums[2]), as_float(nums[3])
                label, serial = nums[4], nums[5]
            else:
                name = ""
                assemblies, value = int(nums[1]), as_float(nums[2])
                label, serial = nums[3], nums[4]
        except (ValueError, IndexError):
            continue
        out[edit].append(
            {
                "batch": first,
                "name": name,
                "assemblies": assemblies,
                "value": value,
                "label": label,
                "serial": serial,
                "location": loc.group(0).strip() if loc else None,
                "line": i,
            }
        )
    return {k: v for k, v in out.items() if v}
