"""Low-level text helpers shared by all layout primitives.

SIMULATE-3 output is fixed-width, column-aligned ASCII produced by Fortran
FORMAT statements. Everything in this module is about recovering the column
structure reliably, without assuming a particular field width.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

_TOKEN_RE = re.compile(r"\S+")


@dataclass(frozen=True)
class Token:
    """A whitespace-delimited run of characters with its position in the line."""

    text: str
    start: int
    end: int  # exclusive

    @property
    def center(self) -> float:
        return (self.start + self.end) / 2.0


def tokenize(line: str) -> list[Token]:
    """Split a line into tokens, keeping character positions."""
    return [Token(m.group(), m.start(), m.end()) for m in _TOKEN_RE.finditer(line)]


def column_cuts(header_tokens: list[Token]) -> list[int]:
    """Compute field boundaries from a header ruler.

    A cut is placed at the midpoint of the gap between consecutive header
    tokens. Field i then spans ``[cuts[i-1], cuts[i])``, which reliably
    captures values that are right-aligned, centered, or contain internal
    spaces (e.g. the ``17, 9`` cells in a ``PIN.EDT 2PLO`` map).

    Returns one cut per header token; the final cut sits one gap-width past
    the last token so trailing row labels fall outside every field.
    """
    if not header_tokens:
        return []

    cuts: list[int] = []
    for i in range(len(header_tokens) - 1):
        gap_start = header_tokens[i].end
        gap_end = header_tokens[i + 1].start
        cuts.append((gap_start + gap_end) // 2)

    # Trailing cut: mirror the average gap so the last field has the same width.
    if len(header_tokens) >= 2:
        gaps = [
            header_tokens[i + 1].start - header_tokens[i].end
            for i in range(len(header_tokens) - 1)
        ]
        pad = max(1, sum(gaps) // len(gaps))
    else:
        pad = 2
    cuts.append(header_tokens[-1].end + pad)
    return cuts


def slice_fields(line: str, cuts: list[int], data_start: int = 0) -> list[str]:
    """Slice a data line into stripped fields using precomputed cuts.

    ``data_start`` lets the caller exclude a leading row label from the first
    field. Fields that are entirely blank come back as empty strings.
    """
    fields: list[str] = []
    lo = data_start
    for cut in cuts:
        hi = max(lo, cut)
        fields.append(line[lo:hi].strip())
        lo = hi
    return fields


def as_float(text: str) -> float | None:
    """Parse a SIMULATE-3 numeric field, tolerating Fortran quirks.

    Returns ``None`` for blanks and non-numeric cells rather than raising, so
    a single odd cell never aborts a whole map.
    """
    if not text:
        return None
    t = text.strip().rstrip("*")
    if not t or t in {"-", "--", "---", "----"}:
        return None
    # Fortran can emit '1.0-3' meaning 1.0E-3, and '****' for overflow.
    if set(t) == {"*"}:
        return None
    try:
        return float(t)
    except ValueError:
        pass
    m = re.fullmatch(r"([+-]?\d*\.?\d+)([+-]\d+)", t)
    if m:
        try:
            return float(f"{m.group(1)}E{m.group(2)}")
        except ValueError:
            return None
    return None


def as_int(text: str) -> int | None:
    """Parse an integer field, returning ``None`` when it is not one."""
    if not text:
        return None
    try:
        return int(text.strip())
    except ValueError:
        return None


def dedupe_consecutive(lines: list[str]) -> list[str]:
    """Drop immediately-repeated identical non-blank lines.

    Some SIMULATE-3 builds interleave the listing and console streams, which
    doubles many lines. Deduplicating consecutive repeats is safe because
    genuine adjacent duplicates (e.g. two identical map rows) are separated
    by their differing row labels.
    """
    out: list[str] = []
    prev: str | None = None
    for line in lines:
        if line.strip() and line == prev:
            continue
        out.append(line)
        prev = line
    return out


def iter_windows(lines: list[str], start: int, limit: int) -> Iterator[tuple[int, str]]:
    """Yield ``(index, line)`` from ``start`` for at most ``limit`` lines."""
    stop = min(len(lines), start + limit)
    for i in range(start, stop):
        yield i, lines[i]


def despace_heading(line: str) -> str:
    """Collapse Fortran letter-spaced banner headings back to normal words.

    SIMULATE-3 prints major headings letter-spaced::

        S u m m a r y   o f   E r r o r s / W a r n i n g s

    Letters within a word are separated by one space and words by two or
    more, so the whole line is classified first (most tokens being single
    characters is the tell) and then split on the wider gaps. Classifying the
    line rather than matching runs is what makes short words like "o f" and
    "a n d" survive. Lines that are not letter-spaced are returned unchanged.
    """
    tokens = line.split()
    if len(tokens) < 6:
        return line
    singles = sum(1 for t in tokens if len(t) == 1)
    if singles / len(tokens) < 0.6:
        return line
    words = [w.replace(" ", "") for w in re.split(r"\s{2,}", line.strip()) if w.strip()]
    return " ".join(w for w in words if w)
