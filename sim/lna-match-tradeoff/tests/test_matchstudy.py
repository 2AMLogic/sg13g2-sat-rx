"""Unit tests for matchstudy.py (issue #74). No simulator, no PDK.

    python3 -m pytest sim/lna-match-tradeoff/tests -q
"""

from __future__ import annotations

import cmath
import copy
import json
import math
import random
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
REPO = BENCH.parents[1]
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "tests"))
sys.path.insert(0, str(REPO / "sim" / "lna-sparam-nf"))

import matchfakes as fakes  # noqa: E402
import lna_nf  # noqa: E402
import matchstudy as ms  # noqa: E402

RAW = json.loads((BENCH / "testbench" / "study.json").read_text())
ST = ms.study_from_manifest(RAW)
FROZEN = (REPO / "design" / "netlist" / "lna_stage1.spice").read_text()


# --- declaration --------------------------------------------------------------


def test_frozen_candidate_list_is_the_declared_generators_expansion():
    cands, excluded = ms.expand_declaration(RAW)
    assert RAW["candidates"] == cands
    assert RAW["excluded_targets"] == excluded


def test_declaration_derived_points_come_from_the_recorded_derivation():
    d = RAW["derivation"]
    assert RAW["family"]["gamma_power_match"] == d["gamma_power_match"]
    assert RAW["family"]["gamma_noise_opt"] == d["gamma_noise_opt"]
    assert d["point"] == {"process": "hbt_typ", "temp_c": 27.0, "vdd": 2.5}


def test_baseline_is_the_schematic_network_and_unique():
    b = ST.baseline
    assert (b.c_sh1, b.l_in, b.c_sh2, b.topology) == (170e-15, 1.41e-9, 0.0, "shunt_first")
    assert [c.role for c in ST.candidates].count("baseline") == 1


def test_screen_thresholds_trace_to_the_ratified_rows():
    s = RAW["screen"]
    assert (s["nf_max_db"], s["s11_max_db"], s["k_min"], s["delta_max"]) == (2.5, -10.0, 1.0, 1.0)
    assert s["s21_min_db"] == 20.0 / 2  # row 2's two-stage 20 dB split evenly in dB
    for key in ("nf_max_db", "s11_max_db", "s21_min_db", "k_min", "operating_point"):
        assert "row" in s["_trace"][key]
    spec = (REPO / "spec" / "target-spec.md").read_text()
    assert "**≤ 2.5 dB** across band" in spec and "**≤ −10 dB** across band" in spec
    assert "**≥ 20 dB** across band (two-stage cascode assumed)" in spec


def test_pvt_grid_matches_the_existing_bench_and_flags_the_excursion():
    assert sorted(ST.processes) == ["hbt_bcs", "hbt_typ", "hbt_wcs"]
    assert ST.temps_c == (-40.0, 27.0, 125.0) and ST.supplies_v == (2.25, 2.5, 2.75)
    assert ST.rail_ceiling_v == 2.5 and len(ST.pvt_points()) == 27


def test_validate_study_rejects_bad_declarations():
    bad = copy.deepcopy(RAW)
    bad["candidates"][0]["l_in"] = 1.5e-9
    with pytest.raises(ms.StudyError, match="baseline must be"):
        ms.study_from_manifest(bad)
    bad = copy.deepcopy(RAW)
    bad["candidates"] = [c for c in bad["candidates"] if c["role"] != "probe"]
    with pytest.raises(ms.StudyError, match="probe_thru"):
        ms.study_from_manifest(bad)
    bad = copy.deepcopy(RAW)
    bad["candidates"].append(dict(bad["candidates"][1]))
    with pytest.raises(ms.StudyError, match="duplicate"):
        ms.study_from_manifest(bad)


# --- network family -----------------------------------------------------------


def test_synthesis_presents_the_target_impedance_at_f0():
    rng = random.Random(74)
    hits = 0
    for _ in range(400):
        g = cmath.rect(rng.uniform(0, 0.95), rng.uniform(-math.pi, math.pi))
        zs = ms.z_from_gamma(g)
        for topo, v in ms.synthesize(zs, 19.45e9).items():
            if isinstance(v, dict):
                hits += 1
                z = ms.source_impedance(v, 19.45e9)
                assert abs(z - zs) <= 1e-9 * abs(zs)
                assert v["l_in"] > 0 and v["c_sh1"] >= 0 and v["c_sh2"] >= 0
                assert (v["c_sh2"] == 0) if topo == "shunt_first" else (v["c_sh1"] == 0)
    assert hits > 300


