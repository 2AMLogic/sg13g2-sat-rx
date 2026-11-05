"""Method qualification of the stage-2 refinement flow (issue #132); no simulator, PDK or network.

A closed-form fake of the klt logs (the memoryless-cubic 'DUT' of test_headroom.py, plus two-tone
bins and a fake small-signal log) is pushed through the real stage-2 request keys, body generators,
log parsers, controls, stage-1 reproduction, convergence verdicts, two-tone IIP3 fit, small-signal
comparison, validity gates and outcome classes.
"""

from __future__ import annotations

import copy
import json

import pytest

import headroom as H
import linearity as L
import small_signal as SS
from test_headroom import GOOD_DC, DUT, HP_FULL, LP

HP = HP_FULL
REF = H.refinement(HP)
CIDS = REF["candidates"]  # ["C08", "C05", "C00"]
A1, A3 = LP["controls"]["a1"], LP["controls"]["a3"]


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


def fake_sweep_log(key, *, a1=10.0, a3=-2000.0, vce2_dc=1.253, swing_per_v=2.0, swing_two=2.0,
                   dc=None, floor_v=1e-9, omit_dc=False, scale=1.0, refine_scale=None):
    """Fake klt log for one stage-2 sweep request (control_one/control_two/<cid>_one/<cid>_two).

    ``scale`` applies to every run; ``refine_scale`` (if given) replaces it for the non-base timing
    variants, which is how a convergence failure is faked."""
    lines = ["fake"]
    for run in H.runs_for_key(HP, LP, key):
        rid, n = run["id"], int(round(run["window_s"] / run["step_s"]))
        two = run["kind"] == "two"
        am = L.cubic_tone_amps(a1, a3, run["vs_peak_v"], two)
        s = scale if refine_scale is None or run["variant"] == "base" else refine_scale
        vals = {f"m_{rid}_n": n}
        for b in run["bins"]:
            if b.startswith("fl_"):
                a = floor_v
            elif two:
                a = am["im3l"] if b.startswith("im3") else am["f1"]
            else:
                a = am["f0"] if b == "f0" else floor_v
            vals[f"m_{rid}_{b}_c"], vals[f"m_{rid}_{b}_s"] = a * 0.6 * s, a * 0.8 * s
        if run["monitors"]:
            sw = (swing_two if two else swing_per_v) * (am["f1"] if two else am["f0"])
            for name, nom, s in (("vce_q1", 1.243, 0.0), ("vce_q2", vce2_dc, sw),
                                 ("vbe_q1", 0.81, 0.0), ("vbe_q2", 0.81, 0.0)):
                vals[f"m_{rid}_{name}_max"], vals[f"m_{rid}_{name}_min"] = nom + s, nom - s
            for name, _ in run["currents"]:
                vals[f"m_{rid}_{name}_max"], vals[f"m_{rid}_{name}_min"] = 1.6e-3, 1.4e-3
        lines += [f"{k} = {v:.12e}" for k, v in vals.items()]
    if not key.startswith(H.CONTROL) and not omit_dc:
        for k, v in (dc or GOOD_DC).items():
            lines.append(f"m_dc_{k} = {v:.9e}")
    lines.append("LNLIN_DONE")
    return "\n".join(lines) + "\n"


_SPARAM_DEFAULTS = {"s11_db": -10.0, "s21_db": 17.0, "s22_db": -8.0, "s12_db": -25.0, "msg_db": 42.0,
                    "k": 2.0, "d": 0.3, "mu": 2.5, "nf_db": 3.0,
                    "q1_vce": 1.243, "q2_vce": 1.253, "q1_icfrac": 0.065, "q2_icfrac": 0.065,
                    "idd_ma": 1.56, "pdc_mw": 3.9, "q1_vbe": 0.81, "q2_vbe": 0.81,
                    "q1_ic": 1.56e-3, "q2_ic": 1.56e-3, "q1_dtj": 1.0, "q2_dtj": 1.0,
                    "q1_ft": 80.0, "q2_ft": 80.0,
                    "qr_vce": 0.8, "qr_vbe": 0.8, "qr_ic": 0.3e-3, "qr_icfrac": 0.1, "qr_dtj": 0.5, "qr_ft": 80.0,
                    "sw_n": 201.0, "sw_kmin": 1.2, "sw_fkmin_ghz": 63.6, "sw_kmin_hi": 1.5, "sw_kmin_lo": 1.4,
                    "sw_dmax": 0.8, "sw_mumin": 2.0, "sw_nunst": 0.0}
