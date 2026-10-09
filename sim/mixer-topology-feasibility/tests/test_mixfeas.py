"""Unit tests for the mixer-topology feasibility study (mixfeas.py).

Pure Python, no simulator and no PDK: every test builds synthetic data with
a known answer. Run from the repo root:

    python3 -m pytest sim/mixer-topology-feasibility/tests -q
"""

from __future__ import annotations

import copy
import dataclasses
import json
import math
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))

import mixfeas as mf  # noqa: E402


def manifest():
    return json.loads((BENCH / "testbench" / "tb.json").read_text())


@pytest.fixture(scope="module")
def study():
    return mf.study_from_manifest(manifest())


def p_dbm(v_peak, r=50.0):
    return 10 * math.log10(v_peak ** 2 / (2 * r) / 1e-3)


# ---------------------------------------------------------------------------
# power conventions
# ---------------------------------------------------------------------------


def test_available_and_delivered_power_conventions():
    # 1 V open-circuit peak behind 50 ohm: V^2/(8R) = 2.5 mW
    assert mf.available_power_w(1.0, 50.0) == pytest.approx(2.5e-3)
    # matched load sees V/2 peak: delivered = (0.5)^2/(2*50) = the available power
    assert mf.delivered_power_w(0.5, 50.0) == pytest.approx(mf.available_power_w(1.0, 50.0))
    assert mf.dbm(1e-3) == pytest.approx(0.0)
    assert mf.dbm(0.0) == float("-inf")


def test_lo_total_differential_available_power():
    # issue #35: P_av = Vdiff_open_peak^2 / (8 * Rdiff), Rdiff = 100 ohm, total (not per leg)
    for p in (-30.0, -3.0, 0.0, 6.0):
        v = mf.v_open_peak_for(p, mf.LO_RDIFF_OHM)
        assert 10 * math.log10(v * v / (8 * 100.0) / 1e-3) == pytest.approx(p)
    # 0 dBm -> sqrt(0.8) V differential open-circuit peak; each 50 ohm leg
    # carries half of it and half the power
    v = mf.v_open_peak_for(0.0, 100.0)
    assert v == pytest.approx(math.sqrt(0.8))
    per_leg = mf.available_power_w(v / 2, 50.0)
    assert 2 * per_leg == pytest.approx(1e-3)


def test_dft_bin_reads_peak_amplitude_on_coherent_bins():
    dt, n = 1e-11, 2000  # 20 ns
    f1, f2 = 1e9, 18.45e9
    xs = [0.3 + 0.7 * math.sin(2 * math.pi * f1 * k * dt + 0.4) + 0.05 * math.sin(2 * math.pi * f2 * k * dt)
          for k in range(n)]
    a1 = mf.dft_bin(xs, dt, f1)
    a2 = mf.dft_bin(xs, dt, f2)
    assert abs(a1) == pytest.approx(0.7, rel=1e-9)
    assert a1.real == pytest.approx(0.7 * math.sin(0.4), abs=1e-9)
    assert abs(a2) == pytest.approx(0.05, rel=1e-9)
    # an empty bin between them reads ~0
    assert abs(mf.dft_bin(xs, dt, 1.05e9)) < 1e-9


# ---------------------------------------------------------------------------
# study declaration
# ---------------------------------------------------------------------------


def test_committed_study_parses(study):
    assert [b.name for b in study.bands] == ["f17p70", "f19p45", "f21p20"]
    for b in study.bands:
        assert b.lo_hz == pytest.approx(b.rf_hz - 1e9)
        assert b.two_tone_lo_hz == pytest.approx(sum(b.two_tone_hz) / 2 - 1e9)
        assert all(17.7e9 - 1 <= f <= 21.2e9 + 1 for f in b.two_tone_hz)
    assert study.matrices["main"].supplies_v == (2.025, 2.25, 2.475)
    assert max(study.matrices["main"].supplies_v) < study.rail_max_v
    assert len(study.lo_sweep_dbm) == 13 and study.lo_sweep_dbm[0] == -30 and study.lo_sweep_dbm[-1] == 6
    assert study.iip3_pin_dbm[0] == -70 and study.iip3_pin_dbm[-1] == -10
    assert {c.role for c in study.candidates} == {"candidate", "floor"}
    assert study.matrices["leakage"].seed is not None


