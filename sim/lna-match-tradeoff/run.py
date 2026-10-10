#!/usr/bin/env python3
"""Driver for the lna-match-tradeoff study (issue #74).

    python3 sim/lna-match-tradeoff/run.py plan
    python3 sim/lna-match-tradeoff/run.py derive            # one local nominal run
    python3 sim/lna-match-tradeoff/run.py declare DERIVE.json   # freeze candidates
    python3 sim/lna-match-tradeoff/run.py smoke             # local controls, records nothing
    python3 sim/lna-match-tradeoff/run.py collect [--dry-run] [--workdir DIR]

``derive``, ``smoke`` and the nominal screen are single-PVT-point runs (one
``ngspice -b`` or one single-unit ``klt sim`` at a time), which the host
rules allow locally. The PVT campaign is expressed as ``klt sim`` requests
and goes to the batch fleet (``collect``); a failed batch submit is an
error, never a local fallback. Nothing but ``collect`` writes evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
SIM_DIR = BENCH_DIR.parent
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(BENCH_DIR))
sys.path.insert(0, str(SIM_DIR / "lna-sparam-nf"))

import localrun  # noqa: E402
import matchstudy as ms  # noqa: E402

STUDY_JSON = BENCH_DIR / "testbench" / "study.json"
FROZEN = REPO_ROOT / "design" / "netlist" / "lna_stage1.spice"
BASELINE_RECORD = "20261010-012923-6cad7fc"
BASELINE_LOGS = SIM_DIR / "lna-sparam-nf" / "corners" / BASELINE_RECORD


def _frozen() -> str:
    return FROZEN.read_text()


def _nominal(st: ms.Study) -> tuple[str, float, float]:
    n = st.nominal
    return n["process"], float(n["temp_c"]), float(n["vdd"])


# ---------------------------------------------------------------------------


def cmd_plan(args) -> int:
    st = ms.load_study()
    roles = {}
    for c in st.candidates:
        roles[c.role] = roles.get(c.role, 0) + 1
    print(f"candidates: {roles}; excluded targets: {len(st.excluded_targets)}")
    print(f"grids: dense {st.grid.dense_n} points {st.band_hz[0] / 1e9:g}-{st.band_hz[1] / 1e9:g} GHz, "
          f"midpoints {st.grid.mid_n}, wide {st.wide_count()} points "
          f"{st.grid.wide_start_hz / 1e9:g}-{st.grid.wide_stop_hz / 1e9:g} GHz")
    p, t, v = _nominal(st)
    print(f"screen: 1 single-unit klt request ({p}, {t:g} C, {v:g} V), {len(st.candidates)} networks, "
          "backend local")
    print(f"corners: {len(st.supplies_v)} klt requests x {len(st.processes) * len(st.temps_c)} units "
          f"({len(st.pvt_points())} PVT points), backend batch; networks = shortlist (<= "
          f"{1 + st.shortlist_rule['max_passing'] + 5}) + {roles.get('probe', 0)} probes")
    return 0


def derivation(st: ms.Study, cands: list[ms.Candidate]) -> dict:
    p, t, v = _nominal(st)
    text = localrun.run_point(ms.body_text(st, _frozen(), cands, v, title="derive"), p, t, "derive")
    pl = ms.parse_log(text)
    if pl.problems or not pl.done:
        raise SystemExit(f"derive: log problems {pl.problems[:5]} (done={pl.done})")
    b = ms.point_bound(st, pl.tables, cands)
    if not b["valid"]:
        raise SystemExit(f"derive: bound invalid: {b['problems']}")
    rows = b["rows"]
    i0 = min(range(len(rows)), key=lambda i: abs(rows[i]["f_hz"] - st.f0_hz))
    r0 = rows[i0]
    zin = complex(*r0["zin_core"])
    zopt = complex(*r0["zopt"])
    g_pm = ms.gamma(zin.conjugate(), st.z0)
    g_opt = ms.gamma(zopt, st.z0)
    pick = sorted({0, i0 // 2, i0, (i0 + len(rows) - 1) // 2, len(rows) - 1})
    return {
        "point": {"process": p, "temp_c": t, "vdd": v},
        "ngspice": localrun.version(),
        "f0_hz": rows[i0]["f_hz"],
        "gamma_power_match": [round(g_pm.real, 4), round(g_pm.imag, 4)],
        "gamma_noise_opt": [round(g_opt.real, 4), round(g_opt.imag, 4)],
        "table": [{"f_ghz": round(rows[i]["f_hz"] / 1e9, 4),
                   "zin_core_ohm": [round(x, 3) for x in rows[i]["zin_core"]],
                   "zopt_ohm": [round(x, 3) for x in rows[i]["zopt"]],
                   "fmin_db": round(rows[i]["fmin_db"], 4), "rn_ohm": round(rows[i]["rn_ohm"], 3),
                   "fit_rms_db": float(f"{rows[i]['fit_rms_db']:.3g}")} for i in pick],
        "probes_used": b["probes_used"],
        "op": {k: round(x, 6) for k, x in pl.op.items()},
    }


def cmd_derive(args) -> int:
    raw = json.loads(STUDY_JSON.read_text())
    st = ms.study_from_manifest(raw, partial=True)
    probes, _ = ms.generate_probes(raw["probes"])
    cands = [ms.candidate_from_dict(ms.BASELINE)] + [ms.candidate_from_dict(d) for d in probes]
    d = derivation(st, cands)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, indent=2) + "\n")
    print(json.dumps(d, indent=2))
    print(f"wrote {out}")
    return 0


def cmd_declare(args) -> int:
    """Fill the family's two derived reflection coefficients and freeze the
    expanded candidate list into study.json (the declaration commit)."""
    raw = json.loads(STUDY_JSON.read_text())
    if raw.get("candidates") and not args.force:
        raise SystemExit("declare: study.json already has a frozen candidate list (append-only declaration); "
                         "use --force only before the declaration is committed")
    d = json.loads(Path(args.derivation).read_text())
    raw["family"]["gamma_power_match"] = d["gamma_power_match"]
    raw["family"]["gamma_noise_opt"] = d["gamma_noise_opt"]
    raw["derivation"] = d
    cands, excluded = ms.expand_declaration(raw)
    raw["candidates"] = cands
    raw["excluded_targets"] = excluded
    ms.study_from_manifest(raw)  # validates
    STUDY_JSON.write_text(json.dumps(raw, indent=2) + "\n")
    roles = {}
    for c in cands:
        roles[c["role"]] = roles.get(c["role"], 0) + 1
    print(f"declared {roles}; excluded {len(excluded)}; wrote {STUDY_JSON}")
    return 0


# ---------------------------------------------------------------------------
# smoke: local single-point controls (records nothing)
# ---------------------------------------------------------------------------


def baseline_reproduction(st: ms.Study, tables: dict, op: dict, process: str, temp_c: float, vdd: float) -> dict:
    """The baseline candidate's cell at one point vs the lna-sparam-nf record."""
    import lna_nf  # noqa: PLC0415 - sim/lna-sparam-nf, read-only use
    cid = ms.corner_id(process, temp_c, vdd)
    old = lna_nf.parse_log((BASELINE_LOGS / f"{cid}.log").read_text())
    cell = ms.make_cell(st, "smoke", st.baseline, process, temp_c, vdd, tables[st.baseline.name], op)
    return dict(ms.compare_baseline(st, cell, old), corner_id=cid)


