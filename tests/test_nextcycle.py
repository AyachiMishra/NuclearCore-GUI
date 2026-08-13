"""Applying, validating, encoding, and generating from a modified loading
pattern."""

from __future__ import annotations

import pytest

from s3dash.parser.geometry import Geometry
from s3dash.parser.loadingpattern import LoadingEntry
from s3dash.parser.nextcycle import PositionChange, ValidationError, apply_change
from tests.conftest import SAMPLES, samples_available


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


from s3dash.parser.loadingpattern import decode_loading_pattern, find_fuel_lab_card
from s3dash.parser.nextcycle import encode_loading_pattern


class TestEncodeLoadingPattern:
    def test_round_trips_a_hand_built_pattern(self):
        geom = _quarter_rotational(17)
        from s3dash.parser.geometry import symmetry_orbit

        orbit = symmetry_orbit(2, 5, geom)
        entries = {(r, c): _entry(r, c, "N-03" if i == 0 else "TP01", "reused" if i == 0 else "fresh")
                   for i, (r, c) in enumerate(orbit)}

        text = encode_loading_pattern(entries, geom)
        lines = ["'FUE.LAB' 4/", *text.splitlines()]
        decoded = decode_loading_pattern(lines, 0, {"TP01"})
        assert decoded.keys() == entries.keys()
        for pos in entries:
            assert decoded[pos].token == entries[pos].token
            assert decoded[pos].kind == entries[pos].kind

    def test_round_trips_the_real_apr1400_pattern(self):
        if not samples_available():
            pytest.skip("reference listing not present (see README)")
        from s3dash.parser import parse_file

        result = parse_file(SAMPLES / "apr1400.c02.out")
        payload = result.payload
        lines = result.document.lines
        fresh_labels = {b["label"] for b in payload["inputDeck"]["batches"]}
        fuel_lab_line = find_fuel_lab_card(lines)
        original = decode_loading_pattern(lines, fuel_lab_line, fresh_labels)

        text = encode_loading_pattern(original, result.geometry)
        reencoded_lines = ["'FUE.LAB' 4/", *text.splitlines()]
        roundtripped = decode_loading_pattern(reencoded_lines, 0, fresh_labels)

        assert roundtripped.keys() == original.keys()
        for pos in original:
            assert roundtripped[pos].token == original[pos].token


from s3dash.parser.nextcycle import GenerationResult, generate_inp