def test_declared_cell_counts(study):
    cells = mf.expected_cells(study)
    by = {}
    for c in cells:
        by[c["matrix"]] = by.get(c["matrix"], 0) + 1
    # 3 topologies x (3 corners x 3 T x 3 V x 3 bands) etc.
    assert by == {"main": 243, "leakage": 243, "lo_select": 3 * 3 * 13 * 2, "iip3": 3 * 3 * 13}
    assert len({c["id"] for c in cells}) == len(cells)


def test_supply_above_rail_is_refused():
    m = manifest()
    m["nominal_supply_v"] = 2.5  # legacy grid: 2.75 V would exceed the ceiling
    with pytest.raises(mf.StudyError, match="rail ceiling"):
        mf.study_from_manifest(m)


def test_out_of_band_two_tone_is_refused():
    m = manifest()
    m["study"]["bands"][2]["two_tone_hz"] = [21.2e9, 21.225e9]
    with pytest.raises(mf.StudyError, match="outside the declared RF band"):
        mf.study_from_manifest(m)


def test_incoherent_window_is_refused():
    m = manifest()
    m["study"]["timing"]["window_two_tone_s"] = 50e-9  # 25 MHz comb needs n * 80 ns
    with pytest.raises(mf.StudyError, match="not coherent"):
        mf.study_from_manifest(m)


def test_leakage_matrix_needs_mismatch_cards_and_seed():
    m = manifest()
    m["study"]["matrices"]["leakage"]["corners"] = ["hbt_typ"]
    with pytest.raises(mf.StudyError, match="mismatch"):
        mf.study_from_manifest(m)
    m = manifest()
    del m["study"]["matrices"]["leakage"]["seed"]
    with pytest.raises(mf.StudyError, match="seed"):
        mf.study_from_manifest(m)


def test_committed_fragments_match_declared_devices(study):
    for cand in study.candidates:
        text = (BENCH / "testbench" / cand.fragment).read_text()
        assert mf.check_fragment_devices(text, cand) == []
    # a wrong Nx, a missing sense source and an undeclared device are caught
    cand = study.candidate("gilbert_stacked")
    text = (BENCH / "testbench" / cand.fragment).read_text()
    assert mf.check_fragment_devices(text.replace("Xq1 c_q1 b_q1 e_q1 0 npn13G2 Nx=1",
                                                  "Xq1 c_q1 b_q1 e_q1 0 npn13G2 Nx=2"), cand)
    assert mf.check_fragment_devices(text.replace("vic_q3 out_p c_q3 0", ""), cand)
    assert mf.check_fragment_devices(text + "\nXq9 a b c 0 npn13G2 Nx=1\n", cand)


# ---------------------------------------------------------------------------
# deck generation and log parsing
# ---------------------------------------------------------------------------


def make_run(study, kind="single", band=1, rf=-60.0, drive=0.0, tstep=5e-12, run_id=None):
    t = study.timing
    window = t.window_two_tone_s if kind == "two_tone" else t.window_single_s
    return mf.RunSpec(run_id=run_id or kind, kind=kind, band=study.bands[band], vlo_dbm=drive,
                      rf_dbm=None if kind == "rfoff" else rf, window_s=window, settle_s=t.settle_s,
                      tmax_s=tstep, tstep_s=tstep, if_hz=study.if_hz)


def test_generated_deck_prints_every_required_key(study):
    cand = study.candidate("gilbert_stacked")
    for kind in ("single", "rfoff", "two_tone"):
        run = make_run(study, kind)
        lines = mf.build_control_lines([run], cand.devices)
        printed = {ln.split()[1] for ln in lines if ln.startswith("print ")}
        assert set(mf.run_keys(run, cand.devices)) <= printed
        assert any(ln.startswith("tran ") for ln in lines) and "linearize" in lines
        dropped = mf.build_control_lines([run], cand.devices, drop_key="mf_l")
        assert "print mf_l" not in dropped


def test_duplicate_run_ids_refused(study):
    run = make_run(study)
    with pytest.raises(ValueError, match="duplicate"):
        mf.build_control_lines([run, run], ())


