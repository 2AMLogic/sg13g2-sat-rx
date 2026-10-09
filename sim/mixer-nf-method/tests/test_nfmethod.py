"""Tests for the mixer SSB-NF method definition and status gates (issue #27).

No simulator needed (analytic and numpy fixtures; the committed probe log is
re-parsed, not re-run). From the repo root:

    python3 -m pytest sim/mixer-nf-method/tests -q
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import nfmethod as M  # noqa: E402
import run_probe as P  # noqa: E402

KT0 = M.K_B * M.T0_K


# ---------------------------------------------------------------- PSD / ENBW

def test_hann_enbw_is_1p5_bins_and_rect_is_1():
    assert M.enbw_bins(M.window("hann", 4096)) == pytest.approx(1.5, rel=1e-9)
    assert M.enbw_bins(M.window("rect", 4096)) == pytest.approx(1.0)


@pytest.mark.parametrize("win", ["hann", "rect"])
def test_white_noise_one_sided_level_and_parseval(win):
    rng = np.random.default_rng(1)
    fs, sigma, n = 1e9, 1e-3, 1 << 16
    x = rng.normal(0.0, sigma, n)
    f, psd, meta = M.one_sided_psd(x, fs, win)
    # one-sided white level 2 sigma^2 / fs
    inner = psd[10:-10]
    assert inner.mean() == pytest.approx(2 * sigma ** 2 / fs, rel=0.02)
    assert M.check_parseval(x, psd, meta) == pytest.approx(1.0, abs=0.03)
    p, bw = M.band_power(f, psd, meta, 0.1e9, 0.3e9)
    assert p / bw == pytest.approx(2 * sigma ** 2 / fs, rel=0.03)


def test_two_sided_psd_is_rejected():
    rng = np.random.default_rng(2)
    x = rng.normal(size=1 << 14)
    f, psd, meta = M.one_sided_psd(x, 1.0)
    with pytest.raises(M.NormalizationError):
        M.check_parseval(x, psd / 2.0, meta)  # a two-sided level integrated over 0..fs/2


def test_window_power_uncorrected_psd_is_rejected():
    rng = np.random.default_rng(3)
    x = rng.normal(size=1 << 14)
    f, psd, meta = M.one_sided_psd(x, 1.0, "hann")
    # dividing by N instead of sum(w^2) (forgetting the window power) is off by 1/0.375
    w = M.window("hann", x.size)
    wrong = psd * float(np.sum(w * w)) / x.size
    with pytest.raises(M.NormalizationError):
        M.check_parseval(x, wrong, meta)


def test_undeclared_one_sided_psd_is_rejected():
    rng = np.random.default_rng(4)
    x = rng.normal(size=1 << 12)
    f, psd, meta = M.one_sided_psd(x, 1.0)
    bad = dict(meta, one_sided=False)
    with pytest.raises(M.NormalizationError):
        M.check_parseval(x, psd, bad)
    with pytest.raises(M.NormalizationError):
        M.band_power(f, psd, bad, 0.1, 0.2)


@pytest.mark.parametrize("lo,hi", [(0.0, 0.1), (0.1, 0.5), (0.2, 0.6), (0.1, 0.1 + 1e-4)])
def test_invalid_bands_are_rejected(lo, hi):
    rng = np.random.default_rng(5)
    x = rng.normal(size=1 << 12)
    f, psd, meta = M.one_sided_psd(x, 1.0)
    with pytest.raises(M.NormalizationError):
        M.band_power(f, psd, meta, lo, hi)


# ----------------------------------------------------------- SSB / image

def _att_budget(loss, t_att=M.T0_K, gw_mix=1.0, gi_mix=1.0, bw=1e6, image=True):
    gw, gi = gw_mix / loss, gi_mix / loss
    t_out = M.T0_K / loss + t_att * (1 - 1 / loss)   # attenuator output temperature
    n_out = M.K_B * bw * t_out * (gw_mix + gi_mix)
    contrib = {"source_wanted": M.K_B * M.T0_K * bw * gw,
               "dut": M.K_B * bw * t_att * (1 - 1 / loss) * (gw_mix + gi_mix),
               "load": 0.0}
    if image:
        contrib["source_image"] = M.K_B * M.T0_K * bw * gi
    return M.NoiseBudget(bandwidth_hz=bw, gain_wanted=gw, gain_image=gi,
                         n_out_w=n_out, contributions=contrib)


@pytest.mark.parametrize("loss_db", [0.0, 3.0, 6.0, 10.0])
def test_attenuator_ideal_mixer_known_answer_equal_sidebands(loss_db):
    loss = 10 ** (loss_db / 10)
    f = M.ssb_noise_factor(_att_budget(loss))
    assert M.db(f) == pytest.approx(10 * math.log10(2) + loss_db, abs=1e-9)
    assert M.db(f) == pytest.approx(M.db(M.attenuator_ideal_mixer_f_ssb(loss, M.T0_K, 1, 1)), abs=1e-9)


def test_attenuator_at_other_temperature_and_unequal_sidebands():
    loss, ta = 4.0, 400.0
    b = _att_budget(loss, t_att=ta, gw_mix=1.0, gi_mix=0.25)
    assert M.ssb_noise_factor(b) == pytest.approx(
        M.attenuator_ideal_mixer_f_ssb(loss, ta, 1.0, 0.25), rel=1e-12)


def test_dsb_is_3db_below_ssb_for_equal_sidebands_and_labelled_separately():
    b = _att_budget(1.0)
    assert M.db(M.ssb_noise_factor(b)) - M.db(M.dsb_noise_factor(b)) == pytest.approx(
        10 * math.log10(2), abs=1e-12)
    assert M.ssb_noise_factor(b) == pytest.approx(2.0)
    assert M.dsb_noise_factor(b) == pytest.approx(1.0)


def test_omitted_image_gain_is_rejected():
    b = _att_budget(2.0)
    b.gain_image = None
    with pytest.raises(M.ImageAccountingError):
        M.ssb_noise_factor(b)


def test_omitted_image_noise_term_is_rejected():
    b = _att_budget(2.0, image=False)
    with pytest.raises(M.ImageAccountingError):
        M.ssb_noise_factor(b)


def test_dropping_image_noise_from_n_out_is_caught_by_accounting():
    b = _att_budget(2.0)
    b.n_out_w -= b.contributions["source_image"]   # silently omitted image noise
    with pytest.raises(M.MethodError):
        M.ssb_noise_factor(b)


def test_explicit_image_rejection_is_allowed():
    bw = 1e6
    b = M.NoiseBudget(bandwidth_hz=bw, gain_wanted=1.0, gain_image=0.0,
                      n_out_w=KT0 * bw, contributions={"source_wanted": KT0 * bw, "dut": 0.0, "load": 0.0})
    assert M.ssb_noise_factor(b) == pytest.approx(1.0)


def test_source_temperature_is_rereferenced_to_t0_in_both_sidebands():
    bw, g = 1e6, 1.0
    ts = 290.0   # simulated termination not at T0
    n = M.K_B * bw * ts * 2 * g
    b = M.NoiseBudget(bandwidth_hz=bw, gain_wanted=g, gain_image=g, n_out_w=n,
                      contributions={"source_wanted": n / 2, "source_image": n / 2, "dut": 0.0, "load": 0.0},
                      t_source_wanted_k=ts, t_source_image_k=ts)
    assert M.ssb_noise_factor(b) == pytest.approx(2.0, rel=1e-12)


@pytest.mark.parametrize("loss,ta,gi", [(1.0, M.T0_K, 1.0), (4.0, M.T0_K, 1.0), (4.0, 400.0, 0.3)])
def test_y_factor_route_converts_dsb_temperature_to_ssb(loss, ta, gi):
    """Hot/cold applied in both sidebands; analytic Y from the attenuator model."""
    gw = 1.0
    te_dsb = ta * (loss - 1)      # attenuator Te referred to its input
    th, tc = 3000.0, M.T0_K
    y = (th + te_dsb) / (tc + te_dsb)
    f = M.y_factor_f_ssb(y, th, tc, gw, gi)
    assert f == pytest.approx(M.attenuator_ideal_mixer_f_ssb(loss, ta, gw, gi), rel=1e-12)
    with pytest.raises(M.ImageAccountingError):
        M.y_factor_f_ssb(y, th, tc, gw, None)


def test_stochastic_ideal_mixer_known_answer_within_control_tolerance():
    """End-to-end estimator on generated data: white source noise at 'T0'
    (both sidebands) through an ideal multiplier 2cos(wLO t); wanted-sideband
    gain from a deterministic tone; 8 seeds; SSB F must recover 2 (3.01 dB)
    within the 0.25 dB control tolerance, with a 95% half-width <= 0.25 dB."""
    fs, n = 64e9, 1 << 15
    f_lo, f_if1, f_if2 = 16e9, 0.5e9, 1.5e9
    t = np.arange(n) / fs
    lo = 2 * np.cos(2 * np.pi * f_lo * t)
    sigma = 1.0
    n_in_psd = 2 * sigma ** 2 / fs          # one-sided source PSD (the 'k T0' level)
    # wanted-sideband gain: tone at f_lo + 1 GHz, coherent
    k = round(1e9 * n / fs)
    f_rf = f_lo + k * fs / n
    a = 1e-3
    y = a * np.cos(2 * np.pi * f_rf * t) * lo
    f, psd, meta = M.one_sided_psd(y, fs, "hann")
    p_if, _ = M.band_power(f, psd, meta, 0.9e9, 1.1e9)
    g_w = p_if / (a ** 2 / 2)
    assert g_w == pytest.approx(1.0, rel=1e-3)
    fl = []
    for seed in range(8):
        x = np.random.default_rng(100 + seed).normal(0.0, sigma, n)
        out = x * lo
        f, psd, meta = M.one_sided_psd(out, fs, "hann")
        M.check_parseval(out, psd, meta)
        p, bw = M.band_power(f, psd, meta, f_if1, f_if2)
        # both sidebands of the source land in the IF band: account them explicitly
        b = M.NoiseBudget(bandwidth_hz=bw, gain_wanted=g_w, gain_image=g_w, n_out_w=p,
                          contributions={"source_wanted": p / 2, "source_image": p / 2,
                                         "dut": 0.0, "load": 0.0})
        fl.append(p / (n_in_psd * bw * g_w))
        assert b.gain_image is not None
    ci = M.nf_interval(fl)
    assert abs(ci["nf_db"] - 10 * math.log10(2)) <= M.CONTROL_TOL_DB
    assert ci["halfwidth_db"] <= M.CI_HALFWIDTH_MAX_DB
    assert ci["n_seeds"] == 8


# --------------------------------------------------------------- statistics

def test_interval_matches_student_t():
    vals = [1.9, 2.0, 2.1, 2.0, 1.95, 2.05, 2.0, 2.0]
    ci = M.nf_interval(vals)
    s = float(np.std(vals, ddof=1))
    assert ci["halfwidth_lin"] == pytest.approx(2.365 * s / math.sqrt(8))
    with pytest.raises(M.MethodError):
        M.nf_interval([2.0])


# ------------------------------------------------------------- status gates

FULL_INV = {m: {"tran": M.SUPPORTED} for m in M.REQUIRED_TRAN_MECHANISMS}
GOOD_CTL = M.Controls(analytic_error_db=0.01, lo_off_hbt_error_db=0.1,
                      omission_detected=True, periodic_coverage=True)
GOOD_CONV = M.Convergence(n_seeds=8, ci_halfwidth_db=0.2, delta_duration_db=0.1,
                          delta_timestep_db=0.1, duration_doublings=1, bandwidth_hz=1e9)


def test_all_gates_pass_reaches_method_validation():
    assert M.decide_status(True, FULL_INV, GOOD_CTL, GOOD_CONV) == (M.METHOD_VALIDATION, [])


def test_runner_unavailable_is_capability_unavailable_not_model_absent():
    st, _ = M.decide_status(False, None)
    assert st == M.CAPABILITY_UNAVAILABLE
    st, _ = M.decide_status(False, FULL_INV, GOOD_CTL, GOOD_CONV)
    assert st == M.CAPABILITY_UNAVAILABLE


@pytest.mark.parametrize("missing", M.REQUIRED_TRAN_MECHANISMS)
@pytest.mark.parametrize("state", [M.UNSUPPORTED, M.UNKNOWN, None])
def test_incomplete_coverage_cannot_emit_method_validation(missing, state):
    inv = {m: dict(v) for m, v in FULL_INV.items()}
    if state is None:
        del inv[missing]
    else:
        inv[missing]["tran"] = state
    st, reasons = M.decide_status(True, inv, GOOD_CTL, GOOD_CONV)
    assert st == M.MODEL_ABSENT and any(missing in r for r in reasons)


@pytest.mark.parametrize("ctl", [
    M.Controls(0.01, 0.4, True, True),        # LO-off control misses
    M.Controls(0.01, 0.1, False, True),       # omission not detected
    M.Controls(0.01, 0.1, True, False),       # no periodic coverage
    M.Controls(0.01, None, True, True),
])
def test_failed_coverage_controls_cannot_emit_method_validation(ctl):
    st, _ = M.decide_status(True, FULL_INV, ctl, GOOD_CONV)
    assert st == M.MODEL_ABSENT


def test_failed_analytic_control_raises_instead_of_recording():
    with pytest.raises(M.MethodError):
        M.decide_status(True, FULL_INV, M.Controls(0.3, 0.1, True, True), GOOD_CONV)
    with pytest.raises(M.MethodError):
        M.decide_status(True, FULL_INV, None, GOOD_CONV)


@pytest.mark.parametrize("field,value", [
    ("n_seeds", 7), ("ci_halfwidth_db", 0.26), ("delta_duration_db", 0.3),
    ("delta_duration_db", None), ("delta_timestep_db", -0.3), ("delta_timestep_db", None),
    ("duration_doublings", 4), ("bandwidth_hz", 0.0), ("ci_halfwidth_db", math.nan),
])
def test_failed_convergence_is_unconverged(field, value):
    conv = M.Convergence(**dict(vars(GOOD_CONV), **{field: value}))
    st, reasons = M.decide_status(True, FULL_INV, GOOD_CTL, conv)
    assert st == M.UNCONVERGED and reasons
    assert M.decide_status(True, FULL_INV, GOOD_CTL, None)[0] == M.UNCONVERGED


# ----------------------------------------------------------- probe parsing

def _log(a_diff="0", b_pp="2.6e-08", r_pp="0", c3="9e-4"):
    out = f"""MARK A_points_seed1=24008 A_points_seed2=24008