def test_declared_candidates_hit_their_targets_within_rounding():
    for c in ST.candidates:
        t = c.target
        if "gamma_re" not in t:
            continue
        g = ms.gamma(ms.source_impedance(c, ST.f0_hz))
        assert abs(g - complex(t["gamma_re"], t["gamma_im"])) < 2e-3, c.name


def test_unrealizable_targets_are_listed_with_reasons():
    assert ST.excluded_targets
    assert all(e["reason"] for e in ST.excluded_targets)


# --- DUT text -----------------------------------------------------------------


def test_dut_text_changes_only_the_two_input_lines():
    dut = ms.dut_text(FROZEN)
    assert ms.unparameterize(dut) == FROZEN.rstrip("\n") + "\n"
    old = set(FROZEN.splitlines())
    new = set(dut.splitlines())
    assert old - new == set(ms.FROZEN_INPUT_LINES.values())
    assert new - old == {"Cshunt in gnd {c_sh1} m=1", "Lin in in2 {l_in} m=1", "Csh2 in2 gnd {c_sh2} m=1"}
    for keep in ("Rd vdd oc 465 m=1", "Lfeed vdd oc 0.962n m=1", "Cm oc out 57.8f m=1", "Rbias nr b1 2k m=1"):
        assert keep in dut


def test_dut_text_refuses_a_changed_schematic():
    with pytest.raises(ms.StudyError, match="changed"):
        ms.dut_text(FROZEN.replace("Lin in in2 1.41n m=1", "Lin in in2 1.5n m=1"))


def test_literal_dut_matches_the_frozen_netlist_for_the_baseline():
    lit = ms.literal_dut_text(FROZEN, ST.baseline)
    assert "Lin in in2 1.41e-09 m=1" in lit and "Csh2 in2 gnd 0.0 m=1" in lit


def test_op_expressions_are_the_lna_sparam_nf_ones():
    tb = json.loads((REPO / "sim" / "lna-sparam-nf" / "testbench" / "tb.json").read_text())
    theirs = {a.split(" = ", 1)[0][4:]: a.split(" = ", 1)[1] for a in tb["analyses"] if a.startswith("let q")
              or a.startswith("let idd") or a.startswith("let pdc")}
    assert dict(ms.op_lets()) == theirs


def test_control_lines_cover_every_network_and_probes_only_dense():
    names = ["baseline", "seg0375_b", "probe_thru"]
    lines = ms.control_lines(ST, [ST.candidate(n) for n in names])
    for n in ("baseline", "seg0375_b"):
        for s in ms.SECTIONS:
            assert f"echo LM_BEGIN {n} {s}" in lines
    assert [ln for ln in lines if ln.startswith("echo LM_BEGIN probe_thru")] == [
        f"echo LM_BEGIN probe_thru {s}" for s in ("fwd_dense", "noise_dense", "rev_dense")]
    assert lines[-1] == "echo LM_DONE"
    assert f"ac lin 71 {17.7e9!r} {21.2e9!r}" in lines
    assert "noise v(p2) vs1 lin 70 " + repr(17.725e9) + " " + repr(21.175e9) in [
        ln.replace("17725000000.000002", "17725000000.0") for ln in lines]


def test_reference_source_stays_noiseless_and_load_noisy():
    assert "Rs1 s1n p1 {z0} noisy=0" in ms.PORTS and "Rs2 s2n p2 {z0}\n" in ms.PORTS


# --- extraction ---------------------------------------------------------------


def test_nf_normalization_matches_lna_sparam_nf():
    for v in (1e-10, 5e-10, 1.3e-9):
        assert ms.nf_db_from_inoise(v) == pytest.approx(lna_nf.nf_db(v), abs=1e-12)


def test_stability_closed_forms():
    # matched 6 dB pad: k = (1 + |Delta|^2) / (2 |S12 S21|) with Delta = -0.25
    r = ms.stability(0j, 0.5 + 0j, 0.5 + 0j, 0j)
    assert r["k"] == pytest.approx(1.0625 / 0.5) and r["delta"] == pytest.approx(0.25)
    # unilateral: k infinite
    assert math.isinf(ms.stability(0.5 + 0j, 3 + 0j, 0j, 0.2 + 0j)["k"])


def test_load_noise_share_of_a_pad_is_l_t_over_t0():
    assert ms.load_noise_share(0.5 + 0j, 0j, 27.0, 300.15) == pytest.approx(4.0)
    assert ms.load_noise_share(0.5 + 0j, 0j, -40.0, 300.15) == pytest.approx(4 * 233.15 / 300.15)