def synth_values(run, devices, amps, *, stress=None):
    """mf_ values a deck would print for waveforms made of the given
    (bin name -> peak amplitude) tones on each probed node, computed with the
    same single-bin DFT on a sampled waveform (not by assumption)."""
    bins = run.bins()
    nodes = {}
    for name, (expr, f) in bins.items():
        nodes.setdefault(expr, [])
    # build each node's waveform as the sum of the tones assigned to it
    for name, amp in amps.items():
        expr, f = bins[name]
        nodes[expr].append((f, amp))
    dt, n = run.tstep_s, run.n_samples
    values = {"mf_l": float(2 * n + 1), "mf_n": float(n), "mf_dcirail": 2e-3, "mf_prail": 4.5e-3}
    cache = {}
    for name, (expr, f) in bins.items():
        if expr not in cache:
            cache[expr] = [sum(a * math.sin(2 * math.pi * ff * k * dt + 0.3 * i)
                               for i, (ff, a) in enumerate(nodes[expr])) for k in range(n)]
        z = mf.dft_bin(cache[expr], dt, f)
        values[f"mf_{name}_re"], values[f"mf_{name}_im"] = z.real, z.imag
    for dev in devices:
        st = (stress or {}).get(dev.name, {})
        for q, (lo, hi) in (("vce", (0.6, 1.1)), ("vbe", (0.75, 0.9)), ("ic", (2e-4, 1e-3))):
            lo, hi = st.get(q, (lo, hi))
            values[f"mf_dc_{q}_{dev.name}"] = (lo + hi) / 2
            for iv in ("su", "ss"):
                values[f"mf_{iv}_{q}max_{dev.name}"] = st.get(f"{iv}_{q}max", hi)
                values[f"mf_{iv}_{q}min_{dev.name}"] = st.get(f"{iv}_{q}min", lo)
    return values


def to_log(runs_values: dict[str, dict]) -> str:
    lines = ["noise", "MF_DECK_BEGIN"]
    for rid, vals in runs_values.items():
        lines.append(f"MFRUN {rid}")
        lines += [f"{k} = {v:.10e}" for k, v in vals.items()]
        lines.append(f"MFEND {rid}")
    lines.append("MF_DECK_END")
    return "\n".join(lines) + "\n"


def test_single_tone_chain_loaded_power_gain_and_leakage(study):
    cand = study.candidate("gilbert_stacked")
    run = make_run(study, "single")
    amps = {"if": 2e-4, "loif": 3e-3, "lorf": 1e-4, "lodiff": 0.6}
    vals = synth_values(run, cand.devices, amps)
    parsed = mf.parse_log(to_log({run.run_id: vals}))
    assert parsed.problems == [] and parsed.complete
    res = mf.analyze_run(run, parsed.runs[run.run_id], cand.devices, study.stress)
    assert res["status"] == "ok", res["problems"]
    assert res["p_if_dbm"] == pytest.approx(p_dbm(2e-4), abs=1e-6)
    assert res["gain_db"] == pytest.approx(p_dbm(2e-4) + 60.0, abs=1e-6)
    assert res["lo_if_dbm"] == pytest.approx(p_dbm(3e-3), abs=1e-6)
    assert res["lo_rf_dbm"] == pytest.approx(p_dbm(1e-4), abs=1e-6)
    assert res["lo_vdiff_loaded_peak_v"] == pytest.approx(0.6, rel=1e-9)
    assert res["lo_vdiff_open_peak_v"] == pytest.approx(math.sqrt(0.8))
    assert all(res["resolved"].values())
    # empty neighbouring bins read nothing: the floor is the absolute floor
    assert res["floor_dbm"]["if"] == pytest.approx(-140.0)


def test_rf_off_leakage_bins(study):
    run = make_run(study, "rfoff", band=0)
    vals = synth_values(run, (), {"loif": 1e-3, "lorf": 2e-5, "lodiff": 0.5})
    res = mf.analyze_run(run, vals, (), study.stress)
    assert res["status"] == "ok"
    assert res["lo_if_dbm"] == pytest.approx(p_dbm(1e-3), abs=1e-6)
    assert res["lo_rf_dbm"] == pytest.approx(p_dbm(2e-5), abs=1e-6)
    assert "gain_db" not in res


def test_unresolved_leakage_is_an_upper_bound(study):
    run = make_run(study, "rfoff")
    vals = synth_values(run, (), {"loif": 1e-9, "lorf": 1e-3, "lodiff": 0.5})  # -150 dBm
    res = mf.analyze_run(run, vals, (), study.stress)
    assert res["resolved"] == {"loif": False, "lorf": True}


