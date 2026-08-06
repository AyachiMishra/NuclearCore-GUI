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


def parse_diagnostics(lines: list[str], start: int, end: int) -> list[Diagnostic]:
    """Parse the ``Summary of Errors/Warnings/Cautions and Notes`` table.

    This roll-up is the authoritative count for the whole run -- individual
    messages are printed many times, but each appears here once with its
    occurrence count. Duplicate rows (some builds echo the block twice) are
    collapsed on the full row identity.
    """
    seen: set[tuple] = set()
    out: list[Diagnostic] = []
    for i in range(start, end):
        m = _DIAG_RE.match(lines[i])
        if not m:
            continue
        key = (m.group("label"), m.group("times"), m.group("sev"), m.group("where"))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Diagnostic(
                label=m.group("label").strip(),
                times=int(m.group("times")),
                severity=m.group("sev"),
                where=m.group("where").strip(),
                info=m.group("info").strip(),
                line=i,
            )
        )
    out.sort(key=lambda d: (-_SEVERITY_ORDER.get(d.severity, 0), d.label))
    return out


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
_SYM_TAG_RE = re.compile(r"^\s*([A-Z]\d)\s*$")
_SYM_HEAD_RE = re.compile(r"\|\s*\(\s*(?P<row>\d+),\s*(?P<col>\d+)\)\s*=\s*(?P<label>\S+?)\s*\|")
_SYM_KV_RE = re.compile(r"\|\s*(?P<key>FUE\.ROT|FUE\.TYP|AVE EXP)\s*=\s*(?P<val>[-\d.]+)\s*\|")
_SYM_PAIR_RE = re.compile(r"\|\s*(?P<a>[-\d.]+)\s+(?P<b>[-\d.]+)\s*\|")


def parse_symmetry_groups(lines: list[str], start: int, end: int) -> list[SymmetryGroup]:
    """Parse ``ERR.CHK - SYMGRP`` violation blocks.

    Each block prints two or three assembly "cards" laid out diagonally across
    the page, one per symmetric position, with the 2x2 sub-assembly exposures,
    fuel type, rotation and average exposure. Cards are matched by their
    ``(row,col)=LABEL`` header line and the tag printed above them.
    """
    groups: list[SymmetryGroup] = []
    current: SymmetryGroup | None = None
    pending_tag: str | None = None
    member: SymmetryMember | None = None

    def close_member() -> None:
        nonlocal member
        if member and current:
            current.members.append(member)
        member = None

    for i in range(start, end):
        line = lines[i]

        m = _SYM_WARN_RE.search(line)
        if m:
            close_member()
            grp = m.group("grp")
            if current is None or current.group != grp:
                current = SymmetryGroup(group=grp, message=m.group("msg").strip(), line=i)
                groups.append(current)
            continue

        if current is None:
            continue

        tag = _SYM_TAG_RE.match(line)
        if tag:
            pending_tag = tag.group(1)
            continue
        # Two cards can share a line; collect every tag on it.
        if "|" not in line and line.strip() and len(line.strip()) <= 24:
            tags = [t.text for t in tokenize(line) if re.fullmatch(r"[A-Z]\d", t.text)]
            if tags:
                pending_tag = tags[0]
                continue

        head = _SYM_HEAD_RE.search(line)
        if head:
            close_member()
            member = SymmetryMember(
                tag=pending_tag or "?",
                row=int(head.group("row")),
                col=int(head.group("col")),
                label=head.group("label"),
            )
            pending_tag = None
            continue

        if member is None:
            continue

        kv = _SYM_KV_RE.search(line)
        if kv:
            key, val = kv.group("key"), kv.group("val")
            if key == "FUE.ROT":
                member.fue_rot = int(float(val))
            elif key == "FUE.TYP":
                member.fue_typ = int(float(val))
            else:
                member.ave_exp = as_float(val)
            continue

        pair = _SYM_PAIR_RE.search(line)
        if pair:
            for g in ("a", "b"):
                v = as_float(pair.group(g))
                if v is not None:
                    member.quadrant_exp.append(v)

    close_member()
    return [g for g in groups if g.members]


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


def parse_axial_table(lines: list[str], start: int, end: int) -> dict:
    """Parse an ``Average Axial Distributions`` block.

    Layout is a node index followed by one column per variable, printed top
    node first, with trailing ``Ave`` / ``A-O`` / ``P**2`` summary rows. In a
    2D case only the summary rows exist, which the caller renders as "no
    axial detail" rather than an empty chart.
    """
    header_idx = None
    columns: list[str] = []
    for i in range(start, min(end, start + 8)):
        toks = tokenize(lines[i])
        if toks and toks[0].text == "K" and len(toks) > 1:
            header_idx = i
            columns = [t.text for t in toks[1:]]
            break
    if header_idx is None:
        return {"columns": [], "nodes": [], "summary": {}}

    nodes: list[dict] = []
    summary: dict[str, dict[str, float | None]] = {}
    for i in range(header_idx + 1, end):
        line = lines[i]
        if not line.strip():
            continue
        toks = tokenize(line)
        if not toks:
            continue
        head = toks[0].text
        vals = [as_float(t.text) for t in toks[1:]]
        if head.isdigit():
            nodes.append({"node": int(head), **dict(zip(columns, vals))})
        elif head in {"Ave", "A-O", "P**2", "Min", "Max"}:
            summary[head] = dict(zip(columns, vals))
        elif nodes or summary:
            break

    nodes.sort(key=lambda n: n["node"])
    return {"columns": columns, "nodes": nodes, "summary": summary}


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
