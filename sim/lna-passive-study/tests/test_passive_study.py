"""Closed-form qualification of the lna-passive-study bench (issue #340).

No simulator, no fleet, no PDK install: everything checked here is a property
of files committed in the tree (plan, sizing table, variant decks, prematch
outcome) or of pure arithmetic in passive.py. The fleet-verified model facts
(closed-form R/C vs the instanced r3_cmc / MIM models) are re-checked against
the sizing table's own embedded model parameters, so a PDK change that breaks
the derivation's assumptions fails here without any ngspice.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import passive as PS  # noqa: E402

REPO = PS.REPO_ROOT


@pytest.fixture(scope="module")
def plan() -> dict:
    return PS.load_plan()


@pytest.fixture(scope="module")
def sizing() -> dict:
    return PS.load_sizing()


@pytest.fixture(scope="module")
def prematch() -> dict:
    return json.loads(PS.PREMATCH_PATH.read_text(encoding="utf-8"))


def test_plan_is_the_frozen_declaration(plan, sizing) -> None:
    assert PS.plan_problems(plan, PS.DUT_PATH.read_text(encoding="utf-8"),
                            sizing) == []


def test_variant_decks_regenerate(plan, sizing, prematch) -> None:
    from run import variant_decks
    decks = variant_decks(plan, sizing, prematch)
    assert sorted(decks) == sorted(v["id"] for v in plan["variants"])
    for vid, text in decks.items():
        committed = PS.VARIANTS_DIR / f"{vid}.spice"
        assert committed.is_file(), f"{vid}.spice missing"
        assert committed.read_text() == text, f"{vid}.spice drifted from plan+sizing+prematch"


def test_control_deck_is_the_committed_netlist_verbatim() -> None:
    text = PS.control_dut_text(PS.DUT_PATH.read_text(encoding="utf-8"))
    body = text.split("* lna_stage1 subcircuit", 1)[1]
    committed = PS.DUT_PATH.read_text(encoding="utf-8").split(
        "* lna_stage1 subcircuit", 1)[1]
    assert body == committed  # only the study's header is added


def test_variant_decks_keep_inductors_ideal(plan, sizing, prematch) -> None:
    from run import variant_decks
    for vid, text in variant_decks(plan, sizing, prematch).items():
        for line in text.splitlines():
            if line.startswith(("Lfeed ", "Le1 ")):
                assert line == next(l for l in PS.DUT_PATH.read_text().splitlines()
                                    if l.startswith(line.split()[0] + " ")), \
                    f"{vid}: an inductor line changed: {line}"


def test_v04_freezes_the_prematch_selection(plan, sizing, prematch) -> None:
    from run import variant_decks
    deck = variant_decks(plan, sizing, prematch)["V04"]
    sel = prematch["selection"]
    assert sel, "prematch selected nothing; V04 must be dropped, not frozen"
    assert f"l={sel['cblk_side_um']:g}u" in deck.replace("l=25.77u", "l=25.77u")
    assert f"{sel['lin_h']:.4g}" in deck or sel["lin_h"] > 0
    # the re-matched Cshunt appears with its own value, not the committed 170f
    line = next(l for l in deck.splitlines() if l.startswith("Cshunt "))
    assert "170f" not in line
    assert sel["worst_s11_db"] <= PS.S11_TARGET_DB


def test_prematch_grid_and_corners_are_the_declared_ones(prematch, plan) -> None:
    assert {f"{v:g}" for v in PS.PREMATCH_GRID_F} == \
        {f"{float(k):g}" for k in prematch["rematches"]}
    assert set(prematch["grid"]) == {
        f"{proc}/novdd/{t:g}C" for proc in PS.PREMATCH_CORNERS
        for t in PS.PREMATCH_TEMPS_C}
    # every grid cell measured every candidate at every band point
    tags = range(1, len(PS.PREMATCH_GRID_F) + 1)
    for cell in prematch["grid"].values():
        for i in tags:
            for band in ("lo", "mid", "hi"):
                assert f"s11_db_{band}_c{i}" in cell


def test_m_multiplier_check_passed(prematch) -> None:
    check = prematch["probe"]["m_multiplier_check"]
    assert abs(check["m2_f"] / check["two_f"] - 1.0) <= 0.01


def test_cell_keys_and_control_mapping() -> None:
    ck = PS.cell_key("V01", "res_wcs__cap_bcs", -40.0, 2.25)
    assert ck == "V01__res_wcs__cap_bcs__-40C__2.25V"
    # the passive-extreme cells compare against the typ control at the same
    # hbt section (hbt_typ), not against a passive corner of the control
    assert PS.control_cell_key("res_wcs__cap_bcs", -40.0, 2.25) == \
        PS.cell_key("V00", "typ", -40.0, 2.25)
    assert PS.control_cell_key("hbt_wcs", 125.0, 2.5) == \
        PS.cell_key("V00", "hbt_wcs", 125.0, 2.5)


def test_deltas_need_every_control_cell() -> None:
    variant = {PS.cell_key("V01", "typ", 27.0, 2.5): {"s21_db_mid": 18.0,
                                                      "nf_db_mid": 3.0}}
    control = {PS.cell_key("V00", "typ", 27.0, 2.5): {"s21_db_mid": 17.0,
                                                      "nf_db_mid": 2.5}}
    d = PS.deltas(variant, control)
    assert d[PS.cell_key("V01", "typ", 27.0, 2.5)]["s21_db_mid"] == pytest.approx(1.0)
    assert d[PS.cell_key("V01", "typ", 27.0, 2.5)]["nf_db_mid"] == pytest.approx(0.5)
    with pytest.raises(ValueError):
        PS.deltas(variant, {})


def test_l_section_match_matches_exactly_at_f0_below_50() -> None:
    r_b, x_b, cblk = 24.0, -148.0, 1e-9
    lin_h, cshunt_f = PS.l_section_match(r_b, x_b, cblk, PS.BAND_CENTRE_HZ)
    w = 2 * math.pi * PS.BAND_CENTRE_HZ
    z_l = complex(r_b, x_b - 1.0 / (w * cblk))
    y = complex(0.0, w * cshunt_f) + 1.0 / (complex(0.0, w * lin_h) + z_l)
    assert y.real == pytest.approx(1.0 / 50.0, abs=1e-9)
    assert y.imag == pytest.approx(0.0, abs=1e-9)


def test_l_section_match_degrades_to_reactance_cancellation_at_or_above_50() -> None:
    # the measured post-Le1 core resistance sits just below 50 ohm; a load at
    # or above 50 cannot be matched by the fixed topology, and the tuner must
    # say so by cancelling reactance only with the committed shunt value
    lin_h, cshunt_f = PS.l_section_match(334.0, -143.0, 1e-12, PS.BAND_CENTRE_HZ)
    w = 2 * math.pi * PS.BAND_CENTRE_HZ
    z_l = complex(334.0, -143.0 - 1.0 / (w * 1e-12))
    assert (w * lin_h + z_l.imag) == pytest.approx(0.0, abs=1e-6)
    assert cshunt_f == 170e-15
    with pytest.raises(ValueError):
        PS.l_section_match(48.0, +200.0, 0.5e-12, PS.BAND_CENTRE_HZ)  # negative Lin


def test_cap_side_inversion_hits_the_design_value(sizing) -> None:
    for value_f in (1e-12, 5e-12, 57.8e-15, 170e-15):
        side = PS.cap_side_for_value(sizing, "cmim", value_f)
        assert abs(side["c_typ_f"] - value_f) / value_f <= 0.01


def test_probe_measured_values_reproduce_from_the_table(sizing) -> None:
    """The fleet-probe cross-check embedded in passive_sizing must re-derive
    from the committed table's own model parameters (PDK-free)."""
    sys.path.insert(0, str(REPO / "layout" / "lna_stage1"))
    import passive_sizing as SZ
    rm, cm = sizing["resistor_models"], sizing["capacitor_models"]
    for label, meas in SZ._PROBE_MEASURED.items():
        kind = label.split()[0]
        if kind in rm:
            w = float(label.split()[1].split("=")[1])
            l = float(label.split()[2].split("=")[1])
            for corner, want in meas.items():
                got = SZ.model_r_ohm(rm[kind], w, l, corner)
                assert abs(got - want) <= max(0.02, 1e-4 * abs(want)), \
                    f"{label} {corner}: {got} vs probe {want}"
        else:
            side = float(label.split()[1].split("x")[0])
            for corner, want in meas.items():
                got = SZ.model_c_f(cm[kind], side, side, corner)
                assert abs(got - want) / want <= 1e-3, \
                    f"{label} {corner}: {got} vs probe {want}"


def test_parse_log_roundtrip() -> None:
    log = "m_s21_db_mid = 1.790494e+01\nm_nf_db_mid = 2.865450e+00\nnoise\n"
    assert PS.parse_log(log) == {"s21_db_mid": 17.90494, "nf_db_mid": 2.86545}


def test_requests_use_per_section_corner_bundles() -> None:
    req = PS.klt_request("body.spice", ["typ", "res_wcs__cap_bcs"], [27.0], 600,
                         "/abs/r3_cmc.osdi")
    axis = req["corners"]["process"]
    assert [c["name"] for c in axis] == ["typ", "res_wcs__cap_bcs"]
    for corner in axis:
        libs = {s["lib"] for s in corner["sections"]}
        assert libs == set(PS.MODEL_LIBS.values())
    assert req["options"]["osdi_preload"] == ["/abs/r3_cmc.osdi"]
    assert req["options"]["stage_model_inputs"] is True
    assert req["models"]["pdk"] == "ihp-sg13g2"