def test_two_tone_both_im3_sidebands_read_independently(study):
    run = make_run(study, "two_tone", band=2)
    f1, f2, flo = run.tones
    assert run.bins()["im3l"][1] == pytest.approx(2 * f1 - f2 - flo)
    assert run.bins()["im3h"][1] == pytest.approx(2 * f2 - f1 - flo)
    amps = {"if1": 1e-3, "if2": 9e-4, "im3l": 2e-6, "im3h": 5e-6, "lodiff": 0.4}
    vals = synth_values(run, (), amps)
    res = mf.analyze_run(run, vals, (), study.stress)
    assert res["status"] == "ok"
    assert res["p_if1_dbm"] == pytest.approx(p_dbm(1e-3), abs=1e-6)
    assert res["p_if2_dbm"] == pytest.approx(p_dbm(9e-4), abs=1e-6)
    assert res["p_im3l_dbm"] == pytest.approx(p_dbm(2e-6), abs=1e-6)
    assert res["p_im3h_dbm"] == pytest.approx(p_dbm(5e-6), abs=1e-6)


def test_missing_nan_and_wrong_window_are_invalid(study):
    cand = study.candidate("folded_single_balanced")
    run = make_run(study, "single")
    good = synth_values(run, cand.devices, {"if": 2e-4, "loif": 1e-3, "lorf": 1e-5, "lodiff": 0.5})
    assert mf.analyze_run(run, good, cand.devices, study.stress)["status"] == "ok"
    for mutate in (lambda v: v.pop("mf_if_re"),
                   lambda v: v.pop("mf_ss_vcemax_q2"),
                   lambda v: v.__setitem__("mf_lorf_im", float("nan")),
                   lambda v: v.__setitem__("mf_n", v["mf_n"] - 1)):
        bad = dict(good)
        mutate(bad)
        assert mf.analyze_run(run, bad, cand.devices, study.stress)["status"] == "invalid"


def test_parse_log_refuses_truncated_duplicate_and_orphan_values():
    ok = "MF_DECK_BEGIN\nMFRUN a\nmf_x = 1.0\nMFEND a\nMF_DECK_END\n"
    p = mf.parse_log(ok)
    assert p.problems == [] and p.runs == {"a": {"mf_x": 1.0}}
    assert mf.parse_log("MF_DECK_BEGIN\nMFRUN a\nmf_x = 1.0\n").problems  # truncated
    assert mf.parse_log(ok.replace("mf_x = 1.0", "mf_x = 1.0\nmf_x = 2.0")).problems
    assert mf.parse_log("MF_DECK_BEGIN\nmf_x = 1\nMF_DECK_END\n").problems
    assert mf.parse_log(ok + ok).problems  # run twice
    nan = mf.parse_log(ok.replace("1.0", "nan"))
    assert math.isnan(nan.runs["a"]["mf_x"])


# ---------------------------------------------------------------------------
# stress classification
# ---------------------------------------------------------------------------


def test_stress_dc_and_retained_reject_startup_flags(study):
    cand = study.candidate("folded_single_balanced")
    run = make_run(study, "single")
    base = {"if": 2e-4, "loif": 1e-3, "lorf": 1e-5, "lodiff": 0.5}
    # startup-only V_BE excursion: recorded flag, not a rejection
    vals = synth_values(run, cand.devices, base, stress={"q2": {"su_vbemin": 0.2}})
    res = mf.analyze_run(run, vals, cand.devices, study.stress)
    assert res["status"] == "ok"
    assert [(v["device"], v["interval"], v["quantity"], v["kind"]) for v in res["stress"]["violations"]] == \
        [("q2", "startup", "vbe", "below")]
    # retained-window V_CE above row 17's 1.4 V: explicit rejected outcome
    vals = synth_values(run, cand.devices, base, stress={"q1": {"ss_vcemax": 1.45}})
    res = mf.analyze_run(run, vals, cand.devices, study.stress)
    assert res["status"] == "rejected_stress"
    assert res["stress"]["rejecting"][0]["limit"] == 1.4
    # DC V_BE above the card window
    vals = synth_values(run, cand.devices, base, stress={"q3": {"vbe": (0.97, 0.97)}})
    assert mf.analyze_run(run, vals, cand.devices, study.stress)["status"] == "rejected_stress"
    # Ic at the card limit 0.003 * Nx is flagged (>=)
    vals = synth_values(run, cand.devices, base, stress={"q1": {"ss_icmax": 0.003}})
    res = mf.analyze_run(run, vals, cand.devices, study.stress)
    assert res["status"] == "rejected_stress"
    assert res["stress"]["rejecting"][0]["quantity"] == "ic"


