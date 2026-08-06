"""Layout primitive tests, written against literal listing excerpts.

Each fixture string is copied verbatim from a real file, so a regression shows
up as a mismatch against text SIMULATE-3 actually produced.
"""

from __future__ import annotations

from s3dash.parser.primitives import (
    parse_banded_map,
    parse_bordered_grid,
    parse_key_values,
    parse_ruled_table,
)
from s3dash.parser.textutil import as_float, column_cuts, despace_heading, tokenize

# Quarter-core map: values are left-packed and rows may end early (row 13).
QUARTER_MAP = [
    " PRI.STA 2RPF  - Assembly 2D RPF - Relative Power Fraction",
    " **    9     10     11     12     13     14     15     16     17     **",
    "  9  1.155  0.831  1.245  1.314  0.836  1.092  1.323  0.899  0.947   09",
    " 10  0.831  1.180  0.891  0.963  0.899  1.296  0.932  1.388  0.978   10",
    " 13  0.836  0.899  1.199  0.801  0.707  0.805  1.223  0.934          13",
    " **   J-     H-     G-     F-     E-     D-     C-     B-     A-     **",
    "",
    "",
]

# Full-core map: rows are RAGGED. Row 1's seven values belong to columns 5-11,
# which is the case that defeats whitespace tokenisation.
FULL_MAP = [
    " PRI.STA 2RPF  - Assembly 2D Ave RPF - Relative Power Fraction",
    " **    1      2      3      4      5      6      7      8      9     10     11     12     13     14     15     **",
    "  1                              0.448  0.549  0.862  0.699  0.861  0.547  0.446                               01",
    "  5  0.444  0.718  0.777  0.958  1.484  1.427  1.356  1.415  1.351  1.409  1.488  0.982  0.788  0.726  0.449   05",
    " **   R-     P-     N-     M-     L-     K-     J-     H-     G-     F-     E-     D-     C-     B-     A-     **",
    "",
    "",
]

# Pin-location map: cells contain a comma AND an internal space ("17, 9"), so
# they must be sliced by column, never split on whitespace.
PIN_LOCATION_MAP = [
    " PIN.EDT 2PLO  - Peak Pin Power Location:     Assembly 2D",
    " Renorm =  1.00000E+00     Axial Plane =  1",
    " **    1      2      3      4      5      6      7      8      9     10     11     12     13     14     15     **",
    "  1                              17,17  17,17  17,17  17, 9  17, 1  17, 1  17, 1                               01",
    "  2                17,17  17,17  17,17  14*13  17,17  10, 9  17, 1  14* 5  17, 1  17, 1  17, 1                 02",
    " **   R-     P-     N-     M-     L-     K-     J-     H-     G-     F-     E-     D-     C-     B-     A-     **",
    "",
    "",
]


