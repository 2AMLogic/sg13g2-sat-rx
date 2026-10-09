"""Unit tests for the Ka-band characterization postprocessor (kaband.py).

Pure Python, no simulator: every test builds synthetic data with a known
answer. Run from the repo root:

    python3 -m pytest sim/hbt-kaband-characterization/tests -q
"""

from __future__ import annotations

import cmath
import json
import math
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))

import kaband  # noqa: E402

K = kaband.K_BOLTZMANN


def manifest():
    return json.loads((BENCH / "testbench" / "tb.json").read_text())


def sweep(profile="reduced"):
    return kaband.sweep_from_manifest(manifest(), profile)


# A synthetic, physically valid noisy two-port: Sv(Zs) = a + b|Zs|^2 + c R + d X.
# Chosen so that Zopt = 120 + 80j ohm and Tmin = 35 K exactly.
R_OPT, X_OPT, T_MIN = 120.0, 80.0, 35.0
B = 4e-23  # |in|^2 (A^2/Hz)
D = -2 * B * X_OPT
C = 4 * K * T_MIN - 2 * B * R_OPT          # from Tmin = (2 sqrt(a' b) + c)/(4k), a' = b Ropt^2
A = B * R_OPT ** 2 + D * D / (4 * B)


def sv(z: complex) -> float:
    return A + B * abs(z) ** 2 + C * z.real + D * z.imag


# ---------------------------------------------------------------------------
# noise-parameter fit
# ---------------------------------------------------------------------------


def test_fit_recovers_known_noise_parameters():
    zs = [complex(r, x) for r, x in manifest()["sweep"]["full"]["source_impedances_ohm"]]
    fit = kaband.fit_noise_parameters([(z, sv(z)) for z in zs])
    assert fit["ropt_ohm"] == pytest.approx(R_OPT, rel=1e-9)
    assert fit["xopt_ohm"] == pytest.approx(X_OPT, rel=1e-9)
    assert fit["tmin_k"] == pytest.approx(T_MIN, rel=1e-9)
    assert fit["fit_max_rel_residual"] < 1e-12


def test_extracted_nfmin_is_reproduced_by_independent_evaluation():
    """An independent brute-force search of F over a dense Zs grid (no use
    of the fit's closed form) lands on the extracted optimum and NFmin."""
    zs = [complex(r, x) for r, x in manifest()["sweep"]["full"]["source_impedances_ohm"]]
    fit = kaband.fit_noise_parameters([(z, sv(z)) for z in zs])
    t0 = 290.0
    nfmin = 10 * math.log10(1 + fit["tmin_k"] / t0)
    best = min(
        (10 * math.log10(1 + sv(complex(r, x)) / (4 * K * t0 * r)), r, x)
        for r in [R_OPT * (0.9 + 0.002 * i) for i in range(101)]
        for x in [X_OPT * (0.9 + 0.002 * i) for i in range(101)]
    )
    assert best[0] == pytest.approx(nfmin, abs=1e-6)
    assert best[1] == pytest.approx(R_OPT, rel=3e-3)
    assert best[2] == pytest.approx(X_OPT, rel=3e-3)
    # and NF anywhere else is higher
    assert kaband.noise_factor(fit, complex(50, 0), t0) > 1 + fit["tmin_k"] / t0


def test_fit_rejects_too_few_points_and_bad_values():
    with pytest.raises(kaband.NoiseFitError):
        kaband.fit_noise_parameters([(complex(50, 0), 1e-18)] * 3)
    zs = [complex(25, 0), complex(100, 0), complex(25, 50), complex(25, -50), complex(200, 200)]
    with pytest.raises(kaband.NoiseFitError):
        kaband.fit_noise_parameters([(z, sv(z) if i else -1.0) for i, z in enumerate(zs)])
    with pytest.raises(kaband.NoiseFitError):
        kaband.fit_noise_parameters([(z, float("nan") if i == 2 else sv(z)) for i, z in enumerate(zs)])


def test_fit_rejects_unbounded_optimum():
    # b < 0: noise falls without bound as |Zs| grows -- no physical optimum.
    zs = [complex(25, 0), complex(100, 0), complex(25, 50), complex(25, -50), complex(200, 200)]
    with pytest.raises(kaband.NoiseFitError, match="no bounded optimum"):
        kaband.fit_noise_parameters([(z, 1e-17 - 1e-23 * abs(z) ** 2 + 1e-21 * z.real) for z in zs])


