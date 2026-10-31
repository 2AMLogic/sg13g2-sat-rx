"""Collector-current diagnostics of plan_version 2 (issue #121).

Pure tests run on the closed-form fake logs: declaration, version separation, sign/scale
normalisation, current-only violations, missing / non-finite diagnostics, unresolved-validity
publication. The simulator tests (skipped without ngspice and the SG13G2 HBT model library) are
SINGLE-unit local runs: a known-answer fixture for sign and scale of the `@q...[ic]` access, and a
with/without comparison proving the instrumentation does not change the extracted voltages/gain.

    python3 -m pytest sim/lna-linearity/tests/test_current_instrumentation.py -q
"""

from __future__ import annotations

import copy
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import analysis as A
import fakes
import linearity as L
from conftest import BENCH

PLAN1 = L.load_plan(BENCH / "testbench" / "plan.json")
PLAN2 = L.load_plan(BENCH / "testbench" / "plan-v2.json")
LIM2 = PLAN2["extraction"]["operating_limits"]
CFG = LIM2["collector_current"]
DUT = BENCH.parents[1] / "design" / "netlist" / "lna_stage1.spice"
MODEL_LIB = Path.home() / "share/pdk/ihp-sg13g2/libs.tech/ngspice/models/cornerHBT.lib"


def plan2(**cc) -> dict:
    p = copy.deepcopy(PLAN2)
    p["extraction"]["operating_limits"]["collector_current"].update(cc)
    return p


# ---- declaration and version separation -------------------------------------


def test_v2_changes_only_the_operating_limit_diagnostics():
    a, b = copy.deepcopy(PLAN1), copy.deepcopy(PLAN2)
    assert (a["plan_version"], b["plan_version"]) == (1, 2)
    for k in ("issue", "plan_version", "development_note", "supersedes_interpretation"):
        a.pop(k, None), b.pop(k, None)
    ol_a, ol_b = a["extraction"].pop("operating_limits"), b["extraction"].pop("operating_limits")
    assert a == b  # sweep, time, numerics, thresholds, controls, targets untouched
    for k in ("vce_max_v", "vce_window_v", "vbe_window_v", "source"):
        assert ol_a[k] == ol_b[k]
    assert "collector_current" not in ol_a


def test_v1_plan_keeps_voltage_only_semantics_and_emits_no_current():
    assert L.current_cfg(PLAN1) is None and L.current_monitors(PLAN1) == ()
    assert all(not r["currents"] for r in A.runs_for_key(PLAN1, "mid_one"))
    body = "\n".join(L.run_block("x", va1=1, va2=0, bins={"f0": 1e8}, step_s=1e-12, discard_s=1e-9,
                                 window_s=1e-9, monitors=True))
    assert "@q" not in body and "save" not in body


def test_v2_declaration_states_units_sign_normalisation_and_applicability():
    for k in ("units", "sign", "normalization", "interpretation", "applicability", "quantity"):
        assert CFG[k]
    assert CFG["applicability"] == "unresolved" and CFG["enforce"] is False
    assert CFG["box_a_per_nx"] == 0.003 and CFG["max_frac"] == 1.0
    assert [a for a, _ in L.current_monitors(PLAN2)] == ["ic_q1", "ic_q2"]


def test_declared_nx_matches_the_dut_netlist():
    txt = DUT.read_text()
    for q, inst in (("q1", "xq1"), ("q2", "xq2")):
        m = re.search(rf"^{inst}\s+.*?\bNx=(\d+)", txt, re.M | re.I)
        assert m and int(m.group(1)) == CFG["devices"][q]["nx"]
        assert CFG["devices"][q]["instance"] == f"q.xdut.{inst}.qnpn13g2"


def test_generated_block_reads_the_simulator_access_and_saves_it():
    runs = A.runs_for_key(PLAN2, "mid_one")
    assert all(r["currents"] for r in runs) and not any(r["currents"] for r in A.runs_for_key(PLAN2, "control_one"))
    body = L.body_for_runs("t", "* c", runs[:1])
    assert "save all @q.xdut.xq1.qnpn13g2[ic] @q.xdut.xq2.qnpn13g2[ic]" in body
    assert "linearize v(p2)" in body and "@q.xdut.xq1.qnpn13g2[ic]" in body
    for q in ("ic_q1", "ic_q2"):
        assert f"m_{runs[0]['id']}_{q}_max" in body and f"m_{runs[0]['id']}_{q}_min" in body


