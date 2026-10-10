"""Method qualification tests for the LNA nonlinear characterization (issue #57).

Analytic positive controls, negative controls, convergence verdicts, deck generation
and log parsing. No simulator, PDK or network.

    python3 -m pytest sim/lna-linearity/tests -q
"""

from __future__ import annotations

import copy
import math

import pytest

import analysis as A
import fakes
import linearity as L
from conftest import BENCH

PLAN = L.load_plan(BENCH / "testbench" / "plan.json")
C = PLAN["controls"]


def plan() -> dict:
    return copy.deepcopy(PLAN)


# ---- conventions ------------------------------------------------------------


def test_available_power_convention():
    assert L.vs_peak_from_pav_dbm(0.0) == pytest.approx(math.sqrt(8 * 50 * 1e-3))
    assert L.pav_dbm_from_vs_peak(L.vs_peak_from_pav_dbm(-37.3)) == pytest.approx(-37.3)
    # a 1 V peak component delivers 10 mW into 50 ohm  -> 10 dBm
    assert L.delivered_dbm(1.0) == pytest.approx(10.0)


def test_plan_is_declared_in_band_and_coherent():
    assert [] == [p for pl in PLAN["placements"] for p in L.band_problems(PLAN, pl)]
    for pl in PLAN["placements"]:
        for v in L.VARIANTS:
            assert L.placement_coherence(PLAN, pl, v) == []
    assert L.sweep_pins(PLAN, "two")[0] == -56.0 and L.sweep_pins(PLAN, "two")[-1] == -36.0
    assert L.sweep_pins(PLAN, "one")[0] == -56.0 and L.sweep_pins(PLAN, "one")[-1] == -16.0
    assert len(L.sweep_pins(PLAN, "two")) == 21 and len(L.sweep_pins(PLAN, "one")) == 21


def test_out_of_band_placement_rejected():
    pl = {"name": "bad", "f_tone1_hz": 17.75e9, "f_tone2_hz": 17.85e9}  # IM3 low = 17.65 GHz < 17.7
    assert any("im3l" in p for p in L.band_problems(PLAN, pl))


def test_tones_and_products_are_on_the_bin_grid():
    for pl in PLAN["placements"]:
        for kind in ("two", "one"):
            for name, f in L.analysis_bins(PLAN, pl, kind).items():
                for v in L.VARIANTS:
                    cyc = f * L.variant_timing(PLAN, v)["window_s"]
                    assert cyc == pytest.approx(round(cyc), abs=1e-6), (pl["name"], name, v)


# ---- reference DFT normalization ---------------------------------------------


def _samples(n, h, comps):
    return [sum(a * math.sin(2 * math.pi * f * k * h + ph) for f, a, ph in comps) for k in range(n)]


def test_window_dft_recovers_peak_amplitude_and_ignores_other_bins():
    h, n = 1.0, 400
    x = _samples(n, h, [(0.05, 0.7, 0.3), (0.0725, 0.02, 1.1)])
    assert L.window_dft(x, h, 0.05) == pytest.approx(0.7, rel=1e-9)
    assert L.window_dft(x, h, 0.0725) == pytest.approx(0.02, rel=1e-9)
    assert L.window_dft(x, h, 0.1) < 1e-12


def test_noncoherent_tone_leaks_and_is_flagged():
    h, n = 1.0, 400
    f = 0.05 + 0.3 / (n * h)  # 0.3 bin off the grid
    x = _samples(n, h, [(f, 1.0, 0.0)])
    assert abs(L.window_dft(x, h, 0.05) - 1.0) > 0.05  # analysed at the planned bin: scalloping error
    assert L.window_dft(x, h, f + 3.0 / (n * h)) > 1e-3  # leakage far from the tone
    assert L.coherence_problems({"tone": f}, n * h, h)
    assert L.coherence_problems({"tone": 0.05}, n * h, h) == []


