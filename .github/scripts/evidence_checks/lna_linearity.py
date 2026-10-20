"""evidence_checks.lna_linearity: split out of check_evidence_formats.py (issue #163); no rule changes."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .common import (Problems, has_section, header_field, load_json_object, need_record_commit, need_sha256, need_str, read_gzip_text, rel)
from .mixer_pra import SHA1_RE, _num
from .passive_p1 import PASSIVE_PACKAGES, _sha256_of
from .spec_rows import SPEC_PATH, SPEC_ROW_RE


# ---------------------------------------------------------------------------
# lna-linearity (sim/lna-linearity/run.py, issue #57)
# ---------------------------------------------------------------------------

LIN_BENCH = "lna-linearity"
LIN_STATUSES = ("COLLECTED", "CONTROLS_FAILED")
LIN_RECORD_FILE_RE = re.compile(r"^(\d{8}-\d{6}-[0-9a-f]{7,40})(\.md|\.json|-sweeps\.json\.gz)$")
LIN_MD_SECTIONS = ("Declaration", "DUT identity", "Controls", "Results (base sweep; converged = both refinements agree)",
                   "Rows 7 and 8", "Provenance and raw artifacts")
LIN_VARIANTS = ("base", "half_step", "double_window")
LIN_VERDICTS = ("meets", "fails", "marginal", "not_determined")
LIN_NEGATIVE_REQUIRED = ("noncoherent_tone_placement", "below_floor_im3", "missing_1_to_3_slope_region",
                         "unbracketed_p1db", "no_small_signal_baseline", "out_of_limit_points_not_fitted_through")
LIN_NEGATIVE_PREFIXES = ("wrong_amplitude_normalization", "wrong_power_axis")
LIN_IIP3_STATUS = ("ok", "unavailable", "unconverged")
LIN_P1DB_STATUS = ("ok", "bounded", "unavailable", "unconverged")
LIN_TWO_KEYS = ("p_f1_dbm", "p_f2_dbm", "p_im3l_dbm", "p_im3h_dbm")


def lin_request_keys(plan: dict) -> list[str]:
    who = ["control"] + [p["name"] for p in plan.get("placements", []) if isinstance(p, dict)]
    return [f"{w}_{k}" for w in who for k in ("two", "one")]


def lin_sweep_len(plan: dict, kind: str) -> int | None:
    try:
        s = plan["sweep"][kind]
        return int(round((s["stop_dbm"] - s["start_dbm"]) / s["step_db"])) + 1
    except (KeyError, TypeError, ZeroDivisionError, ValueError):
        return None


def lin_spec_targets(root: Path) -> dict[str, float] | None:
    """The ratified row 7 / row 8 targets (dBm) parsed from the spec table, or None."""
    spec = root / SPEC_PATH
    if not spec.is_file():
        return None
    out: dict[str, float] = {}
    for line in spec.read_text(encoding="utf-8").splitlines():
        m = SPEC_ROW_RE.match(line)
        if not m or int(m.group(1)) not in (7, 8):
            continue
        t = re.search(r"\*\*\s*≥\s*([−-]?\d+(?:\.\d+)?)\s*dBm\s*\*\*", line)
        if t:
            out["iip3_dbm" if int(m.group(1)) == 7 else "p1db_dbm"] = float(t.group(1).replace("−", "-"))
    return out if len(out) == 2 else None


def lin_expected_verdict(value: float, target: float, unc: float) -> str:
    if value - unc >= target:
        return "meets"
    if value + unc < target:
        return "fails"
    return "marginal"


def lin_check_iip3(problems: Problems, where: str, res: dict, ext: dict, sweep: dict) -> None:
    st = res.get("status")
    if st == "unavailable":
        if not (isinstance(res.get("reason"), str) and res["reason"]):
            problems.add(where, "IIP3 unavailable without a reason")
        return
    if st != "ok":
        problems.add(where, f"IIP3 base result status {st!r} is not ok/unavailable")
        return
    prm = ext.get("iip3", {})
    sides = res.get("sidebands")
    if not isinstance(sides, dict) or set(sides) != {"low", "high"}:
        problems.add(where, "IIP3 ok result must carry both IM3 sidebands ('low' and 'high')")
        return
    vals = []
    for name, sd in sides.items():
        w = f"{where} {name} sideband"
        if not isinstance(sd, dict) or sd.get("status") != "ok":
            problems.add(w, "ok IIP3 requires both sidebands ok")
            continue
        iv = sd.get("interval_dbm")
        if not (isinstance(iv, list) and len(iv) == 2 and all(_num(x) for x in iv) and iv[0] < iv[1]):
            problems.add(w, "missing fit interval_dbm")
        elif sweep and not (sweep["start_dbm"] <= iv[0] and iv[1] <= sweep["stop_dbm"]):
            problems.add(w, "fit interval lies outside the declared sweep")
        if not (_num(sd.get("n_points")) and sd["n_points"] >= prm.get("min_points", 3)):
            problems.add(w, "fit interval has fewer points than the plan's min_points")
        sf, si = sd.get("slope_fund"), sd.get("slope_im3")
        if not (_num(sf) and _num(si)):
            problems.add(w, "missing fitted slopes")
        else:
            lo, hi = prm.get("slope_fund", [0.9, 1.1]), prm.get("slope_im3", [2.7, 3.3])
            if not (lo[0] <= sf <= lo[1] and hi[0] <= si <= hi[1]):
                problems.add(w, f"fitted slopes {sf!r}/{si!r} are outside the declared 1:3 tolerance")
        rf, ri = sd.get("residual_fund_db"), sd.get("residual_im3_db")
        if not (_num(rf) and _num(ri)):
            problems.add(w, "missing fit residuals")
        elif max(rf, ri) > prm.get("max_residual_db", 0.5):
            problems.add(w, "fit residual exceeds the declared maximum")
        if not (isinstance(sd.get("baseline"), dict) and _num(sd["baseline"].get("gain_db"))):
            problems.add(w, "missing small-signal gain baseline")
        if not isinstance(sd.get("excluded_points"), dict):
            problems.add(w, "missing excluded_points (rejected-point reasons)")
        if not (_num(sd.get("iip3_dbm")) and _num(sd.get("iip3_free_slope_dbm")) and _num(sd.get("extrapolation_db"))):
            problems.add(w, "missing iip3_dbm / iip3_free_slope_dbm / extrapolation_db")
        else:
            vals.append(sd["iip3_dbm"])
            if abs(sd["iip3_dbm"] - sd["iip3_free_slope_dbm"]) > prm.get("free_fixed_tol_db", 1.0) + 1e-6:
                problems.add(w, "fixed-slope and free-slope IIP3 disagree beyond the declared tolerance")
    if len(vals) == 2 and (not _num(res.get("iip3_dbm")) or abs(res["iip3_dbm"] - min(vals)) > 1e-6):
        problems.add(where, "reported iip3_dbm is not the lower of the two sidebands")


def lin_check_p1db(problems: Problems, where: str, res: dict, ext: dict) -> None:
    st = res.get("status")
    prm = ext.get("p1db", {})
    if st == "unavailable":
        if not (isinstance(res.get("reason"), str) and res["reason"]):
            problems.add(where, "P1dB unavailable without a reason")
        return
    if st not in ("ok", "bounded"):
        problems.add(where, f"P1dB base result status {st!r} is not ok/bounded/unavailable")
        return
    b = res.get("baseline")
    if not (isinstance(b, dict) and _num(b.get("gain_db")) and isinstance(b.get("pin_dbm"), list)
            and len(b["pin_dbm"]) >= prm.get("baseline_points", 3) and _num(b.get("spread_db"))):
        problems.add(where, "P1dB result lacks an established small-signal baseline (gain_db, pin_dbm, spread_db)")
    elif b["spread_db"] > prm.get("baseline_flat_db", 0.15) + 1e-9:
        problems.add(where, "P1dB baseline spread exceeds the declared flatness")
    if not isinstance(res.get("excluded_points"), dict):
        problems.add(where, "missing excluded_points (rejected-point reasons)")
    if st == "bounded":
        if not (_num(res.get("p1db_in_dbm_gt")) and isinstance(res.get("reason"), str) and res["reason"]):
            problems.add(where, "bounded P1dB needs p1db_in_dbm_gt and a reason")
        if "p1db_in_dbm" in res:
            problems.add(where, "bounded P1dB must not carry a p1db_in_dbm number")
        return
    br = res.get("bracket")
    ok = isinstance(br, dict) and isinstance(br.get("pin_dbm"), list) and isinstance(br.get("drop_db"), list) \
        and len(br["pin_dbm"]) == 2 and len(br["drop_db"]) == 2 and all(_num(x) for x in br["pin_dbm"] + br["drop_db"])
    if not ok:
        problems.add(where, "ok P1dB requires a bracket {pin_dbm: [lo, hi], drop_db: [d0, d1]}")
        return
    drop = prm.get("drop_db", 1.0)
    if not (br["drop_db"][0] < drop <= br["drop_db"][1]):
        problems.add(where, "bracket does not straddle the declared gain drop")
    if not (_num(res.get("p1db_in_dbm")) and br["pin_dbm"][0] <= res["p1db_in_dbm"] <= br["pin_dbm"][1]):
        problems.add(where, "p1db_in_dbm lies outside its bracket")
    if isinstance(b, dict) and _num(b.get("gain_db")) and _num(res.get("p1db_out_dbm")) and _num(res.get("p1db_in_dbm")) \
            and abs(res["p1db_out_dbm"] - (res["p1db_in_dbm"] + b["gain_db"] - drop)) > 1e-6:
        problems.add(where, "p1db_out_dbm is inconsistent with p1db_in_dbm, baseline gain and the drop")


def lin_check_sweeps(problems: Problems, where: str, plan: dict, sweeps: object) -> None:
    if not isinstance(sweeps, dict):
        problems.add(where, "sweeps sidecar is not an object")
        return
    names = [p["name"] for p in plan.get("placements", []) if isinstance(p, dict)]
    if sorted(sweeps) != sorted(names):
        problems.add(where, f"sweeps sidecar placements {sorted(sweeps)} != plan placements {sorted(names)}")
        return
    for n in names:
        for v in LIN_VARIANTS:
            for kind in ("two", "one"):
                rows = (sweeps[n].get(v) or {}).get(kind) if isinstance(sweeps[n], dict) else None
                w = f"{where} [{n}/{v}/{kind}]"
                want = lin_sweep_len(plan, kind)
                if not isinstance(rows, list) or want is None or len(rows) != want:
                    problems.add(w, f"sweep has {len(rows) if isinstance(rows, list) else 'no'} points, the plan declares {want}")
                    continue
                pins = [r.get("pin_dbm") for r in rows if isinstance(r, dict)]
                if len(set(pins)) != len(pins) or not all(_num(x) for x in pins):
                    problems.add(w, "sweep power axis has duplicates or non-numbers")
                for r in rows:
                    if not isinstance(r, dict):
                        problems.add(w, "sweep point is not an object")
                        continue
                    keys = LIN_TWO_KEYS if kind == "two" else ("p_f0_dbm",)
                    if r.get("sim_failed"):
                        continue  # a published aborted transient: classified, no values
                    if not all(_num(r.get(k)) for k in keys) or not _num(r.get("floor_dbm")):
                        problems.add(w, f"point {r.get('pin_dbm')!r}: missing delivered powers/floor ({', '.join(keys)}, floor_dbm); "
                                     "both IM3 sidebands are required in every two-tone point")
                    if not isinstance(r.get("excursion_v"), dict):
                        problems.add(w, f"point {r.get('pin_dbm')!r}: no device excursions (operating-limit classification)")


def lin_check_placement(problems: Problems, where: str, plan: dict, name: str, pe: object, targets: dict) -> None:
    if not isinstance(pe, dict):
        problems.add(where, f"placement {name}: not an object")
        return
    w = f"{where} [{name}]"
    ext = plan.get("extraction", {})
    res, fin, conv = pe.get("results"), pe.get("final"), pe.get("convergence")
    if not (isinstance(res, dict) and isinstance(fin, dict) and isinstance(conv, dict)):
        problems.add(w, "placement lacks results/final/convergence")
        return
    if not isinstance(pe.get("frequencies_hz"), dict):
        problems.add(w, "missing frequencies_hz")
    if not isinstance(pe.get("unrestricted_reference"), dict) or "NOT A RESULT" not in str(pe["unrestricted_reference"].get("label")):
        problems.add(w, "unrestricted_reference must be labelled 'NOT A RESULT'")
    flv = pe.get("first_limit_violation")
    if not (isinstance(flv, dict) and set(flv) == {"two_tone", "single_tone"}):
        problems.add(w, "missing first_limit_violation (two_tone, single_tone)")
    if isinstance(res.get("iip3"), dict):
        lin_check_iip3(problems, w + " IIP3", res["iip3"], ext, plan.get("sweep", {}).get("two", {}))
    else:
        problems.add(w, "missing results.iip3")
    if isinstance(res.get("p1db"), dict):
        lin_check_p1db(problems, w + " P1dB", res["p1db"], ext)
    else:
        problems.add(w, "missing results.p1db")
    for kind, tkey, allowed in (("iip3", "iip3_dbm", LIN_IIP3_STATUS), ("p1db", "p1db_dbm", LIN_P1DB_STATUS)):
        f = fin.get(kind)
        cv = conv.get(kind)
        wk = f"{w} {kind}"
        if not isinstance(f, dict) or not isinstance(cv, list):
            problems.add(wk, "missing final/convergence entry")
            continue
        variants = []
        for c in cv:
            if not isinstance(c, dict) or not isinstance(c.get("ok"), bool) or not isinstance(c.get("estimator"), dict):
                problems.add(wk, "malformed convergence entry")
                continue
            variants.append(c.get("variant"))
            if not isinstance(c.get("pointwise_fundamental"), dict):
                problems.add(wk, "convergence entry lacks pointwise_fundamental")
        if sorted(v for v in variants if isinstance(v, str)) != ["double_window", "half_step"]:
            problems.add(wk, "convergence must carry exactly the half_step and double_window variants")
            continue
        converged = all(c["ok"] for c in cv if isinstance(c, dict) and isinstance(c.get("ok"), bool))
        if f.get("converged") is not converged:
            problems.add(wk, "final.converged disagrees with the convergence entries")
        base_status = (res.get(kind) or {}).get("status")
        want_status = base_status if converged else "unconverged"
        if f.get("status") != want_status or f.get("status") not in allowed:
            problems.add(wk, f"final.status {f.get('status')!r} must be {want_status!r} (base {base_status!r}, converged {converged})")
        a = f.get("assessment")
        if not (isinstance(a, dict) and a.get("verdict") in LIN_VERDICTS and _num(a.get("target_dbm"))):
            problems.add(wk, "final.assessment needs a verdict and the target")
            continue
        if a["target_dbm"] != targets[tkey]:
            problems.add(wk, f"assessment target {a['target_dbm']!r} differs from the ratified spec target {targets[tkey]!r} "
                         "(a target may not be relaxed)")
        if plan.get("targets", {}).get(tkey) != targets[tkey]:
            problems.add(wk, "plan_declaration.targets differs from the ratified spec table")
        unc = f.get("max_estimator_delta_db")
        if converged and f.get("status") == "ok" and _num(unc):
            b = res.get(kind, {})
            val = b.get("iip3_dbm") if kind == "iip3" else b.get("p1db_in_dbm")
            if _num(val) and a["verdict"] != lin_expected_verdict(val, targets[tkey], unc):
                problems.add(wk, f"assessment verdict {a['verdict']!r} does not follow from the value {val!r}, "
                             f"target {targets[tkey]!r} and convergence spread {unc!r}")
        if not converged and a["verdict"] != "not_determined":
            problems.add(wk, "an unconverged estimator must be 'not_determined'")


def check_lin_record(problems: Problems, root: Path, exp_dir: Path, rid: str) -> None:
    md_path = exp_dir / "records" / f"{rid}.md"
    where_md = rel(root, md_path)
    md = md_path.read_text(encoding="utf-8", errors="replace")
    first = md.splitlines()[0] if md.strip() else ""
    if first != f"# {LIN_BENCH} record {rid}":
        problems.add(where_md, f"first line must be '# {LIN_BENCH} record {rid}', found {first[:80]!r}")
    for sec in LIN_MD_SECTIONS:
        if not has_section(md, sec):
            problems.add(where_md, f"missing required section '## {sec}'")
    claim = header_field(md, "Claim")
    if claim is None or "placeholder circuit" not in claim or "IDEAL" not in claim:
        problems.add(where_md, "Claim line must state the IDEAL-matching placeholder circuit")
    js_path = exp_dir / "records" / f"{rid}.json"
    where_js = rel(root, js_path)
    if not js_path.is_file():
        problems.add(where_md, f"record has no JSON sidecar {rid}.json")
        return
    rec = load_json_object(problems, root, js_path)
    if rec is None:
        return
    if rec.get("record_id") != rid:
        problems.add(where_js, f"JSON record_id {rec.get('record_id')!r} != {rid!r}")
    status = rec.get("status")
    if status not in LIN_STATUSES:
        problems.add(where_js, f"status {status!r} is not one of {', '.join(LIN_STATUSES)}")
    elif f"- **Status: {status}**" not in md:
        problems.add(where_md, f"Markdown does not state '- **Status: {status}**'")
    if rec.get("spec_rows_claimed_met") != []:
        problems.add(where_js, "spec_rows_claimed_met must be [] (placeholder circuit, nominal corner)")
    scope = rec.get("scope")
    if not (isinstance(scope, str) and "placeholder" in scope and "ratified targets unchanged" in scope):
        problems.add(where_js, "scope must state the placeholder circuit and that the ratified targets are unchanged")

    snap = exp_dir / "netlist-snapshots" / rid
    plan_snap = snap / "plan.json"
    dut_snap = snap / "lna_stage1.spice"
    plan = None
    if not snap.is_dir():
        problems.add(rel(root, snap), "netlist-snapshots/<id>/ directory missing")
        return
    if plan_snap.is_file():
        plan = load_json_object(problems, root, plan_snap)
    else:
        problems.add(rel(root, snap), "snapshot lacks the frozen plan.json")
    if not dut_snap.is_file():
        problems.add(rel(root, snap), "snapshot lacks the frozen DUT lna_stage1.spice")
    if plan is None:
        return
    prov = rec.get("plan")
    if not isinstance(prov, dict):
        problems.add(where_js, "missing 'plan' provenance")
    else:
        if prov.get("sha256") != _sha256_of(plan_snap):
            problems.add(where_js, "plan.sha256 does not match the frozen netlist-snapshots/<id>/plan.json")
        if not (isinstance(prov.get("commit"), str) and SHA1_RE.match(prov["commit"])):
            problems.add(where_js, "plan.commit must name the commit that declared the plan")
        if prov.get("dirty") is not False:
            problems.add(where_js, "plan.dirty must be false: the plan is committed before the collection it judges")
    if rec.get("plan_declaration") != plan:
        problems.add(where_js, "plan_declaration differs from the frozen plan.json")
    dut = rec.get("dut")
    if not isinstance(dut, dict):
        problems.add(where_js, "missing 'dut' identity")
    else:
        if dut.get("sha256") != (_sha256_of(dut_snap) if dut_snap.is_file() else None):
            problems.add(where_js, "dut.sha256 does not match the frozen DUT snapshot")
        if not (isinstance(dut.get("last_commit"), str) and SHA1_RE.match(dut["last_commit"])):
            problems.add(where_js, "dut.last_commit must name the commit of the exported netlist")
        if not isinstance(dut.get("fixture_embeds_verbatim"), bool):
            problems.add(where_js, "dut.fixture_embeds_verbatim must be a bool")
        if not (isinstance(dut.get("file"), str) and dut["file"].endswith("lna_stage1.spice")):
            problems.add(where_js, "dut.file must name the exported lna_stage1.spice")
    env = rec.get("environment") if isinstance(rec.get("environment"), dict) else {}
    need_record_commit(problems, where_js, env, rid)
    need_sha256(problems, where_js, env.get("pdk_artifact_sha256"), "environment.pdk_artifact_sha256")
    need_str(problems, where_js, env, "klt_client", "environment.klt_client")

    targets = lin_spec_targets(root)
    if targets is None:
        problems.add(where_js, f"cannot parse the ratified row 7/8 targets from {SPEC_PATH}")
        targets = {"iip3_dbm": float("nan"), "p1db_dbm": float("nan")}
    keys = lin_request_keys(plan)
    reqs = rec.get("klt_requests")
    if not isinstance(reqs, list) or sorted(str(r.get("key")) for r in reqs if isinstance(r, dict)) != sorted(keys):
        problems.add(where_js, f"klt_requests must carry exactly the requests {sorted(keys)}")
        reqs = []
    for r in reqs:
        if not isinstance(r, dict):
            continue
        k = r.get("key")
        if r.get("status") != "pass":
            problems.add(where_js, f"request {k}: klt status {r.get('status')!r} is not pass")
        if r.get("engine") != "ngspice" or not r.get("engine_version"):
            problems.add(where_js, f"request {k}: simulator provenance (engine, engine_version) missing")
        need_sha256(problems, where_js, r.get("models_lib_sha256"), f"request {k}: models_lib_sha256")
        if not r.get("backend"):
            problems.add(where_js, f"request {k}: backend missing")
        elif r["backend"] == "batch" and not (isinstance(r.get("remote"), dict) and r["remote"].get("job_id")):
            problems.add(where_js, f"request {k}: a batch request must carry its remote job id")
    for k in keys:
        for stem in (f"body_{k}.spice", f"request_{k}.json", f"report_{k}.json"):
            if not (snap / stem).is_file():
                problems.add(rel(root, snap), f"snapshot lacks {stem}")
        rp = snap / f"report_{k}.json"
        if rp.is_file():
            rj = load_json_object(problems, root, rp)
            if rj is not None and "corners" not in rj:
                problems.add(rel(root, rp), "klt report has no corners")
        qp = snap / f"request_{k}.json"
        if qp.is_file():
            qj = load_json_object(problems, root, qp)
            if qj is not None and not (isinstance(qj.get("corners"), dict)
                                       and qj["corners"].get("process") == [plan.get("nominal", {}).get("process")]):
                problems.add(rel(root, qp), "request does not target the plan's nominal process corner")
    for p in sorted(snap.iterdir()):
        if p.name in ("plan.json", "lna_stage1.spice"):
            continue
        m = re.match(r"^(body|request|report)_(.+)\.(spice|json)$", p.name)
        if not m or m.group(2) not in keys:
            problems.add(rel(root, p), "unexpected file in an lna-linearity netlist-snapshots directory")
    logs = exp_dir / "corners" / rid
    if not logs.is_dir():
        problems.add(rel(root, logs), "no corners/<id>/ raw logs for this record")
    else:
        names = sorted(p.name for p in logs.iterdir())
        if names != sorted(f"{k}.log.gz" for k in keys):
            problems.add(rel(root, logs), f"raw logs {names} != the requests {sorted(k + '.log.gz' for k in keys)}")
        for p in sorted(logs.glob("*.log.gz")):
            text = read_gzip_text(problems, root, p)
            if text is not None and "LNLIN_DONE" not in text:
                problems.add(rel(root, p), "frozen log lacks LNLIN_DONE (the deck did not finish)")

    pc = rec.get("python_controls")
    if not isinstance(pc, dict) or pc.get("pass") is not True:
        problems.add(where_js, "python_controls.pass must be true before any collection is recorded")
    else:
        neg = pc.get("negative")
        names = [n.get("name") for n in neg if isinstance(n, dict)] if isinstance(neg, list) else []
        if not names or not all(isinstance(n, dict) and n.get("rejected") is True for n in neg):
            problems.add(where_js, "every negative control must be recorded as rejected")
        for want in LIN_NEGATIVE_REQUIRED:
            if want not in names:
                problems.add(where_js, f"negative control {want!r} missing")
        for pre in LIN_NEGATIVE_PREFIXES:
            if not any(str(n).startswith(pre) for n in names):
                problems.add(where_js, f"no {pre}* negative control recorded")
    ctl = rec.get("controls")
    if not isinstance(ctl, dict) or not isinstance(ctl.get("evaluations"), dict) or set(ctl["evaluations"]) != {"two", "one"}:
        problems.add(where_js, "controls.evaluations must carry the 'two' and 'one' ngspice analytic controls")
    else:
        allp = True
        for kind, ev in ctl["evaluations"].items():
            ok = (isinstance(ev, dict) and _num(ev.get("error_db")) and _num(ev.get("gain_error_db")) and _num(ev.get("tol_db"))
                  and abs(ev["error_db"]) <= ev["tol_db"] and abs(ev["gain_error_db"]) <= ev.get("gain_tol_db", 0))
            if isinstance(ev, dict) and ev.get("pass") is not bool(ok):
                problems.add(where_js, f"controls.evaluations[{kind}].pass disagrees with its errors and tolerances")
            allp = allp and bool(ok)
        if ctl.get("pass") is not allp:
            problems.add(where_js, "controls.pass disagrees with its evaluations")
        if status in LIN_STATUSES and (status == "COLLECTED") is not bool(ctl.get("pass")):
            problems.add(where_js, f"status {status} is inconsistent with controls.pass={ctl.get('pass')!r}")
    pls = rec.get("placements")
    names = [p.get("name") for p in plan.get("placements", []) if isinstance(p, dict)]
    if not isinstance(pls, dict) or sorted(pls) != sorted(names):
        problems.add(where_js, f"placements must be exactly {sorted(names)}")
    else:
        for n in names:
            lin_check_placement(problems, where_js, plan, n, pls[n], targets)
            if f"### Placement `{n}`" not in md:
                problems.add(where_md, f"Markdown lacks the section for placement {n}")
    rows = rec.get("rows")
    if not isinstance(rows, dict) or set(rows) != {"7", "8"}:
        problems.add(where_js, "rows must carry exactly '7' and '8'")
    elif isinstance(pls, dict) and sorted(pls) == sorted(names):
        rank = {"fails": 0, "marginal": 1, "not_determined": 2, "meets": 3}
        for row, kind in (("7", "iip3"), ("8", "p1db")):
            per = {}
            for n in names:
                f = (pls[n].get("final") or {}).get(kind) if isinstance(pls[n], dict) else None
                if isinstance(f, dict) and isinstance(f.get("assessment"), dict):
                    per[n] = (f.get("status"), f["assessment"].get("verdict"))
            r = rows[row]
            if not isinstance(r, dict) or r.get("kind") != kind:
                problems.add(where_js, f"rows[{row}] malformed")
                continue
            got = {n: (v.get("status"), v.get("verdict")) for n, v in (r.get("per_placement") or {}).items() if isinstance(v, dict)}
            if got != per:
                problems.add(where_js, f"rows[{row}].per_placement disagrees with the placements")
            if per and r.get("worst_verdict") != min((v for _, v in per.values()), key=lambda x: rank.get(x, 9)):
                problems.add(where_js, f"rows[{row}].worst_verdict is not the worst placement verdict")
            if f"- row {row} (" not in md:
                problems.add(where_md, f"Markdown lacks the row {row} summary")
    if rec.get("sweeps_file") != f"{rid}-sweeps.json.gz":
        problems.add(where_js, f"sweeps_file {rec.get('sweeps_file')!r} != {rid + '-sweeps.json.gz'!r}")
    sp = exp_dir / "records" / f"{rid}-sweeps.json.gz"
    if not sp.is_file():
        problems.add(where_md, f"record has no sweeps file {sp.name}")
    else:
        raw = read_gzip_text(problems, root, sp)
        if raw is not None:
            try:
                sweeps = json.loads(raw)
            except ValueError as exc:
                problems.add(rel(root, sp), f"sweeps file is not valid JSON ({exc})")
            else:
                lin_check_sweeps(problems, rel(root, sp), plan, sweeps)
    for ref in (f"corners/{rid}/", f"netlist-snapshots/{rid}/", f"{rid}-sweeps.json.gz"):
        if ref not in md:
            problems.add(where_md, f"Markdown does not reference {ref}")


def check_lna_linearity(problems: Problems, root: Path, exp_dir: Path) -> None:
    if not (exp_dir / "testbench" / "plan.json").is_file():
        problems.add(rel(root, exp_dir), "lna-linearity has no testbench/plan.json declaration")
    records = exp_dir / "records"
    ids: set[str] = set()
    if records.is_dir():
        groups: dict[str, set[str]] = {}
        for p in sorted(records.iterdir()):
            m = LIN_RECORD_FILE_RE.match(p.name)
            if not m:
                problems.add(rel(root, p), "unexpected file in lna-linearity records/ (only <id>.md, <id>.json, <id>-sweeps.json.gz)")
                continue
            groups.setdefault(m.group(1), set()).add(m.group(2))
        for rid, parts in sorted(groups.items()):
            if ".md" not in parts:
                problems.add(rel(root, records), f"evidence for {rid} belongs to no record (no {rid}.md)")
                continue
            ids.add(rid)
            check_lin_record(problems, root, exp_dir, rid)
    for sub in ("corners", "netlist-snapshots"):
        d = exp_dir / sub
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.name not in ids:
                    problems.add(rel(root, p), f"{sub} entry belongs to no record in this experiment (orphan evidence)")
    for sub in ("probe-logs", PASSIVE_PACKAGES):
        if (exp_dir / sub).exists():
            problems.add(rel(root, exp_dir / sub), f"{sub}/ is not part of the {LIN_BENCH} evidence layout")