def cmd_smoke(args) -> int:
    st = ms.load_study()
    p, t, v = _nominal(st)
    fails = []
    # 1. normalization controls (independent closed form)
    for temp in (27.0, -40.0):
        r = localrun.pad_control(st, temp)
        print(f"pad control {temp:g} C: NF err {r.get('nf_err_db', float('nan')):.2e} dB "
              f"(expect {r.get('nf_expected_db', float('nan')):.4f}), S21 err {r.get('s21_err_db', float('nan')):.2e} dB, "
              f"worst S11/S22 {r.get('return_loss_worst_db', float('nan')):.1f} dB -> {'ok' if r['ok'] else 'FAIL'}")
        if not r["ok"]:
            fails.append(f"pad control {temp:g} C: {r}")
    # 2. baseline + one series_first + one shunt_first candidate + probes, nominal
    sel = [c for c in st.candidates if c.role == "candidate"]
    pick = [st.baseline] + [next(c for c in sel if c.topology == "series_first"),
                            next(c for c in sel if c.topology == "shunt_first")]
    probes = [c for c in st.candidates if c.role == "probe"]
    cands = pick + probes
    pl = ms.parse_log(localrun.run_point(ms.body_text(st, _frozen(), cands, v, title="smoke"), p, t, "smoke"))
    if pl.problems or not pl.done:
        fails.append(f"smoke deck: {pl.problems[:5]} done={pl.done}")
    rep = baseline_reproduction(st, pl.tables, pl.op, p, t, v)
    print(f"baseline vs {BASELINE_RECORD}/{rep['corner_id']}: worst {rep['worst']} -> "
          f"{'ok' if not rep['problems'] else 'FAIL ' + str(rep['problems'])}")
    fails += rep["problems"]
    b = ms.point_bound(st, pl.tables, cands)
    if b["valid"]:
        s = b["summary"]
        print(f"bound: NF floor with |S11| <= {st.screen['s11_max_db']} dB: max over band "
              f"{s['nf_bound_max_db']:.3f} dB at {s['f_at_nf_bound_max_hz'] / 1e9:.3f} GHz; "
              f"Fmin {s['fmin_min_db']:.3f}-{s['fmin_max_db']:.3f} dB; model check worst "
              f"{s['model_check_worst_db']:.2e} dB")
    else:
        fails.append(f"bound: {b['problems']}")
    for c in pick:
        cell = ms.make_cell(st, "smoke", c, p, t, v, pl.tables[c.name], pl.op)
        sm = cell.get("summary") or {}
        print(f"  {c.name:>16}: {cell['status']}; NFmax {sm.get('nf_max_db', float('nan')):.3f} dB, "
              f"S11max {sm.get('s11_max_db', float('nan')):.2f} dB, S21min {sm.get('s21_min_db', float('nan')):.2f} dB, "
              f"refined {cell.get('refined', {}).get('delta')}; screen {cell['screen']['reasons'] or 'pass'}")
        if cell["status"] != "ok":
            fails.append(f"{c.name}: {cell.get('reason')}")
    # 3. alterparam-independent cross-check + op invariance (one network, literal values)
    other = pick[1]
    lit = ms.body_text(st, _frozen(), [other], v, title="literal cross-check",
                       dut=ms.literal_dut_text(_frozen(), other), network_alter=False)
    pl2 = ms.parse_log(localrun.run_point(lit, p, t, "smoke_literal"))
    a1 = ms.analyze_candidate(st, other, pl.tables[other.name])
    a2 = ms.analyze_candidate(st, other, pl2.tables.get(other.name, {}))
    if not (a1.get("band") and a2.get("band")):
        fails.append("cross-check decks did not produce data")
    else:
        worst = max(abs(x - y) for k in ("nf_db", "s11_db", "s21_db", "s22_db")
                    for x, y in zip(a1["band"][k], a2["band"][k]))
        dop = max(abs(pl.op[k] - pl2.op[k]) for k in pl.op)
        print(f"cross-check {other.name}: alterparam deck vs literal deck worst {worst:.2e} dB; "
              f"op with baseline vs with {other.name} worst {dop:.2e}")
        if worst > st.tolerances["crosscheck_db"]:
            fails.append(f"alterparam cross-check {worst:.3g} dB")
        if dop > 1e-9 * max(1.0, max(abs(x) for x in pl.op.values())):
            fails.append(f"op not invariant to the input network ({dop:.3g})")
    # 4. sabotage: hbt_wcs must move the baseline
    plw = ms.parse_log(localrun.run_point(ms.body_text(st, _frozen(), [st.baseline], v, title="wcs"),
                                          "hbt_wcs", t, "smoke_wcs"))
    aw = ms.analyze_candidate(st, st.baseline, plw.tables.get(st.baseline.name, {}))
    a0 = ms.analyze_candidate(st, st.baseline, pl.tables[st.baseline.name])
    if aw.get("summary") and a0.get("summary"):
        d = aw["summary"]["s21_f0_db"] - a0["summary"]["s21_f0_db"]
        print(f"process sensitivity: baseline S21(f0) hbt_wcs - hbt_typ = {d:+.3f} dB")
        if abs(d) < 1e-3:
            fails.append("hbt_wcs does not move the baseline (corner section not applied?)")
    else:
        fails.append("wcs deck did not produce data")
    for f in fails:
        print(f"FAIL: {f}", file=sys.stderr)
    print("smoke: " + ("FAILED" if fails else "ok (records nothing)"))
    return 1 if fails else 0


def cmd_collect(args) -> int:
    import matchcollect as collect  # noqa: PLC0415
    return collect.collect(args)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("plan").set_defaults(func=cmd_plan)
    d = sub.add_parser("derive")
    d.add_argument("--out", default=str(localrun.SCRATCH / "derive.json"))
    d.set_defaults(func=cmd_derive)
    dc = sub.add_parser("declare")
    dc.add_argument("derivation")
    dc.add_argument("--force", action="store_true")
    dc.set_defaults(func=cmd_declare)
    sub.add_parser("smoke").set_defaults(func=cmd_smoke)
    c = sub.add_parser("collect")
    c.add_argument("--klt-cmd", default="klt")
    c.add_argument("--backend", default="batch", help="backend for the multi-unit corner requests")
    c.add_argument("--screen-backend", default="local", help="backend for the single-unit nominal screen")
    c.add_argument("--timeout-s", type=int, default=3600)
    c.add_argument("--no-stage-models", action="store_true")
    c.add_argument("--runner-version-check", default="", choices=("", "enforce", "warn"))
    c.add_argument("--workdir", default="")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--screen-only", action="store_true")
    c.set_defaults(func=cmd_collect)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