def test_cubic_closed_forms_match_a_brute_force_dft():
    """The 9/4 (two-tone fundamental), 3/4 (IM3) and 3/4 (single tone) cubic coefficients, verified by transform."""
    a1, a3, a = 3.0, -1.7, 0.2
    h, n = 1.0, 2000
    f1, f2 = 0.0500, 0.0600  # both multiples of 1/(n*h) = 0.0005
    x = [a1 * s + a3 * s ** 3 for s in _samples(n, h, [(f1, a, 0.4), (f2, a, 1.3)])]
    assert L.window_dft(x, h, f1) == pytest.approx(abs(a1 * a + 2.25 * a3 * a ** 3), rel=1e-9)
    assert L.window_dft(x, h, 2 * f1 - f2) == pytest.approx(0.75 * abs(a3) * a ** 3, rel=1e-9)
    assert L.window_dft(x, h, 2 * f2 - f1) == pytest.approx(0.75 * abs(a3) * a ** 3, rel=1e-9)
    y = [a1 * s + a3 * s ** 3 for s in _samples(n, h, [(f1, a, 0.4)])]
    assert L.window_dft(y, h, f1) == pytest.approx(abs(a1 * a + 0.75 * a3 * a ** 3), rel=1e-9)


def test_closed_form_iip3_p1db_definitions():
    exp = L.cubic_expectations(C["a1"], C["a3"])
    # IIP3: fundamental and IM3 amplitudes (linear extrapolation) are equal at A^2 = 4/3 |a1/a3|
    a_in = math.sqrt(4.0 / 3.0 * abs(C["a1"] / C["a3"]))
    assert C["a1"] * a_in == pytest.approx(0.75 * abs(C["a3"]) * a_in ** 3)
    assert exp["iip3_dbm"] == pytest.approx(L.pav_dbm_from_vs_peak(2 * a_in))
    # P1dB: the single-tone fundamental is exactly 1 dB below linear there
    a_p = math.sqrt((10 ** (-1 / 20) - 1) / (0.75 * C["a3"] / C["a1"]))
    assert 20 * math.log10((C["a1"] * a_p + 0.75 * C["a3"] * a_p ** 3) / (C["a1"] * a_p)) == pytest.approx(-1.0)
    assert exp["p1db_in_dbm"] == pytest.approx(L.pav_dbm_from_vs_peak(2 * a_p))
    assert exp["iip3_dbm"] - exp["p1db_in_dbm"] == pytest.approx(9.64, abs=0.01)  # the textbook cubic offset
    assert exp["gain_db"] == pytest.approx(10 * math.log10(C["a1"] ** 2 / 4))


# ---- positive controls -------------------------------------------------------


@pytest.mark.parametrize("floor_v", [1e-9, 1e-7, 1e-6])
@pytest.mark.parametrize("kind", ["two", "one"])
def test_analytic_positive_controls_recover_declared_coefficients(kind, floor_v):
    rows = L.synthetic_rows(PLAN, C["a1"], C["a3"], floor_v, kind=kind)
    ev = L.evaluate_control(PLAN, kind, rows, C["a1"], C["a3"])
    assert ev["pass"], ev
    assert abs(ev["error_db"]) <= ev["tol_db"] and abs(ev["gain_error_db"]) <= ev["gain_tol_db"]


def test_iip3_uses_a_one_to_three_region_and_reports_the_interval():
    rows = L.synthetic_rows(PLAN, C["a1"], C["a3"], 1e-6, kind="two")
    r = L.fit_iip3(rows, PLAN["extraction"]["iip3"], None, enforce_limits=False)
    assert r["status"] == "ok"
    for side in ("low", "high"):
        s = r["sidebands"][side]
        assert 0.9 <= s["slope_fund"] <= 1.1 and 2.7 <= s["slope_im3"] <= 3.3
        assert s["n_points"] >= 4 and s["interval_dbm"][1] > s["interval_dbm"][0]
        assert s["extrapolation_db"] > 0
        assert s["baseline"]["n_points"] == 3


# ---- negative controls -------------------------------------------------------


def test_every_negative_control_is_rejected():
    neg = L.negative_controls(PLAN)
    assert neg and all(n["rejected"] for n in neg), [n["name"] for n in neg if not n["rejected"]]
    names = {n["name"] for n in neg}
    for want in ("noncoherent_tone_placement", "below_floor_im3", "missing_1_to_3_slope_region", "unbracketed_p1db",
                 "no_small_signal_baseline", "out_of_limit_points_not_fitted_through"):
        assert want in names
    assert any(n.startswith("wrong_amplitude_normalization") for n in names)
    assert any(n.startswith("wrong_power_axis") for n in names)


