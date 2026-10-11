"""Pure-logic tests for lna-core-variants (issue #79). No simulator, no PDK."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))

import corestudy as cs  # noqa: E402
import matchstudy as ms  # noqa: E402

ST = ms.load_study(cs.METHOD_STUDY)
RAW = json.loads(cs.DECLARATION.read_text())
DEC = cs.load_declaration()
FROZEN = cs.FROZEN.read_text()


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# --- declaration ------------------------------------------------------------


def test_declaration_pins_the_method_and_the_frozen_dut():
    assert sha(cs.METHOD_STUDY) == RAW["method"]["study_json_sha256"]
    assert sha(cs.FROZEN) == RAW["frozen_dut"]["sha256"]


def test_every_placeholder_has_a_derived_value_with_its_scan_result():
    for d in RAW["derivations"]:
        assert "value" in d and "result" in d, d["param"]
        assert d["value"] == ms.round_sig(d["result"]["crossing"], d["sig"])
        xs = [b[0] for b in d["result"]["bracket"]]
        ys = [b[1] for b in d["result"]["bracket"]]
        assert min(ys) <= d["target"] <= max(ys), "the declared crossing is bracketed by the scan"
        assert min(xs) <= d["result"]["crossing"] <= max(xs)


def test_three_issue_candidates_each_make_exactly_one_change():
    cands = {v.name: v for v in DEC.variants if v.role == "candidate"}
    classes = {DEC.changes[v.changes[0]]["class"] for v in cands.values()}
    assert classes == {"a", "b", "c"}
    assert all(v.n_changes == 1 for v in cands.values())


def test_validation_rejects_bad_declarations():
    bad = copy.deepcopy(RAW)
    bad["changes"]["A"]["edits"][0]["line"] = "Lin in in2 1.41n m=1"
    with pytest.raises(cs.CoreStudyError, match="protected"):
        cs.declaration_from_dict(bad)
    bad = copy.deepcopy(RAW)
    next(v for v in bad["variants"] if v["name"] == "a_le")["changes"] = ["A", "C"]
    with pytest.raises(cs.CoreStudyError, match="exactly one"):
        cs.declaration_from_dict(bad)
    bad = copy.deepcopy(RAW)
    for d in bad["derivations"]:
        d.pop("value")
    with pytest.raises(cs.CoreStudyError, match="no derived value"):
        cs.declaration_from_dict(bad)
    cs.declaration_from_dict(bad, partial=True)  # derive may load it


# --- variant netlists -------------------------------------------------------


def test_core0_is_the_frozen_netlist_byte_for_byte():
    net = cs.variant_netlist(FROZEN, DEC, DEC.baseline)
    assert net.split("\n", 1)[1] == FROZEN


@pytest.mark.parametrize("name", [v.name for v in DEC.variants])
def test_each_variant_changes_only_its_declared_lines(name):
    v = DEC.variant(name)
    net = cs.variant_netlist(FROZEN, DEC, v)
    old = set(e["line"] for c in v.changes for e in DEC.changes[c]["edits"])
    kept = [ln for ln in FROZEN.splitlines() if ln.strip() not in old]
    body = net.splitlines()[1:]
    assert all(ln in body for ln in kept)
    added = [ln for ln in body if ln not in kept]
    assert len(added) == sum(len(e["with"]) for c in v.changes for e in DEC.changes[c]["edits"])
    # the #74 input-network parameterization still applies unchanged
    assert ms.unparameterize(ms.dut_text(net)) == net
    assert "{" not in net


def test_apply_changes_refuses_missing_and_doubly_edited_lines():
    with pytest.raises(cs.CoreStudyError, match="found 0 times"):
        cs.apply_changes(FROZEN.replace("Re1 e1 gnd 3 m=1", "Re1 e1 gnd 4 m=1"), DEC, ["A"], {"le": 5e-11})
    with pytest.raises(cs.CoreStudyError, match="already edited"):
        cs.apply_changes(FROZEN, DEC, ["A", "B_NX"], {"le": 5e-11})
    with pytest.raises(cs.CoreStudyError, match="no value"):
        cs.apply_changes(FROZEN, DEC, ["A"], {})


def test_devices_follow_the_netlist():
    assert cs.devices_of(FROZEN) == ms.DEVICES
    nx10 = cs.devices_of(cs.variant_netlist(FROZEN, DEC, DEC.variant("b_nx10")))
    assert [d[2] for d in nx10] == [10, 10, 1]
    c = cs.devices_of(cs.variant_netlist(FROZEN, DEC, DEC.variant("c_rbias")))
    assert c[2][5] == "br", "the compensated mirror's base node is br, not nr"
    lets = dict(ms.op_lets(c))
    assert lets["qr_vbe"] == "v(xdut.br) - v(xdut.er)"
    assert dict(ms.op_lets(nx10))["q1_icfrac"].endswith("/(3e-3*10)")


def test_body_uses_the_variant_devices_and_the_74_networks():
    v = DEC.variant("ac")
    net = cs.variant_netlist(FROZEN, DEC, v)
    body = ms.body_text(ST, net, cs.networks(ST), 2.5, title="t", devices=cs.devices_of(net))
    assert "Le1 e1 e1d" in body and "Rbr nr br" in body
    assert "let m_op_qr_vbe = v(xdut.br) - v(xdut.er)" in body
    assert body.count("echo LM_BEGIN probe_") == 9 * 3
    # the frozen core's body equals the #74 deck apart from the variant comment line
    b0 = ms.body_text(ST, cs.variant_netlist(FROZEN, DEC, DEC.baseline), cs.networks(ST), 2.5, title="t",
                      devices=cs.devices_of(FROZEN))
    ref = ms.body_text(ST, FROZEN, cs.networks(ST), 2.5, title="t")
    assert [ln for ln in b0.splitlines() if not ln.startswith("* CORE VARIANT")] == ref.splitlines()


# --- derivation scans -------------------------------------------------------


def test_scan_body_sweeps_the_parameter_in_one_deck():
    net = cs.apply_changes(FROZEN, DEC, ["A"], {"le": "{scan_x}"})
    body = cs.scan_body(ST, net, "zin_f0", [0.0, 1e-11, 2e-11], 2.5, title="t")
    assert body.count("alterparam scan_x = ") == 3
    assert "v(p1)[35]" in body and "Le1 e1 e1d {scan_x}" in body
    body = cs.scan_body(ST, net, "ic_q1", [0.0, 1e-11], 2.5, title="t")
    assert body.count("\nop\n") == 2


def test_parse_scan_and_metrics():
    text = "LMSCAN 0 0.0 1.945e10 0.25 0.0\nLMSCAN 1 1e-11 1.945e10 0.5 0.0\nLM_DONE\n"
    rows = cs.parse_scan(text, 2)
    # V(p1) = 0.25 -> S11 = -0.5 -> Z = 50 * 0.5 / 1.5
    assert cs.scan_metric("zin_f0", rows[0]) == pytest.approx(50 / 3)
    assert cs.scan_metric("zin_f0", rows[1]) == pytest.approx(50.0)
    with pytest.raises(cs.CoreStudyError):
        cs.parse_scan(text.replace("LM_DONE", ""), 2)
    with pytest.raises(cs.CoreStudyError):
        cs.parse_scan(text, 3)


def test_solve_crossing_requires_a_unique_crossing():
    assert cs.solve_crossing([0, 1, 2], [0.0, 10.0, 20.0], 15.0) == pytest.approx(1.5)
    with pytest.raises(cs.CoreStudyError, match="0 times"):
        cs.solve_crossing([0, 1, 2], [0.0, 10.0, 20.0], 25.0)
    with pytest.raises(cs.CoreStudyError, match="2 times"):
        cs.solve_crossing([0, 1, 2], [0.0, 10.0, 0.0], 5.0)


# --- summaries, selection, gate --------------------------------------------


def fake_point(variant: str, process: str, temp: float, vdd: float, *, bound: float = 2.0, fmin=(1.5, 1.7),
               gt: float = 15.0, op_pass: bool = True, k: float = 3.0, s21: float = 18.0, status: str = "ok") -> dict:
    v = DEC.variant(variant)
    pt = {"id": cs.point_id(variant, process, temp, vdd), "variant": variant, "role": v.role, "process": process,
          "model_section": process, "temp_c": temp, "vdd_v": vdd, "corner_id": ms.corner_id(process, temp, vdd),
          "supply_class": "excursion" if vdd > 2.5 else "in_rail", "status": status,
          "op": {"pass": op_pass, "failures": [] if op_pass else ["q1:vce_le_1v4"]}}
    if status != "ok":
        pt["reason"] = "x"
        return pt
    pt["summary"] = {"nf_bound_max_db": bound, "f_at_nf_bound_max_hz": 21.2e9, "nf_bound_top_db": bound,
                     "margin_top_db": 2.5 - bound, "margin_db": 2.5 - bound, "fmin_min_db": fmin[0],
                     "fmin_max_db": fmin[1], "fmin_top_db": fmin[1],
                     "n_freq_jointly_infeasible": 71 if bound > 2.5 else 0, "n_freq": 71,
                     "gt_at_nf_bound_min_db": gt, "zin_core_f0_ohm": [50.0, -140.0], "zopt_f0_ohm": [140.0, 100.0],
                     "model_check_worst_db": 1e-7, "fit_rms_max_db": 1e-9, "drawn_s21_min_db": s21,
                     "drawn_nf_max_db": 3.0, "drawn_s11_max_db": -5.0, "k_min": k, "delta_max": 0.5,
                     "wide_f_kmin_hz": 6e10, "vce_max_v": 1.3, "q1_ic_ma": 1.56}
    return pt


def all_points(**over) -> list[dict]:
    out = []
    for v in DEC.variants:
        for p, t, vv in ST.pvt_points():
            kw = dict(over.get(v.name, {}))
            out.append(fake_point(v.name, p, t, vv, s21=18.0 + {"hbt_typ": 0, "hbt_bcs": 1, "hbt_wcs": -1}[p], **kw))
    return out


def test_selection_prefers_fewest_changes_then_margin():
    pts = all_points(core0={"bound": 3.0}, a_le={"bound": 2.6}, b_jopt={"bound": 2.7}, b_nx10={"bound": 2.8},
                     c_rbias={"bound": 2.9}, diag_rbias_noiseless={"bound": 1.0}, ac={"bound": 2.3},
                     abc={"bound": 2.0})
    S = {v.name: cs.summarize_variant(ST, DEC, v, pts) for v in DEC.variants}
    assert S["core0"]["n_infeasible"] == 18 and not S["core0"]["eligible"]
    assert not S["diag_rbias_noiseless"]["eligible"], "diagnostics are never chosen"
    sel = cs.select(DEC, S)
    assert sel["chosen"] == "ac" and sel["ranking"] == ["ac", "abc"]
    assert S["ac"]["worst_margin_db"] == pytest.approx(0.2)
    assert S["ac"]["binding_fmin_db"]["2.25v"] == [1.5, 1.7]


def test_a_single_change_that_closes_beats_a_combination():
    pts = all_points(a_le={"bound": 2.45}, ac={"bound": 2.0}, abc={"bound": 1.8})
    S = {v.name: cs.summarize_variant(ST, DEC, v, pts) for v in DEC.variants}
    assert cs.select(DEC, S)["chosen"] in ("a_le", "b_jopt", "b_nx10", "c_rbias")


def test_row17_gain_and_stability_failures_make_a_variant_ineligible():
    for over, why in (({"op_pass": False}, "row 17"), ({"gt": 9.0}, "GT"), ({"k": 0.9}, "k min")):
        pts = all_points(**{v.name: {"bound": 3.0} for v in DEC.variants if v.name != "ac"}, ac=over)
        S = {v.name: cs.summarize_variant(ST, DEC, v, pts) for v in DEC.variants}
        assert not S["ac"]["eligible"] and any(why in r for r in S["ac"]["ineligible_reasons"])
        sel = cs.select(DEC, S)
        assert sel["chosen"] is None and "no declared core change" in sel["outcome"]


def test_excursion_points_never_enter_the_verdict():
    pts = all_points(**{v.name: {"bound": 3.0} for v in DEC.variants if v.name != "ac"})
    for p in pts:
        if p["variant"] == "ac" and p["supply_class"] == "excursion":
            p["op"] = {"pass": False, "failures": ["q1:vce_le_1v4"]}
            p["summary"]["nf_bound_max_db"] = 2.9
            p["summary"]["n_freq_jointly_infeasible"] = 5
    S = {v.name: cs.summarize_variant(ST, DEC, v, pts) for v in DEC.variants}
    assert S["ac"]["eligible"] and len(S["ac"]["op_fail_excursion"]) == 9


def test_gate_catches_missing_duplicate_undeclared_and_unmoved_process():
    pts = all_points()
    assert cs.validate_collection(ST, DEC, pts) == []
    assert any("missing" in x for x in cs.validate_collection(ST, DEC, pts[1:]))
    assert any("duplicate" in x for x in cs.validate_collection(ST, DEC, pts + pts[:1]))
    extra = dict(pts[0], id="zzz__x")
    assert any("undeclared" in x for x in cs.validate_collection(ST, DEC, pts + [extra]))
    flat = copy.deepcopy(pts)
    for p in flat:
        p["summary"]["drawn_s21_min_db"] = 18.0
    assert any("process corners" in x for x in cs.validate_collection(ST, DEC, flat))
    nan = copy.deepcopy(pts)
    nan[0]["summary"]["k_min"] = math.nan
    assert any("non-finite" in x for x in cs.validate_collection(ST, DEC, nan))


def test_reproduction_against_the_74_bounds():
    pts = all_points()
    ref = {f"corners__{p['corner_id']}": {"summary": {"nf_bound_max_db": 2.0, "fmin_min_db": 1.5, "fmin_max_db": 1.7,
                                                      "n_freq_jointly_infeasible": 0}}
           for p in pts if p["variant"] == "core0"}
    r = cs.reproduction(pts, ref, "core0", 1e-3)
    assert r["ok"] and r["compared_points"] == 27
    ref["corners__hbt_typ_27c_2.50v"]["summary"]["nf_bound_max_db"] = 2.01
    assert not cs.reproduction(pts, ref, "core0", 1e-3)["ok"]


def test_the_74_baseline_record_is_reproducible_input():
    """The comparison base exists and carries a bound for all 27 points."""
    rec = json.loads((cs.METHOD_DIR / "records" / "20261010-042556-dae8519.json").read_text())
    pts = [k for k in rec["bounds"] if k.startswith("corners__")]
    assert len(pts) == 27
    inf = [k for k in pts if rec["bounds"][k]["summary"]["n_freq_jointly_infeasible"] > 0
           and not k.endswith("2.75v")]
    assert len(inf) == 8, "issue #79 quotes 8 of 18 in-rail points"