def _cell(name="seg0375_b", **kw):
    log = fakes.fake_log(ST, [name], "hbt_typ", 27.0, 2.5, **kw)
    pl = ms.parse_log(log)
    return pl, ms.make_cell(ST, "screen", ST.candidate(name), "hbt_typ", 27.0, 2.5, pl.tables.get(name, {}), pl.op)


def test_extraction_recovers_the_closed_form_two_port():
    pl, cell = _cell("baseline")
    assert pl.problems == [] and pl.done and cell["status"] == "ok"
    f = ST.dense_freqs()[10]
    s, inz = fakes.total(ST.baseline, f, "hbt_typ", 27.0, 2.5)
    assert cell["band"]["s21_db"][10] == pytest.approx(ms.db20(s["s21"]), abs=1e-7)
    assert cell["band"]["s11_db"][10] == pytest.approx(ms.db20(s["s11"]), abs=1e-6)
    assert cell["band"]["nf_db"][10] == pytest.approx(ms.nf_db_from_inoise(inz), abs=1e-8)
    st = ms.stability(s["s11"], s["s21"], s["s12"], s["s22"])
    assert cell["band"]["k"][10] == pytest.approx(st["k"], rel=1e-6)
    assert len(cell["band"]["f_hz"]) == 71 and len(cell["wide"]["f_hz"]) == 201
    assert cell["refined"]["ok"] and cell["op"]["pass"] and cell["supply_class"] == "in_rail"


def test_nonfinite_value_makes_the_cell_invalid_and_unselectable():
    _, cell = _cell(nan_in="seg0375_b")
    assert cell["status"] == "rejected_invalid" and "non-finite" in cell["reason"]
    assert not cell["screen"]["pass"]
    sl = ms.shortlist(ST, [cell])
    assert sl["names"] == ["baseline"]


def test_missing_block_makes_the_cell_invalid():
    _, cell = _cell(drop=("seg0375_b", "rev_mid"))
    assert cell["status"] == "rejected_invalid" and "rev_mid" in cell["reason"]


def test_wrong_frequency_grid_is_invalid():
    pl, _ = _cell()
    t = pl.tables["seg0375_b"]
    t["fwd_dense"] = t["fwd_dense"][:-1]
    t["noise_dense"] = t["noise_dense"][:-1]
    t["rev_dense"] = t["rev_dense"][:-1]
    an = ms.analyze_candidate(ST, ST.candidate("seg0375_b"), t)
    assert not an["valid"] and any("grid" in p for p in an["problems"])


