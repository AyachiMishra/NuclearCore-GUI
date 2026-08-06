"""Shared fixtures: the three reference listings, parsed once per session.

Parsing is ~0.15 s per file, but every test would otherwise re-read a 13k-line
listing; session scope keeps the suite fast enough to run on every edit.

The listings are not in the repository -- they are SIMULATE-3 output for
specific plant models. Tests that need them skip with an explanation rather
than failing, so a fresh clone still exercises everything that can be checked
without plant data (roughly half the suite). Drop your own ``.out`` files into
``sample_data/`` to run the rest; see the README.
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

_MISSING = "reference listing not present (see README: Running the tests)"


def samples_available() -> bool:
    return all((SAMPLES / name).is_file() for name in CASES.values())


def pytest_collection_modifyitems(config, items):
    """Skip listing-dependent tests when the listings are absent.

    Detection is by fixture use, so a new test that asks for ``parsed`` (or a
    per-file fixture) is covered automatically and cannot silently fail on a
    fresh clone.
    """
    if samples_available():
        return
    needs_data = {"parsed", "apr", "apr_alt", "beavrs", "raw_lines", "reports", "bundled",
                  "run_id"}
    skip = pytest.mark.skip(reason=_MISSING)
    for item in items:
        if needs_data & set(getattr(item, "fixturenames", ())):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def parsed() -> dict:
    if not samples_available():
        pytest.skip(_MISSING)
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
    if not samples_available():
        pytest.skip(_MISSING)
    out = {}
    for key, name in CASES.items():
        text = (SAMPLES / name).read_text(encoding="latin-1", errors="replace")
        out[key] = text.split("\n")
    return out