class TestGenerateInp:
    def test_fue_lab_block_is_replaced_and_res_wre_substituted(self):
        geom = _quarter_rotational(4)
        source_lines = [
            "'TIT.CAS' 'ORIGINAL TITLE' /",
            "'RES' 's3.plant.c01.depl.res' 20000./",
            "'FUE.LAB' 4/",
            "  1  1 N-03 TP01",
            "  0  0",
            "'FUE.NEW', 'TP01', 'F-101', 2, 8, ,,3/",
            "'WRE' 's3.plant.c02.depl.res' /",
            "'STA'/",
        ]
        entries = {
            (1, 1): _entry(1, 1, "N-03"),
            (1, 2): _entry(1, 2, "TP01", "fresh"),
        }
        result = generate_inp(
            lines=source_lines,
            section_start=0,
            section_end=len(source_lines),
            original_entries=entries,
            modified_entries=entries,
            geom=geom,
            operations=[],
            res_filename="s3.plant.c02.depl.res",
            res_exposure="24.112",
            wre_filename="s3.plant.c03.depl.res",
        )
        assert isinstance(result, GenerationResult)
        assert "'RES' 's3.plant.c02.depl.res' 24.112/" in result.text
        assert "'WRE' 's3.plant.c03.depl.res' /" in result.text
        assert "s3.plant.c01.depl.res" not in result.text
        assert "N-03" in result.text and "TP01" in result.text
        # unrelated cards survive verbatim
        assert "'FUE.NEW', 'TP01', 'F-101', 2, 8, ,,3/" in result.text
        assert "'STA'/" in result.text

    def test_tit_cas_and_bat_lab_preserved_but_flagged(self):
        geom = _quarter_rotational(4)
        source_lines = [
            "'TIT.CAS' 'PWR CYCLE 2' /",
            "'BAT.LAB' 2 'CYC-2' /",
            "'RES' 's3.plant.c01.depl.res' 20000./",
            "'FUE.LAB' 4/",
            "  1  1 N-03",
            "  0  0",
            "'WRE' 's3.plant.c02.depl.res' /",
        ]
        entries = {(1, 1): _entry(1, 1, "N-03")}
        result = generate_inp(
            lines=source_lines, section_start=0, section_end=len(source_lines),
            original_entries=entries, modified_entries=entries, geom=geom, operations=[],
            res_filename="x", res_exposure="1.0", wre_filename=None,
        )
        assert "'TIT.CAS' 'PWR CYCLE 2' /" in result.text
        assert "'BAT.LAB' 2 'CYC-2' /" in result.text
        assert "TIT.CAS" in result.flagged_cards
        assert "BAT.LAB" in result.flagged_cards

    def test_dep_cyc_gets_advisory_comment(self):
        geom = _quarter_rotational(4)
        source_lines = [
            "'RES' 's3.plant.c01.depl.res' 20000./",
            "'FUE.LAB' 4/",
            "  1  1 N-03",
            "  0  0",
            "'DEP.CYC' 'CYCLE 2 ' .0 2 /",
        ]
        entries = {(1, 1): _entry(1, 1, "N-03")}
        result = generate_inp(
            lines=source_lines, section_start=0, section_end=len(source_lines),
            original_entries=entries, modified_entries=entries, geom=geom, operations=[],
            res_filename="x", res_exposure="1.0", wre_filename=None,
        )
        lines_out = result.text.splitlines()
        dep_idx = next(i for i, l in enumerate(lines_out) if "DEP.CYC" in l)
        assert "'COM'" in lines_out[dep_idx - 1]
        assert "review" in lines_out[dep_idx - 1].lower()

    def test_no_wre_filename_means_wre_card_untouched(self):
        geom = _quarter_rotational(4)
        source_lines = [
            "'RES' 's3.plant.c01.depl.res' 20000./",
            "'FUE.LAB' 4/",
            "  1  1 N-03",
            "  0  0",
            "'WRE' 's3.plant.c02.depl.res' /",
        ]
        entries = {(1, 1): _entry(1, 1, "N-03")}
        result = generate_inp(
            lines=source_lines, section_start=0, section_end=len(source_lines),
            original_entries=entries, modified_entries=entries, geom=geom, operations=[],
            res_filename="x", res_exposure="1.0", wre_filename=None,
        )
        assert "'WRE' 's3.plant.c02.depl.res' /" in result.text


class TestInferNextRestartFilename:
    def test_increments_the_cycle_number_the_source_deck_demonstrates(self):
        from s3dash.parser.nextcycle import infer_next_restart_filename

        # apr1400.c02.out's own RES reads .c01., its own WRE writes .c02. --
        # a within-deck, read-then-write pair that unambiguously increments.
        # The parallel move for a generated next-cycle deck is .c02. -> .c03.
        assert infer_next_restart_filename("s3.apr1400_PPF.uo2.c02.depl.res") == \
            "s3.apr1400_PPF.uo2.c03.depl.res"

    def test_double_digit_cycle_number(self):
        from s3dash.parser.nextcycle import infer_next_restart_filename

        assert infer_next_restart_filename("s3.plant.c09.depl.res") == "s3.plant.c10.depl.res"

    def test_no_recognisable_cycle_pattern_returns_none(self):
        # Must not guess when the filename doesn't demonstrate a pattern --
        # the caller falls back to asking the user, per the design's
        # explicit "expose as an editable field" instruction.
        from s3dash.parser.nextcycle import infer_next_restart_filename

        assert infer_next_restart_filename("restart_file.res") is None
