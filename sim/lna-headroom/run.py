#!/usr/bin/env python3
"""Driver for the lna-headroom screening study (issue #123).

    python3 sim/lna-headroom/run.py check-plan
    python3 sim/lna-headroom/run.py variants [--check]      # (re)write / check the frozen variant decks
    python3 sim/lna-headroom/run.py build [--workdir DIR]
    python3 sim/lna-headroom/run.py collect [--dry-run]
    python3 sim/lna-headroom/run.py verify [RECORD_ID ...]

``collect`` submits one klt request per candidate (plus one analytic control) with an EXPLICIT
``--backend batch`` (Spot fleet) and never falls back to a local run: a failed submit stops the
collection, writes nothing and prints the error. ``verify`` re-derives every published verdict from
the frozen logs with no simulator.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import json
import shlex
import subprocess
import sys
from pathlib import Path

import headroom as H
from headroom import BENCH_DIR, REPO_ROOT, SIM_DIR
from harness import klt_driver
from harness.report import RecordExists, allocate_record_id, git_provenance

RECORDS = BENCH_DIR / "records"
LOGS = BENCH_DIR / "corners"
SNAPS = BENCH_DIR / "netlist-snapshots"
SCRATCH = BENCH_DIR / "_build"
MODEL_FILES = ("cornerHBT.lib", "sg13g2_hbt_mod.lib")
HIST_ID = "20261010-174208-0f67eaf"


class CollectionError(RuntimeError):
    pass


def git_out(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()


def sha256_file(p: Path) -> str:
    return H.sha256_bytes(p.read_bytes())


# ---------------------------------------------------------------------------
# plan / variants
# ---------------------------------------------------------------------------


def cmd_check_plan(args) -> int:
    hp, lp = H.load_plans()
    probs = H.plan_problems(hp, lp, H.DUT_PATH.read_text())
    for p in probs:
        print("FAIL:", p, file=sys.stderr)
    if probs:
        return 1
    print(f"plan ok: {len(H.candidates(hp))} candidates (baseline {hp['candidates']['baseline_id']}) x {len(lp['placements'])} "
          f"placements x {len(L_pins(lp))} single-tone powers; references lna-linearity plan-v2 (sha256 verified)")
    return 0


def L_pins(lp):
    return H.L.sweep_pins(lp, "one")


def cmd_variants(args) -> int:
    hp, _ = H.load_plans()
    dut = H.DUT_PATH.read_text()
    bad = 0
    H.VARIANTS_DIR.mkdir(exist_ok=True)
    for c in H.candidates(hp):
        p = H.VARIANTS_DIR / f"{c['id']}.spice"
        text = H.variant_text(dut, c)
        if args.check:
            if not p.is_file() or p.read_text() != text:
                print(f"FAIL: {p.name} does not regenerate from the DUT and the plan", file=sys.stderr)
                bad += 1
        else:
            p.write_text(text)
    if not args.check:
        print(f"wrote {len(H.candidates(hp))} variant decks under {H.VARIANTS_DIR}")
    return 1 if bad else 0


# ---------------------------------------------------------------------------
# bodies / klt
# ---------------------------------------------------------------------------


def write_requests(hp, lp, work: Path, backend: str, args) -> dict[str, Path]:
    dut = H.DUT_PATH.read_text()
    n = lp["nominal"]
    reqs = {}
    for key in H.request_keys(hp):
        body = work / f"body_{key}.spice"
        body.write_text(H.body_for_key(hp, lp, key, dut))
        req = work / f"request_{key}.json"
        req.write_text(json.dumps(klt_driver.klt_request(
            body.name, [n["process"]], [float(n["temperature_c"])], backend, args.timeout_s,
            sentinel_name="lin_sentinel_v", sentinel_node="v(p2)", stage_models=not args.no_stage_models,
            runner_version_check=args.runner_version_check), indent=2) + "\n")
        reqs[key] = req
    return reqs


def submit(key: str, req: Path, work: Path, backend: str, args) -> Path:
    report = work / f"report_{key}.json"
    if report.is_file():
        try:
            if "corners" in json.loads(report.read_text()):
                print(f"  reuse {report.name}", flush=True)
                return report
        except ValueError:
            pass
    out = (work / f"out_{key}").resolve()
    cmd = shlex.split(args.klt_cmd) + ["sim", str(req), "--backend", backend, "-o", str(out), "--format", "json"]
    print("$ " + " ".join(cmd), flush=True)
    with report.open("w") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, text=True)
    if proc.stderr:
        (work / f"stderr_{key}.log").write_text(proc.stderr)
    if proc.returncode != 0:
        report.rename(work / f"report_{key}.failed.json")
        raise CollectionError(f"klt sim failed for {key} (exit {proc.returncode}, backend {backend}): {proc.stderr[-3000:]}")
    return report


def read_unit(report: Path) -> tuple[dict, str]:
    data = json.loads(report.read_text())
    if "corners" not in data or len(data["corners"]) != 1:
        raise CollectionError(f"{report.name}: expected exactly one corner unit ({data.get('error')})")
    log = (data["corners"][0].get("artifacts") or {}).get("log")
    if not log:
        raise CollectionError(f"{report.name}: no log returned ({data['corners'][0].get('diagnostics')})")
    path = Path(log)
    if not path.is_absolute():
        path = (report.parent / path).resolve()
    return data, path.read_text()


def cmd_build(args) -> int:
    hp, lp = H.load_plans()
    work = Path(args.workdir or SCRATCH / "build").resolve()
    work.mkdir(parents=True, exist_ok=True)
    reqs = write_requests(hp, lp, work, args.backend, args)
    print(f"wrote {len(reqs)} bodies/requests under {work}")
    return 0


# ---------------------------------------------------------------------------
# provenance / record
# ---------------------------------------------------------------------------


def dirty_code() -> list[str]:
    st = git_out("status", "--porcelain", "--", "sim/lna-headroom", "sim/lna-linearity", "design/netlist/lna_stage1.spice")
    return [ln for ln in st.splitlines() if "_build" not in ln]


def _f(x, fmt="{:.2f}") -> str:
    return "n/a" if x is None or isinstance(x, str) else fmt.format(x)


def render_md(rid: str, status: str, rec: dict) -> str:
    hp, rk, bl = rec["plan_declaration"], rec["ranking"], rec["baseline_reproduction"]
    tgt = hp["targets"]["p1db_dbm"]
    L = [f"# lna-headroom record {rid}", "", f"- **Status: {status}**",
         "- **Experiment**: lna-headroom (issue #123), stage 1 screening", f"- **Started (UTC)**: {rec['started_utc']}", "",
         f"**Claim**: {hp['scope']}", "",
         "**Spec rows**: row 8 (input P1dB, target >= -25 dBm), row 7 (IIP3, target >= -15 dBm; not re-measured in this stage) and "
         "row 17 (V_CE <= 1.4 V). None is relaxed. Ideal passives, the draft band and nominal-only scope are unchanged.", "",
         "## Declaration",
         f"- Plan `sim/lna-headroom/testbench/plan.json` sha256 `{rec['plan']['sha256']}`, committed at `{rec['plan']['commit']}` "
         f"(dirty: {str(rec['plan']['dirty']).lower()}). Candidate table, gates, ranking, shortlist and outcome rules were frozen before collection.",
         f"- Reused nonlinear method: `{hp['linearity_plan']['file']}` sha256 `{hp['linearity_plan']['sha256']}` (single-tone sweep -56..-16 dBm, 2 dB, "
         "three placements, available-power convention, P1dB extractor, V_CE/V_BE limits, collector-current diagnostics with applicability UNRESOLVED and "
         "complete_envelope false).",
         "- Screening is single-tone, base timing only: no timestep/window convergence, no two-tone IIP3, no NF or stability is claimed by this record.",
         f"- DUT `{rec['dut']['file']}` sha256 `{rec['dut']['sha256']}`; varied only R1b/R2b (sum held at 8.5 kohm) and Rd; frozen decks in `variants/` and the snapshot.",
         "", "## Controls and baseline reproduction",
         f"- ngspice analytic cubic control (identical generated block and extractor, klt batch): {'PASS' if rec['ngspice_control']['pass'] else 'FAIL'} "
         f"(P1dB error {rec['ngspice_control']['error_db']:+.3f} dB, tol {rec['ngspice_control']['tol_db']}; gain error {rec['ngspice_control']['gain_error_db']:+.3f} dB, tol {rec['ngspice_control']['gain_tol_db']})",
         f"- Baseline C00 vs `{bl['record']}`: **{'REPRODUCED' if bl['reproduced'] else 'NOT REPRODUCED'}** (tolerances {bl['tolerances']})"]
    for n, c in bl["per_placement"].items():
        L.append(f"  - {n}: first violation {c['first_violation_pin_dbm']} dBm ({c['identity']}) vs historical {c['historical_first_violation_pin_dbm']} dBm "
                 f"({c['historical_identity']}); max Q2 V_CE peak delta {c['max_vce_q2_peak_delta_v'] * 1e3:.2f} mV, max delivered-power delta "
                 f"{c['max_delivered_power_delta_db']:.3f} dB: {'ok' if c['reproduced'] else 'FAIL'}")
    L += ["", "## DC voltage allocation (nominal)", "",
          "| cand | R2b | Rd | Vc1 | Vb2 | V_CE Q1 | V_CE Q2 | V_BE Q2 | Ic(Q1) mA | gates failed |", "|---|---|---|---|---|---|---|---|---|---|"]
    for cid, c in rec["candidates"].items():
        d, k = c["dc"], c["candidate"]
        L.append(f"| {cid} | {k['r2b_ohm']:g} | {k['rd_ohm']:g} | {d['vc1_v']:.3f} | {d['vb2_v']:.3f} | {d['vce_q1_v']:.3f} | {d['vce_q2_v']:.3f} | "
                 f"{d['vbe_q2_v']:.3f} | {d['ic_q1_ma_from_re1']:.2f} | {', '.join(c['gates']['failed']) or 'none'} |")
    L += ["", "## Single-tone stress-qualified outcomes (all candidates, rejected ones included)", "",
          "Stress-free power = last swept available power before the first limit violation. P1dB is a number only where the 1 dB crossing is bracketed by "
          "stress-valid points; otherwise `> x` is a one-sided bound. 'gap' = how far (dB) the stress-free power is below the unchanged -25 dBm target.", "",
          "| cand | placement | baseline gain dB | stress-free dBm | first violation | limit | gain drop at stress-free dB | P1dB | gap to -25 dBm dB |",
          "|---|---|---|---|---|---|---|---|---|"]
    for cid, c in rec["candidates"].items():
        for n, p in c["placements"].items():
            s, q = p["stress"], p["p1db"]
            pd = f"{q['p1db_in_dbm']:.2f}" if q["status"] == "ok" else (f"> {q['p1db_in_dbm_gt']:g} (bounded)" if q["status"] == "bounded" else "unavailable")
            L.append(f"| {cid} | {n} | {_f(p['baseline_gain_db'])} | {_f(s['stress_free_pin_dbm'], '{:g}')} | "
                     f"{_f(s['first_violation_pin_dbm'], '{:g}')} | {s['limit_identity'] or 'none in sweep'} | "
                     f"{_f(p['gain_drop_at_stress_free_db'], '{:.3f}')} | {pd} | {_f(p['gap_to_row8_target_db'], '{:.0f}')} |")
    L += ["", "## Gain versus stress tradeoff (relative to C00)", "",
          "| cand | worst stress-free dBm | headroom gain dB (input-referred) | min gain loss dB | net OUTPUT headroom dB | gates failed |", "|---|---|---|---|---|---|"]
    for cid, c in rec["candidates"].items():
        m, g = c["metrics"], c["gates"]
        loss = [v for v in (g["gain_loss_db"] or {}).values() if v is not None]
        L.append(f"| {cid} | {_f(m['worst_stress_free_pin_dbm'], '{:g}')} | {_f(m['headroom_gain_db'], '{:+.1f}')} | "
                 f"{_f(max(loss) if loss else None, '{:.2f}')} (worst) | {_f(m['net_output_headroom_db'], '{:+.1f}')} | {', '.join(g['failed']) or 'none'} |")
    L += ["", "## Ranking, shortlist and outcome (rules from the frozen plan)",
          f"- Ranked (G_dc, G_gain, G_base all pass): {', '.join(rk['admitted']) or 'none'}",
          f"- Shortlist for refinement (headroom gain >= {hp['shortlist']['min_headroom_gain_db']:g} dB and net output headroom > 0): {', '.join(rk['shortlist']) or 'EMPTY'}",
          f"- Not ranked: " + ("; ".join(f"{k}: {', '.join(v)}" for k, v in rk["not_ranked"].items()) or "none"),
          f"- **Outcome class: `{rk['outcome_class']}`**", "",
          "## Provenance and raw artifacts",
          f"- Git: commit `{rec['environment']['git']['commit']}` (dirty: {str(rec['environment']['git']['dirty']).lower()}), minted by `python3 sim/lna-headroom/run.py collect`.",
          f"- Client: `{rec['environment']['klt_client']}`; PDK artifact pin sha256 `{rec['environment']['pdk_artifact_sha256']}`."]
    for r in rec["klt_requests"]:
        L.append(f"- request `{r['key']}`: backend {r['backend']}, status {r['status']}, engine {r['engine']} {r['engine_version']}, "
                 f"models_lib_sha256 `{r['models_lib_sha256']}`, remote {json.dumps(r['remote'], sort_keys=True)}")
    L += [f"- Raw logs `corners/{rid}/<request>.log.gz`; frozen plan, DUT, variants, bodies, requests, reports `netlist-snapshots/{rid}/`; every point "
          f"`records/{rid}-sweeps.json.gz`. Re-derive with `python3 sim/lna-headroom/run.py verify`.", ""]
    return "\n".join(L)


def collect(args) -> int:
    hp, lp = H.load_plans()
    probs = H.plan_problems(hp, lp, H.DUT_PATH.read_text())
    if probs:
        print("\n".join(probs), file=sys.stderr)
        return 1
    dirty = dirty_code()
    if dirty and not args.dry_run and not args.allow_dirty:
        print("refusing to collect with uncommitted changes in sim/lna-headroom, sim/lna-linearity or the DUT:\n" + "\n".join(dirty), file=sys.stderr)
        return 1
    started = _dt.datetime.now(_dt.timezone.utc)
    work = Path(args.workdir or SCRATCH / f"klt-{started.strftime('%Y%m%d-%H%M%S')}").resolve()
    work.mkdir(parents=True, exist_ok=True)
    reqs = write_requests(hp, lp, work, args.backend, args)
    if args.dry_run:
        print(f"--dry-run: {len(reqs)} requests written under {work}; nothing submitted")
        return 0
    pdk = klt_driver.find_pdk_or_exit(SIM_DIR, require_artifact=True)
    texts, reports = {}, {}
    try:
        for key, req in reqs.items():
            rep = submit(key, req, work, args.backend, args)
            data, text = read_unit(rep)
            texts[key], reports[key] = text, data
    except CollectionError as exc:
        print(f"collect: {exc}\ncollect: NO record written, no local fallback. Requests/bodies kept under {work}", file=sys.stderr)
        return 1
    return finalize(hp, lp, work, reqs, texts, reports, pdk, started, args)


def finalize(hp, lp, work, reqs, texts, reports, pdk, started, args) -> int:
    hist, hist_sw = H.load_historical(HIST_ID)
    res = H.analyze(hp, lp, texts, hist, hist_sw)
    if res["problems"]:
        for p in res["problems"][:40]:
            print("FAIL:", p, file=sys.stderr)
        print("collect: log integrity gate failed; NO record written", file=sys.stderr)
        return 1
    git = git_provenance(REPO_ROOT)
    git["dirty"] = bool(dirty_code())
    rid = allocate_record_id(REPO_ROOT, RECORDS, git=git)
    status = ("COLLECTED" if res["ngspice_control"]["pass"] and res["baseline_reproduction"]["reproduced"]
              else "CONTROLS_FAILED" if not res["ngspice_control"]["pass"] else "BASELINE_NOT_REPRODUCED")
    client = subprocess.run(shlex.split(args.klt_cmd) + ["--version"], capture_output=True, text=True)
    requests = []
    for key in H.request_keys(hp):
        d = reports[key]
        env = d.get("environment") or {}
        requests.append({"key": key, "backend": args.backend, "status": d.get("status"), "engine": env.get("engine"),
                         "engine_version": env.get("engine_version"), "models_lib_sha256": env.get("models_lib_sha256"),
                         "netlist_sha256": env.get("netlist_sha256"), "remote": env.get("remote"),
                         "klt_version": (d.get("provenance") or {}).get("klt_version")})
    sweeps = res.pop("sweeps")
    plan_rel = H.PLAN_PATH.relative_to(REPO_ROOT).as_posix()
    rec = {"record_id": rid, "status": status, "stage": 1, "started_utc": started.isoformat(), "spec_rows_claimed_met": [],
           "plan": {"file": plan_rel, "sha256": sha256_file(H.PLAN_PATH), "commit": git_out("log", "-1", "--format=%H", "--", plan_rel),
                    "dirty": bool(dirty_code())},
           "plan_declaration": hp,
           "dut": {"file": H.DUT_PATH.relative_to(REPO_ROOT).as_posix(), "sha256": sha256_file(H.DUT_PATH)},
           "ngspice_control": res["ngspice_control"], "baseline_reproduction": res["baseline_reproduction"],
           "candidates": res["candidates"], "ranking": res["ranking"], "klt_requests": requests, "sweeps_file": f"{rid}-sweeps.json.gz",
           "environment": {"git": git, "klt_client": (client.stdout or client.stderr).strip(),
                           "pdk_artifact_sha256": sha256_file(SIM_DIR / "pdk-artifact.json"),
                           "pdk": klt_driver.pdk_provenance(pdk, MODEL_FILES)}}
    for d in (RECORDS, LOGS / rid, SNAPS / rid):
        d.mkdir(parents=True, exist_ok=True)
    published = H.roundtrip({k: v for k, v in rec.items() if k != "plan_declaration"})
    published["plan_declaration"] = hp
    (RECORDS / f"{rid}.json").write_text(json.dumps(published, indent=2) + "\n")
    with gzip.open(RECORDS / f"{rid}-sweeps.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(H.roundtrip(sweeps), fh)
    for key, text in texts.items():
        with gzip.open(LOGS / rid / f"{key}.log.gz", "wt", encoding="utf-8") as fh:
            fh.write(text)
    snap = SNAPS / rid
    (snap / "plan.json").write_bytes(H.PLAN_PATH.read_bytes())
    (snap / "lna_stage1.spice").write_bytes(H.DUT_PATH.read_bytes())
    (snap / "linearity-plan-v2.json").write_bytes((REPO_ROOT / hp["linearity_plan"]["file"]).read_bytes())
    for key in reqs:
        for stem in ("body_{}.spice", "request_{}.json", "report_{}.json"):
            (snap / stem.format(key)).write_bytes((work / stem.format(key)).read_bytes())
    for c in H.candidates(hp):
        (snap / f"variant_{c['id']}.spice").write_text(H.variant_text(H.DUT_PATH.read_text(), c))
    (RECORDS / f"{rid}.md").write_text(render_md(rid, status, json.loads((RECORDS / f"{rid}.json").read_text())))
    print(f"record {rid}: {status}; outcome class {res['ranking']['outcome_class']}; shortlist {res['ranking']['shortlist']}")
    return 0


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def verify_record(rid: str) -> list[str]:
    snap = SNAPS / rid
    hp = json.loads((snap / "plan.json").read_text())
    lp = json.loads((snap / "linearity-plan-v2.json").read_text())
    if H.sha256_bytes((snap / "linearity-plan-v2.json").read_bytes()) != hp["linearity_plan"]["sha256"]:
        return ["frozen linearity plan does not match the hash declared in the frozen plan"]
    rec = json.loads((RECORDS / f"{rid}.json").read_text())
    texts = {}
    for key in H.request_keys(hp):
        with gzip.open(LOGS / rid / f"{key}.log.gz", "rt", encoding="utf-8") as fh:
            texts[key] = fh.read()
    hist, hist_sw = H.load_historical(HIST_ID)
    res = H.analyze(hp, lp, texts, hist, hist_sw)
    if res["problems"]:
        return res["problems"]
    sweeps = res.pop("sweeps")
    with gzip.open(RECORDS / rec["sweeps_file"], "rt", encoding="utf-8") as fh:
        stored = json.load(fh)
    out = []
    rt = lambda x: json.loads(json.dumps(H.roundtrip(x)))  # noqa: E731
    for k in ("ngspice_control", "baseline_reproduction", "candidates", "ranking"):
        if rt(res[k]) != rec[k]:
            out.append(f"{k} does not reproduce from the frozen logs")
    if rt(sweeps) != stored:
        out.append("stored sweeps do not reproduce from the frozen logs")
    if rec["plan_declaration"] != hp:
        out.append("record plan_declaration differs from the frozen plan")
    dut = (snap / "lna_stage1.spice").read_text()
    for key in H.request_keys(hp):
        if (snap / f"body_{key}.spice").read_text() != H.body_for_key(hp, lp, key, dut):
            out.append(f"frozen body_{key}.spice does not regenerate from the frozen plan and DUT")
    for c in H.candidates(hp):
        if (snap / f"variant_{c['id']}.spice").read_text() != H.variant_text(dut, c):
            out.append(f"frozen variant_{c['id']}.spice does not regenerate")
    return out


def cmd_verify(args) -> int:
    ids = args.records or sorted(p.stem for p in RECORDS.glob("*.json") if not p.name.endswith("-sweeps.json"))
    bad = 0
    for rid in ids:
        probs = verify_record(rid)
        for p in probs:
            print(f"FAIL {rid}: {p}", file=sys.stderr)
        bad += bool(probs)
        if not probs:
            print(f"verify {rid}: ok")
    if not ids:
        print("verify: no records committed yet (collection pending)")
    return 1 if bad else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-plan").set_defaults(fn=cmd_check_plan)
    v = sub.add_parser("variants")
    v.add_argument("--check", action="store_true")
    v.set_defaults(fn=cmd_variants)
    for name, fn in (("build", cmd_build), ("collect", collect)):
        p = sub.add_parser(name)
        p.add_argument("--klt-cmd", default="klt")
        p.add_argument("--backend", default="batch")
        p.add_argument("--timeout-s", type=int, default=7200)
        p.add_argument("--no-stage-models", action="store_true")
        p.add_argument("--runner-version-check", default="", choices=("", "enforce", "warn"))
        p.add_argument("--workdir", default="")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--allow-dirty", action="store_true", help=argparse.SUPPRESS)
        p.set_defaults(fn=fn)
    vv = sub.add_parser("verify")
    vv.add_argument("records", nargs="*")
    vv.set_defaults(fn=cmd_verify)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (CollectionError, RecordExists) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
