"""symmetry_orbit() is the one place this feature computes rotation math --
it must reuse geometry.py's existing, already-correct _images(), not
duplicate it."""

from __future__ import annotations

from s3dash.parser.geometry import Geometry, symmetry_orbit


def _quarter_rotational(iafull: int) -> Geometry:
    g = Geometry()
    g.iafull = iafull
    g.ihave = 2
    g.symmetry = "ROTATIONAL"
    return g


def test_general_position_has_four_member_orbit():
    geom = _quarter_rotational(17)
    orbit = symmetry_orbit(2, 5, geom)
    assert len(orbit) == 4
    assert (2, 5) in orbit


def test_orbit_is_self_consistent_for_every_member():
    # Every member of an orbit must produce the identical orbit set --
    # otherwise "the atomic unit a drag affects" would depend on which
    # member the user happened to grab.
    geom = _quarter_rotational(17)
    orbit = symmetry_orbit(2, 5, geom)
    for (r, c) in orbit:
        assert set(symmetry_orbit(r, c, geom)) == set(orbit)


def test_core_centre_is_a_fixed_point_on_odd_width_grid():
    geom = _quarter_rotational(17)
    centre = (9, 9)
    assert symmetry_orbit(*centre, geom) == [centre]


def test_orbit_matches_expand_to_full_core_images():
    # symmetry_orbit must describe exactly the same symmetry the existing,
    # already-relied-upon expand_to_full_core uses for value maps -- two
    # different notions of symmetry in one codebase would be a real bug.
    from s3dash.parser.geometry import expand_to_full_core

    geom = _quarter_rotational(17)
    expanded = expand_to_full_core({(2, 5): 1.0}, geom)
    assert set(expanded) == set(symmetry_orbit(2, 5, geom))