def test_measured_noise_factor_adds_source_noise_at_t0():
    # A noiseless DUT (isp = 0) has F = 1 exactly, whatever T0.
    assert kaband.measured_noise_factor(0.0, complex(50, 0), 290.0) == 1.0
    # Device noise equal to the source's own at T0 gives F = 2 (3.01 dB).
    isp = math.sqrt(4 * K * 290.0 * 50)
    assert kaband.measured_noise_factor(isp, complex(50, 0), 290.0) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# gain / stability
# ---------------------------------------------------------------------------


def test_y_to_s_matched_and_reciprocal():
    s11, s12, s21, s22 = kaband.y_to_s(1 / 50, 0, 0, 1 / 50)
    assert abs(s11) < 1e-15 and abs(s22) < 1e-15 and s12 == 0 and s21 == 0
    s11, s12, s21, s22 = kaband.y_to_s(0.03 + 0.01j, -0.002j, -0.002j, 0.01)
    assert s12 == pytest.approx(s21)


def test_gain_unconditionally_stable_reports_mag():
    s11, s12, s21, s22 = 0.3, 0.05, 2.0, 0.2
    g = kaband.gain_metrics(s11, s12, s21, s22)
    delta = s11 * s22 - s12 * s21
    k = (1 - s11 ** 2 - s22 ** 2 + abs(delta) ** 2) / (2 * s12 * s21)
    assert k > 1 and abs(delta) < 1
    assert g["gmax_kind"] == "MAG"
    assert g["gmax_db"] == pytest.approx(10 * math.log10(s21 / s12 * (k - math.sqrt(k * k - 1))))
    assert g["gmax_db"] < g["msg_db"]


def test_gain_potentially_unstable_reports_msg():
    g = kaband.gain_metrics(0.9, 0.2, 3.0, 0.8)
    assert g["k"] < 1
    assert g["gmax_kind"] == "MSG"
    assert g["gmax_db"] == pytest.approx(10 * math.log10(3.0 / 0.2))


def test_gain_k_above_one_but_delta_above_one_is_not_mag():
    # |Delta| > 1 with K > 1: not unconditionally stable -> MSG, never MAG.
    s11, s12, s21, s22 = 2.0 + 0j, 0.01 + 0j, 0.5 + 0j, 2.0 + 0j
    g = kaband.gain_metrics(s11, s12, s21, s22)
    assert g["delta_mag"] > 1 and g["k"] > 1
    assert g["gmax_kind"] == "MSG"


# ---------------------------------------------------------------------------
# fT from h21
# ---------------------------------------------------------------------------


def _h21_table(ft, f0=1e9, f1=3e12, per_dec=10):
    n = int(round(math.log10(f1 / f0) * per_dec)) + 1
    fs = [f0 * 10 ** (i / per_dec) for i in range(n)]
    return [(f, ft / f) for f in fs]


def test_ft_bracketed_crossing_is_exact_for_single_pole_rolloff():
    r = kaband.ft_from_h21(_h21_table(437e9))
    assert r["ft_status"] == "bracketed"
    assert r["ft_hz"] == pytest.approx(437e9, rel=1e-9)


def test_ft_absent_crossing_is_reported_not_extrapolated():
    assert kaband.ft_from_h21(_h21_table(0.5e9))["ft_status"] == "below_sweep_start"
    r = kaband.ft_from_h21(_h21_table(5e12))
    assert r["ft_status"] == "above_sweep_stop" and r["ft_hz"] is None
    assert kaband.ft_from_h21([])["ft_status"] == "no_h21_data"
    assert kaband.ft_from_h21([(1e9, float("nan")), (1e10, 0.5)])["ft_status"] == "h21_nonfinite"


# ---------------------------------------------------------------------------
# log parsing + per-point analysis on a fully synthetic log
# ---------------------------------------------------------------------------


