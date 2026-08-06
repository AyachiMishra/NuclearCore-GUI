"""The echoed input deck: titles, fuel definitions, and raw card capture.

Input cards are the least reliable source of core layout -- they are
free-format, and their column meaning depends on card-specific rules. Where
SIMULATE-3 echoes the same information as a coordinate-explicit output edit
(``PRI.INP`` FMAP/CMAP), that edit is preferred. This module exists for the
metadata that appears nowhere else, and for showing the deck in the UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .textutil import as_float, tokenize

_CARD_RE = re.compile(r"^\s*'(?P<name>[A-Z][A-Z0-9]{2}(?:\.[A-Z0-9]{3})?)'\s*(?P<args>.*)$")
_QUOTED_RE = re.compile(r"'([^']*)'")


@dataclass
class FuelBatch:
    """A batch declared by ``FUE.NEW``: fresh fuel loaded this cycle."""

    label: str
    serial_base: str | None = None
    count: int | None = None
    fuel_type: int | None = None
    batch_number: int | None = None
    line: int = 0

    def to_json(self) -> dict:
        return {
            "label": self.label,
            "serialBase": self.serial_base,
            "count": self.count,
            "fuelType": self.fuel_type,
            "batchNumber": self.batch_number,
            "line": self.line,
        }


@dataclass
class SegmentSpec:
    """A fuel segment from the ``Fueled Segments`` table (enrichment, BP)."""

    number: int
    name: str
    loading: float | None = None
    enrichment: float | None = None
    plutonium: float | None = None
    bp_loading: float | None = None
    bp_rods: int | None = None
    bp_rods_original: int | None = None
    equivalent_assemblies: float | None = None

    def to_json(self) -> dict:
        return {
            "number": self.number,
            "name": self.name,
            "loading": self.loading,
            "enrichment": self.enrichment,
            "plutonium": self.plutonium,
            "bpLoading": self.bp_loading,
            "bpRods": self.bp_rods,
            "bpRodsOriginal": self.bp_rods_original,
            "equivalentAssemblies": self.equivalent_assemblies,
        }


@dataclass
class InputDeck:
    case_title: str | None = None
    project: str | None = None
    run_name: str | None = None
    restart_file: str | None = None
    restart_exposure: float | None = None
    batches: list[FuelBatch] = field(default_factory=list)
    batch_labels: dict[int, str] = field(default_factory=dict)
    fuel_type_grid: dict[tuple[int, int], int] = field(default_factory=dict)
    cards: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "caseTitle": self.case_title,
            "project": self.project,
            "runName": self.run_name,
            "restartFile": self.restart_file,
            "restartExposure": self.restart_exposure,
            "batches": [b.to_json() for b in self.batches],
            "batchLabels": self.batch_labels,
            "cards": self.cards,
        }


def parse_input_deck(lines: list[str], start: int, end: int) -> InputDeck:
    """Parse the ``Listing of Input Cards`` echo."""
    deck = InputDeck()
    counts: dict[str, int] = {}

    for i in range(start, end):
        line = lines[i]
        m = _CARD_RE.match(line)
        if not m:
            continue
        name = m.group("name")
        args = m.group("args").rstrip()
        counts[name] = counts.get(name, 0) + 1
        if len(deck.cards) < 4000:
            deck.cards.append({"card": name, "args": args.strip(), "line": i})

        quoted = _QUOTED_RE.findall(args)
        if name == "TIT.CAS" and quoted:
            deck.case_title = quoted[0].strip()
        elif name == "TIT.PRO" and quoted:
            deck.project = quoted[0].strip()
        elif name == "TIT.RUN" and quoted:
            deck.run_name = quoted[0].strip()
        elif name == "RES":
            if quoted:
                deck.restart_file = quoted[0].strip()
            nums = re.findall(r"([\d.]+)\s*/", args)
            if nums:
                deck.restart_exposure = as_float(nums[0])
        elif name == "FUE.NEW":
            deck.batches.append(_parse_fue_new(args, i))
        elif name == "BAT.LAB":
            toks = args.replace("/", " ").split()
            if toks and toks[0].isdigit() and quoted:
                deck.batch_labels[int(toks[0])] = quoted[0].strip()
        elif name == "FUE.TYP":
            grid = _parse_numeric_grid(lines, i, end)
            if grid:
                deck.fuel_type_grid = grid

    return deck


def _parse_fue_new(args: str, line: int) -> FuelBatch:
    """``'FUE.NEW', 'TP01', 'F-101', 56, 8, ,,3/`` -> a FuelBatch."""
    quoted = _QUOTED_RE.findall(args)
    label = quoted[0].strip() if quoted else "?"
    serial_base = quoted[1].strip() if len(quoted) > 1 else None
    tail = _QUOTED_RE.sub(" ", args).replace("/", " ")
    # Empty positional slots are meaningful, so split on commas, not whitespace.
    slots = [s.strip() for s in tail.split(",")]
    nums = [int(s) if s.isdigit() else None for s in slots]
    nums = [n for n in nums if n is not None] or []
    return FuelBatch(
        label=label,
        serial_base=serial_base,
        count=nums[0] if len(nums) > 0 else None,
        fuel_type=nums[1] if len(nums) > 1 else None,
        batch_number=nums[2] if len(nums) > 2 else None,
        line=line,
    )


def _parse_numeric_grid(lines: list[str], start: int, end: int) -> dict[tuple[int, int], int]:
    """Read the integer matrix that follows a map card such as ``FUE.TYP``.

    Rows are read in printed order starting at 1. The matrix includes the
    reflector ring, so callers offset by ``NREF`` to reach core coordinates.
    """
    grid: dict[tuple[int, int], int] = {}
    row = 0
    for i in range(start + 1, min(end, start + 60)):
        line = lines[i]
        if not line.strip():
            if grid:
                break
            continue
        if "'" in line:
            break
        toks = tokenize(line)
        vals = []
        for t in toks:
            if re.fullmatch(r"\d+", t.text):
                vals.append(int(t.text))
            elif t.text == "/":
                break
            else:
                vals = []
                break
        if not vals:
            break
        row += 1
        for c, v in enumerate(vals, start=1):
            grid[(row, c)] = v
    return grid


# ------------------------------------------------------------ segment table

# Columns that do not apply to a segment are printed as a run of dashes
# ("------"), not left blank -- a segment with no burnable poison shows dashes
# for both PU and BP loading. Requiring digits there drops those segments
# entirely, which quietly loses a large fraction of the core.
_NUM_OR_DASH = r"(?:[\d.]+|-{2,})"
_SEG_ROW_RE = re.compile(
    rf"^\s*(?P<num>\d+)\s+(?P<name>\S+)\s+(?P<loading>{_NUM_OR_DASH})\s+"
    rf"(?P<enr>{_NUM_OR_DASH})\s+(?P<pu>{_NUM_OR_DASH})\s+(?P<bp>{_NUM_OR_DASH})\s+"
    r"(?P<n1>\d+)\s+(?P<n2>\d+)\s+(?P<eq>[\d.]+)"
)


def parse_fueled_segments(lines: list[str], start: int, end: int) -> list[SegmentSpec]:
    """Parse the ``Fueled Segments`` table (enrichment and burnable poison)."""
    out: list[SegmentSpec] = []
    seen: set[int] = set()
    for i in range(start, end):
        m = _SEG_ROW_RE.match(lines[i])
        if not m:
            continue
        num = int(m.group("num"))
        if num in seen:
            continue
        seen.add(num)
        out.append(
            SegmentSpec(
                number=num,
                name=m.group("name"),
                loading=as_float(m.group("loading")),
                enrichment=as_float(m.group("enr")),
                plutonium=as_float(m.group("pu")),
                bp_loading=as_float(m.group("bp")),
                bp_rods=int(m.group("n1")),
                bp_rods_original=int(m.group("n2")),
                equivalent_assemblies=as_float(m.group("eq")),
            )
        )
    return out
