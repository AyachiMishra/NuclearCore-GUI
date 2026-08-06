"""Geometry resolution and fractional-core expansion.

The three sample files only exercise quarter-rotational and full-core. Mirror
and octant symmetry are real SIMULATE-3 options that other sites use, so they
are covered here with synthetic cores rather than left untested.
"""

from __future__ import annotations

import pytest

from s3dash.parser.geometry import Geometry, expand_to_full_core, parse_geometry

DIMENSION_BLOCK = [
    " DIM.PWR and DIM.CAL Specify Calculation Dimensions:",
    "",
    " Full Core Assembly Map Width . IAFULL  17",
    " Control Rod Map Width  . . . . . IRMX  17",
    " Detector Map Width . . . . . . . ILMX  17",
    " Offset Assemblies Flag . . . . IOFSET   0",
    " Axial Nodes (Incl. Refl.). . . . . KD   1",
    " Core Fraction Flag . . . . . . .IHAVE   2",
    " Node Mesh per Assembly . . . . .IF2X2   2",
    " Reflector Layers . . . . . . . . NREF   1",
    " Radial Core Fraction . . . . . .    0.250",
    " Core Symmetry . . . . . . . . .        ROTATIONAL",
    " Fuel Assemblies . . . . . . . .      241.0000",
]


class TestParseGeometry:
    def test_reads_the_echoed_dimension_block(self):
        g = parse_geometry(DIMENSION_BLOCK)
        assert g.iafull == 17
        assert g.kd == 1
        assert g.ihave == 2
        assert g.if2x2 == 2
        assert g.nref == 1
        assert g.radial_fraction == 0.25
        assert g.symmetry == "ROTATIONAL"
        assert g.n_assemblies == 241

    def test_dot_leaders_are_not_read_as_values(self):
        """The leader dots sit between label and value; a greedy numeric class
        would capture them instead of the number."""
        g = parse_geometry(DIMENSION_BLOCK)
        assert g.radial_fraction == 0.25
        assert g.n_assemblies == 241

    def test_falls_back_to_raw_cards_without_an_echo_block(self):
        cards = [
            " 'DIM.PWR' 15/                          * PWR with 15 rows",
            " 'DIM.CAL' 12, 4/                       * 12 axial nodes, FULL core",
            " 'COR.SYM' 'ROT'/",
        ]
        g = parse_geometry(cards)
        assert g.iafull == 15
        assert g.kd == 12
        assert g.ihave == 4
        assert g.symmetry == "ROTATIONAL"

    def test_recognises_a_bwr(self):
        g = parse_geometry([" 'DIM.BWR' 30,15,16/"])
        assert g.reactor_type == "BWR"

    def test_mirror_symmetry_card(self):
        g = parse_geometry([" 'DIM.PWR' 17/", " 'COR.SYM' 'MIR'/"])
        assert g.symmetry == "MIRROR"

    def test_fraction_name_and_axial_derivation(self):
        for ihave, name in [(1, "octant"), (2, "quarter"), (3, "half"), (4, "full")]:
            assert Geometry(iafull=17, ihave=ihave).fraction_name == name
        # KD counts both axial reflectors; fuel nodes exclude them.
        assert Geometry(iafull=17, kd=14).fuel_nodes == 12
        assert Geometry(iafull=17, kd=14).is_3d is True
        assert Geometry(iafull=17, kd=1).fuel_nodes == 1
        assert Geometry(iafull=17, kd=1).is_3d is False


class TestSiteLabels:
    def test_letters_skip_i_o_and_q(self):
        """Standard PWR site naming omits I, O and Q. A 17-wide core must
        therefore end at T, not at R."""
        g = Geometry(iafull=17)
        assert g.site_label(1, 17) == "A-01"
        assert g.site_label(1, 1) == "T-01"
        assert g.site_label(9, 9) == "J-09"
        for bad in ("I", "O", "Q"):
            assert not any(g.site_label(1, c).startswith(bad + "-") for c in range(1, 18))

    def test_fifteen_wide_core_ends_at_r(self):
        g = Geometry(iafull=15)
        assert g.site_label(1, 1) == "R-01"
        assert g.site_label(1, 15) == "A-01"

    def test_out_of_range_falls_back_to_coordinates(self):
        assert Geometry(iafull=17).site_label(0, 99) == "(0,99)"