def synthetic_log(sw, *, drop=None, warn=False, malformed=None, nx=4, vce=1.0, vbe=0.84,
                  ic=1.8e-3, ft=300e9, shifted_block=None, unbiased_block=None):
    """A log in run.py's protocol whose noise data come from the synthetic
    two-port above and whose Y-parameters are a fixed, plausible device."""
    y11, y12, y21, y22 = 0.004 + 0.02j, -0.0001 - 0.003j, 0.06 - 0.03j, 0.002 + 0.006j
    lines = ["KA_DECK_BEGIN", f"KA_POINT nx={nx} vce={vce:.3f} vbe={vbe:.4f}", "KA_BLOCK op"]
    op = {"ka_icn": ic, "ka_ibn": ic / 500, "ka_icy": ic, "ka_iby": ic / 500, "ka_vb": vbe,
          "ka_vc": vce, "ka_dtj": 3.0, "ka_vsup": 2.5}
    if warn:
        lines.append("Warning: singular matrix:  check nodes xqy.s1 and q.xqy.qnpn13g2#emitter")

    def bias(tag, copy):
        if tag == unbiased_block:
            return []
        value = ic * (1.001 if tag == shifted_block else 1.0)
        return [f"@q.xq{copy}.qnpn13g2[ic] = {value!r}"]
    for kname, v in op.items():
        if drop != kname:
            lines.append(f"{kname} = {v!r}")
    for tag, names in (("yfwd", (("y11", y11), ("y21", y21))), ("yrev", (("y12", y12), ("y22", y22)))):
        lines.append(f"KA_BLOCK {tag}")
        lines += bias(tag, "y")
        for k in range(len(sw.frequencies_hz)):
            for name, y in names:
                lines += [f"ka_{name}r_{k} = {y.real!r}", f"ka_{name}i_{k} = {y.imag!r}"]
    lines.append("KA_BLOCK h21")
    lines += bias("h21", "y")
    lines += [f"{i}\t{f!r}\t{h!r}" for i, (f, h) in enumerate(_h21_table(ft))]
    for k, fk in enumerate(sw.frequencies_hz):
        for j, (r, x) in enumerate(sw.source_impedances_ohm):
            lines.append(f"KA_BLOCK nz f={k} z={j}")
            lines += bias(f"nz.f{k}.z{j}", "n")
            z = kaband.applied_impedance(*kaband.source_elements(r, x, fk), fk)
            if drop == ("nz", k, j):
                continue
            val = math.sqrt(sv(z))
            lines.append(f"ka_isp = {val!r}" if malformed != ("nz", k, j) else "ka_isp = 1.2.3e-9")
            if j == 3:
                rv, lv, cv = kaband.source_elements(R_OPT, X_OPT, fk)
                zo = kaband.applied_impedance(rv, lv, cv, fk)
                lines += [f"KA_BLOCK zopt f={k}", *bias(f"zopt.f{k}", "n"), f"ka_isp = {math.sqrt(sv(zo))!r}",
                          f"@rsz[resistance] = {rv!r}", f"@lsz[inductance] = {lv!r}",
                          f"@csz[capacitance] = {cv!r}"]
        z50 = kaband.applied_impedance(*kaband.source_elements(*sw.nf50_check_ohm, fk), fk)
        lines += [f"KA_BLOCK nf50 f={k}", *bias(f"nf50.f{k}", "n"), f"ka_isp = {math.sqrt(sv(z50))!r}"]
    lines.append("KA_DECK_END")
    return "\n".join(lines) + "\n"


def test_synthetic_log_round_trip_recovers_known_answers():
    sw = sweep()
    sw = kaband.Sweep(**{**sw.__dict__, "vbe_v": (0.84,)})  # one bias point
    rows, problems = kaband.analyze_log(synthetic_log(sw), sw, 27.0)
    assert problems == []
    assert len(rows) == len(sw.frequencies_hz)
    for row in rows:
        assert row["status"] == "ok", row.get("reason")
        assert row["tmin_k"] == pytest.approx(T_MIN, rel=1e-9)
        assert row["nfmin_db_t290"] == pytest.approx(10 * math.log10(1 + T_MIN / 290), abs=1e-9)
        assert row["nfmin_check"] == "pass"
        # the 1 nF DC block puts the check point 0.008 ohm off Zopt: second order
        assert abs(row["nfmin_check_delta_db"]) < 1e-6
        assert abs(row["nf50_fit_delta_db"]) < 1e-9
        assert row["ft_hz"] == pytest.approx(300e9, rel=1e-9)
        assert row["jc_ma_um2"] == pytest.approx(1.8 / (4 * 0.063))
        assert row["in_box"] and row["active"]


@pytest.mark.parametrize("drop,reason", [
    ("ka_icn", "missing op value"),
    (("nz", 1, 2), "missing noise value (f=1, Zs #2)"),
])
def test_missing_values_exclude_with_reason(drop, reason):
    sw = sweep()
    sw = kaband.Sweep(**{**sw.__dict__, "vbe_v": (0.84,)})
    rows, _ = kaband.analyze_log(synthetic_log(sw, drop=drop), sw, 27.0)
    bad = [r for r in rows if r["status"] != "ok"]
    assert bad and all(reason in r["reason"] for r in bad)