class TestBandedMap:
    def test_quarter_core_values_match_listing(self):
        m = parse_banded_map(QUARTER_MAP, 0, len(QUARTER_MAP))
        assert m.values[(9, 9)] == 1.155
        assert m.values[(9, 10)] == 0.831
        assert m.values[(9, 17)] == 0.947
        assert m.values[(10, 16)] == 1.388

    def test_short_row_leaves_trailing_column_empty(self):
        m = parse_banded_map(QUARTER_MAP, 0, len(QUARTER_MAP))
        assert m.values[(13, 16)] == 0.934
        assert (13, 17) not in m.values

    def test_trailing_row_label_is_not_read_as_a_value(self):
        m = parse_banded_map(QUARTER_MAP, 0, len(QUARTER_MAP))
        # The "09" repeated at end of row 9 must not become a 10th column.
        assert len([c for (r, c) in m.values if r == 9]) == 9

    def test_ragged_full_core_row_lands_in_correct_columns(self):
        m = parse_banded_map(FULL_MAP, 0, len(FULL_MAP))
        # Row 1 holds exactly seven values, in columns 5..11.
        assert m.values[(1, 5)] == 0.448
        assert m.values[(1, 11)] == 0.446
        assert (1, 4) not in m.values
        assert (1, 12) not in m.values
        assert sorted(c for (r, c) in m.values if r == 1) == [5, 6, 7, 8, 9, 10, 11]

    def test_full_row_spans_every_column(self):
        m = parse_banded_map(FULL_MAP, 0, len(FULL_MAP))
        assert m.values[(5, 1)] == 0.444
        assert m.values[(5, 15)] == 0.449
        assert len([c for (r, c) in m.values if r == 5]) == 15

    def test_column_site_labels_come_from_the_footer(self):
        m = parse_banded_map(FULL_MAP, 0, len(FULL_MAP))
        assert m.col_labels[1] == "R"
        assert m.col_labels[8] == "H"
        assert m.col_labels[15] == "A"

    def test_cells_containing_spaces_survive_intact(self):
        m = parse_banded_map(PIN_LOCATION_MAP, 0, len(PIN_LOCATION_MAP))
        assert m.numeric is False
        assert m.raw[(1, 8)] == "17, 9"
        assert m.raw[(1, 5)] == "17,17"
        assert m.raw[(2, 6)] == "14*13"

    def test_metadata_above_the_ruler_is_captured(self):
        m = parse_banded_map(PIN_LOCATION_MAP, 0, len(PIN_LOCATION_MAP))
        assert m.plane == 1
        assert m.renorm == 1.0

    def test_returns_none_without_a_ruler(self):
        assert parse_banded_map([" no ruler here", " 1 2 3"], 0, 2) is None


FMAP_BAND = [
    " PRI.INP - FMAP - Loading Map for Full Core",
    " I / J =    1      2      3      4      5      6      7      8",
    "        +------+------+------+------+------+------+------+------+",
    "        FUE.LAB:      :      :      :      :M-01  :L-01  :K-01  :",
    "   1    FUE.SER:      :      :      :      :H226  :F-101 :F-102 :  01",
    "        TYP,ROT:      :      :      :      :     0:     0:     0:",
    "        +------+------+------+------+------+------+------+------+",
]

# CMAP embeds the site label in the rule and prints the full-core row on the right.
CMAP_BAND = [
    " PRI.INP - CMAP - Loading Map for Calculated Core",
    " I / J =    1      2      3",
    "        +J-09--+H-09--+G-09--+",
    "        :  9  3:  5  1:  9  3:",
    "   1    :  5.51:  3.77:  5.51:  09",
    "        :  0.00: 30.85:  0.00:",
    "        +J-10--+H-10--+G-10--+",
]


class TestBorderedGrid:
    def test_reads_stacked_fields_and_names_them(self):
        g = parse_bordered_grid(FMAP_BAND, 0, len(FMAP_BAND))
        assert g.field_names == ["FUE.LAB", "FUE.SER", "TYP,ROT"]
        assert g.cells[(1, 6)] == ["M-01", "H226", "0"]
        assert g.field(1, 7, "FUE.SER") == "F-101"

    def test_legend_is_not_mistaken_for_assembly_data(self):
        g = parse_bordered_grid(FMAP_BAND, 0, len(FMAP_BAND))
        # The legend occupies cell slot 1; it must not appear as an assembly.
        assert (1, 1) not in g.cells

    def test_handles_rules_with_embedded_site_labels(self):
        g = parse_bordered_grid(CMAP_BAND, 0, len(CMAP_BAND))
        assert g.cells[(1, 1)] == ["9  3", "5.51", "0.00"]
        assert g.site_labels[(1, 1)] == "J-09"
        assert g.row_aliases[1] == "09"


BATCH_TABLE = [
    "             NPIN  -  PEAK PIN POWER                   SCALE =    1.000E+00",
    "",
    "              BATCH                          MAXIMUM",
    "",
    "     Number   Name   Assemblies       NPIN  Label  Serial  Location",
    "     ------  ------  ----------       ----- ------ ------ ----------",
    "        3              121            1.610 H-16   F-149  (14, 3, 1)",
    "        1    CYC-1     120            1.233 J-14   H147   (11, 1, 1)",
    "",
    "     CORE              241            1.610 H-16   F-149  (14, 3, 1)",
]