def test_negative_control_would_notice_a_blind_estimator():
    """Meta-test: the gain check is what catches a common output-scale fault (IIP3/P1dB cannot see it)."""
    for kind in ("two", "one"):
        rows = L.synthetic_rows(PLAN, C["a1"], C["a3"], 1e-6, kind=kind, scale=2.0)
        ev = L.evaluate_control(PLAN, kind, rows, C["a1"], C["a3"])
        assert abs(ev["error_db"]) <= ev["tol_db"]   # input-referred quantity is blind to it
        assert not ev["pass"]                        # but the control as a whole is not


def test_below_floor_im3_is_unavailable_not_extrapolated():
    rows = L.synthetic_rows(PLAN, C["a1"], C["a3"], 1e-6, kind="two")
    for r in rows:  # bury IM3 under the floor everywhere
        r["p_im3l_dbm"] = r["floor_dbm"] + 3.0
        r["p_im3h_dbm"] = r["floor_dbm"] + 3.0
    r = L.fit_iip3(rows, PLAN["extraction"]["iip3"], None, enforce_limits=False)
    assert r["status"] == "unavailable" and "sideband" in r["reason"]
    assert all("floor" in "".join(s["excluded_points"].values()) for s in r["sidebands"].values())


def test_single_usable_pair_is_not_enough():
    rows = L.synthetic_rows(PLAN, C["a1"], C["a3"], 1e-6, kind="two")[:3]
    assert L.fit_iip3(rows, PLAN["extraction"]["iip3"], None, enforce_limits=False)["status"] == "unavailable"


def test_p1db_unbracketed_is_a_bound():
    rows = [r for r in L.synthetic_rows(PLAN, C["a1"], C["a3"], 1e-6, kind="one") if r["pin_dbm"] <= -30]
    r = L.fit_p1db(rows, PLAN["extraction"]["p1db"], None, enforce_limits=False)
    assert r["status"] == "bounded" and r["p1db_in_dbm_gt"] == -30.0 and "p1db_in_dbm" not in r


def test_p1db_ok_reports_baseline_and_bracket():
    rows = L.synthetic_rows(PLAN, C["a1"], C["a3"], 1e-6, kind="one")
    r = L.fit_p1db(rows, PLAN["extraction"]["p1db"], None, enforce_limits=False)
    assert r["status"] == "ok"
    x0, x1 = r["bracket"]["pin_dbm"]
    assert x0 < r["p1db_in_dbm"] <= x1
    d0, d1 = r["bracket"]["drop_db"]
    assert d0 < 1.0 <= d1
    assert r["baseline"]["gain_db"] == pytest.approx(L.cubic_expectations(C["a1"], C["a3"])["gain_db"], abs=0.05)
    assert r["p1db_out_dbm"] == pytest.approx(r["p1db_in_dbm"] + r["baseline"]["gain_db"] - 1.0)


def test_out_of_limit_points_break_the_fit_instead_of_being_fitted_through():
    rows = L.synthetic_rows(PLAN, C["a1"], C["a3"], 1e-6, kind="one")
    ok = {"vce_q1_max": 1.2, "vce_q1_min": 1.2, "vce_q2_max": 1.2, "vce_q2_min": 1.2,
          "vbe_q1_max": 0.8, "vbe_q1_min": 0.8, "vbe_q2_max": 0.8, "vbe_q2_min": 0.8}
    for r in rows:
        r["excursion_v"] = dict(ok, vce_q2_max=1.6 if r["pin_dbm"] >= -28 else 1.2)
    lim = PLAN["extraction"]["operating_limits"]
    r = L.fit_p1db(rows, PLAN["extraction"]["p1db"], lim)
    assert r["status"] == "bounded" and "rejected" in r["reason"]
    free = L.fit_p1db(rows, PLAN["extraction"]["p1db"], lim, enforce_limits=False)
    assert free["status"] == "ok"
    # unmonitored points are never fitted through either
    for r_ in rows:
        r_["excursion_v"] = None
    assert L.fit_p1db(rows, PLAN["extraction"]["p1db"], lim)["status"] == "unavailable"


