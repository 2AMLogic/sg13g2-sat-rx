"""Method qualification of the lna-headroom screening bench (issue #123); no simulator, PDK or network.

A closed-form fake of the klt logs (a memoryless cubic 'DUT' whose Q2 V_CE excursion grows with the
output amplitude) is pushed through the real body generator, log parser, extractor, gates and ranking.
"""

from __future__ import annotations

import gzip
import json
import re

import pytest

import headroom as H
import linearity as L

HP, LP = H.load_plans()
DUT = H.DUT_PATH.read_text()
GOOD_DC = {"vc1": 1.2472, "ve1": 0.0047, "vb1": 0.814, "vb2": 2.056, "voc": 2.5, "idd": 0.002}


def fake_log(key, *, a1=10.0, a3=-2000.0, vce2_dc=1.253, swing_per_v=2.0, dc=None, floor_v=1e-9, omit_dc=False):
    lines = ["fake"]
    runs = H.runs_for_key(HP, LP, key)
    for run in runs:
        rid, n = run["id"], int(round(run["window_s"] / run["step_s"]))
        am = L.cubic_tone_amps(a1, a3, run["vs_peak_v"], False)
        vals = {f"m_{rid}_n": n}
        for b in run["bins"]:
            a = am["f0"] if b == "f0" else floor_v
            vals[f"m_{rid}_{b}_c"], vals[f"m_{rid}_{b}_s"] = a * 0.6, a * 0.8
        if run["monitors"]:
            sw = swing_per_v * am["f0"]
            for name, nom, s in (("vce_q1", 1.243, 0.0), ("vce_q2", vce2_dc, sw), ("vbe_q1", 0.81, 0.0), ("vbe_q2", 0.81, 0.0)):
                vals[f"m_{rid}_{name}_max"], vals[f"m_{rid}_{name}_min"] = nom + s, nom - s
            for name, _ in run["currents"]:
                vals[f"m_{rid}_{name}_max"], vals[f"m_{rid}_{name}_min"] = 1.6e-3, 1.4e-3
        lines += [f"{k} = {v:.12e}" for k, v in vals.items()]
    if key != H.CONTROL and not omit_dc:
        for k, v in (dc or GOOD_DC).items():
            lines.append(f"m_dc_{k} = {v:.9e}")
    lines.append("LNLIN_DONE")
    return "\n".join(lines) + "\n"


def hist_from(text):
    """A stand-in 'historical record' built from the same fake: the reproduction check then has a known answer."""
    summ, _, _ = H.summaries(HP, LP, "C00", text)
    pl_res, sweeps = {}, {}
    for pl in LP["placements"]:
        ss = [s for s in summ if s["placement"] == pl["name"]]
        rows = L.points_from_summaries(ss, "one")
        pl_res[pl["name"]] = {"first_limit_violation": {"single_tone": _fv(rows)}}
        sweeps[pl["name"]] = {"base": {"one": rows}}
    return {"placements": pl_res}, sweeps


def _fv(rows):
    for r in sorted(rows, key=lambda x: x["pin_dbm"]):
        v = L.limit_violations(r["excursion_v"], LP["extraction"]["operating_limits"], r.get("current_a"))
        if v:
            return {"pin_dbm": r["pin_dbm"], "violations": v}


def all_texts(**per):
    out = {H.CONTROL: fake_log(H.CONTROL, a1=LP["controls"]["a1"], a3=LP["controls"]["a3"])}
    for c in H.candidates(HP):
        out[c["id"]] = fake_log(c["id"], **per.get(c["id"], {}))
    return out


def test_plan_is_coherent():
    assert H.plan_problems(HP, LP, DUT) == []


def test_baseline_candidate_is_the_committed_dut_and_divider_sum_is_held():
    base = H.variant_text(DUT, next(c for c in H.candidates(HP) if c["id"] == "C00"))
    strip = lambda t: [ln for ln in t.splitlines() if not ln.startswith("*")]  # noqa: E731
    got = {m.group(1): H.spice_value(m.group(2)) for m in re.finditer(r"^(R1b|R2b|Rd) \S+ \S+ (\S+) m=1$", base, re.M)}
    assert got == {"R1b": 1500.0, "R2b": 7000.0, "Rd": 465.0}
    assert len(strip(base)) == len(strip(DUT))


def test_variants_change_only_the_three_declared_resistors():
    for c in H.candidates(HP):
        a, b = DUT.splitlines(), [ln for ln in H.variant_text(DUT, c).splitlines() if not ln.startswith("* EXPERIMENTAL") and not ln.startswith("* GENERATED")]
        diff = [x for x, y in zip(a, b) if x != y]
        assert len(a) == len(b)
        assert all(x.split()[0] in ("R1b", "R2b", "Rd") for x in diff), diff


def test_committed_variant_decks_regenerate():
    for c in H.candidates(HP):
        assert (H.VARIANTS_DIR / f"{c['id']}.spice").read_text() == H.variant_text(DUT, c)


