"""SIMULATE-3 output parser.

Public entry points::

    from s3dash.parser import parse_file, parse_text
    result = parse_file("case_002495.out")
    result.payload            # the JSON document the dashboard renders
    result.document.lines     # raw listing, for the section text viewer
"""

from __future__ import annotations

from pathlib import Path

from .build import BuildResult, build, describe_variable
from .document import Document, Section, load, load_text

__all__ = [
    "BuildResult",
    "Document",
    "Section",
    "build",
    "describe_variable",
    "parse_file",
    "parse_text",
]


def parse_file(path: str | Path) -> BuildResult:
    """Parse a SIMULATE-3 listing from disk."""
    return build(load(path))


def parse_text(raw: str, source_file: str | None = None) -> BuildResult:
    """Parse a SIMULATE-3 listing already held in memory."""
    return build(load_text(raw, source_file=source_file))