MARK A_coll_pp_lo_on_window=0.46
MARK A_coll_seed_diff_max={a_diff}
MARK B_coll_pp_lo_off={b_pp} B_coll_dc=1.58
MARK B_rdiv_pp={r_pp} B_tnl_pp_trnoise_off=0
MARK C_tnl_rms_seed1=0.00042 C_tnl_at21n_seed1=0.001 C_tnl_at23n_seed1=-0.0003
MARK C_tnl_rms_seed2=0.00041 C_tnl_at21n_seed2=-0.001 C_tnl_at23n_seed2=0.0005
MARK C_tnl_at21n_seed1_repeat={c3} C_tnl_at23n_seed1_repeat=0.0002
onoise_total = 2.5e-03
onoise_total_q.xq1.qnpn13g2_ic = 1.0e-03
onoise_total_q.xq1.qnpn13g2_iccp = 2.0e-16
onoise_total_q.xq1.qnpn13g2_ib = 1.5e-04
onoise_total_q.xq1.qnpn13g2_ibep = 5.7e-08
onoise_total_q.xq1.qnpn13g2_rb = 7.5e-04
onoise_total_q.xq1.qnpn13g2_rbi = 1.0e-03
onoise_total_q.xq1.qnpn13g2_1overfbe = 2.5e-06
onoise_total_rc_thermal = 5.0e-04
MARK done
"""
    return out, "pss: no such command available in ngspice\n"


def test_flat_deterministic_probe_is_model_absent():
    inv = P.build_inventory(P.parse_log(*_log()))
    mech = inv["mechanisms"]
    for m in ("hbt_shot_collector", "hbt_shot_base", "hbt_terminal_resistor_thermal",
              "hbt_flicker", "resistor_thermal"):
        assert mech[m]["tran"] == M.UNSUPPORTED, m
    assert mech["external_trnoise_injection"]["tran"] == M.SUPPORTED
    assert mech["pss_pnoise"]["noise_analysis"] == M.UNSUPPORTED
    st, _ = M.decide_status(True, mech, P.controls_from_inventory(inv))
    assert st == M.MODEL_ABSENT


def test_run_to_run_difference_is_not_called_unsupported():
    inv = P.build_inventory(P.parse_log(*_log(a_diff="1e-5")))
    assert inv["mechanisms"]["hbt_shot_collector"]["tran"] == M.UNKNOWN
    # still not METHOD_VALIDATION: unknown coverage is not coverage
    st, _ = M.decide_status(True, inv["mechanisms"], P.controls_from_inventory(inv))
    assert st == M.MODEL_ABSENT


def test_visible_noise_floor_is_not_called_unsupported():
    inv = P.build_inventory(P.parse_log(*_log(b_pp="1e-3", r_pp="1e-3")))
    assert inv["mechanisms"]["hbt_shot_collector"]["tran"] == M.UNKNOWN
    assert inv["mechanisms"]["resistor_thermal"]["tran"] == M.UNKNOWN


def test_incomplete_log_raises():
    out, err = _log()
    with pytest.raises(M.MethodError):
        P.build_inventory(P.parse_log(out.replace("MARK done", ""), err))
    with pytest.raises(M.MethodError):
        P.build_inventory(P.parse_log(out.replace("MARK A_coll_seed_diff_max=0", ""), err))


def test_committed_probe_logs_reparse_to_their_record_status():
    logs = sorted((HERE / "probe-logs").glob("*/stdout.txt"))
    if not logs:
        pytest.skip("no committed probe log")
    for stdout in logs:
        d = stdout.parent
        inv = P.build_inventory(P.parse_log(stdout.read_text(), (d / "stderr.txt").read_text()))
        st, _ = M.decide_status(True, inv["mechanisms"], P.controls_from_inventory(inv))
        recs = list((HERE / "records").glob(f"{d.name}-*.md"))
        assert recs, f"probe log {d.name} has no record"
        assert recs[0].name == f"{d.name}-{st}.md"
        assert st != M.METHOD_VALIDATION
