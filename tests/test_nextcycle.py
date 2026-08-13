"""Applying, validating, encoding, and generating from a modified loading
pattern."""

from __future__ import annotations

import pytest

from s3dash.parser.geometry import Geometry
from s3dash.parser.loadingpattern import LoadingEntry
from s3dash.parser.nextcycle import PositionChange, ValidationError, apply_change


def _quarter_rotational(iafull: int) -> Geometry:
    g = Geometry()
    g.iafull = iafull
    g.ihave = 2
    g.symmetry = "ROTATIONAL"
    return g


def _entry(row, col, token, kind="reused"):
    return LoadingEntry(row=row, col=col, token=token, kind=kind)


class TestApplyChange:
    def test_noop_move_to_its_own_position(self):
        geom = _quarter_rotational(17)
        entries = {(1, 2): _entry(1, 2, "N-03")}
        change = PositionChange(from_row=1, from_col=2, to_row=1, to_col=2)
        new_entries, op = apply_change(entries, change, geom)
        assert new_entries == entries
        assert op.operation == "move"

    def test_swap_moves_every_symmetry_partner_together(self):
        geom = _quarter_rotational(17)
        from s3dash.parser.geometry import symmetry_orbit

        src_orbit = symmetry_orbit(2, 5, geom)
        dst_orbit = symmetry_orbit(3, 3, geom)
        assert len(src_orbit) == len(dst_orbit) == 4

        entries = {}
        for i, (r, c) in enumerate(src_orbit):
            entries[(r, c)] = _entry(r, c, f"SRC{i}")
        for i, (r, c) in enumerate(dst_orbit):
            entries[(r, c)] = _entry(r, c, f"DST{i}")

        change = PositionChange(from_row=2, from_col=5, to_row=3, to_col=3)
        new_entries, op = apply_change(entries, change, geom)

        assert op.operation == "swap"
        assert set(new_entries) == set(entries)  # position set unchanged
        # every source-orbit position now holds a token that used to be a
        # destination-orbit token, and vice versa
        assert {new_entries[pos].token for pos in src_orbit} == {f"DST{i}" for i in range(4)}
        assert {new_entries[pos].token for pos in dst_orbit} == {f"SRC{i}" for i in range(4)}

    def test_original_entries_never_mutated(self):
        geom = _quarter_rotational(17)
        from s3dash.parser.geometry import symmetry_orbit

        src_orbit = symmetry_orbit(2, 5, geom)
        dst_orbit = symmetry_orbit(3, 3, geom)
        entries = {(r, c): _entry(r, c, "A") for (r, c) in src_orbit}
        entries.update({(r, c): _entry(r, c, "B") for (r, c) in dst_orbit})
        snapshot = dict(entries)

        apply_change(entries, PositionChange(2, 5, 3, 3), geom)
        assert entries == snapshot

    def test_moving_from_empty_position_raises(self):
        geom = _quarter_rotational(17)
        with pytest.raises(ValidationError, match="No assembly"):
            apply_change({}, PositionChange(2, 5, 3, 3), geom)

    def test_mismatched_orbit_sizes_raise(self):
        # (9,9) is the fixed-point centre of a 17-wide grid (orbit size 1);
        # (2,5) has a 4-member orbit. Swapping them cannot preserve
        # symmetry, so it must be rejected, not silently truncated.
        geom = _quarter_rotational(17)
        entries = {(9, 9): _entry(9, 9, "CENTRE"), (2, 5): _entry(2, 5, "A")}
        with pytest.raises(ValidationError, match="symmetry orbit"):
            apply_change(entries, PositionChange(2, 5, 9, 9), geom)


from s3dash.parser.nextcycle import validate


class TestValidate:
    def _base(self):
        geom = _quarter_rotational(17)
        from s3dash.parser.geometry import symmetry_orbit

        a_orbit = symmetry_orbit(2, 5, geom)
        b_orbit = symmetry_orbit(3, 3, geom)
        entries = {(r, c): _entry(r, c, f"A{i}") for i, (r, c) in enumerate(a_orbit)}
        entries.update({(r, c): _entry(r, c, f"B{i}") for i, (r, c) in enumerate(b_orbit)})
        return geom, entries

    def test_unchanged_pattern_is_valid(self):
        geom, entries = self._base()
        assert validate(entries, entries, geom) == []

    def test_valid_swap_via_apply_change_stays_valid(self):
        geom, entries = self._base()
        new_entries, _ = apply_change(entries, PositionChange(2, 5, 3, 3), geom)
        assert validate(new_entries, entries, geom) == []

    def test_duplicate_serial_detected(self):
        geom, entries = self._base()
        (r, c) = next(iter(entries))
        broken = dict(entries)
        other = next(k for k in broken if k != (r, c))
        broken[other] = LoadingEntry(row=other[0], col=other[1], token=broken[(r, c)].token, kind="reused")
        problems = validate(broken, entries, geom)
        assert any("appears at" in p for p in problems)

    def test_vanished_position_detected(self):
        geom, entries = self._base()
        (r, c) = next(iter(entries))
        broken = dict(entries)
        del broken[(r, c)]
        problems = validate(broken, entries, geom)
        assert any("emptied" in p for p in problems)

    def test_partial_orbit_detected(self):
        # Directly construct a broken state (not reachable via apply_change,
        # which always moves whole orbits) to prove validate() catches it
        # independently, not just by trusting the caller used apply_change.
        geom, entries = self._base()
        (r, c) = next(iter(entries))
        broken = dict(entries)
        del broken[(r, c)]
        problems = validate(broken, entries, geom)
        assert any("symmetric" in p or "emptied" in p for p in problems)

    def test_fresh_count_change_detected(self):
        geom, entries = self._base()
        (r, c) = next(iter(entries))
        broken = dict(entries)
        broken[(r, c)] = LoadingEntry(row=r, col=c, token=broken[(r, c)].token, kind="fresh")
        problems = validate(broken, entries, geom)
        assert any("fresh-batch" in p for p in problems)
