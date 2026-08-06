"""Core geometry: dimensions, symmetry, and fractional-core expansion.

Everything downstream is driven from here. A 17x17 quarter-core 2D PWR and a
15x15 full-core 3D PWR differ only in the values this module recovers, so the
map renderer and the analytics never need to special-case a plant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Column site letters, inboard-edge first. Standard PWR site naming skips I, O
# and Q (confusable with 1, 0 and 0). Verified against the column footers this
# parser reads back from the listing: a 17-wide core ends at T, a 15-wide at R.
_SITE_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"

# ``[\s.]*`` absorbs the dot leader; the capture must start at a digit so the
# leader's own dots are never mistaken for the value.
_DIM_FIELDS = {
    "iafull": r"Full Core Assembly Map Width[\s.]*IAFULL\s+(\d+)",
    "irmx": r"Control Rod Map Width[\s.]*IRMX\s+(\d+)",
    "ilmx": r"Detector Map Width[\s.]*ILMX\s+(\d+)",
    "ioffset": r"Offset Assemblies Flag[\s.]*IOFSET\s+(\d+)",
    "kd": r"Axial Nodes \(Incl\. Refl\.\)[\s.]*KD\s+(\d+)",
    "ihave": r"Core Fraction Flag[\s.]*IHAVE\s+(\d+)",
    "if2x2": r"Node Mesh per Assembly[\s.]*IF2X2\s+(\d+)",
    "nref": r"Reflector Layers[\s.]*NREF\s+(\d+)",
}

_FRACTION_RE = re.compile(r"Radial Core Fraction[\s.]*(\d[\d.]*)")
_SYMMETRY_RE = re.compile(r"Core Symmetry[\s.]*([A-Z]{3,})")
_NASSEM_RE = re.compile(r"Fuel Assemblies[\s.]*(\d[\d.]*)")
_DIMCARD_RE = re.compile(r"'DIM\.(PWR|BWR)'\s*,?\s*(\d+)")
_DIMCAL_RE = re.compile(r"'DIM\.CAL'\s*,?\s*([\d\s,]+)/")
_CORSYM_RE = re.compile(r"'COR\.SYM'\s*,?\s*'(\w+)'")

# IWANT on the DIM.CAL card -> geometric fraction actually calculated.
_FRACTION_BY_IHAVE = {1: 0.125, 2: 0.25, 3: 0.5, 4: 1.0}
_FRACTION_NAME = {1: "octant", 2: "quarter", 3: "half", 4: "full"}


@dataclass
class Geometry:
    """Resolved core geometry for one run."""

    reactor_type: str = "PWR"
    iafull: int = 0  # full-core assembly map width
    irmx: int | None = None
    ilmx: int | None = None
    ioffset: int = 0
    kd: int = 1  # axial nodes INCLUDING reflectors
    ihave: int = 4  # 1=octant 2=quarter 3=half 4=full
    if2x2: int = 1
    nref: int = 1
    radial_fraction: float | None = None
    symmetry: str = "ROTATIONAL"
    n_assemblies: int | None = None

    @property
    def fraction_name(self) -> str:
        return _FRACTION_NAME.get(self.ihave, "unknown")

    @property
    def is_full_core(self) -> bool:
        return self.ihave == 4

    @property
    def fuel_nodes(self) -> int:
        """Axial fuel nodes, excluding the top and bottom axial reflectors."""
        return max(1, self.kd - 2) if self.kd > 2 else self.kd

    @property
    def is_3d(self) -> bool:
        return self.fuel_nodes > 1

    def site_label(self, row: int, col: int) -> str:
        """Site name for a full-core position, e.g. ``H-08``.

        Columns are lettered outboard-to-inboard from the high-column edge,
        which is the convention the listing's own map footers use.
        """
        n = self.iafull
        if not (1 <= col <= n and 1 <= row <= n):
            return f"({row},{col})"
        letter = _SITE_LETTERS[n - col] if n - col < len(_SITE_LETTERS) else "?"
        return f"{letter}-{row:02d}"

    def to_json(self) -> dict:
        return {
            "reactorType": self.reactor_type,
            "iafull": self.iafull,
            "kd": self.kd,
            "fuelNodes": self.fuel_nodes,
            "is3d": self.is_3d,
            "ihave": self.ihave,
            "fraction": self.fraction_name,
            "radialFraction": self.radial_fraction,
            "if2x2": self.if2x2,
            "nref": self.nref,
            "symmetry": self.symmetry,
            "nAssemblies": self.n_assemblies,
            "isFullCore": self.is_full_core,
        }


def parse_geometry(lines: list[str], limit: int = 4000) -> Geometry:
    """Recover geometry from the listing.

    The echoed ``DIM.PWR and DIM.CAL Specify Calculation Dimensions`` block is
    authoritative because it reflects what SIMULATE-3 actually ran, including
    values inherited from a restart file rather than typed on a card. Input
    cards are used only to fill gaps.
    """
    geom = Geometry()
    window = lines[: min(len(lines), limit)]
    blob = "\n".join(window)

    # Raw cards first, so the echo block can override them field by field.
    # Doing it the other way round would need "was this defaulted?" tracking:
    # kd defaults to 1 and ihave to 4, both truthy, so a "did we get a value?"
    # test on the attribute cannot distinguish a default from a real read.
    m = _DIMCAL_RE.search(blob)
    if m:
        parts = [p for p in m.group(1).replace(",", " ").split() if p.isdigit()]
        if len(parts) > 0:
            geom.kd = int(parts[0])
        if len(parts) > 1:
            geom.ihave = int(parts[1])
        if len(parts) > 2:
            geom.if2x2 = int(parts[2])
        if len(parts) > 3:
            geom.nref = int(parts[3])

    for attr, pattern in _DIM_FIELDS.items():
        m = re.search(pattern, blob)
        if m:
            setattr(geom, attr, int(m.group(1)))

    m = _FRACTION_RE.search(blob)
    if m:
        geom.radial_fraction = float(m.group(1))
    m = _SYMMETRY_RE.search(blob)
    if m:
        geom.symmetry = m.group(1)
    m = _NASSEM_RE.search(blob)
    if m:
        geom.n_assemblies = int(float(m.group(1)))

    m = _DIMCARD_RE.search(blob)
    if m:
        geom.reactor_type = m.group(1)
        if not geom.iafull:
            geom.iafull = int(m.group(2))
    elif re.search(r"'DIM\.BWR'", blob):
        geom.reactor_type = "BWR"

    m = _CORSYM_RE.search(blob)
    if m:
        token = m.group(1).upper()
        geom.symmetry = {"ROT": "ROTATIONAL", "MIR": "MIRROR"}.get(token, token)

    if geom.radial_fraction is None:
        geom.radial_fraction = _FRACTION_BY_IHAVE.get(geom.ihave)

    return geom


# ------------------------------------------------------------------ expansion


def expand_to_full_core(
    cells: dict[tuple[int, int], float],
    geom: Geometry,
) -> dict[tuple[int, int], float]:
    """Expand a fractional-core map to full core using the declared symmetry.

    SIMULATE-3 prints quarter-core edits over the *lower-right* quadrant, i.e.
    rows and columns ``c..n`` where ``c`` is the centre index. Rotational
    symmetry maps a point to three images by successive 90 degree turns about
    the core centre; mirror symmetry reflects it across both mid-planes.

    Cells already present are never overwritten, so genuinely asymmetric input
    (the thing the SYMGRP check exists to find) is preserved rather than
    smoothed over.
    """
    n = geom.iafull
    if not n or geom.is_full_core or not cells:
        return dict(cells)

    out: dict[tuple[int, int], float] = dict(cells)
    for (r, c), v in cells.items():
        for rr, cc in _images(r, c, n, geom.symmetry, geom.ihave):
            out.setdefault((rr, cc), v)
    return out


def _images(r: int, c: int, n: int, symmetry: str, ihave: int) -> list[tuple[int, int]]:
    """All symmetric images of ``(r, c)`` in an ``n x n`` full-core map."""
    pts: set[tuple[int, int]] = set()

    if symmetry.startswith("ROT"):
        # 90 degree rotation about the centre of a 1..n grid.
        rr, cc = r, c
        for _ in range(3):
            rr, cc = cc, n + 1 - rr
            pts.add((rr, cc))
    else:
        pts.update({(r, n + 1 - c), (n + 1 - r, c), (n + 1 - r, n + 1 - c)})

    if ihave == 1:  # octant input additionally mirrors across the diagonal
        for rr, cc in list(pts) + [(r, c)]:
            pts.add((cc, rr))

    pts.discard((r, c))
    return sorted(pts)


def quarter_origin(geom: Geometry) -> int:
    """First row/column index of the printed fractional map."""
    if geom.is_full_core:
        return 1
    return (geom.iafull + 1) // 2