def test_stress_ic_limit_scales_with_nx(study):
    cand = study.candidate("placeholder_floor")  # Nx = 4
    run = make_run(study, "single")
    vals = synth_values(run, cand.devices, {"if": 2e-4, "loif": 1e-3, "lorf": 1e-5, "lodiff": 0.5},
                        stress={"q1": {"ss_icmax": 0.011}})
    assert mf.analyze_run(run, vals, cand.devices, study.stress)["status"] == "ok"
    vals["mf_ss_icmax_q1"] = 0.012
    assert mf.analyze_run(run, vals, cand.devices, study.stress)["status"] == "rejected_stress"


# ---------------------------------------------------------------------------
# LO-drive selection
# ---------------------------------------------------------------------------

BANDS = ["f17p70", "f19p45", "f21p20"]
DRIVES = [-30.0, -27.0, -24.0, -21.0, -18.0, -15.0, -12.0]


def sweep(gain_by_band, status=None, ss=None):
    pts = []
    for b in BANDS:
        for i, d in enumerate(DRIVES):
            pts.append({"band": b, "drive_dbm": d, "gain_db": gain_by_band[b][i],
                        "status": (status or {}).get((b, d), "ok"), "ss_ok": (ss or {}).get((b, d), True)})
    return pts


RISING = [-10.0, -5.0, -1.0, 0.0, 0.2, 0.3, 0.3]


def test_selects_lowest_drive_on_common_plateau():
    r = mf.select_lo_drive(sweep({b: RISING for b in BANDS}), BANDS, DRIVES)
    assert r["status"] == "selected" and r["drive_dbm"] == -21.0
    assert r["run_dbm"] == [-21.0, -18.0, -15.0]


def test_plateau_tie_picks_lowest():
    flat = [1.0] * len(DRIVES)
    r = mf.select_lo_drive(sweep({b: flat for b in BANDS}), BANDS, DRIVES)
    assert r["drive_dbm"] == -30.0


def test_no_plateau_is_no_acceptable_drive():
    steep = [-12.0, -9.0, -6.0, -3.0, 0.0, 3.0, 6.0]  # every step > 0.5 dB
    r = mf.select_lo_drive(sweep({b: steep for b in BANDS}), BANDS, DRIVES)
    assert r["status"] == "no acceptable drive in declared sweep"
    assert "drive_dbm" not in r


def test_stress_rejected_points_are_excluded_not_averaged():
    # the gain maximum sits at stress-rejected drives; the plateau is judged
    # against the best STRESS-VALID gain only
    g = [-10.0, -5.0, 0.0, 0.1, 0.2, 5.0, 5.0]
    status = {(b, d): "rejected_stress" for b in BANDS for d in (-15.0, -12.0)}
    r = mf.select_lo_drive(sweep({b: g for b in BANDS}, status=status), BANDS, DRIVES)
    assert r["status"] == "selected" and r["drive_dbm"] == -24.0
    assert r["per_band"]["f19p45"]["max_valid_gain_db"] == 0.2
    # if stress rejection breaks every run of three, nothing is selected
    status = {(b, d): "rejected_stress" for b in BANDS for d in (-21.0, -15.0)}
    r = mf.select_lo_drive(sweep({b: RISING for b in BANDS}, status=status), BANDS, DRIVES)
    assert r["status"] == "no acceptable drive in declared sweep"


def test_small_signal_failure_disqualifies():
    ss = {(b, -18.0): False for b in BANDS}
    r = mf.select_lo_drive(sweep({b: RISING for b in BANDS}, ss=ss), BANDS, DRIVES)
    # qualifying drives are -21, -15, -12 (gain within 0.5 dB of 0.3 dB) but
    # -18 fails the small-signal check, so no run of three is unbroken
    assert r["status"] == "no acceptable drive in declared sweep"