_MEASURE_NAMES = SS.measure_names(SS.load_refs(HP)[1])


def fake_sparam_log(cid, *, overrides=None, drop=(), scale_all=1.0, markers=True):
    vals = {}
    for name in _MEASURE_NAMES:
        stem = name.rsplit("_", 1)[0] if name.rsplit("_", 1)[-1] in ("lo", "mid", "hi") else name
        vals[name] = (_SPARAM_DEFAULTS.get(stem) or 0.0) * scale_all
    vals.update(overrides or {})
    for name in drop:
        vals.pop(name, None)
    lines = ["fake"]
    lines += [f"m_{k} = {v:.10e}" for k, v in vals.items()]
    if markers:
        lines += ["SWEEP_BEGIN", "wf wk wd wmu", "SWEEP_END"]
    return "\n".join(lines) + "\n"


def stage2_texts(**per):
    """A full fake stage-2 log set; per is {cid: kwargs for that candidate's logs}."""
    out = {}
    for kind in ("one", "two"):
        out[f"{H.CONTROL}_{kind}"] = fake_sweep_log(f"{H.CONTROL}_{kind}", a1=A1, a3=A3)
    for cid in CIDS:
        kw = per.get(cid, {})
        out[f"{cid}_one"] = fake_sweep_log(f"{cid}_one", **kw)
        out[f"{cid}_two"] = fake_sweep_log(f"{cid}_two", **kw)
        out[f"{H.SPARAM}{cid}"] = fake_sparam_log(cid, overrides=kw.get("sparam"), drop=kw.get("sparam_drop", ()),
                                                  scale_all=kw.get("sparam_scale", 1.0))
    return out


def hist_from(text):
    """A stand-in stage-1 'historical record' built from the same fake (known-answer reproduction)."""
    hp1 = {k: v for k, v in HP.items() if k != "refinement"}
    summ, _, _ = H.summaries(hp1, LP, "C00", text)
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


def analyze(texts, **kw):
    hist = kw.pop("hist", None) or hist_from(texts["C00_one"])
    return H.analyze(HP, LP, texts, hist[0], hist[1], **kw)


# ---------------------------------------------------------------------------
# plan, keys, decks
# ---------------------------------------------------------------------------


def test_stage2_request_keys_and_run_counts():
    assert H.request_keys(HP) == ["control_one", "control_two"] + \
        [k for cid in CIDS for k in (f"{cid}_one", f"{cid}_two", f"{H.SPARAM}{cid}")]
    one = H.runs_for_key(HP, LP, "C08_one")
    two = H.runs_for_key(HP, LP, "C08_two")
    assert len(one) == 3 * len(L.sweep_pins(LP, "one")) * len(REF["single_tone"]["variants"]) == 189
    assert len(two) == 3 * len(L.sweep_pins(LP, "two")) == 63
    ids = [r["id"] for r in one + two]
    assert len(ids) == len(set(ids))
    assert {r["variant"] for r in one} == set(REF["single_tone"]["variants"])
    assert {r["variant"] for r in two} == {"base"}
    with pytest.raises(KeyError):
        H.runs_for_key(HP, LP, "sparam_C08")


def test_stage2_bodies_carry_the_declared_numerics_and_dc_block():
    for key in H.request_keys(HP):
        if key.startswith(H.SPARAM):
            continue
        body = H.body_for_key(HP, LP, key, DUT)
        kind = "two" if key.endswith("_two") else "one"
        assert L.options_line(LP, kind) in body
        if key.startswith(H.CONTROL):
            assert "m_dc_" not in body
        else:
            assert "  op\n" in body and "m_dc_idd" in body
    ctl = H.body_for_key(HP, LP, "control_two", DUT)
    assert L.options_line(LP, "two") in ctl and "m_dc_" not in ctl


def test_sparam_variant_fixture_changes_only_the_embedded_dut_block():
    fixture_text, tb = SS.load_refs(HP)
    assert SS.fixture_problems(fixture_text, tb, DUT) == []
    # the baseline candidate's deck is the production fixture itself, byte-identical
    assert H.sparam_deck(HP, fixture_text, DUT, "C00") is fixture_text
    v = H.sparam_deck(HP, fixture_text, DUT, "C08")
    pre, post = fixture_text.split("* ==== BEGIN"), v.split("* ==== BEGIN")
    assert pre[0] == post[0]
    assert pre[1].split("====\n", 1)[1].split("\n* ==== END")[0] != \
        post[1].split("====\n", 1)[1].split("\n* ==== END")[0]
    tail_a = pre[1].split("* ==== END design/netlist/lna_stage1.spice ====", 1)[1]
    tail_b = post[1].split("* ==== END design/netlist/lna_stage1.spice ====", 1)[1]
    assert tail_a == tail_b
    diff = [x for x in v.splitlines() if x not in fixture_text.splitlines() and not x.startswith(("* EXPERIMENTAL", "* GENERATED"))]
    assert all(x.split()[0] in ("R1b", "R2b", "Rd") for x in diff), diff


