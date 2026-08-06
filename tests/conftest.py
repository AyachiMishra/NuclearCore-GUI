"""Shared fixtures: the three reference listings, parsed once per session.

Parsing is ~0.15 s per file, but every test would otherwise re-read a 13k-line
listing; session scope keeps the suite fast enough to run on every edit.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLES = ROOT / "sample_data"

from s3dash.parser import parse_file  # noqa: E402  (needs sys.path first)

# The three reference files span every structural axis the parser must handle:
# core width, core fraction, 2D vs 3D, exposure unit, and which edits exist.
CASES = {
    "apr_c2": "case_002495.out",
    "apr_alt": "apr1400.c02.out",
    "beavrs": "9074.out",
}


@pytest.fixture(scope="session")
def parsed() -> dict:
    return {key: parse_file(SAMPLES / name) for key, name in CASES.items()}


@pytest.fixture(scope="session")
def apr(parsed) -> object:
    return parsed["apr_c2"]


@pytest.fixture(scope="session")
def apr_alt(parsed) -> object:
    return parsed["apr_alt"]


@pytest.fixture(scope="session")
def beavrs(parsed) -> object:
    return parsed["beavrs"]


@pytest.fixture(scope="session")
def raw_lines() -> dict:
    """Untouched file lines, for asserting parsed values against the source."""
    out = {}
    for key, name in CASES.items():
        text = (SAMPLES / name).read_text(encoding="latin-1", errors="replace")
        out[key] = text.split("\n")
    return out