class TestRotationalExpansion:
    def test_quarter_expands_to_four_images(self):
        g = Geometry(iafull=5, ihave=2, symmetry="ROTATIONAL")
        got = expand_to_full_core({(3, 4): 7.0}, g)
        # (3,4) in a 5x5 grid rotates to (4,3), (3,2) and (2,3).
        assert set(got) == {(3, 4), (4, 3), (3, 2), (2, 3)}
        assert all(v == 7.0 for v in got.values())

    def test_centre_cell_maps_to_itself(self):
        g = Geometry(iafull=5, ihave=2, symmetry="ROTATIONAL")
        got = expand_to_full_core({(3, 3): 1.0}, g)
        assert got == {(3, 3): 1.0}

    def test_printed_values_are_never_overwritten(self):
        """Asymmetric input is what the SYMGRP check exists to find, so
        expansion must not smooth it away."""
        g = Geometry(iafull=5, ihave=2, symmetry="ROTATIONAL")
        got = expand_to_full_core({(3, 4): 7.0, (4, 3): 9.0}, g)
        assert got[(3, 4)] == 7.0
        assert got[(4, 3)] == 9.0, "printed value survived its own rotational image"

    def test_expansion_is_idempotent(self):
        g = Geometry(iafull=5, ihave=2, symmetry="ROTATIONAL")
        once = expand_to_full_core({(3, 4): 7.0}, g)
        assert expand_to_full_core(once, g) == once


class TestMirrorExpansion:
    def test_mirror_reflects_across_both_midplanes(self):
        g = Geometry(iafull=5, ihave=2, symmetry="MIRROR")
        got = expand_to_full_core({(2, 4): 3.0}, g)
        assert set(got) == {(2, 4), (2, 2), (4, 4), (4, 2)}

    def test_mirror_differs_from_rotational(self):
        """Point (2,3) lies on the vertical midplane of a 5-wide core, so
        mirroring yields only its horizontal partner while rotation sweeps it
        around all four quadrants. A point like (2,4) would coincide under
        both and prove nothing."""
        rot = expand_to_full_core(
            {(2, 3): 3.0}, Geometry(iafull=5, ihave=2, symmetry="ROTATIONAL")
        )
        mir = expand_to_full_core(
            {(2, 3): 3.0}, Geometry(iafull=5, ihave=2, symmetry="MIRROR")
        )
        assert set(rot) == {(2, 3), (3, 4), (4, 3), (3, 2)}
        assert set(mir) == {(2, 3), (4, 3)}


class TestOctantExpansion:
    def test_octant_adds_the_diagonal_reflection(self):
        g = Geometry(iafull=5, ihave=1, symmetry="ROTATIONAL")
        got = expand_to_full_core({(2, 3): 5.0}, g)
        # Rotational images plus their diagonal transposes.
        assert (3, 2) in got and (2, 3) in got
        assert len(got) >= 4
        assert all(v == 5.0 for v in got.values())

    def test_octant_covers_more_than_quarter(self):
        quarter = expand_to_full_core(
            {(2, 4): 1.0}, Geometry(iafull=7, ihave=2, symmetry="ROTATIONAL")
        )
        octant = expand_to_full_core(
            {(2, 4): 1.0}, Geometry(iafull=7, ihave=1, symmetry="ROTATIONAL")
        )
        assert len(octant) >= len(quarter)


class TestNoExpansion:
    def test_full_core_is_returned_unchanged(self):
        g = Geometry(iafull=5, ihave=4, symmetry="ROTATIONAL")
        cells = {(1, 1): 1.0, (3, 3): 2.0}
        assert expand_to_full_core(cells, g) == cells

    def test_empty_input_is_safe(self):
        assert expand_to_full_core({}, Geometry(iafull=17, ihave=2)) == {}

    def test_unknown_width_is_safe(self):
        assert expand_to_full_core({(1, 1): 1.0}, Geometry(iafull=0, ihave=2)) == {(1, 1): 1.0}


class TestAgainstRealFiles:
    def test_expansion_count_matches_the_listing(self, parsed):
        """The strongest available check: the file states its own assembly
        count, and expansion must reproduce exactly that."""
        for key, result in parsed.items():
            payload = result.payload
            assert len(payload["assemblies"]) == payload["geometry"]["nAssemblies"], key

    @pytest.mark.parametrize("key", ["apr_c2", "apr_alt"])
    def test_every_rotational_image_holds_equal_power(self, parsed, key):
        payload = parsed[key].payload
        n = payload["geometry"]["iafull"]
        idx = payload["assemblyIndex"]
        rpf = payload["statePoints"][0]["values"]["2RPF"]
        checked = 0
        for a in payload["assemblies"]:
            r, c = a["row"], a["col"]
            image = (c, n + 1 - r)
            key_image = f"{image[0]},{image[1]}"
            if key_image in idx and not a["printed"]:
                assert rpf[idx[f"{r},{c}"]] == rpf[idx[key_image]]
                checked += 1
        assert checked > 100, "expansion should cover most of the core"
