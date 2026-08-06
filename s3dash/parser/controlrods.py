"""Control rod withdrawal maps and run timing.

The rod map uses an ``IR/JR =`` ruler rather than the ``**`` ruler the state
variable maps use, and its cells are either a step count or ``--`` meaning
fully withdrawn. It is otherwise the same banded shape, so the same
column-cut arithmetic applies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .textutil import Token, as_float, column_cuts, slice_fields, tokenize

_RULER_RE = re.compile(r"^\s*I[RL]?\s*/\s*J[RL]?\s*=\s*(?P<cols>.+)$")
_WITHDRAWN_RE = re.compile(r"--\s*Indicates fully withdrawn to\s*(?P<steps>[\d.]+)\s*Steps")
_TOTAL_RE = re.compile(r"Total control rod positions withdrawn in full core\s*=\s*(?P<n>\d+)")
_BANNER_RE = re.compile(r"S\s?I\s?M\s?U\s?L\s?A\s?T\s?E\s?-\s?3")


@dataclass
class ControlRodMap:
    """Rod insertion by control-rod-drive location.

    ``inserted`` holds the step count at each location where a rod is
    partially or fully inserted. Fully withdrawn locations are recorded in
    ``withdrawn`` rather than as a number, because "withdrawn" and "inserted
    zero steps" are printed differently and mean different things.
    """

    inserted: dict[tuple[int, int], float] = field(default_factory=dict)
    withdrawn: set[tuple[int, int]] = field(default_factory=set)
    rows: list[int] = field(default_factory=list)
    cols: list[int] = field(default_factory=list)
    full_withdrawal_steps: float | None = None
    total_withdrawn: int | None = None
    note: str | None = None

    @property
    def any_inserted(self) -> bool:
        return bool(self.inserted)

    def to_json(self) -> dict:
        return {
            "inserted": [
                {"row": r, "col": c, "steps": v} for (r, c), v in sorted(self.inserted.items())
            ],
            "withdrawn": [{"row": r, "col": c} for r, c in sorted(self.withdrawn)],
            "rows": self.rows,
            "cols": self.cols,
            "fullWithdrawalSteps": self.full_withdrawal_steps,
            "totalWithdrawn": self.total_withdrawn,
            "anyInserted": self.any_inserted,
            "note": self.note,
        }


def parse_control_rod_map(lines: list[str], start: int, end: int) -> ControlRodMap | None:
    """Parse a ``Control Rod Withdrawal Map`` block."""
    result = ControlRodMap()

    ruler_idx = None
    for i in range(start, min(end, start + 10)):
        line = lines[i]
        m = _WITHDRAWN_RE.search(line)
        if m:
            result.full_withdrawal_steps = as_float(m.group("steps"))
        if "CRD positions defined by" in line:
            result.note = line.strip()
        if _RULER_RE.match(line):
            ruler_idx = i
            break
    if ruler_idx is None:
        return None

    header = lines[ruler_idx]
    match = _RULER_RE.match(header)
    # Offset from the group's real start, not from "=": the pattern's \s* eats
    # the gap after "=", so anchoring there would shift every column left.
    offset = match.start("cols")
    header_tokens = [
        Token(t.text, t.start + offset, t.end + offset) for t in tokenize(match.group("cols"))
    ]
    try:
        col_indices = [int(t.text) for t in header_tokens]
    except ValueError:
        return None

    cuts = column_cuts(header_tokens)
    result.cols = col_indices

    blanks = 0
    for i in range(ruler_idx + 1, end):
        line = lines[i]
        if _BANNER_RE.search(line):
            break
        m = _TOTAL_RE.search(line)
        if m:
            result.total_withdrawn = int(m.group("n"))
            break
        if not line.strip():
            blanks += 1
            # Rows are printed in groups separated by a blank line, so only a
            # long gap ends the map.
            if blanks >= 3 and result.rows:
                break
            continue
        blanks = 0

        toks = tokenize(line)
        if not toks or not toks[0].text.isdigit():
            if result.rows:
                break
            continue
        row = int(toks[0].text)
        fields = slice_fields(line, cuts, data_start=toks[0].end)
        got = False
        for col, text in zip(col_indices, fields):
            if not text:
                continue
            got = True
            if set(text) <= {"-"}:
                result.withdrawn.add((row, col))
            else:
                value = as_float(text)
                if value is not None:
                    result.inserted[(row, col)] = value
        if got:
            result.rows.append(row)

    result.rows = sorted(set(result.rows))
    return result if (result.rows or result.total_withdrawn is not None) else None


# ------------------------------------------------------------------- timing

_TIMING_FIELDS = {
    "cpuSeconds": re.compile(r"Total CPU Time\s+([\d.]+)\s*Seconds"),
    "elapsedSeconds": re.compile(r"Elapsed Real Time\s+([\d.]+)\s*Seconds"),
    "cpuUtilisation": re.compile(r"CPU Utilization\s+([\d.]+)\s*%"),
    "containerWords": re.compile(r"Maximum Container Usage:\s*(\d+)\s*words", re.IGNORECASE),
}
_START_RE = re.compile(r"Start Time/Date\s+(\S+)\s+(\S+)")
_END_RE = re.compile(r"End\s+Time/Date\s+(\S+)\s+(\S+)")
_COMPLETION_RE = re.compile(r"SIMULATE Run Completed\s*-\s*(.+)$")


def parse_timing(lines: list[str], start: int, end: int) -> dict:
    """Parse the closing CPU-time report and completion status.

    Also scans to the very end of the file for the termination banner, which
    is printed after the timing block and tells the user whether the run
    finished normally.
    """
    out: dict = {}
    for i in range(start, end):
        line = lines[i]
        for key, pattern in _TIMING_FIELDS.items():
            if key in out:
                continue
            m = pattern.search(line)
            if m:
                out[key] = float(m.group(1)) if "." in m.group(1) or key.endswith(
                    ("Seconds", "Utilisation")
                ) else int(m.group(1))
        m = _START_RE.search(line)
        if m:
            out["startTime"], out["startDate"] = m.group(1), m.group(2)
        m = _END_RE.search(line)
        if m:
            out["endTime"], out["endDate"] = m.group(1), m.group(2)
        m = _COMPLETION_RE.search(line)
        if m:
            out["completion"] = m.group(1).strip()
    return out


def parse_subroutine_timing(lines: list[str], start: int, end: int) -> list[dict]:
    """Parse the per-subroutine CPU breakdown table."""
    rows: list[dict] = []
    pattern = re.compile(
        r"^\s*(?P<name>[A-Z][A-Z0-9_]{2,})\s+(?P<cpu>[\d.]+)\s+(?P<pct>[\d.]+)\s+"
        r"(?P<calls>[\d.]+)\s+(?P<per>[\d.]+)\s*$"
    )
    for i in range(start, end):
        m = pattern.match(lines[i])
        if m:
            rows.append(
                {
                    "subroutine": m.group("name"),
                    "cpuSeconds": float(m.group("cpu")),
                    "percent": float(m.group("pct")),
                    "calls": float(m.group("calls")),
                    "msPerCall": float(m.group("per")),
                }
            )
    return rows