def test_bodies_have_dc_block_unique_runs_and_current_monitors():
    for c in H.candidates(HP):
        body = H.body_for_key(HP, LP, c["id"], DUT)
        runs = H.runs_for_key(HP, LP, c["id"])
        ids = [r["id"] for r in runs]
        assert len(ids) == len(set(ids)) == 3 * len(L.sweep_pins(LP, "one"))
        assert "  op\n" in body and "m_dc_idd" in body
        assert body.count("@q.xdut.xq2.qnpn13g2[ic]") >= len(runs)
    assert "m_dc_" not in H.body_for_key(HP, LP, H.CONTROL, DUT)


def test_a_missing_dc_value_is_a_log_problem_not_a_result():
    t = all_texts()
    t["C03"] = fake_log("C03", omit_dc=True)
    res = H.analyze(HP, LP, t, *hist_from(t["C00"]))
    assert any("DC operating-point" in p for p in res["problems"])


def test_baseline_reproduction_and_stress_boundary():
    t = all_texts()
    res = H.analyze(HP, LP, t, *hist_from(t["C00"]))
    assert res["problems"] == [] and res["baseline_reproduction"]["reproduced"]
    p = res["candidates"]["C00"]["placements"]["mid"]
    s = p["stress"]
    assert s["violated"] and s["limit_identity"] == "q2 V_CE peak"
    assert s["stress_free_pin_dbm"] < s["first_violation_pin_dbm"]
    # P1dB is bounded, never a number, when the first violation precedes the crossing
    assert p["p1db"]["status"] == "bounded" and p["p1db"]["p1db_in_dbm_gt"] == s["stress_free_pin_dbm"]
    assert res["ngspice_control"]["pass"]


def test_baseline_not_reproduced_blocks_the_ranking():
    t = all_texts()
    hist, sweeps = hist_from(t["C00"])
    for n in hist["placements"]:
        hist["placements"][n]["first_limit_violation"]["single_tone"]["pin_dbm"] -= 10
    res = H.analyze(HP, LP, t, hist, sweeps)
    assert not res["baseline_reproduction"]["reproduced"]
    assert res["ranking"]["outcome_class"] == "BASELINE_NOT_REPRODUCED" and res["ranking"]["shortlist"] == []


def test_bias_only_gain_is_not_headroom_and_attenuation_is_gated():
    # C03: same gain, Q2 DC V_CE lowered by 0.1 V (real input-referred headroom, same compression);
    # C01: swing per volt unchanged but gain 6.5 dB lower (an attenuated candidate); C02: lower still.
    per = {"C03": dict(vce2_dc=1.153, dc=dict(GOOD_DC, vc1=1.347)), "C01": dict(a1=10 * 10 ** (-6.5 / 20), a3=-2000 * 10 ** (-6.5 / 20 * 3)),
           "C02": dict(a1=10 * 10 ** (-9 / 20), a3=-2000 * 10 ** (-9 / 20 * 3))}
    t = all_texts(**per)
    res = H.analyze(HP, LP, t, *hist_from(t["C00"]))
    c = res["candidates"]
    assert c["C03"]["metrics"]["headroom_gain_db"] > 2.0 and not c["C03"]["gates"]["failed"]
    assert c["C01"]["gates"]["G_gain"] is False and "G_gain" in res["ranking"]["not_ranked"]["C01"]
    assert "C01" not in res["ranking"]["admitted"] and "C02" not in res["ranking"]["admitted"]
    assert res["ranking"]["admitted"][0] == "C03"


def test_dc_gate_rejects_a_q1_over_limit_and_stays_visible():
    t = all_texts(C09=dict(dc=dict(GOOD_DC, vc1=1.395)))
    res = H.analyze(HP, LP, t, *hist_from(t["C00"]))
    assert "G_dc" in res["candidates"]["C09"]["gates"]["failed"]
    assert "C09" in res["candidates"] and "C09" not in res["ranking"]["admitted"]


def test_no_feasible_candidate_when_nothing_clears_the_shortlist_rule():
    t = all_texts()
    res = H.analyze(HP, LP, t, *hist_from(t["C00"]))
    assert res["ranking"]["shortlist"] == [] and res["ranking"]["outcome_class"] == "no_feasible_candidate"


def test_stress_valid_p1db_is_reported_when_the_crossing_is_inside_the_limits():
    t = all_texts(C03=dict(swing_per_v=0.0))  # no excursion growth: the 1 dB crossing is reachable
    res = H.analyze(HP, LP, t, *hist_from(t["C00"]))
    ps = res["candidates"]["C03"]["placements"]
    assert all(p["p1db"]["status"] == "ok" for p in ps.values())
    assert res["ranking"]["outcome_class"] in ("stress_valid_p1db_meets_row8", "stress_valid_p1db_below_row8")


def test_analysis_is_deterministic_and_roundtrips():
    t = all_texts()
    h = hist_from(t["C00"])
    a, b = H.analyze(HP, LP, t, *h), H.analyze(HP, LP, t, *h)
    assert json.dumps(H.roundtrip(a), sort_keys=True) == json.dumps(H.roundtrip(b), sort_keys=True)


def test_committed_records_verify():
    import importlib.util
    spec = importlib.util.spec_from_file_location("lna_headroom_run", H.BENCH_DIR / "run.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    for p in sorted(R.RECORDS.glob("*.json")):
        if not p.name.endswith("-sweeps.json"):
            assert R.verify_record(p.stem) == []