def test_plateau_failing_at_band_edge_blocks_selection():
    edge = [-10.0, -8.0, -6.0, -4.0, -2.0, 0.0, 2.0]  # still rising at 21.2 GHz
    r = mf.select_lo_drive(sweep({"f17p70": RISING, "f19p45": RISING, "f21p20": edge}), BANDS, DRIVES)
    assert r["status"] == "no acceptable drive in declared sweep"
    assert "f21p20" in r["reason"]


def test_missing_or_invalid_point_is_inconclusive():
    pts = sweep({b: RISING for b in BANDS})
    r = mf.select_lo_drive(pts[:-1], BANDS, DRIVES)
    assert r["status"] == "inconclusive"
    pts = sweep({b: RISING for b in BANDS}, status={("f19p45", -27.0): "invalid"})
    assert mf.select_lo_drive(pts, BANDS, DRIVES)["status"] == "inconclusive"
    pts = sweep({b: RISING for b in BANDS})
    pts[3]["gain_db"] = float("nan")
    assert mf.select_lo_drive(pts, BANDS, DRIVES)["status"] == "inconclusive"
    pts = sweep({b: RISING for b in BANDS})
    assert mf.select_lo_drive(pts + [dict(pts[0])], BANDS, DRIVES)["status"] == "inconclusive"


# ---------------------------------------------------------------------------
# IIP3
# ---------------------------------------------------------------------------


def two_tone_sweep(iip3=0.0, gain=5.0, pins=None, floor=-140.0, comp_from=None, noise=None, im3h_offset=0.0):
    pins = pins if pins is not None else [-70.0 + 5 * i for i in range(13)]
    pts = []
    for i, p in enumerate(pins):
        fund = p + gain
        im3 = 3 * p + gain - 2 * iip3
        if comp_from is not None and p > comp_from:
            fund -= 2.0 * (p - comp_from) / 5.0
        if noise:
            im3 += noise[i % len(noise)]
        pts.append({"pin_dbm": p, "status": "ok", "p_if1_dbm": fund, "p_if2_dbm": fund,
                    "p_im3l_dbm": im3, "p_im3h_dbm": im3 + im3h_offset, "floor_dbm": floor})
    return pts


def test_iip3_recovers_intercept_from_ideal_slopes():
    r = mf.fit_iip3(two_tone_sweep(iip3=-2.0))
    assert r["status"] == "ok"
    assert r["iip3_dbm"] == pytest.approx(-2.0, abs=1e-9)
    low = r["sidebands"]["low"]
    assert low["slope_fund"] == pytest.approx(1.0) and low["slope_im3"] == pytest.approx(3.0)


def test_iip3_conservative_is_lower_sideband():
    # the high IM3 sideband 2 dB stronger -> its intercept is 1 dB lower
    r = mf.fit_iip3(two_tone_sweep(iip3=0.0, im3h_offset=2.0))
    assert r["status"] == "ok"
    assert r["sidebands"]["high"]["iip3_dbm"] == pytest.approx(-1.0)
    assert r["iip3_dbm"] == pytest.approx(-1.0)


def test_iip3_excludes_below_floor_and_compressed_steps():
    # IM3 at -70 dBm in is 3*-70+5 = -205 dBm: below a -140 dBm floor
    r = mf.fit_iip3(two_tone_sweep(iip3=0.0, comp_from=-30.0))
    assert r["status"] == "ok"
    lo, hi = r["sidebands"]["low"]["interval_dbm"]
    assert 3 * lo + 5 >= -140 + 10       # IM3 at the interval start clears floor + margin
    assert hi <= -25.0                    # stops before >1 dB compression
    assert r["iip3_dbm"] == pytest.approx(0.0, abs=1e-9)


def test_iip3_unavailable_cases():
    assert mf.fit_iip3(two_tone_sweep(pins=[-30.0]))["status"] == "IIP3 unavailable"
    assert mf.fit_iip3(two_tone_sweep(pins=[-35.0, -30.0]))["status"] == "IIP3 unavailable"
    # everything below the extraction floor
    r = mf.fit_iip3(two_tone_sweep(iip3=40.0, floor=-100.0))
    assert r["status"] == "IIP3 unavailable"
    # compressed from the start: no 1:3 region
    r = mf.fit_iip3(two_tone_sweep(iip3=0.0, comp_from=-75.0, floor=-300.0))
    assert r["status"] == "IIP3 unavailable"
    # noisy IM3 (slope wanders far from 3) -> unavailable, not a guessed fit
    r = mf.fit_iip3(two_tone_sweep(iip3=0.0, noise=[0.0, 6.0, -6.0], floor=-300.0))
    assert r["status"] == "IIP3 unavailable"
    # a non-ok step breaks contiguity
    pts = two_tone_sweep(iip3=0.0, pins=[-45.0, -40.0, -35.0, -30.0])
    pts[1]["status"] = "invalid"
    assert mf.fit_iip3(pts)["status"] == "IIP3 unavailable"


