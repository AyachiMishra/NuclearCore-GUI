"""Layout primitives: the handful of physical shapes SIMULATE-3 prints.

Generality comes from here. Every ``PRI.STA`` variable, every ``PIN.EDT``
map, present and future, is the same *banded map* shape; every ``PRI.INP``
map is the same *bordered grid*. Section handlers only need to say which
primitive to run and what to call the result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .textutil import Token, as_float, column_cuts, slice_fields, tokenize

_RULE_RE = re.compile(r"^[\s\-_+|]*$")


@dataclass
class BandedMap:
    """A 2D core map keyed by ``(row, col)`` integer coordinates.

    ``values`` holds parsed floats where the cell was numeric; ``raw`` always
    holds the original text so non-numeric maps (e.g. ``PIN.EDT 2PLO`` pin
    locations like ``17, 9``) survive intact.
    """

    values: dict[tuple[int, int], float] = field(default_factory=dict)
    raw: dict[tuple[int, int], str] = field(default_factory=dict)
    col_labels: dict[int, str] = field(default_factory=dict)
    row_labels: dict[int, str] = field(default_factory=dict)
    rows: list[int] = field(default_factory=list)
    cols: list[int] = field(default_factory=list)
    numeric: bool = True
    plane: int | None = None
    renorm: float | None = None

    def bounds(self) -> tuple[float, float] | None:
        if not self.values:
            return None
        vals = list(self.values.values())
        return min(vals), max(vals)

    def merge(self, other: "BandedMap") -> "BandedMap":
        """Stitch a continuation band (wide cores split across pages)."""
        self.values.update(other.values)
        self.raw.update(other.raw)
        self.col_labels.update(other.col_labels)
        self.row_labels.update(other.row_labels)
        self.rows = sorted(set(self.rows) | set(other.rows))
        self.cols = sorted(set(self.cols) | set(other.cols))
        self.numeric = self.numeric and other.numeric
        return self

    def to_json(self) -> dict:
        return {
            "cells": [
                {"row": r, "col": c, "value": self.values.get((r, c)), "text": t}
                for (r, c), t in sorted(self.raw.items())
            ],
            "rows": self.rows,
            "cols": self.cols,
            "colLabels": self.col_labels,
            "numeric": self.numeric,
            "plane": self.plane,
            "renorm": self.renorm,
        }


def _is_ruler(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("**") and stripped.endswith("**")


def parse_banded_map(lines: list[str], start: int, end: int) -> BandedMap | None:
    """Parse a ``**``-ruled 2D map starting at or after ``start``.

    Layout::

        **    9     10    ...    17     **     <- column ruler (numeric indices)
         9  1.155  0.831  ...  0.947   09      <- row index, values, row index
        **   J-     H-    ...    A-     **     <- column site labels

    Fields are cut at the midpoints between ruler tokens, which is what makes
    ragged full-core rows (BEAVRS) and space-containing cells (``17, 9``)
    parse correctly. Whitespace tokenisation would misalign both.
    """
    ruler_idx = None
    for i in range(start, min(end, start + 12)):
        if _is_ruler(lines[i]):
            ruler_idx = i
            break
    if ruler_idx is None:
        return None

    header = lines[ruler_idx]
    header_tokens = [t for t in tokenize(header) if t.text != "**"]
    if len(header_tokens) < 2:
        return None
    try:
        col_indices = [int(t.text) for t in header_tokens]
    except ValueError:
        return None

    cuts = column_cuts(header_tokens)
    result = BandedMap(cols=col_indices)

    # Optional metadata line above the ruler (PIN.EDT prints Renorm/Axial Plane).
    for j in range(max(start, ruler_idx - 3), ruler_idx):
        m = re.search(r"Axial Plane\s*=\s*(\d+)", lines[j])
        if m:
            result.plane = int(m.group(1))
        m = re.search(r"Renorm\s*=\s*([0-9.E+-]+)", lines[j])
        if m:
            result.renorm = as_float(m.group(1))

    for i in range(ruler_idx + 1, end):
        line = lines[i]
        if not line.strip():
            # A blank line inside a map is padding; two in a row ends it.
            if i + 1 < end and not lines[i + 1].strip():
                break
            continue
        if _is_ruler(line):
            # Footer ruler: site labels for each column, then the map is done.
            labels = [t for t in tokenize(line) if t.text != "**"]
            for tok in labels:
                best = _nearest_column(tok, header_tokens, col_indices)
                if best is not None:
                    result.col_labels[best] = tok.text.rstrip("-")
            break

        toks = tokenize(line)
        if not toks:
            continue
        try:
            row_index = int(toks[0].text)
        except ValueError:
            # Not a data row (page banner, heading, note) -- stop cleanly.
            if toks[0].start < 2 and len(toks) > 2:
                break
            continue

        data_start = toks[0].end
        fields = slice_fields(line, cuts, data_start=data_start)
        got_any = False
        for col, text in zip(col_indices, fields):
            if not text:
                continue
            result.raw[(row_index, col)] = text
            val = as_float(text)
            if val is None:
                result.numeric = False
            else:
                result.values[(row_index, col)] = val
            got_any = True
        if got_any:
            result.rows.append(row_index)

    result.rows = sorted(set(result.rows))
    return result if result.raw else None


def _nearest_column(tok: Token, header_tokens: list[Token], col_indices: list[int]) -> int | None:
    """Map a footer-label token to the column index it sits under."""
    best, best_d = None, 1e9
    for h, col in zip(header_tokens, col_indices):
        d = abs(h.center - tok.center)
        if d < best_d:
            best, best_d = col, d
    return best if best_d < 6 else None


# --------------------------------------------------------------------- grids


@dataclass
class BorderedGrid:
    """A ``+---+`` bordered grid where each cell stacks several named fields.

    Used by ``PRI.INP`` FMAP/CMAP/QMAP/BMAP. Field names come from the
    legend the listing prints beside the cell area. CMAP/BMAP additionally
    embed the assembly site label in the rule itself (``+J-09--+``), which is
    captured in ``site_labels``.
    """

    cells: dict[tuple[int, int], list[str]] = field(default_factory=dict)
    field_names: list[str] = field(default_factory=list)
    site_labels: dict[tuple[int, int], str] = field(default_factory=dict)
    row_aliases: dict[int, str] = field(default_factory=dict)
    rows: list[int] = field(default_factory=list)
    cols: list[int] = field(default_factory=list)

    def merge(self, other: "BorderedGrid") -> "BorderedGrid":
        self.cells.update(other.cells)
        self.site_labels.update(other.site_labels)
        self.row_aliases.update(other.row_aliases)
        if not self.field_names:
            self.field_names = other.field_names
        self.rows = sorted(set(self.rows) | set(other.rows))
        self.cols = sorted(set(self.cols) | set(other.cols))
        return self

    def field(self, row: int, col: int, name: str) -> str | None:
        cell = self.cells.get((row, col))
        if not cell or name not in self.field_names:
            return None
        i = self.field_names.index(name)
        return cell[i] if i < len(cell) else None

    def to_json(self) -> dict:
        return {
            "fieldNames": self.field_names,
            "cells": [
                {
                    "row": r,
                    "col": c,
                    "fields": v,
                    "site": self.site_labels.get((r, c)),
                }
                for (r, c), v in sorted(self.cells.items())
            ],
            "rows": self.rows,
            "cols": self.cols,
            "rowAliases": self.row_aliases,
        }


_COLHDR_RE = re.compile(r"^\s*I\s*/\s*J\s*=\s*(?P<cols>.+)$")
_BANNER_RE = re.compile(r"S\s?I\s?M\s?U\s?L\s?A\s?T\s?E\s?-\s?3")
_LEGEND_RE = re.compile(r"(FUE\.[A-Z]{3}|TYP,ROT|[A-Z]{2,4}[.,][A-Z]{3})")


def parse_bordered_grid(lines: list[str], start: int, end: int) -> BorderedGrid | None:
    """Parse a ``PRI.INP``-style bordered grid band.

    Cell boundaries come from the ``+------+`` rule, whose ``+`` positions
    delimit the columns exactly -- far more reliable than inferring them from
    the ``I / J =`` header. Each grid row is a stack of lines between two
    rules; the listing writes a legend (``FUE.LAB`` / ``FUE.SER`` /
    ``TYP,ROT``) outside the cell area, on the left for the first band and on
    the right for later bands, which names the stacked fields.
    """
    header_idx = None
    for i in range(start, min(end, start + 10)):
        if _COLHDR_RE.match(lines[i]):
            header_idx = i
            break
    if header_idx is None:
        return None

    try:
        col_indices = [
            int(t.text) for t in tokenize(_COLHDR_RE.match(lines[header_idx]).group("cols"))
        ]
    except ValueError:
        return None

    rule_idx = None
    for i in range(header_idx + 1, min(end, header_idx + 6)):
        if _is_grid_rule(lines[i]):
            rule_idx = i
            break
    if rule_idx is None:
        return None

    plus = [m.start() for m in re.finditer(r"\+", lines[rule_idx])]
    if len(plus) < 2:
        return None
    spans = [(plus[i] + 1, plus[i + 1]) for i in range(len(plus) - 1)]
    body_lo, body_hi = plus[0], plus[-1] + 1
    # More rule segments than header columns can happen if the rule runs long.
    spans = spans[: len(col_indices)]

    grid = BorderedGrid(cols=col_indices[: len(spans)])
    block: list[str] = []
    row_index: int | None = None
    row_alias: str | None = None
    pending_sites: dict[int, str] = {}

    def flush() -> None:
        nonlocal block, row_index, row_alias
        if row_index is not None and block:
            for depth, line in enumerate(block):
                for col, (a, b) in zip(grid.cols, spans):
                    text = line[a:b].strip(": ").strip()
                    # The legend is printed over an edge cell slot; it names a
                    # field and is not assembly data.
                    if text and _looks_like_legend(text):
                        text = ""
                    cell = grid.cells.setdefault((row_index, col), [])
                    while len(cell) <= depth:
                        cell.append("")
                    cell[depth] = text
            for col, site in pending_sites.items():
                grid.site_labels[(row_index, col)] = site
            if row_alias:
                grid.row_aliases[row_index] = row_alias
            grid.rows.append(row_index)
        block = []
        row_index = None
        row_alias = None

    for i in range(rule_idx, end):
        line = lines[i]
        if _BANNER_RE.search(line):
            # A page break interrupts the grid; the band ends here.
            break
        if _is_grid_rule(line):
            flush()
            pending_sites = _rule_site_labels(line, spans)
            continue
        if not line.strip():
            continue

        # The legend sits outside the cell area on later bands, but the first
        # band prints it into the leading cell slot -- check both places.
        probe = (
            line[max(0, body_lo - 1) :][: 1]
            + line[:body_lo]
            + " "
            + line[body_hi:]
            + " "
            + line[max(0, spans[0][0] - 1) : spans[0][1]]
            + " "
            + line[max(0, spans[-1][0] - 1) : spans[-1][1]]
        )
        legend = _LEGEND_RE.search(probe)
        if legend and legend.group(1) not in grid.field_names:
            grid.field_names.append(legend.group(1))

        # The row index is the bare integer printed to the left of the grid;
        # a trailing label on the right is the full-core row it maps to.
        if row_index is None:
            for t in tokenize(line[:body_lo]):
                if t.text.isdigit():
                    row_index = int(t.text)
                    break
        if row_alias is None:
            tail = tokenize(line[body_hi:])
            if tail and tail[0].text.isdigit():
                row_alias = tail[0].text
        block.append(line)
        if len(block) > 8:  # runaway guard
            flush()

    flush()
    grid.rows = sorted(set(grid.rows))
    grid.cells = {k: v for k, v in grid.cells.items() if any(x for x in v)}
    return grid if grid.cells else None


_LEGEND_CELL_RE = re.compile(r"(?:FUE\.[A-Z]{0,3}|TYP,[A-Z]{0,3}|[A-Z]{2,4}[.,][A-Z]{0,3})")


def _looks_like_legend(text: str) -> bool:
    """True when a cell holds legend text rather than assembly data.

    The legend is printed into an edge cell slot and gets clipped by the cell
    width (``FUE.LAB`` -> ``FUE.LA``), so an exact match is not enough. Every
    real site label, serial and type field contains a digit, which makes the
    absence of digits a reliable discriminator.
    """
    return not any(ch.isdigit() for ch in text) and bool(_LEGEND_CELL_RE.fullmatch(text))


def _is_grid_rule(line: str) -> bool:
    """True for a grid border line.

    FMAP/QMAP print ``+------+------+``; CMAP/BMAP embed the assembly site
    label in the rule (``+J-09--+H-09--+``), so a plain ``+--`` test misses
    them. Requiring several ``+`` and no lowercase covers both.
    """
    s = line.strip()
    if not s.startswith("+") or s.count("+") < 3:
        return False
    return not any(c.islower() for c in s)


_SITE_RE = re.compile(r"[A-Z]{1,2}-?\d{1,2}")


def _rule_site_labels(line: str, spans: list[tuple[int, int]]) -> dict[int, str]:
    """Pull per-column site labels out of a CMAP/BMAP rule line."""
    out: dict[int, str] = {}
    for idx, (a, b) in enumerate(spans, start=1):
        seg = line[a:b].strip("-+ ")
        if seg and _SITE_RE.fullmatch(seg):
            out[idx] = seg
    return out


# -------------------------------------------------------------------- tables


@dataclass
class RuledTable:
    """A dashed-rule table: header row(s), a ``----`` rule, then data rows."""

    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"columns": self.columns, "rows": self.rows}


def parse_ruled_table(lines: list[str], start: int, end: int, max_scan: int = 400) -> RuledTable | None:
    """Parse a table whose columns are delimited by a row of dashes.

    The dash rule defines the column spans; the line above it holds the
    headings. Data rows are read until a blank run or a non-conforming line.
    """
    rule_idx = None
    stop = min(end, start + max_scan)
    for i in range(start, stop):
        s = lines[i].strip()
        if s and set(s) <= {"-", " "} and s.count("-") >= 6:
            rule_idx = i
            break
    if rule_idx is None or rule_idx == 0:
        return None

    rule_tokens = tokenize(lines[rule_idx])
    if not rule_tokens:
        return None
    spans = [(t.start, t.end) for t in rule_tokens]

    header_line = lines[rule_idx - 1]
    columns = [header_line[a:b].strip() or f"col{n}" for n, (a, b) in enumerate(spans)]

    table = RuledTable(columns=columns)
    blanks = 0
    for i in range(rule_idx + 1, stop):
        line = lines[i]
        if not line.strip():
            blanks += 1
            if blanks >= 2 and table.rows:
                break
            continue
        s = line.strip()
        if set(s) <= {"-", " ", "_"} and len(s) > 6:
            break
        blanks = 0
        row = {}
        for name, (a, b) in zip(columns, spans):
            row[name] = line[a:b].strip()
        # Trailing text past the last span is kept so nothing is silently lost.
        tail = line[spans[-1][1] :].strip()
        if tail:
            row["_tail"] = tail
        if any(v for k, v in row.items() if k != "_tail"):
            table.rows.append(row)
    return table if table.rows else None


# ---------------------------------------------------------------- key/values

# A label may contain single spaces but never a run of two or more -- that run
# is column padding, and allowing it lets one entry swallow the entry to its
# left (e.g. "Hydraulic Iterations" absorbing "K-effective").
_KV_RE = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z0-9()/%\-]*(?: [A-Za-z0-9()/%\-]+)*?)\s*\.\s*\.[\s.]*"
    r"(?P<code>[A-Z][A-Z0-9\-+]{1,8})?[ \t]*"
    r"(?P<value>-?\d[\d.,]*(?:[eE][+-]?\d+)?)"
    r"(?:[ \t]+(?P<unit>[A-Za-z%][A-Za-z0-9()/%*\-^]{0,14}(?:\([^)]*\))?))?"
)


@dataclass
class KeyValueBlock:
    """Dot-leader ``Label . . . CODE  value units`` entries."""

    entries: dict[str, dict] = field(default_factory=dict)

    def value(self, label: str) -> float | None:
        e = self.entries.get(label)
        return e["value"] if e else None

    def to_json(self) -> dict:
        return {"entries": self.entries}


def parse_key_values(lines: list[str], start: int, end: int) -> KeyValueBlock:
    """Extract every dot-leader entry in a region.

    SIMULATE-3 prints these two or three per line, so each line is scanned
    for all matches rather than just the first.
    """
    block = KeyValueBlock()
    for i in range(start, end):
        line = lines[i]
        if "." * 2 not in line.replace(" ", ""):
            continue
        for m in _KV_RE.finditer(line):
            label = " ".join(m.group("label").split())
            if not label or len(label) < 3:
                continue
            raw = m.group("value").replace(",", "")
            val = as_float(raw)
            if val is None:
                continue
            unit = (m.group("unit") or "").strip()
            # Guard against swallowing the next label as a unit.
            if unit and (len(unit) > 12 or unit.endswith(".")):
                unit = unit.split()[0] if unit.split() else ""
            block.entries[label] = {
                "value": val,
                "code": (m.group("code") or "").strip() or None,
                "unit": unit or None,
                "line": i,
            }
    return block
