"""Corner-set expansion and the sabotage negative control (corners.py)."""

import pytest

from harness import corners as C


def test_hbt_set_expands_typical_first():
    assert [c.name for c in C.resolve_corners(["hbt"])] == ["hbt_typ", "hbt_bcs", "hbt_wcs"]


def test_hbt_corners_use_their_own_lib_sections():
    for c in C.resolve_corners(["hbt"]):
        assert c.sections == (c.name,)


def test_resolve_dedupes_and_mixes_sets_and_names():
    got = [c.name for c in C.resolve_corners(["hbt_typ", "hbt", "hbt_wcs"])]
    assert got == ["hbt_typ", "hbt_bcs", "hbt_wcs"]


def test_default_is_the_five_mos_corners():
    assert [c.name for c in C.resolve_corners(None)] == ["tt", "ff", "ss", "fs", "sf"]


def test_unknown_corner_names_the_known_ones():
    with pytest.raises(KeyError, match="hbt_typ"):
        C.resolve_corners(["nope"])


def test_register_corner_checks_family_arity():
    with pytest.raises(ValueError, match="one per family"):
        C.register_corner("bad", ("a", "b"))


def test_register_corner_set_rejects_unknown_member():
    with pytest.raises(KeyError):
        C.register_corner_set("bad_set", ("hbt_typ", "missing"))


def test_sabotage_keeps_names_but_forces_typical_sections():
    real = C.resolve_corners(["hbt"])
    sab = C.sabotage(real)
    assert [c.name for c in sab] == [c.name for c in real]
    assert {c.sections for c in sab} == {("hbt_typ",)}
    assert all(c.description.startswith("SABOTAGED") for c in sab)
    assert C.sabotage([]) == []


def test_supply_points():
    assert C.supply_points(2.5, 0.10) == [2.25, 2.5, 2.75]
    assert C.supply_points(2.5, 0) == [2.5]


def test_hbt_grid_is_27_unique_ids_in_stable_order():
    grid = C.build_grid(C.resolve_corners(["hbt"]), [-40, 27, 125], C.supply_points(2.5, 0.10))
    ids = [p.corner_id for p in grid]
    assert len(ids) == 27 == len(set(ids))
    assert ids[0] == "hbt_typ_-40c_2.25v"
    assert ids[-1] == "hbt_wcs_125c_2.75v"
    assert [p.index for p in grid] == list(range(27))
    assert ids == [p.corner_id for p in C.build_grid(C.resolve_corners(["hbt"]), [-40, 27, 125], [2.25, 2.5, 2.75])]


def test_point_dict_carries_sections():
    p = C.build_grid(C.resolve_corners(["hbt_bcs"]), [27], [2.5])[0]
    d = p.as_dict()
    assert d["corner"] == "hbt_bcs" and d["corner_sections"] == ["hbt_bcs"] and d["corner_id"] == "hbt_bcs_27c_2.50v"