def test_sparam_body_text_mirrors_the_bench_conventions():
    fixture_text, tb = SS.load_refs(HP)
    body = SS.body_text(tb, H.sparam_deck(HP, fixture_text, DUT, "C08"), "C08", 2.5)
    for a in tb["analyses"]:
        assert f"  {a}" in body
    for n, e in tb["measure"].items():
        assert f"  let m_{n} = {e}" in body and f"  print m_{n}" in body
    assert ".param vdd_val=2.5" in body
    assert "Xq2 oc b2 c1 gnd npn13G2 Nx=8" in body and "R2b b2 gnd 7300 m=1" in body


def test_sparam_parse_problems_on_missing_and_nonfinite():
    names = _MEASURE_NAMES
    vals, probs = SS.parse_measurements(fake_sparam_log("C08"), names)
    assert probs == [] and set(vals) == set(names)
    _, probs = SS.parse_measurements(fake_sparam_log("C08", drop=("s21_db_mid",)), names)
    assert any("s21_db_mid" in p for p in probs)
    _, probs = SS.parse_measurements(fake_sparam_log("C08", markers=False), names)
    assert any("markers" in p for p in probs)
    _, probs = SS.parse_measurements(None, names)
    assert probs == ["no log"]


def test_sparam_compare_deltas():
    base = SS.parse_measurements(fake_sparam_log("C00"), _MEASURE_NAMES)[0]
    other = SS.parse_measurements(fake_sparam_log("C08", overrides={"s21_db_mid": 13.0, "nf_db_mid": 3.5}), _MEASURE_NAMES)[0]
    v = SS.compare(other, base)
    assert v["s21_db"]["s21_db_mid"] == pytest.approx(-4.0)
    assert v["nf_db"]["nf_db_mid"] == pytest.approx(0.5)
    assert v["stability_sweep"]["sw_kmin"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# plan coherence of the refinement block
# ---------------------------------------------------------------------------


def _bad(mutate):
    hp = copy.deepcopy(HP)
    mutate(hp)
    return H.plan_problems(hp, LP, DUT)


def test_refinement_plan_problems():
    assert H.plan_problems(HP, LP, DUT) == []
    assert any("not in the candidate table" in p for p in _bad(lambda h: h["refinement"].__setitem__("candidates", ["C08", "C05", "C00", "C99"])))
    assert any("baseline reference candidate" in p for p in _bad(lambda h: h["refinement"].__setitem__("candidates", ["C08", "C05"])))
    assert any("unknown or empty timing variant" in p for p in _bad(lambda h: h["refinement"]["single_tone"].__setitem__("variants", ["quarter_step"])))
    assert any("base timing only" in p for p in _bad(lambda h: h["refinement"]["two_tone"].__setitem__("variants", ["half_step", "base"])))
    assert any("Rd < 200 ohm extension" in p for p in _bad(lambda h: h["refinement"].pop("rd_extension")))
    assert any("sha256 differs" in p for p in _bad(lambda h: h["refinement"]["small_signal"]["fixture"].__setitem__("sha256", "0" * 64)))
    assert any("stage-1 baseline record is missing" in p for p in _bad(lambda h: h["refinement"]["baseline_reproduction"].__setitem__("record_id", "19990101-000000-abc")))


# ---------------------------------------------------------------------------
# analysis: good path and edge cases
# ---------------------------------------------------------------------------


def test_stage2_good_path_converged_and_bounded():
    t = stage2_texts()
    res = analyze(t)
    assert res["problems"] == []
    assert res["ngspice_control"]["pass"]
    assert res["baseline_reproduction"]["reproduced"]
    for cid in CIDS:
        c = res["candidates"][cid]
        assert c["validity"]["V_conv"]
        for pl in LP["placements"]:
            assert all(cv["ok"] for cv in c["convergence"][pl["name"]])
            assert c["placements"][pl["name"]]["p1db"]["status"] == "bounded"
            iip = c["two_tone"][pl["name"]]["iip3"]
            assert iip["status"] == "ok"
    iip = res["candidates"]["C08"]["two_tone"]["mid"]["iip3"]
    exp = L.cubic_expectations(A1, A3)["iip3_dbm"]
    assert iip["iip3_dbm"] == pytest.approx(exp, abs=0.2)
    assert res["candidates"]["C05"]["small_signal"]["vs_baseline"]["s21_db"]["s21_db_mid"] == pytest.approx(0.0)
    assert res["candidates"]["C00"]["small_signal"]["vs_baseline"] is None
    assert res["ranking"]["ranked"] == ["C00", "C05", "C08"]  # identical fakes: id tiebreak
    assert res["ranking"]["outcome_class"] == "refined_converged_p1db_still_bounded"
    assert res["ranking"]["not_ranked"] == {}


def test_stage2_stress_valid_p1db_outcome_when_the_crossing_is_inside_the_limits():
    # C00 keeps the stage-1 excursion (it anchors the reproduction check); the shortlist candidates
    # get no excursion growth, so their 1 dB crossing is reachable inside the limits.
    t = stage2_texts(C05=dict(swing_per_v=0.0, swing_two=0.0), C08=dict(swing_per_v=0.0, swing_two=0.0))
    res = analyze(t)
    assert res["problems"] == [] and res["baseline_reproduction"]["reproduced"]
    for cid in ("C05", "C08"):
        assert all(p["p1db"]["status"] == "ok" for p in res["candidates"][cid]["placements"].values())
    assert res["ranking"]["outcome_class"] in ("refined_stress_valid_p1db_meets_row8", "refined_stress_valid_p1db_below_row8")


def test_stage2_unconverged_candidate_stays_visible_and_is_not_ranked():
    t = stage2_texts(C08=dict(refine_scale=1.02))  # refined-variant amplitudes shifted ~0.17 dB
    res = analyze(t)
    assert res["problems"] == []
    assert res["candidates"]["C08"]["validity"]["failed"] == ["V_conv"]
    assert "C08" in res["ranking"]["not_ranked"]
    assert "C08" not in res["ranking"]["ranked"]
    assert res["ranking"]["ranked"] == ["C00", "C05"]
    assert res["ranking"]["outcome_class"] == "refined_converged_p1db_still_bounded"


def test_stage2_two_tone_all_points_stress_excluded_is_a_published_outcome():
    t = stage2_texts(C08=dict(vce2_dc=1.55, swing_two=2.0))  # every two-tone point breaks the V_CE limit
    res = analyze(t)
    assert res["problems"] == []
    iip = res["candidates"]["C08"]["two_tone"]["mid"]["iip3"]
    assert iip["status"] == "unavailable" and "no valid 1:3 region" in iip["reason"]
    # the excluded points are published with their reason, never silently dropped
    for s in iip["sidebands"].values():
        whys = set(s["excluded_points"].values())
        assert len(s["excluded_points"]) == len(L.sweep_pins(LP, "two"))
        assert any(w.startswith("outside DUT operating limits") for w in whys)
    assert res["candidates"]["C08"]["two_tone"]["mid"]["first_violation"]["violations"]


def test_stage2_reproduction_drift_is_refinement_invalid():
    t = stage2_texts()
    hist, sweeps = hist_from(t["C00_one"])
    for n in hist["placements"]:
        hist["placements"][n]["first_limit_violation"]["single_tone"]["pin_dbm"] -= 10
    res = H.analyze(HP, LP, t, hist, sweeps)
    assert not res["baseline_reproduction"]["reproduced"]
    assert res["ranking"]["outcome_class"] == "refinement_invalid" and res["ranking"]["ranked"] == []


def test_stage2_failing_control_is_refinement_invalid():
    t = stage2_texts()
    t["control_one"] = fake_sweep_log("control_one", a1=A1, a3=A3, scale=1.5)
    res = analyze(t)
    assert not res["ngspice_control"]["pass"]
    assert res["ranking"]["outcome_class"] == "refinement_invalid"


def test_stage2_analysis_is_deterministic_and_roundtrips():
    t = stage2_texts()
    h = hist_from(t["C00_one"])
    refs = SS.load_refs(HP)
    a = H.analyze(HP, LP, t, *h, refs=refs)
    b = H.analyze(HP, LP, t, *h, refs=refs)
    assert json.dumps(H.roundtrip(a), sort_keys=True) == json.dumps(H.roundtrip(b), sort_keys=True)