class TestRuledTable:
    def test_columns_come_from_the_dash_rule(self):
        t = parse_ruled_table(BATCH_TABLE, 0, len(BATCH_TABLE))
        assert t.columns == [
            "Number", "Name", "Assemblies", "NPIN", "Label", "Serial", "Location",
        ]

    def test_reads_rows_including_blank_cells(self):
        t = parse_ruled_table(BATCH_TABLE, 0, len(BATCH_TABLE))
        assert t.rows[0]["Number"] == "3"
        assert t.rows[0]["Name"] == ""
        assert t.rows[0]["NPIN"] == "1.610"
        assert t.rows[1]["Name"] == "CYC-1"


OUTPUT_SUMMARY = [
    " Relative Power. . . . . . .PERCTP   100.0 %                               Core Average Exposure . . . . EBAR  11.542 GWd/MT",
    " Hydraulic Iterations                                                      K-effective . . . . . . . . . . . . .  1.14074",
    " Thermal Power . . . . . . . . CTP  3983.8 MWt                             Depletion Step Length . . . . .  0.000E+00 Hours",
]


class TestKeyValues:
    def test_reads_both_columns_of_a_line(self):
        kv = parse_key_values(OUTPUT_SUMMARY, 0, len(OUTPUT_SUMMARY))
        assert kv.entries["Relative Power"]["value"] == 100.0
        assert kv.entries["Relative Power"]["code"] == "PERCTP"
        assert kv.entries["Core Average Exposure"]["value"] == 11.542
        assert kv.entries["Core Average Exposure"]["unit"] == "GWd/MT"

    def test_a_label_does_not_swallow_the_one_to_its_left(self):
        kv = parse_key_values(OUTPUT_SUMMARY, 0, len(OUTPUT_SUMMARY))
        # "Hydraulic Iterations" sits far to the left on the same line.
        assert kv.entries["K-effective"]["value"] == 1.14074
        assert "Hydraulic Iterations K-effective" not in kv.entries

    def test_a_label_containing_a_colon_is_captured_whole(self):
        """Excluding ':' makes the match restart inside the parenthesis and
        publish the fragment "D-ACTUAL)" as if it were its own quantity."""
        line = [
            " Inlet Subcooling (PRMEAS) .SUBCOL   82.17 kcal/kg 147.90 Btu/lb"
            "           Buckling (2D-USED:3D-ACTUAL). .  8.200E-05  CM-2"
        ]
        kv = parse_key_values(line, 0, 1)
        assert kv.entries["Buckling (2D-USED:3D-ACTUAL)"]["value"] == 8.2e-05
        assert kv.entries["Buckling (2D-USED:3D-ACTUAL)"]["unit"] == "CM-2"
        assert not any(k.startswith("D-ACTUAL") for k in kv.entries)


class TestTextUtil:
    def test_cuts_isolate_each_field(self):
        header = [t for t in tokenize(QUARTER_MAP[1]) if t.text != "**"]
        cuts = column_cuts(header)
        assert len(cuts) == len(header)
        assert cuts == sorted(cuts)

    def test_despace_collapses_letter_spaced_headings(self):
        assert (
            despace_heading(" S u m m a r y   o f   F i l e   A c t i v i t y")
            == "Summary of File Activity"
        )

    def test_despace_handles_short_words(self):
        got = despace_heading(
            " S u m m a r y   o f   E r r o r s / W a r n i n g s / "
            "C a u t i o n s   a n d   N o t e s"
        )
        assert got == "Summary of Errors/Warnings/Cautions and Notes"

    def test_despace_leaves_ordinary_lines_alone(self):
        line = "  9  1.155  0.831  1.245  1.314  0.836  1.092  1.323  0.899  0.947   09"
        assert despace_heading(line) == line

    def test_as_float_rejects_non_numeric_cells(self):
        assert as_float("1.155") == 1.155
        assert as_float("") is None
        assert as_float("----") is None
        assert as_float("****") is None
        assert as_float("17, 9") is None

    def test_as_float_reads_fortran_exponent_without_e(self):
        assert as_float("1.0-3") == 0.001
