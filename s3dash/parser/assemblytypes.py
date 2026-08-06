"""Assembly type descriptions: the authoritative FUE.TYP -> segment mapping.

``FUE.TYP`` numbers and segment numbers are two different numbering systems.
They coincide in some decks and not in others, so deriving enrichment by
treating a fuel type as a segment number is wrong in general -- in BEAVRS it
silently attributes the wrong enrichment to most of the core.

The ``Assembly Physical Descriptions`` block states the mapping outright, and
also prints each type's assembly count, which is an independent cross-check on
the core map.

The block is printed as several records side by side, separated by ``|``, so
it is read column-first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .textutil import as_float

# Keys may begin with '#' ("# Assm in Core") and carry a unit in parentheses
# ("Loading (gram)"), so both must be allowed inside the key.
_FIELD_RE = re.compile(r"^\s*(?P<key>[A-Za-z#][A-Za-z.#()/ ]*?)\s*:\s*(?P<value>.*?)\s*$")
_SEGMENT_RE = re.compile(r"\*\s*Segment\s*:\s*(?P<num>\d+)\s*\*")
# The height printed *inside* a segment box is that segment's own thickness;
# the height on the box rule is the elevation of the boundary.
_BOX_HEIGHT_RE = re.compile(r"^\s*\*\s*(?P<cm>[\d.]+)\s*cm\s*\*\s*$")


@dataclass
class AssemblyType:
    """One entry from the Assembly Physical Descriptions block."""

    fuel_type: int
    name: str | None = None
    assembly_class: str | None = None
    mech_design: int | None = None
    loading_grams: float | None = None
    axial_zones: int | None = None
    count_in_core: float | None = None
    sub_types: list[int] = field(default_factory=list)
    segments: list[int] = field(default_factory=list)

    @property
    def is_fuel(self) -> bool:
        return (self.assembly_class or "").lower().startswith("fuel")

    segment_heights: dict[int, float] = field(default_factory=dict)

    @property
    def active_segment(self) -> int | None:
        """The segment of the active fuel zone.

        The axial stack lists reflectors and short end regions (axial blankets
        or cutbacks) alongside the fuel segment. The fuel segment is the one
        that occupies the most height -- a physical criterion that works
        whether the short region is a reflector, a blanket or a cutback, and
        regardless of how the segment is named.
        """
        if not self.segments:
            return None
        if self.segment_heights:
            return max(self.segment_heights, key=lambda s: self.segment_heights[s])
        counts: dict[int, int] = {}
        for seg in self.segments:
            counts[seg] = counts.get(seg, 0) + 1
        return max(counts, key=lambda s: (counts[s], s))

    def to_json(self) -> dict:
        return {
            "fuelType": self.fuel_type,
            "name": self.name,
            "class": self.assembly_class,
            "mechDesign": self.mech_design,
            "loadingGrams": self.loading_grams,
            "axialZones": self.axial_zones,
            "countInCore": self.count_in_core,
            "subTypes": self.sub_types,
            "segments": sorted(set(self.segments)),
            "segmentHeights": self.segment_heights,
            "activeSegment": self.active_segment,
            "isFuel": self.is_fuel,
        }


def parse_assembly_types(lines: list[str], start: int, end: int) -> list[AssemblyType]:
    """Parse the ``Assembly Physical Descriptions`` block.

    Records are laid out side by side and separated by ``|``; each vertical
    slice is one assembly type. The block repeats for as many groups as are
    needed to cover every type.
    """
    records: list[AssemblyType] = []
    column_state: dict[int, dict] = {}

    def flush() -> None:
        for slot in sorted(column_state):
            data = column_state[slot]
            ftype = data.get("fuel_type")
            if ftype is None:
                continue
            records.append(
                AssemblyType(
                    fuel_type=ftype,
                    name=data.get("name"),
                    assembly_class=data.get("class"),
                    mech_design=data.get("mech"),
                    loading_grams=data.get("loading"),
                    axial_zones=data.get("zones"),
                    count_in_core=data.get("count"),
                    sub_types=data.get("subs", []),
                    segments=data.get("segments", []),
                    segment_heights=data.get("heights", {}),
                )
            )
        column_state.clear()

    for i in range(start, end):
        line = lines[i]
        if "Assembly Physical Descriptions" in line or set(line.strip()) <= {"-"}:
            continue
        if "|" not in line and not line.strip():
            continue
        # The block runs over several pages, so page furniture is skipped
        # rather than treated as the end of the block.
        if _is_page_furniture(line):
            continue
        # The section extends to the next indexed heading, which can be well
        # past the end of this block -- the control rod descriptions that
        # follow use the same boxed layout, and their heights would otherwise
        # be attributed to the last assembly segment seen.
        if _is_new_heading(line):
            break

        cells = line.split("|")
        if line.strip().startswith("Assm. Name"):
            # A new group of records begins; emit whatever came before.
            flush()

        for slot, cell in enumerate(cells):
            if not cell.strip():
                continue
            data = column_state.setdefault(slot, {})

            m = _SEGMENT_RE.search(cell)
            if m:
                data.setdefault("segments", []).append(int(m.group("num")))
                continue

            # A height inside a box belongs to the segment named just above it.
            m = _BOX_HEIGHT_RE.match(cell)
            if m and data.get("segments"):
                height = as_float(m.group("cm"))
                if height is not None:
                    heights = data.setdefault("heights", {})
                    seg = data["segments"][-1]
                    heights[seg] = heights.get(seg, 0.0) + height
                continue

            field_match = _FIELD_RE.match(cell)
            if field_match:
                # "Assm. Name" and "Mech. Design" carry abbreviation dots that
                # are noise for matching; strip them all, then squash spaces.
                key = " ".join(field_match.group("key").replace(".", " ").split())
                value = field_match.group("value").strip()
                _assign(data, key, value)
                continue

    flush()

    # Later groups repeat nothing, but guard against duplicates anyway.
    seen: dict[int, AssemblyType] = {}
    for rec in records:
        seen.setdefault(rec.fuel_type, rec)
    return [seen[k] for k in sorted(seen)]


def _is_page_furniture(line: str) -> bool:
    """True for a page banner, run line or case line inside the block."""
    if re.search(r"S\s?I\s?M\s?U\s?L\s?A\s?T\s?E\s?-\s?3", line):
        return True
    stripped = line.lstrip()
    return stripped.startswith("Run:") or stripped.startswith("Case ")


def _is_new_heading(line: str) -> bool:
    """True for prose that starts a different block.

    Record lines always carry a ``|`` separator or sit inside a ``*`` box, so
    a bare line of words means this block has ended.
    """
    if "|" in line:
        return False
    stripped = line.strip()
    if not stripped or stripped.startswith("*") or stripped.startswith("_"):
        return False
    return any(ch.isalpha() for ch in stripped)


def _assign(data: dict, key: str, value: str) -> None:
    if key == "Assm Name":
        data["name"] = value or None
    elif key == "Assm Sub Type":
        nums = [int(n) for n in re.findall(r"\d+", value)]
        data.setdefault("subs", []).extend(nums)
    elif key == "Assm Class":
        data["class"] = value or None
    elif key == "Fuel Type":
        try:
            data["fuel_type"] = int(value)
        except ValueError:
            pass
    elif key == "Mech Design":
        try:
            data["mech"] = int(value)
        except ValueError:
            pass
    elif key.startswith("Loading"):
        data["loading"] = as_float(value.rstrip("."))
    elif key.startswith("# Axial Zone"):
        try:
            data["zones"] = int(value)
        except ValueError:
            pass
    elif key.startswith("# Assm"):
        data["count"] = as_float(value)


def segment_for_type(types: list[AssemblyType]) -> dict[int, int]:
    """``{fuel_type: segment_number}`` for the fuelled types only."""
    out: dict[int, int] = {}
    for t in types:
        if t.is_fuel:
            seg = t.active_segment
            if seg is not None:
                out[t.fuel_type] = seg
    return out


def count_for_type(types: list[AssemblyType]) -> dict[int, float]:
    """``{fuel_type: assemblies in core}`` as the listing states it."""
    return {
        t.fuel_type: t.count_in_core
        for t in types
        if t.is_fuel and t.count_in_core is not None
    }
