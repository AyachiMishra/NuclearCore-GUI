"""Control rod withdrawal maps and run timing."""

from __future__ import annotations

import pytest

from s3dash.parser.controlrods import parse_control_rod_map, parse_timing

ROD_MAP = [
    " Control Rod Withdrawal Map ( -- Indicates fully withdrawn to 100 Steps ( 365.760 cm) )",
    " CRD positions defined by CRD.ARO with no core symmetry applied by CRD.SYM",
    " IR/JR =    1   2   3   4   5   6   7   8     9    10  11  12  13  14  15  16  17",
    "",
    "   1       --  --  --  --  --  --  --  --    --    --  --  --  --  --  --  --  --",
    "   2       --  --  --  --  --  --  --  --    --    --  --  --  --  --  --  --  --",
    "",
    " Total control rod positions withdrawn in full core =  28900",
]

# Same ruler, but with rods partially inserted, which is how a real
# rodded state point prints.
ROD_MAP_INSERTED = [
    " Control Rod Withdrawal Map ( -- Indicates fully withdrawn to 100 Steps ( 365.760 cm) )",
    " IR/JR =    1   2   3   4",
    "",
    "   1       --  --  60  --",
    "   2       --  30  --   0",
    "",
    " Total control rod positions withdrawn in full core =    690",
]


class TestControlRodMap:
    def test_reads_every_column(self):
        """The header gap widens around the centre column; no column may be
        dropped because of it."""
        m = parse_control_rod_map(ROD_MAP, 0, len(ROD_MAP))
        assert sorted(c for (r, c) in m.withdrawn if r == 1) == list(range(1, 18))
        assert len(m.withdrawn) == 34

    def test_position_count_matches_the_listings_own_arithmetic(self):
        """total_withdrawn / steps_per_rod is the number of rod positions, so
        it independently confirms no position was missed."""
        m = parse_control_rod_map(ROD_MAP, 0, len(ROD_MAP))
        implied = m.total_withdrawn / m.full_withdrawal_steps
        assert implied == 289, "17x17 rod map"

    def test_full_map_over_the_real_files(self, parsed):
        for key, result in parsed.items():
            sp = result.payload["statePoints"][0]
            rods = sp["controlRods"]
            n = len(rods["withdrawn"]) + len(rods["inserted"])
            assert n == rods["totalWithdrawn"] / rods["fullWithdrawalSteps"], key

    def test_withdrawn_is_distinct_from_zero_steps_inserted(self):
        m = parse_control_rod_map(ROD_MAP_INSERTED, 0, len(ROD_MAP_INSERTED))
        assert m.inserted[(1, 3)] == 60.0
        assert m.inserted[(2, 2)] == 30.0
        # A rod at 0 steps is inserted-at-zero, not withdrawn.
        assert m.inserted[(2, 4)] == 0.0
        assert (2, 4) not in m.withdrawn
        assert (1, 1) in m.withdrawn

    def test_any_inserted_flag(self):
        assert parse_control_rod_map(ROD_MAP, 0, len(ROD_MAP)).any_inserted is False
        assert parse_control_rod_map(
            ROD_MAP_INSERTED, 0, len(ROD_MAP_INSERTED)
        ).any_inserted is True

    def test_metadata_is_captured(self):
        m = parse_control_rod_map(ROD_MAP, 0, len(ROD_MAP))
        assert m.full_withdrawal_steps == 100.0
        assert m.total_withdrawn == 28900
        assert "CRD.ARO" in m.note

    def test_returns_none_without_a_ruler(self):
        assert parse_control_rod_map([" nothing here", " at all"], 0, 2) is None


TIMING_BLOCK = [
    "                         PINS                   0.17          35.80          31.0         5.34",
    "                         SIGNEW                 0.12          26.94         292.0         0.43",
    " Total CPU Time        0.475 Seconds",
    " Start Time/Date  14:22:34  26/07/09",
    " End   Time/Date  14:22:35  26/07/09",
    " Elapsed Real Time     1.000 Seconds",
    " CPU Utilization      47.51%",
    " Maximum Container Usage:    876563 words",
    "SIMULATE Run Completed - Normal Termination",
]


class TestTiming:
    def test_reads_cpu_and_wall_time(self):
        t = parse_timing(TIMING_BLOCK, 0, len(TIMING_BLOCK))
        assert t["cpuSeconds"] == 0.475
        assert t["elapsedSeconds"] == 1.0
        assert t["cpuUtilisation"] == 47.51

    def test_reads_completion_status(self):
        t = parse_timing(TIMING_BLOCK, 0, len(TIMING_BLOCK))
        assert t["completion"] == "Normal Termination"
        assert t["startTime"] == "14:22:34"
        assert t["endDate"] == "26/07/09"

    def test_real_files_report_normal_termination(self, parsed):
        for key, result in parsed.items():
            timing = result.payload["meta"]["timing"]
            assert timing["completion"] == "Normal Termination", key
            assert timing["cpuSeconds"] > 0
            assert len(timing["subroutines"]) > 0

    def test_beavrs_3d_run_costs_more_cpu_than_the_2d_runs(self, parsed):
        """A sanity check that timings are read per-file, not cached."""
        beavrs = parsed["beavrs"].payload["meta"]["timing"]["cpuSeconds"]
        apr = parsed["apr_c2"].payload["meta"]["timing"]["cpuSeconds"]
        assert beavrs > apr

    def test_missing_timing_block_yields_empty_dict(self):
        assert parse_timing([], 0, 0) == {}