# ---- convergence -------------------------------------------------------------


def _conv(kind, base_rows, other_rows):
    ex = PLAN["extraction"]
    fit = (lambda r: L.fit_iip3(r, ex["iip3"], None, enforce_limits=False)) if kind == "iip3" else \
        (lambda r: L.fit_p1db(r, ex["p1db"], None, enforce_limits=False))
    return L.convergence_verdict(PLAN, kind, base_rows, fit(base_rows), other_rows, fit(other_rows), "t")


def test_identical_refinement_converges():
    two = L.synthetic_rows(PLAN, C["a1"], C["a3"], 1e-6, kind="two")
    one = L.synthetic_rows(PLAN, C["a1"], C["a3"], 1e-6, kind="one")
    assert _conv("iip3", two, copy.deepcopy(two))["ok"]
    assert _conv("p1db", one, copy.deepcopy(one))["ok"]


def test_iip3_convergence_failure_is_explicit():
    two = L.synthetic_rows(PLAN, C["a1"], C["a3"], 1e-6, kind="two")
    other = copy.deepcopy(two)
    for r in other:
        r["p_im3l_dbm"] += 1.2
        r["p_im3h_dbm"] += 1.2
    v = _conv("iip3", two, other)
    assert not v["ok"] and not v["estimator"]["ok"] and "dB" in v["estimator"]["reason"]


def test_pointwise_disagreement_inside_the_fit_fails_even_if_the_estimate_agrees():
    two = L.synthetic_rows(PLAN, C["a1"], C["a3"], 1e-6, kind="two")
    other = copy.deepcopy(two)
    mid = next(r for r in other if r["pin_dbm"] == -40.0)
    mid["p_f1_dbm"] += 0.3   # one fundamental off by 0.3 dB: larger than point_fund_tol_db
    v = _conv("iip3", two, other)
    assert v["estimator"]["ok"] and not v["pointwise_ok"] and not v["ok"]


def test_p1db_convergence_failure_and_status_change():
    one = L.synthetic_rows(PLAN, C["a1"], C["a3"], 1e-6, kind="one")
    other = copy.deepcopy(one)
    for r in other:
        if r["pin_dbm"] >= -24:
            r["p_f0_dbm"] -= 0.4
    assert not _conv("p1db", one, other)["ok"]
    trunc = [r for r in one if r["pin_dbm"] <= -34]
    v = _conv("p1db", one, trunc)
    assert not v["ok"] and "status differs" in v["estimator"]["reason"]


def test_both_unavailable_agree_but_nothing_is_claimed():
    est = L.compare_estimates("iip3", {"status": "unavailable"}, {"status": "unavailable"}, 0.25, 2.0)
    assert est["ok"] and est["delta_db"] is None


# ---- decks and logs ----------------------------------------------------------


def test_run_block_geometry_and_normalization_text():
    pl = PLAN["placements"][1]
    runs = L.sweep_runs(PLAN, pl, "two", monitors=True)
    assert len(runs) == 3 * len(L.sweep_pins(PLAN, "two"))
    assert {r["variant"] for r in runs} == set(L.VARIANTS)
    base = [r for r in runs if r["variant"] == "base"]
    body = L.body_for_runs("t", L.dut_circuit("* dut\n.subckt lna_stage1 in out vdd gnd\n.ends", 2.5), base)
    # discard 40 ns / 1 ps = 40000, window 20 ns = 20000 samples: indices 40000..59999, tran starts at 0
    assert "let tt = time[40000,59999]" in body and "tran 1e-12 6e-08 0 1e-12" in body
    assert "2*mean(xo*cos(2*pi*" in body and "2*mean(xo*sin(2*pi*" in body
    assert "alterparam fq1" in body and "linearize v(p2)" in body and "LNLIN_DONE" in body
    half = L.body_for_runs("t", "", [r for r in runs if r["variant"] == "half_step"])
    assert "time[80000,119999]" in half and "tran 5e-13 6e-08 0 5e-13" in half
    dbl = L.body_for_runs("t", "", [r for r in runs if r["variant"] == "double_window"])
    assert "time[40000,79999]" in dbl
    # two-tone runs drive both tones equally, single-tone runs drive one
    assert all(r["va1"] == r["va2"] for r in runs)
    assert all(r["va2"] == 0.0 for r in L.sweep_runs(PLAN, pl, "one", monitors=True))
    assert L.options_line(PLAN, "two") == ".options reltol=1e-07 trtol=1.0"
    assert L.options_line(PLAN, "one") == ".options reltol=1e-06"
    ids = [r["id"] for r in runs]
    assert len(set(ids)) == len(ids)


