"""Tests for the shared two-tone IIP3 estimator, ``harness.iip3`` (issue #276).

The engine owns the single ``linfit`` and the single gated run-selection
pipeline; ``mixfeas.fit_iip3`` and ``linearity.fit_iip3`` are wrappers over
it. These tests pin the engine directly and reproduce the four probe cases
of the issue's measured table as PROPERTIES, through both wrappers:

- cases A/B -- residual-free rows with ``s3 - s1 == 2``: all three intercept
  definitions agree exactly (with each other and with the true intercept);
- case C -- fractional slopes, noiseless: the free-slope intersection is
  still exact, ``mixfeas`` publishes it, and ``linearity`` returns
  ``unavailable`` via its injected free-vs-fixed cross-check while every
  shared gate passes;
- case D -- fractional slopes plus sub-tolerance IM3 scatter: both wrappers
  publish, each its own headline, measurably apart (the issue's table came
  from a different synthetic generator, so the decimals here are this
  generator's own and only the properties are pinned).

The wrappers' default return shapes are the pre-#276 ones (frozen records
pin them structurally); the full three-intercept shape surfaces behind each
wrapper's ``diagnostics=True`` and is pinned here too.

No simulator, no PDK. From the repo root:

    python3 -m pytest sim/harness/tests/test_iip3.py -q
"""

import math
import sys
from pathlib import Path

import pytest