def test_refined_grid_failure_rejects_the_cell():
    pl, _ = _cell()
    t = pl.tables["seg0375_b"]
    mid = t["noise_mid"]
    mid[len(mid) // 2] = [mid[len(mid) // 2][0], mid[len(mid) // 2][1] * 3]  # a hidden NF peak between dense points
    an = ms.analyze_candidate(ST, ST.candidate("seg0375_b"), t)
    assert not an["valid"] and "refined-grid control failed" in " ".join(an["problems"])


def test_parse_log_flags_simulator_errors_and_unterminated_blocks():
    pl = ms.parse_log("LM_BEGIN a fwd_dense\n0\t1e9\t1\t2\t3\t4\nError: something\n")
    assert any("simulator message" in p for p in pl.problems)
    assert any("unterminated" in p for p in pl.problems) and not pl.done


def test_op_checks_label_the_excursion_and_fail_row17():
    op = fakes.op_values("hbt_typ", 27.0, 2.75)
    r = ms.op_checks(op, 2.75, ST)
    assert r["supply_class"] == "excursion" and not r["pass"] and "q1:vce_le_1v4" in r["failures"]
    assert ms.op_checks(fakes.op_values("hbt_typ", 27.0, 2.5), 2.5, ST)["pass"]


# --- noise parameters and the bound ----------------------------------------------


def test_noise_parameter_fit_recovers_known_parameters():
    fmin, rn, zopt = 1.4, 37.0, complex(146, 100)
    gopt = ms.gamma(zopt)
    ring = [ms.z_from_gamma(cmath.rect(0.5, math.radians(a))) for a in range(0, 360, 45)]

    def pts(zs):
        return [(z, ms.nf_lin_at(ms.gamma(z), fmin, rn / 50, gopt)) for z in zs]

    fit = ms.fit_noise_params(pts([50 + 0j] + ring))  # the declared probe geometry: thru + ring
    assert fit["fmin"] == pytest.approx(fmin, rel=1e-9) and fit["rn_ohm"] == pytest.approx(rn, rel=1e-9)
    assert abs(fit["zopt"] - zopt) < 1e-6 and fit["rms_residual_db"] < 1e-9
    # a ring alone is degenerate (a Gamma circle is a Y circle): refuse, never fit garbage
    with pytest.raises(ms.StudyError, match="singular|non-physical"):
        ms.fit_noise_params(pts(ring))


def test_mismatch_circle_boundary_has_the_declared_return_loss():
    gin = 0.9 * cmath.exp(-1.2j)
    c, r = ms.mismatch_circle(gin, 10 ** (-10 / 20))
    for a in range(0, 360, 30):
        g = c + r * cmath.exp(1j * math.radians(a))
        assert ms.db20(ms.mismatch(g, gin)) == pytest.approx(-10.0, abs=1e-9)
    assert ms.mismatch(gin.conjugate(), gin) == pytest.approx(0, abs=1e-12)


def test_frequency_bound_equals_brute_force():
    s = fakes.core_s(19.45e9)
    npar = fakes.core_noise(19.45e9)
    npar = {"fmin": npar["fmin"], "rn_ohm": npar["rn"], "zopt": npar["zopt"]}
    b = ms.frequency_bound(s, npar, 50.0, 2.5, -10.0)
    gopt = ms.gamma(npar["zopt"])

    def nf(g):
        return 10 * math.log10(ms.nf_lin_at(g, npar["fmin"], npar["rn_ohm"] / 50, gopt))

    # the reported point is feasible and has the reported NF
    g_b = complex(*b["gamma_at_nf_bound"])
    assert ms.db20(ms.mismatch(g_b, s["s11"])) <= -10 + 1e-6
    assert nf(g_b) == pytest.approx(b["nf_bound_db"], abs=1e-9)
    # and no feasible sample in the mismatch disk beats it
    c, r = ms.mismatch_circle(s["s11"], 10 ** (-0.5))
    rng = random.Random(1)
    best = float("inf")
    for _ in range(100000):
        g = c + r * math.sqrt(rng.random()) * cmath.exp(2j * math.pi * rng.random())
        best = min(best, nf(g))
    assert b["nf_bound_db"] <= best + 1e-9 and b["nf_bound_db"] == pytest.approx(best, abs=5e-3)
    # s11 bound: Fmin here is below 2.5 dB, so a minimum mismatch on the 2.5 dB noise circle exists
    assert b["s11_bound_db"] is not None and b["s11_bound_db"] > -10


def test_point_bound_on_fake_core_is_exact_and_model_check_passes():
    names = ["baseline", "seg0375_b"] + [c.name for c in ST.candidates if c.role == "probe"]
    pl = ms.parse_log(fakes.fake_log(ST, names, "hbt_typ", 27.0, 2.5))
    b = ms.point_bound(ST, pl.tables, [ST.candidate(n) for n in names])
    assert b["valid"], b["problems"]
    r = b["rows"][35]
    assert r["fmin_db"] == pytest.approx(10 * math.log10(fakes.core_noise(r["f_hz"])["fmin"]), abs=1e-6)
    assert complex(*r["zopt"]) == pytest.approx(fakes.core_noise(r["f_hz"])["zopt"], abs=1e-3)
    assert b["summary"]["model_check_worst_db"] < 1e-4


def test_point_bound_needs_enough_probes():
    names = ["baseline", "probe_thru", "probe_r50a000_b"]
    pl = ms.parse_log(fakes.fake_log(ST, names, "hbt_typ", 27.0, 2.5))
    b = ms.point_bound(ST, pl.tables, [ST.candidate(n) for n in names])
    assert not b["valid"] and "usable probes" in b["problems"][0]


# --- screen, shortlist, gate, conclusion -------------------------------------------


def _synthetic(name, nf, s11, s21=15.0, k=3.0, status="ok", role="candidate"):
    sm = dict(nf_max_db=nf, s11_max_db=s11, s21_min_db=s21, k_min=k, delta_max=0.3, wide_k_min=k,
              wide_delta_max=0.5)
    c = {"candidate": name, "role": role, "status": status, "summary": sm, "op": {"pass": True}}
    c["screen"] = ms.screen_cell(ST, c) if status == "ok" else {"pass": False, "reasons": ["x"], "joint_margin_db": None}
    return c


def test_screen_names_every_failed_threshold():
    c = _synthetic("x", 3.0, -5.0, s21=8.0, k=0.9)
    reasons = " | ".join(c["screen"]["reasons"])
    for frag in ("NF max", "S11 max", "S21 min", "k min"):
        assert frag in reasons
    assert _synthetic("y", 2.4, -11.0)["screen"]["pass"]


def test_shortlist_rule_is_deterministic_and_excludes_probes_unstable_invalid():
    cells = [_synthetic("baseline", 3.9, -4.7, role="baseline"),
             _synthetic("a", 2.0, -4.0), _synthetic("b", 3.0, -12.0), _synthetic("c", 2.55, -9.8),
             _synthetic("d", 1.5, -20.0, k=0.95), _synthetic("e", 1.0, -30.0, status="rejected_invalid"),
             _synthetic("probe_x", 1.0, -30.0, role="probe")]
    sl = ms.shortlist(ST, cells)
    assert sl["names"][0] == "baseline"
    assert set(sl["names"]) == {"baseline", "a", "b", "c"}
    assert "lowest in-band NF max" in sl["why"]["a"] and "lowest in-band S11 max" in sl["why"]["b"]
    assert sl["why"]["c"] == ["best joint margin"]
    assert sl == ms.shortlist(ST, list(reversed(cells)))


def _collection_cells(shortlist):
    names = ms.corner_deck_names(ST, shortlist)
    cells = []
    n = ST.nominal
    pl = ms.parse_log(fakes.fake_log(ST, [c.name for c in ST.candidates], n["process"], n["temp_c"], n["vdd"]))
    for c in ST.candidates:
        cells.append(ms.make_cell(ST, "screen", c, n["process"], n["temp_c"], n["vdd"], pl.tables[c.name], pl.op))
    for p, t, v in ST.pvt_points():
        pl = ms.parse_log(fakes.fake_log(ST, names, p, t, v))
        for name in names:
            cells.append(ms.make_cell(ST, "corners", ST.candidate(name), p, t, v, pl.tables[name], pl.op))
    return cells


@pytest.fixture(scope="module")
def coll():
    return _collection_cells(["baseline", "seg0375_b"])


def test_gate_accepts_a_complete_collection(coll):
    assert ms.validate_collection(ST, coll, ["baseline", "seg0375_b"]) == []


def test_gate_rejects_missing_duplicate_undeclared_and_bad_status(coll):
    sl = ["baseline", "seg0375_b"]
    assert any("missing declared cell" in p for p in ms.validate_collection(ST, coll[1:], sl))
    assert any("duplicate cell" in p for p in ms.validate_collection(ST, coll + [coll[0]], sl))
    extra = dict(coll[0], id="screen__nope__hbt_typ_27c_2.50v")
    assert any("undeclared cell" in p for p in ms.validate_collection(ST, coll + [extra], sl))
    bad = [dict(c) for c in coll]
    bad[0]["status"] = "error"
    assert any("status" in p for p in ms.validate_collection(ST, bad, sl))
    bad = [dict(c) for c in coll]
    bad[3] = dict(bad[3], model_section="hbt_wcs")
    assert any("model section" in p for p in ms.validate_collection(ST, bad, sl))


def test_gate_sabotage_control_catches_ignored_corners(coll):
    sab = []
    typ = {(c["candidate"], c["temp_c"], c["vdd_v"]): c for c in coll
           if c["phase"] == "corners" and c["process"] == "hbt_typ"}
    for c in coll:
        if c["phase"] == "corners" and c["process"] != "hbt_typ":
            c = dict(c, summary=typ[(c["candidate"], c["temp_c"], c["vdd_v"])]["summary"])
        sab.append(c)
    assert any("do not move" in p for p in ms.validate_collection(ST, sab, ["baseline", "seg0375_b"]))


def test_conclusion_keeps_the_excursion_separate(coll):
    concl = ms.conclude(ST, coll, {"names": ["baseline", "seg0375_b"]})
    v = concl["per_candidate"]["seg0375_b"]
    assert v["in_rail_cells"] == 18
    assert all("2.75v" not in x for x in v["in_rail_fail"])
    assert all("2.75v" in x for x in v["excursion_fail"]) and v["excursion_fail"]


def test_compare_baseline_uses_band_edges_and_centre():
    pl, cell = _cell("baseline")
    b = cell["band"]
    old = {}
    for suf, i in (("lo", 0), ("mid", 35), ("hi", 70)):
        for q in ("s11", "s21", "s22", "s12"):
            old[f"{q}_db_{suf}"] = b[f"{q}_db"][i]
        old[f"nf_db_{suf}"] = b["nf_db"][i]
        old[f"k_{suf}"] = b["k"][i]
    assert ms.compare_baseline(ST, cell, old)["problems"] == []
    old["nf_db_mid"] += 0.01
    assert ms.compare_baseline(ST, cell, old)["problems"]