def test_request_layout_is_one_request_per_subject_and_kind():
    keys = A.request_keys(PLAN)
    assert keys == ["control_two", "control_one", "low_two", "low_one", "mid_two", "mid_one", "high_two", "high_one"]
    assert {r["variant"] for r in A.runs_for_key(PLAN, "control_two")} == {"base"}
    assert {r["variant"] for r in A.runs_for_key(PLAN, "mid_one")} == set(L.VARIANTS)
    assert all(r["monitors"] for r in A.runs_for_key(PLAN, "mid_one"))
    assert not any(r["monitors"] for r in A.runs_for_key(PLAN, "control_one"))


def test_parse_and_summary_reject_incomplete_runs():
    logs = fakes.fake_logs(PLAN)
    s, probs = A.summaries_for_key(PLAN, "mid_two", logs["mid_two"])
    assert probs == [] and len(s) == 3 * len(L.sweep_pins(PLAN, "two"))
    cut = "\n".join(ln for ln in logs["mid_two"].splitlines() if not ln.startswith("m_b_two05_im3l_c"))
    s, probs = A.summaries_for_key(PLAN, "mid_two", cut)
    assert any("b_two05" in p for p in probs)
    s, probs = A.summaries_for_key(PLAN, "mid_two", logs["mid_two"].replace("LNLIN_DONE", ""))
    assert any("LNLIN_DONE" in p for p in probs)
    bad = logs["mid_one"].replace("m_b_one03_n = 2.000000000000e+04", "m_b_one03_n = 1.000000000000e+04")
    assert any("b_one03" in p for p in A.summaries_for_key(PLAN, "mid_one", bad)[1])


# ---- end to end on closed-form logs ------------------------------------------


def test_analyze_end_to_end_on_closed_form_logs():
    # limits break just above -40 dBm per tone (output amplitude grows with the input): 0.14 V swing at -40, limit 0.15 V
    amp40 = L.cubic_tone_amps(10.0, -2000.0, L.vs_peak_from_pav_dbm(-40.0), False)["f0"]
    res = A.analyze(PLAN, fakes.fake_logs(PLAN, excursion_per_v=0.14 / amp40, floor_v=1e-9))
    assert res["problems"] == [] and res["ngspice_control"]["pass"]
    exp = L.cubic_expectations(10.0, -2000.0)
    for name, pe in res["placements"].items():
        iip3 = pe["results"]["iip3"]
        assert iip3["status"] == "ok" and iip3["iip3_dbm"] == pytest.approx(exp["iip3_dbm"], abs=0.15)
        hi = max(s["interval_dbm"][1] for s in iip3["sidebands"].values())
        assert hi <= -40.0, "fit must stop before the operating-limit violation"
        p1 = pe["results"]["p1db"]
        assert p1["status"] == "bounded" and p1["p1db_in_dbm_gt"] <= -40.0
        assert pe["unrestricted_reference"]["p1db"]["status"] == "ok"
        assert pe["unrestricted_reference"]["p1db"]["p1db_in_dbm"] == pytest.approx(exp["p1db_in_dbm"], abs=0.1)
        assert -38.0 <= pe["first_limit_violation"]["single_tone"]["pin_dbm"] <= -36.0
        assert pe["final"]["iip3"]["status"] == "ok" and pe["final"]["p1db"]["status"] == "bounded"
    assert res["rows"]["7"]["worst_verdict"] in ("meets", "fails", "marginal")
    assert res["rows"]["8"]["kind"] == "p1db"