SIM = Path(__file__).resolve().parents[2]
for _p in (SIM, SIM / "mixer-topology-feasibility", SIM / "lna-linearity"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import linearity as L  # noqa: E402
import mixfeas as mf  # noqa: E402

from harness import iip3  # noqa: E402

LIN_PARAMS = {"min_points": 3, "floor_margin_db": 10.0, "compression_db": 1.0,
              "slope_fund": (0.9, 1.1), "slope_im3": (2.7, 3.3), "max_residual_db": 0.5,
              "free_fixed_tol_db": 1.0, "max_point_spread_db": 1.5,
              "baseline_points": 3, "baseline_flat_db": 0.15}

CASE_D_NOISE = [0.30, -0.35, 0.20, -0.10, 0.15, -0.25, 0.10, -0.05]


def two_line_rows(s1, s3, iip3=10.0, *, lin, noise=None, n=8, step=4.0, start=-60.0,
                  gain=20.0, floor=-200.0):
    """Fractional-slope two-line sweep rows crossing exactly at ``iip3``:
    fund = y0 + s1 (pin - iip3), im3 = y0 + s3 (pin - iip3). ``lin`` selects
    linearity's row keys, otherwise mixfeas's point keys."""
    x0, y0 = iip3, iip3 + gain
    noise = noise if noise is not None else [0.0] * n
    out = []
    for i in range(n):
        p = start + step * i
        f = y0 + s1 * (p - x0)
        im = y0 + s3 * (p - x0) + noise[i]
        if lin:
            out.append({"pin_dbm": p, "p_f1_dbm": f, "p_f2_dbm": f, "p_im3l_dbm": im,
                        "p_im3h_dbm": im, "floor_dbm": floor, "excursion_v": None})
        else:
            out.append({"pin_dbm": p, "status": "ok", "p_if1_dbm": f, "p_if2_dbm": f,
                        "p_im3l_dbm": im, "p_im3h_dbm": im, "floor_dbm": floor})
    return out


# ---- linfit -----------------------------------------------------------------


def test_linfit_recovers_an_exact_line_and_reports_the_max_residual():
    assert iip3.linfit([0.0, 1.0, 2.0], [1.0, 3.0, 5.0]) == (1.0, 2.0, 0.0)
    xs_, ys_ = [0.0, 1.0, 2.0, 3.0], [1.0, 3.0, 5.0, 7.25]
    a, s, res = iip3.linfit(xs_, ys_)
    assert res > 0
    # the returned residual is the max deviation from the RETURNED line
    assert res == pytest.approx(max(abs(y - (a + s * x)) for x, y in zip(xs_, ys_)))


def test_linfit_has_exactly_one_definition_and_the_benches_do_not_restate_it():
    # issue #276's gate: `git grep -nE '^def _?linfit' -- 'sim/**/*.py'` must
    # return exactly one definition, in sim/harness/iip3.py -- the bench
    # modules carry no copy (mixfeas's used builtin sum, whose Python 3.12
    # compensated summation could differ from fsum in the last kept digit)
    assert not hasattr(mf, "_linfit")
    assert not hasattr(L, "linfit")


# ---- select_run -------------------------------------------------------------


def test_select_run_prefers_the_longest_run_and_ties_to_the_lowest_power():
    # exact 1/3 lines everywhere: every usable window qualifies, so the
    # longest usable run wins; two equal-length runs tie to the first (the
    # lowest-power one, the sweep being sorted)
    xs = [-30.0 + i for i in range(12)]
    fund = [x + 20.0 for x in xs]
    im3 = [3.0 * x - 20.0 for x in xs]
    usable = [False, False, True, True, True, False, False, True, True, True, False, False]
    best, rejected = iip3.select_run(xs=xs, fund_ys=fund, im3_ys=im3, usable=usable,
                                     min_points=3, slope_fund=(0.9, 1.1), slope_im3=(2.7, 3.3),
                                     max_residual_db=0.5)
    assert best["interval_dbm"] == [-28.0, -26.0] and best["n_points"] == 3 and rejected == []
    usable = [True] * 12
    best, _ = iip3.select_run(xs=xs, fund_ys=fund, im3_ys=im3, usable=usable,
                              min_points=3, slope_fund=(0.9, 1.1), slope_im3=(2.7, 3.3),
                              max_residual_db=0.5)
    assert best["interval_dbm"] == [-30.0, -19.0] and best["n_points"] == 12
    best, _ = iip3.select_run(xs=xs, fund_ys=fund, im3_ys=im3, usable=[False] * 12,
                              min_points=3, slope_fund=(0.9, 1.1), slope_im3=(2.7, 3.3),
                              max_residual_db=0.5)
    assert best is None


def test_select_run_gate_order_is_slopes_residual_then_injected_gates():
    xs = [-10.0, -5.0, 0.0, 5.0, 10.0]
    # slope 1.5 everywhere: every window is rejected on slopes, in scan order
    fund = [x + 20.0 + 0.5 * x for x in xs]
    im3 = [x + 20.0 for x in xs]
    best, rejected = iip3.select_run(xs=xs, fund_ys=fund, im3_ys=im3, usable=[True] * 5,
                                     min_points=3, slope_fund=(0.9, 1.1), slope_im3=(2.7, 3.3),
                                     max_residual_db=0.5)
    assert best is None
    assert [r["interval_dbm"] for r in rejected] == [[-10.0, 0.0], [-10.0, 5.0], [-10.0, 10.0],
                                                     [-5.0, 5.0], [-5.0, 10.0], [0.0, 10.0]]
    assert all(r["reason"].startswith("slopes ") for r in rejected)
    # exact lines but zero residual budget: scatter the IM3 reads slightly so
    # every window carries a nonzero residual and the residual gate fires
    fund = [x + 20.0 for x in xs]
    im3 = [3.0 * x for x in xs]
    im3_noisy = [v + d for v, d in zip(im3, [0.2, -0.3, 0.1, 0.0, -0.2])]
    best, rejected = iip3.select_run(xs=xs, fund_ys=fund, im3_ys=im3_noisy, usable=[True] * 5,
                                     min_points=3, slope_fund=(0.9, 1.1), slope_im3=(2.7, 3.3),
                                     max_residual_db=0.0)
    assert best is None and all(r["reason"].endswith("dB too large") for r in rejected)
    # qualifying window + a rejecting injected gate: the gate's reason is kept
    best, rejected = iip3.select_run(xs=xs, fund_ys=fund, im3_ys=im3, usable=[True] * 5,
                                     min_points=3, slope_fund=(0.9, 1.1), slope_im3=(2.7, 3.3),
                                     max_residual_db=0.5,
                                     extra_gate=lambda **kw: "campaign gate said no")
    assert best is None and all(r["reason"] == "campaign gate said no" for r in rejected)


def test_select_run_computes_all_three_intercepts_on_the_selected_run():
    # fund = pin + 20, im3 = 3 pin: the lines cross at pin = +10 dBm
    xs = [-60.0 + 4.0 * i for i in range(8)]
    fund = [x + 20.0 for x in xs]
    im3 = [3.0 * x for x in xs]
    best, _ = iip3.select_run(xs=xs, fund_ys=fund, im3_ys=im3, usable=[True] * 8,
                              min_points=3, slope_fund=(0.9, 1.1), slope_im3=(2.7, 3.3),
                              max_residual_db=0.5)
    per_pt = best["per_point_iip3_dbm"]
    assert best["iip3_ideal_slope_dbm"] == pytest.approx(sum(per_pt) / len(per_pt), abs=1e-12)
    assert best["iip3_topfit_dbm"] == per_pt[-1]
    assert best["iip3_free_slope_dbm"] == pytest.approx(10.0, abs=1e-9)


# ---- probe cases A/B: the real agreement condition --------------------------


@pytest.mark.parametrize("s1,s3", [(1.0, 3.0), (1.05, 3.05)])
def test_three_intercepts_agree_exactly_on_residual_free_rows_when_s3_minus_s1_is_two(s1, s3):
    # cases A and B of the issue's probe table: the agreement condition is
    # s3 - s1 == 2, NOT "slopes exactly 1 and 3"
    rows = two_line_rows(s1, s3, lin=False)
    best, _ = iip3.select_run(xs=[p["pin_dbm"] for p in rows], fund_ys=[p["p_if1_dbm"] for p in rows],
                              im3_ys=[p["p_im3l_dbm"] for p in rows], usable=[True] * len(rows),
                              min_points=3, slope_fund=(0.9, 1.1), slope_im3=(2.7, 3.3),
                              max_residual_db=0.5)
    for key in iip3.INTERCEPT_KEYS:
        assert best[key] == pytest.approx(10.0, abs=1e-9), key
    assert abs(best["iip3_free_slope_dbm"] - best["iip3_ideal_slope_dbm"]) < 1e-9
    assert abs(best["iip3_free_slope_dbm"] - best["iip3_topfit_dbm"]) < 1e-9


def test_free_intercept_stays_exact_for_any_slopes_but_the_others_move():
    # case C at the engine level: slopes (1.08, 2.80), noiseless -- s3 - s1 = 1.72
    rows = two_line_rows(1.08, 2.80, lin=False)
    best, _ = iip3.select_run(xs=[p["pin_dbm"] for p in rows], fund_ys=[p["p_if1_dbm"] for p in rows],
                              im3_ys=[p["p_im3l_dbm"] for p in rows], usable=[True] * len(rows),
                              min_points=3, slope_fund=(0.9, 1.1), slope_im3=(2.7, 3.3),
                              max_residual_db=0.5)
    assert best["iip3_free_slope_dbm"] == pytest.approx(10.0, abs=1e-9)
    assert abs(best["iip3_ideal_slope_dbm"] - 10.0) > 5.0
    assert abs(best["iip3_topfit_dbm"] - 10.0) > 1.0


# ---- probe cases C/D through both wrappers ----------------------------------


def _lin_fit(rows, *, diagnostics=False, **overrides):
    return L.fit_iip3(rows, dict(LIN_PARAMS, **overrides), None, diagnostics=diagnostics)


def test_case_d_both_wrappers_publish_their_own_headlines_measurably_apart():
    # fractional slopes (0.988 / 3.02) plus IM3 scatter every gate tolerates:
    # each wrapper accepts the run and publishes a DIFFERENT intercept for it
    m = mf.fit_iip3(two_line_rows(0.988, 3.02, lin=False, noise=CASE_D_NOISE))
    r = _lin_fit(two_line_rows(0.988, 3.02, lin=True, noise=CASE_D_NOISE))
    assert m["status"] == "ok" and r["status"] == "ok"
    m_lo, r_lo = m["sidebands"]["low"], r["sidebands"]["low"]
    assert m["iip3_dbm"] == m_lo["iip3_dbm"]                      # mixfeas: free-slope headline
    # linearity: headline is the ideal-slope intercept, i.e. the per-point mean
    assert r["iip3_dbm"] == pytest.approx(
        math.fsum(r_lo["per_point_iip3_dbm"]) / len(r_lo["per_point_iip3_dbm"]), abs=1e-12)
    # linearity's own cross-check held: headline and free value within its tol
    assert abs(r["iip3_dbm"] - r_lo["iip3_free_slope_dbm"]) <= LIN_PARAMS["free_fixed_tol_db"]
    # the headlines genuinely disagree -- measurably, but inside the tol
    assert abs(m["iip3_dbm"] - r["iip3_dbm"]) > 0.05
    # both values appear in linearity's DEFAULT returned dict (it has always
    # published the free-slope value beside its headline)...
    assert r_lo["iip3_free_slope_dbm"] == pytest.approx(m["iip3_dbm"], abs=1e-9)
    # ...and all three in mixfeas's diagnostics dict (its default shape
    # predates the second definition and is what frozen records pin)
    md = mf.fit_iip3(two_line_rows(0.988, 3.02, lin=False, noise=CASE_D_NOISE), diagnostics=True)
    md_lo = md["sidebands"]["low"]
    for key in iip3.INTERCEPT_KEYS:
        assert key in md_lo, key
    assert md["iip3_dbm"] == md_lo["iip3_free_slope_dbm"] == pytest.approx(m["iip3_dbm"], abs=1e-12)


def test_case_d_free_and_ideal_intercepts_match_across_the_two_wrappers():
    # the same rows fitted by both campaigns: the engine computes each
    # definition once, so the published free-slope numbers agree to 1e-9 even
    # though neither wrapper derives them from the other
    m = mf.fit_iip3(two_line_rows(0.988, 3.02, lin=False, noise=CASE_D_NOISE), diagnostics=True)
    r = _lin_fit(two_line_rows(0.988, 3.02, lin=True, noise=CASE_D_NOISE), diagnostics=True)
    m_lo, r_lo = m["sidebands"]["low"], r["sidebands"]["low"]
    assert m_lo["iip3_free_slope_dbm"] == pytest.approx(r_lo["iip3_free_slope_dbm"], abs=1e-9)
    assert m_lo["iip3_ideal_slope_dbm"] == pytest.approx(r_lo["iip3_ideal_slope_dbm"], abs=1e-9)
    assert m_lo["iip3_topfit_dbm"] == pytest.approx(r_lo["iip3_topfit_dbm"], abs=1e-9)


def test_case_c_mixfeas_publishes_where_linearity_refuses():
    # slopes (1.08 / 2.80), noiseless: every shared gate passes in both
    # campaigns; linearity's injected free-vs-fixed cross-check rejects every
    # window (the definitions sit ~9 dB apart), mixfeas has no such gate and
    # publishes the exact free-slope intercept
    m = mf.fit_iip3(two_line_rows(1.08, 2.80, lin=False, n=12, step=1.0, start=-55.0))
    r = _lin_fit(two_line_rows(1.08, 2.80, lin=True, n=12, step=1.0, start=-55.0),
                 baseline_flat_db=0.20)  # keep a flat small-signal baseline despite slope-1.08 gain
    assert m["status"] == "ok"
    assert m["iip3_dbm"] == pytest.approx(10.0, abs=1e-9)
    assert r["status"] == "unavailable"
    for side in ("low", "high"):
        rej = r["sidebands"][side]["rejected_intervals"]
        assert rej, side
        assert all("disagree" in e["reason"] for e in rej), side
    # the cross-check is campaign-local: the identical rows stay publishable
    # in mixfeas (asserted above) and the engine's own gates accept them
    rows = two_line_rows(1.08, 2.80, lin=True, n=12, step=1.0, start=-55.0)
    best, _ = iip3.select_run(xs=[p["pin_dbm"] for p in rows], fund_ys=[p["p_f1_dbm"] for p in rows],
                              im3_ys=[p["p_im3l_dbm"] for p in rows],
                              usable=[True] * 12, min_points=3, slope_fund=(0.9, 1.1),
                              slope_im3=(2.7, 3.3), max_residual_db=0.5)
    assert best is not None and best["iip3_free_slope_dbm"] == pytest.approx(10.0, abs=1e-9)


# ---- the wrapper shape contract ---------------------------------------------


def test_default_wrapper_shapes_are_the_pre_276_key_sets():
    # frozen records pin these structurally: the default returns must keep
    # the exact pre-consolidation key sets on an ok sideband
    m = mf.fit_iip3(two_line_rows(1.0, 3.0, lin=False))
    assert set(m["sidebands"]["low"]) == {"interval_dbm", "n_points", "slope_fund", "slope_im3",
                                          "residual_fund_db", "residual_im3_db", "iip3_dbm",
                                          "per_point_iip3_dbm", "status", "excluded_steps"}
    r = _lin_fit(two_line_rows(1.0, 3.0, lin=True))
    assert set(r["sidebands"]["low"]) == {"interval_dbm", "n_points", "slope_fund", "slope_im3",
                                          "residual_fund_db", "residual_im3_db", "iip3_dbm",
                                          "iip3_free_slope_dbm", "per_point_iip3_dbm",
                                          "extrapolation_db", "baseline", "excluded_points",
                                          "rejected_intervals", "status"}
    assert set(m) == {"status", "iip3_dbm", "sidebands", "convention"}
    assert set(r) == {"status", "iip3_dbm", "sidebands", "sideband_spread_db", "convention"}


def test_diagnostics_mode_publishes_the_three_intercepts_from_both_wrappers():
    md = mf.fit_iip3(two_line_rows(1.0, 3.0, lin=False), diagnostics=True)
    rd = _lin_fit(two_line_rows(1.0, 3.0, lin=True), diagnostics=True)
    for s in (md["sidebands"]["low"], md["sidebands"]["high"], rd["sidebands"]["low"], rd["sidebands"]["high"]):
        for key in iip3.INTERCEPT_KEYS:
            assert key in s, key
    # headlines are unchanged by the flag
    assert md["iip3_dbm"] == md["sidebands"]["low"]["iip3_free_slope_dbm"]
    assert rd["iip3_dbm"] == rd["sidebands"]["low"]["iip3_ideal_slope_dbm"]
    # and on residual-free 1:3 rows all three coincide at the intercept
    for s in (md["sidebands"]["low"], rd["sidebands"]["low"]):
        for key in iip3.INTERCEPT_KEYS:
            assert s[key] == pytest.approx(10.0, abs=1e-9), key