# ---------------------------------------------------------------------------
# convergence comparison
# ---------------------------------------------------------------------------


def test_compare_converged():
    kw = dict(tol_db=0.2, floor_margin_db=10.0)
    assert mf.compare_converged("g", -2.0, -2.1, -140.0, **kw)["ok"]
    assert not mf.compare_converged("g", -2.0, -2.3, -140.0, **kw)["ok"]
    both = mf.compare_converged("leak", -288.0, -260.0, -140.0, **kw)
    assert both["ok"] and both["reason"] == "both at extraction floor"
    assert not mf.compare_converged("leak", -125.0, -135.0, -140.0, **kw)["ok"]
    assert not mf.compare_converged("g", float("nan"), -2.0, -140.0, **kw)["ok"]


def test_interpolation_bound():
    assert mf.interp_bound_db(1e9, 1e-12) < 1e-4
    b = mf.interp_bound_db(18.45e9, 1e-12)
    assert 0.01 < b < 0.02


def test_analytic_closed_forms_are_self_consistent(study):
    params = study.control.params
    run = make_run(study, "two_tone", rf=-40.0)
    exp = mf.analytic_expectations(params, run)
    assert exp["p_im3l_dbm"] == exp["p_im3h_dbm"]
    # in the small-signal limit the intercept implied by the closed forms
    # matches analytic_iip3_dbm
    run = make_run(study, "two_tone", rf=-90.0)
    e = mf.analytic_expectations(params, run)
    implied = -90.0 + (e["p_if1_dbm"] - e["p_im3l_dbm"]) / 2
    assert implied == pytest.approx(mf.analytic_iip3_dbm(params), abs=1e-6)


# ---------------------------------------------------------------------------
# collection gate and conclusion (negative controls)
# ---------------------------------------------------------------------------


def good_collection(study):
    off = {"hbt_typ": 0.0, "hbt_bcs": 0.4, "hbt_wcs": -0.6}
    cells = []
    for c in mf.expected_cells(study):
        cell = dict(c, status="ok", model_section=c["corner"], stress={"rejecting": [], "violations": []},
                    gain_db=5.0 + off.get(c["corner"], 0.0), rail_power_mw=4.5, dc_rail_power_mw=4.5,
                    lo_vdiff_loaded_peak_v=0.3, lo_rf_dbm=-60.0, lo_if_dbm=-50.0, p_if1_dbm=-30.0,
                    p_if2_dbm=-30.0, p_im3l_dbm=-80.0, p_im3h_dbm=-80.0)
        if c["matrix"] != "leakage":
            cell.pop("seed", None)
        cells.append(cell)
    return cells


def test_gate_accepts_complete_collection(study):
    assert mf.validate_collection(study, good_collection(study)) == []


def test_gate_accepts_explicit_scientific_rejection(study):
    cells = good_collection(study)
    cells[5] = dict(cells[5], status="rejected_stress", gain_db=None,
                    stress={"rejecting": [{"device": "q3", "interval": "retained", "quantity": "vbe"}]})
    assert mf.validate_collection(study, cells) == []