def test_analyze_without_limit_violation_gives_a_p1db_number():
    res = A.analyze(PLAN, fakes.fake_logs(PLAN))
    for pe in res["placements"].values():
        assert pe["final"]["p1db"]["status"] == "ok"
        assert pe["final"]["p1db"]["assessment"]["verdict"] in ("meets", "marginal", "fails")


def test_analyze_unconverged_when_a_refinement_disagrees():
    logs = fakes.fake_logs(PLAN)
    c = PLAN["controls"]
    logs["low_two"] = fakes.fake_log(PLAN, "low_two", a1=10.0, a3=-2000.0, im3_scale=3.0, only_variant="half_step")
    res = A.analyze(PLAN, logs)
    low = res["placements"]["low"]
    assert low["final"]["iip3"]["status"] == "unconverged" and not low["final"]["iip3"]["converged"]
    assert low["final"]["iip3"]["assessment"]["verdict"] == "not_determined"
    assert res["placements"]["mid"]["final"]["iip3"]["status"] == "ok"


def test_failing_ngspice_control_is_reported():
    logs = fakes.fake_logs(PLAN)
    logs["control_two"] = fakes.fake_log(PLAN, "control_two", a1=10.0, a3=-1000.0, floor_v=1e-9)  # not the declared coefficients
    res = A.analyze(PLAN, logs)
    assert not res["ngspice_control"]["pass"]


def test_missing_log_is_a_problem_not_a_result():
    logs = fakes.fake_logs(PLAN)
    del logs["high_one"]
    res = A.analyze(PLAN, logs)
    assert res["problems"] and "placements" not in res


def test_target_assessment_never_relaxes_and_uses_measured_spread():
    ok = {"status": "ok", "iip3_dbm": -14.9}
    assert A.assess_target("iip3", ok, -15.0, 0.05)["verdict"] == "meets"
    assert A.assess_target("iip3", ok, -15.0, 0.3)["verdict"] == "marginal"
    assert A.assess_target("iip3", {"status": "ok", "iip3_dbm": -16.0}, -15.0, 0.3)["verdict"] == "fails"
    assert A.assess_target("p1db", {"status": "bounded", "p1db_in_dbm_gt": -30.0}, -25.0, 0.0)["verdict"] == "not_determined"
    assert A.assess_target("p1db", {"status": "bounded", "p1db_in_dbm_gt": -20.0}, -25.0, 0.0)["verdict"] == "meets"
    assert A.assess_target("iip3", {"status": "unavailable"}, -15.0, 0.0)["verdict"] == "not_determined"


def test_aborted_transient_is_a_published_sweep_outcome_not_corruption():
    logs = fakes.fake_logs(PLAN)
    text = logs["mid_two"]
    # the simulator aborts the highest two-tone run: its values vanish and the log says why
    text = "\n".join(ln for ln in text.splitlines() if not ln.startswith("m_b_two20_"))
    abort = text + "\ndoAnalyses: TRAN:  Timestep too small; time = 1e-9, timestep = 1e-24\n"
    s, probs = A.summaries_for_key(PLAN, "mid_two", abort)
    assert probs == []
    failed = [x for x in s if x["status"] == "sim_failed"]
    assert [x["id"] for x in failed] == ["b_two20"]
    # without the abort message the same hole is a log-integrity problem
    assert A.summaries_for_key(PLAN, "mid_two", text)[1]
    rows = L.points_from_summaries([x for x in s if x["variant"] == "base"], "two")
    assert rows[-1]["sim_failed"] and rows[-1]["p_f1_dbm"] is None
    r = L.fit_iip3(rows, PLAN["extraction"]["iip3"], None, enforce_limits=False)
    assert r["status"] == "ok"
    assert any("simulation failed" in w for w in r["sidebands"]["low"]["excluded_points"].values())
    # a failed point inside the single-tone sweep stops the P1dB bracket instead of being interpolated across
    one = [dict(x) for x in L.synthetic_rows(PLAN, C["a1"], C["a3"], 1e-6, kind="one")]
    for x in one:
        if x["pin_dbm"] == -22.0:
            x.update(p_f0_dbm=None, sim_failed="aborted")
    p = L.fit_p1db(one, PLAN["extraction"]["p1db"], None, enforce_limits=False)
    assert p["status"] == "bounded" and "rejected" in p["reason"]