def test_malformed_value_is_missing_not_misread():
    sw = sweep()
    sw = kaband.Sweep(**{**sw.__dict__, "vbe_v": (0.84,)})
    rows, _ = kaband.analyze_log(synthetic_log(sw, malformed=("nz", 0, 4)), sw, 27.0)
    assert rows[0]["status"] == "excluded" and "missing noise value (f=0, Zs #4)" in rows[0]["reason"]
    assert rows[1]["status"] == "ok"


def _one_point_sweep():
    sw = sweep()
    return kaband.Sweep(**{**sw.__dict__, "vbe_v": (0.84,)})


def test_simulator_warning_is_annotated_not_an_exclusion():
    """A recovered warning (ngspice carried on) does not by itself discard a
    point whose values are complete and pass every check."""
    sw = _one_point_sweep()
    rows, problems = kaband.analyze_log(synthetic_log(sw, warn=True), sw, 27.0)
    assert problems == []
    assert all(r["status"] == "ok" for r in rows)
    assert all("singular matrix" in r["sim_messages"] for r in rows)


def test_analysis_at_a_different_bias_excludes_the_point():
    """Every analysis re-solves the operating point; one that converged to a
    different bias (0.1 % here) must not be mixed into the row."""
    sw = _one_point_sweep()
    rows, _ = kaband.analyze_log(synthetic_log(sw, shifted_block="nz.f1.z6"), sw, 27.0)
    assert all(r["status"] == "excluded" and "bias differs between analyses" in r["reason"] for r in rows)


def test_missing_per_analysis_bias_excludes_the_point():
    sw = _one_point_sweep()
    rows, _ = kaband.analyze_log(synthetic_log(sw, unbiased_block="h21"), sw, 27.0)
    assert all(r["status"] == "excluded" and "missing per-analysis bias value in h21" in r["reason"]
               for r in rows)


def test_log_messages_tally_normalizes_numbers_and_nodes():
    text = ("Warning: singular matrix:  check nodes a and b\n"
            "Warning: singular matrix:  check node c\n"
            "Warning: spfactor.c, 230, Pivot for step = 41 not found\n"
            "Warning: spfactor.c, 230, Pivot for step = 7 not found\nka_isp = 1e-9\n")
    tally = kaband.log_messages(text)
    assert tally == {"Warning: singular matrix:  check nodes ...": 2,
                     "Warning: spfactor.c, N, Pivot for step = N not found": 2}


def test_truncated_log_and_missing_points_are_problems():
    sw = sweep()  # reduced: 3 bias points expected
    text = synthetic_log(kaband.Sweep(**{**sw.__dict__, "vbe_v": (0.84,)}))
    _, problems = kaband.analyze_log(text.replace("KA_DECK_END\n", ""), sw, 27.0)
    assert any("truncated" in p for p in problems)
    assert any("expected 3 bias points" in p for p in problems)


def test_out_of_box_point_is_flagged_not_dropped():
    sw = sweep()
    sw = kaband.Sweep(**{**sw.__dict__, "vbe_v": (0.98,)})
    rows, _ = kaband.analyze_log(synthetic_log(sw, vbe=0.98, ic=13e-3), sw, 27.0)
    assert all(r["status"] == "ok" for r in rows)
    assert all(r["validity_flags"] == "ic_high;vbe_high" and not r["in_box"] for r in rows)


# ---------------------------------------------------------------------------
# reductions
# ---------------------------------------------------------------------------


def _row(jc, nf, *, flags="", active=True, status="ok", ft=300e9):
    return {"jc_ma_um2": jc, "nfmin_db_t290": nf, "validity_flags": flags, "in_box": not flags,
            "active": active, "status": status, "ft_hz": ft, "freq_hz": 19.45e9}


def test_cell_optimum_interior_is_unconstrained():
    rows = [_row(1, 1.0), _row(2, 0.8), _row(4, 0.7), _row(8, 0.9), _row(16, 1.2)]
    c = kaband.cell_optima(rows, 290.0)
    assert c["opt_row"]["jc_ma_um2"] == 4 and c["opt_constrained_by"] == ""
    assert c["eligible_jc_decades"] == pytest.approx(math.log10(16))


def test_cell_optimum_at_box_edge_is_constrained_and_names_the_bound():
    rows = [_row(1, 1.0), _row(2, 0.9), _row(4, 0.8), _row(8, 0.7, flags="ic_high")]
    c = kaband.cell_optima(rows, 290.0)
    assert c["opt_row"]["jc_ma_um2"] == 4
    assert c["opt_constrained_by"] == "upper: ic_high"