@pytest.mark.parametrize("case", [
    "delete", "duplicate", "nan", "missing_key", "typical_forced", "wrong_section",
    "ok_with_violation", "rejected_without_violation", "corrupt_status", "undeclared", "wrong_seed",
])
def test_gate_negative_controls(study, case):
    cells = good_collection(study)
    if case == "delete":
        cells = cells[1:]
    elif case == "duplicate":
        cells.append(copy.deepcopy(cells[0]))
    elif case == "nan":
        cells[0]["gain_db"] = float("nan")
    elif case == "missing_key":
        del cells[0]["rail_power_mw"]
    elif case == "typical_forced":
        for c in cells:
            c["gain_db"] = 5.0
    elif case == "wrong_section":
        cells[0]["model_section"] = "hbt_typ" if cells[0]["corner"] != "hbt_typ" else "hbt_bcs"
    elif case == "ok_with_violation":
        cells[0]["stress"] = {"rejecting": [{"device": "q1"}]}
    elif case == "rejected_without_violation":
        cells[0]["status"] = "rejected_stress"
    elif case == "corrupt_status":
        cells[0]["status"] = "failed"
    elif case == "undeclared":
        cells.append(dict(cells[0], id="matrix=main|candidate=nope"))
    elif case == "wrong_seed":
        for c in cells:
            if c["matrix"] == "leakage":
                c["seed"] = 7
    assert mf.validate_collection(study, cells), case


def test_conclusion_never_recommends_floor_and_respects_stress(study):
    cells = good_collection(study)
    per = {}
    for cand in study.candidates:
        per[cand.name] = {"lo_selection": {"status": "selected", "drive_dbm": -9.0},
                          "main_cells": [c for c in cells if c["matrix"] == "main" and c["candidate"] == cand.name]}
    # make the floor look best: it must still not be recommended
    for c in per["placeholder_floor"]["main_cells"]:
        c["gain_db"] = 30.0
    out = mf.conclude(study, per)
    assert out["recommendation"]["draw_first"] in ("gilbert_stacked", "folded_single_balanced")
    # one stress-rejected cell removes a candidate from feasibility
    g = per["gilbert_stacked"]["main_cells"]
    g[0] = dict(g[0], status="rejected_stress")
    f = per["folded_single_balanced"]["main_cells"]
    f[0] = dict(f[0], status="rejected_stress")
    out = mf.conclude(study, per)
    assert out["verdicts"]["gilbert_stacked"]["verdict"] == "infeasible at the declared sizing"
    assert out["recommendation"]["draw_first"] is None
    # no acceptable drive / inconclusive are explicit verdicts, not forced choices
    per["gilbert_stacked"]["lo_selection"] = {"status": "inconclusive", "reason": "missing"}
    per["folded_single_balanced"]["lo_selection"] = {"status": "no acceptable drive in declared sweep",
                                                     "reason": "x"}
    out = mf.conclude(study, per)
    assert out["verdicts"]["gilbert_stacked"]["verdict"] == "inconclusive"
    assert out["verdicts"]["folded_single_balanced"]["verdict"] == "infeasible at the declared sizing"
    assert out["recommendation"]["draw_first"] is None


def test_run_params_follow_port_conventions(study):
    run = make_run(study, "two_tone", rf=-30.0, drive=-6.0)
    p = run.params()
    assert p["vrf1"] == p["vrf2"] == pytest.approx(mf.v_open_peak_for(-30.0, 50.0))
    assert p["vlo"] == pytest.approx(mf.v_open_peak_for(-6.0, 100.0))
    off = dataclasses.replace(run, kind="rfoff", rf_dbm=None)
    assert off.params()["vrf1"] == 0.0 and off.params()["vrf2"] == 0.0


def test_ideal_sink_compliance_is_required_and_reported(study):
    cand = study.candidate("gilbert_stacked")
    assert cand.sink_nodes == ("tail",)
    run = make_run(study, "rfoff")
    lines = mf.build_control_lines([run], cand.devices, sink_nodes=cand.sink_nodes)
    printed = {ln.split()[1] for ln in lines if ln.startswith("print ")}
    assert {"mf_dc_sink_tail", "mf_su_sinkmin_tail", "mf_ss_sinkmin_tail"} <= printed
    vals = synth_values(run, cand.devices, {"loif": 1e-3, "lorf": 1e-5, "lodiff": 0.5})
    assert mf.analyze_run(run, vals, cand.devices, study.stress, sink_nodes=cand.sink_nodes)["status"] == "invalid"
    vals.update(mf_dc_sink_tail=0.22, mf_su_sinkmin_tail=0.21, mf_ss_sinkmin_tail=0.215)
    res = mf.analyze_run(run, vals, cand.devices, study.stress, sink_nodes=cand.sink_nodes)
    assert res["status"] == "ok"
    assert res["ideal_sink_v"]["tail"] == {"dc": 0.22, "startup_min": 0.21, "retained_min": 0.215}