# ---- normalisation, sign and known answers ----------------------------------


def test_normalisation_is_signed_and_sized():
    # 24 mA through Nx = 8 is exactly the 3 mA x Nx box; -12 mA is -0.5 of it (sign kept)
    assert L.current_frac(CFG, "ic_q1", 0.024) == pytest.approx(1.0)
    assert L.current_frac(CFG, "ic_q2", -0.012) == pytest.approx(-0.5)


def _logs(plan, **kw):
    return fakes.fake_logs(plan, excursion_per_v=0.0, floor_v=1e-9, **kw)


def test_summary_carries_finite_signed_current_extrema_and_fraction():
    texts = _logs(PLAN2, ic_swing_a_per_v=0.0, ic_quiescent_a=0.012)
    s, probs = A.summaries_for_key(PLAN2, "mid_one", texts["mid_one"])
    assert not probs
    cur = s[0]["current_a"]
    assert set(cur) == {"ic_q1_max", "ic_q1_min", "ic_q2_max", "ic_q2_min"}
    assert all(math.isfinite(v) for v in cur.values())
    row = L.points_from_summaries(s, "one")[0]
    assert L.current_frac(CFG, "ic_q1", row["current_a"]["ic_q1_max"]) == pytest.approx(0.5)


# ---- missing / non-finite diagnostics ---------------------------------------


def test_missing_current_diagnostic_is_a_log_problem_not_a_pass():
    texts = _logs(PLAN2, omit_current=True)
    s, probs = A.summaries_for_key(PLAN2, "mid_one", texts["mid_one"])
    assert probs and not s


def test_nonfinite_current_diagnostic_is_a_log_problem():
    texts = _logs(PLAN2, bad_current=float("nan"))
    _, probs = A.summaries_for_key(PLAN2, "mid_one", texts["mid_one"])
    assert probs


def test_row_without_current_diagnostics_is_rejected_even_when_unresolved():
    rows = L.synthetic_rows(PLAN2, 10.0, -2000.0, 1e-6, kind="one")
    for r in rows:
        r["excursion_v"] = {k: v for k, v in zip(
            [f"{n}_{q}" for n in ("vce_q1", "vce_q2", "vbe_q1", "vbe_q2") for q in ("max", "min")],
            [1.2] * 4 + [0.8] * 4)}
    # voltage-only rows under a v2 plan: never fitted through
    res = L.fit_p1db(rows, PLAN2["extraction"]["p1db"], LIM2)
    assert res["status"] == "unavailable"
    # and a nan inside an otherwise complete dict is the same rejection
    good = {f"ic_{q}_{m}": 0.01 for q in ("q1", "q2") for m in ("max", "min")}
    for r in rows:
        r["current_a"] = dict(good, ic_q2_max=float("nan"))
    assert L.fit_p1db(rows, PLAN2["extraction"]["p1db"], LIM2)["status"] == "unavailable"
    for r in rows:
        r["current_a"] = dict(good)
    assert L.fit_p1db(rows, PLAN2["extraction"]["p1db"], LIM2)["status"] == "ok"


# ---- current-only violation --------------------------------------------------


def _rows_with_current(plan, over_from_dbm):
    rows = L.synthetic_rows(plan, 10.0, -2000.0, 1e-6, kind="one")
    v = dict(zip([f"{n}_{q}" for n in ("vce_q1", "vce_q2", "vbe_q1", "vbe_q2") for q in ("max", "min")],
                 [1.2] * 4 + [0.8] * 4))
    for r in rows:
        r["excursion_v"] = dict(v)  # every VOLTAGE limit is respected at every point
        hi = 0.030 if r["pin_dbm"] >= over_from_dbm else 0.012  # 30 mA = 1.25 x box (Nx 8)
        r["current_a"] = {"ic_q1_max": 0.012, "ic_q1_min": 0.009, "ic_q2_max": hi, "ic_q2_min": 0.009}
    return rows