def test_cell_optimum_never_uses_inactive_or_excluded_points():
    rows = [_row(0.01, 0.5, active=False), _row(0.1, 1.3), _row(1, 0.9), _row(4, 0.95),
            _row(8, 0.1, status="excluded")]
    c = kaband.cell_optima(rows, 290.0)
    assert c["opt_row"]["jc_ma_um2"] == 1
    rows = [_row(0.01, 0.5, active=False), _row(0.1, 0.8), _row(1, 0.9)]
    c = kaband.cell_optima(rows, 290.0)
    assert c["opt_row"]["jc_ma_um2"] == 0.1
    assert c["opt_constrained_by"].startswith("lower: inactive")


def test_cell_with_no_eligible_point_has_no_optimum():
    c = kaband.cell_optima([_row(1, 0.5, flags="vbe_high")], 290.0)
    assert "opt_row" not in c and c["n_eligible"] == 0


def test_row3_screen_margins_and_verdicts():
    rows = {("a", 1.0): {"nfmin_db_t290": 0.6}, ("b", 1.0): {"nfmin_db_t290": 1.1}}
    s = kaband.row3_screen(rows, 290.0)
    assert s["verdict"] == "below_limit_everywhere"
    assert s["worst_corner_freq"] == ("b", 1.0) and s["worst_margin_db"] == pytest.approx(1.4)
    rows[("c", 2.0)] = {"nfmin_db_t290": 2.6}
    s = kaband.row3_screen(rows, 290.0)
    assert s["verdict"] == "exceeds_limit_somewhere" and s["n_exceeding"] == 1
    rows[("d", 2.0)] = None
    assert kaband.row3_screen(rows, 290.0)["verdict"] == "incomplete"


# ---------------------------------------------------------------------------
# sweep declaration + deck structure
# ---------------------------------------------------------------------------


def test_declared_sweep_is_valid_and_brackets_requirements():
    sw = sweep("full")
    assert set(sw.nx) == {1, 4, 8}
    assert {0.6, 1.0, 1.4} <= set(sw.vce_v)
    assert sw.frequencies_hz == (17.7e9, 19.45e9, 21.2e9)
    # both card VBE limits must be crossed so either can be seen to bind
    assert sw.vbe_v[0] < kaband.VALID_VBE_V[0] and sw.vbe_v[-1] > kaband.VALID_VBE_V[1]


@pytest.mark.parametrize("mutate,msg", [
    (lambda f: f.update(nx=[0, 4]), "Nx=0"),
    (lambda f: f.update(source_impedances_ohm=[[25, 0], [25, 0], [25, 50], [25, -50], [200, 200]]),
     "first four"),
    (lambda f: f.update(nf50_check_ohm=[25, 0]), "independent check"),
    (lambda f: f.update(frequencies_hz=[17.7e9, 19e9, 21.2e9]), "equally spaced"),
])
def test_sweep_validation_rejects_bad_declarations(mutate, msg):
    m = manifest()
    mutate(m["sweep"]["full"])
    with pytest.raises(kaband.SweepError, match=msg):
        kaband.sweep_from_manifest(m, "full")


def test_every_analysis_is_preceded_by_destroy_all():
    """No analysis may run with a previous plot still current -- that is
    what turns a failed analysis into a missing (not stale) value."""
    lines = [ln.strip() for ln in kaband.build_control_lines(sweep())]
    analyses = [i for i, ln in enumerate(lines) if ln.split()[:1] in (["op"], ["ac"], ["noise"])]
    assert analyses
    for i in analyses:
        prior = lines[max(0, i - 6):i]
        assert "destroy all" in prior, lines[max(0, i - 6):i + 1]


def test_sabotaged_deck_differs_only_in_the_sabotaged_measurement():
    a = kaband.build_control_lines(sweep())
    b = kaband.build_control_lines(sweep(), sabotage_measurement=True)
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    assert len(a) == len(b) and len(diff) == 1 and "nonexistent_field" in diff[0][1]


def test_source_elements_realise_requested_impedance():
    for r, x in ((25, 0), (25, 200), (25, -200), (1000, 1500)):
        z = kaband.applied_impedance(*kaband.source_elements(r, x, 19.45e9), 19.45e9)
        assert z.real == r
        assert z.imag == pytest.approx(x, abs=0.02)  # the 1 nF DC block's -0.008 ohm
    assert cmath.isclose(kaband.applied_impedance(50, 1e-15, 1e-9, 1e10),
                         complex(50, 2 * math.pi * 1e10 * 1e-15 - 1 / (2 * math.pi * 1e10 * 1e-9)))