def test_enforced_current_only_violation_cannot_enter_a_fit():
    p = plan2(enforce=True, applicability="applicable")
    lim = p["extraction"]["operating_limits"]
    rows = _rows_with_current(p, -28.0)
    assert not L.limit_violations(rows[0]["excursion_v"], lim, rows[0]["current_a"])
    v = L.limit_violations(rows[-1]["excursion_v"], lim, rows[-1]["current_a"])
    assert v and "I_C peak" in v[0]
    res = L.fit_p1db(rows, p["extraction"]["p1db"], lim)
    assert res["status"] == "bounded" and "rejected" in res["reason"]  # the 1 dB crossing lies in the rejected region
    free = L.fit_p1db(rows, p["extraction"]["p1db"], lim, enforce_limits=False)
    assert free["status"] == "ok"
    # also kept out of the baseline: a violating low-power point does not seed it
    low = _rows_with_current(p, -100.0)
    assert L.fit_p1db(low, p["extraction"]["p1db"], lim)["status"] == "unavailable"
    # and out of the IIP3 estimator
    two = L.synthetic_rows(p, 10.0, -2000.0, 1e-9, kind="two")
    for r in two:
        r["excursion_v"] = rows[0]["excursion_v"]
        r["current_a"] = {"ic_q1_max": 0.030, "ic_q1_min": 0.0, "ic_q2_max": 0.012, "ic_q2_min": 0.0}
    assert L.fit_iip3(two, p["extraction"]["iip3"], lim)["status"] == "unavailable"


def test_unresolved_applicability_publishes_extrema_and_does_not_claim_a_complete_envelope():
    rows = _rows_with_current(PLAN2, -28.0)
    assert not L.limit_violations(rows[-1]["excursion_v"], LIM2, rows[-1]["current_a"])  # not excluded on this basis
    v = L.current_validity(rows, LIM2)
    assert v["status"] == "unresolved" and v["complete_envelope"] is False
    assert v["points_without_diagnostics"] == 0 and v["points_over_box_pin_dbm"]
    q2 = v["extrema"]["q2"]
    assert q2["max_a"] == pytest.approx(0.030) and q2["max_frac_of_box"] == pytest.approx(1.25)
    assert q2["min_a"] == pytest.approx(0.009) and q2["min_frac_of_box"] == pytest.approx(0.375)
    assert v["extrema"]["q1"]["max_frac_of_box"] == pytest.approx(0.5)
    assert v["interpretation"] == CFG["interpretation"]


def test_complete_envelope_requires_enforcement_and_full_coverage():
    p = plan2(enforce=True, applicability="applicable")
    lim = p["extraction"]["operating_limits"]
    rows = _rows_with_current(p, 100.0)
    assert L.current_validity(rows, lim)["complete_envelope"] is True
    rows[3].pop("current_a")
    v = L.current_validity(rows, lim)
    assert v["complete_envelope"] is False and v["points_without_diagnostics"] == 1


def test_end_to_end_v2_analysis_publishes_the_flag_and_v1_does_not():
    texts = _logs(PLAN2, ic_swing_a_per_v=0.0)
    res = A.analyze(PLAN2, texts)
    assert not res["problems"]
    for pl in res["placements"].values():
        assert pl["current_validity"]["single_tone"]["status"] == "unresolved"
        assert pl["final"]["p1db"]["current_validity"]["complete_envelope"] is False
    res1 = A.analyze(PLAN1, fakes.fake_logs(PLAN1, excursion_per_v=0.0, floor_v=1e-9))
    for pl in res1["placements"].values():
        assert "current_validity" not in pl and "current_validity" not in pl["final"]["p1db"]
        assert all("current_a" not in r for sw in pl["sweeps"]["base"].values() for r in sw)


# ---- simulator qualification (single local units) ---------------------------

NGSPICE = shutil.which("ngspice")
needs_sim = pytest.mark.skipif(not (NGSPICE and MODEL_LIB.is_file()), reason="needs ngspice and the SG13G2 HBT model library")

FIXTURE_SUBCKT = """\
* known-answer fixture: two independent common-emitter branches, collector resistors give the answer
.subckt lna_stage1 in out vdd gnd
Vbias1 bb1 gnd DC 0.80
Rb1 bb1 b1 1k
Cin1 in b1 100n
Xq1 c1 b1 e1 gnd npn13G2 Nx=8
Re1 e1 gnd 3
Rc1 vdd c1 150
Vbias2 bb2 gnd DC 0.78
Rb2 bb2 b2 1k
Cin2 in b2 100n
Xq2 oc b2 e2 gnd npn13G2 Nx=8
Re2 e2 gnd 3
Rc2 vdd oc 200
Cout oc out 100n
.ends
"""


def _run_deck(body: str, tmp_path: Path, tag: str) -> str:
    deck = body.replace("\n", f"\n.lib {MODEL_LIB} hbt_typ\n", 1)
    f = tmp_path / f"{tag}.cir"
    f.write_text(deck)
    p = subprocess.run([NGSPICE, "-b", f.name], cwd=tmp_path, capture_output=True, text=True, timeout=900, check=False)
    assert "LNLIN_DONE" in p.stdout, p.stdout[-2000:] + p.stderr[-500:]
    return p.stdout


def _one_point_plan(base: dict, pin_dbm: float) -> dict:
    p = copy.deepcopy(base)
    p["sweep"]["one"] = {"start_dbm": pin_dbm, "stop_dbm": pin_dbm, "step_db": 1.0}
    return p


@needs_sim
def test_sign_and_scale_against_collector_resistor_known_answer(tmp_path):
    p = _one_point_plan(PLAN2, -30.0)
    pl = {"name": "fx", "f_tone1_hz": 1e8, "f_tone2_hz": 1.1e8}  # 100 MHz: displacement current negligible
    runs = L.sweep_runs(p, pl, "one", monitors=True, variants=("base",))
    rid = runs[0]["id"]
    circuit = L.dut_circuit(FIXTURE_SUBCKT, 2.5) + "\n" + L.options_line(p, "one")
    body = L.body_for_runs("fixture", circuit, runs)
    i0 = int(round(runs[0]["settle_discard_s"] / runs[0]["step_s"]))
    i1 = i0 + int(round(runs[0]["window_s"] / runs[0]["step_s"])) - 1
    ref = [f"  let r1 = (2.5 - v(xdut.c1)[{i0},{i1}])/150", f"  let r2 = (2.5 - v(xdut.oc)[{i0},{i1}])/200 - xo/50",  # KCL at oc: Rc2 feeds the collector and the 50 ohm load
           "  let ref1max = maximum(r1)", "  let ref1min = minimum(r1)", "  let ref2max = maximum(r2)", "  let ref2min = minimum(r2)",
           "  print ref1max ref1min ref2max ref2min"]
    body = body.replace("  echo LNLIN_DONE", "\n".join(ref) + "\n  echo LNLIN_DONE")
    out = _run_deck(body, tmp_path, "fixture")
    vals, _ = L.parse_log(out)
    ref_vals = {k: float(v) for k, v in re.findall(r"(ref\dm\w+)\s*=\s*([-+0-9.eE]+)", out)}
    for q, r in (("q1", "ref1"), ("q2", "ref2")):
        for m in ("max", "min"):
            got, want = vals[f"m_{rid}_ic_{q}_{m}"], ref_vals[f"{r}{m}"]
            assert want > 3e-4  # a real sub-mA to mA-scale current, so sign and scale are testable
            assert got > 0  # sign: forward conduction into the collector is positive
            assert got == pytest.approx(want, rel=0.02)  # scale: 2 % on a sub-mA to mA-scale current
    s = L.run_summary(vals, runs[0])
    fr = L.current_frac(CFG, "ic_q1", s["current_a"]["ic_q1_max"])
    assert fr == pytest.approx(vals[f"m_{rid}_ic_q1_max"] / 0.024)  # Nx = 8 -> 24 mA box


@needs_sim
def test_instrumentation_does_not_perturb_voltages_or_gain_on_the_dut(tmp_path):
    p = _one_point_plan(PLAN2, -36.0)
    pl = PLAN2["placements"][1]
    results = {}
    for tag, mon in (("with", True), ("without", False)):
        runs = L.sweep_runs(p, pl, "one", monitors=True, variants=("base",))
        if not mon:
            runs = [dict(r, currents=()) for r in runs]
        body = L.body_for_runs(tag, L.dut_circuit(DUT.read_text(), 2.5) + "\n" + L.options_line(p, "one"), runs)
        vals, _ = L.parse_log(_run_deck(body, tmp_path, tag))
        results[tag] = (L.run_summary(vals, runs[0]), runs[0])
    (w, _), (wo, _) = results["with"], results["without"]
    assert "current_a" in w and "current_a" not in wo
    assert all(math.isfinite(v) for v in w["current_a"].values())
    for b in w["p_dbm"]:
        assert w["p_dbm"][b] == pytest.approx(wo["p_dbm"][b], abs=1e-9)
    assert w["excursion_v"] == pytest.approx(wo["excursion_v"], abs=1e-12)
    gain = w["p_dbm"]["f0"] - w["pin_dbm"]
    assert gain == pytest.approx(wo["p_dbm"]["f0"] - wo["pin_dbm"], abs=1e-9)
    assert 0.0 < w["current_a"]["ic_q1_max"] and 0.0 < w["current_a"]["ic_q2_max"]
