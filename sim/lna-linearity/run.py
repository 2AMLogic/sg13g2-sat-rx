#!/usr/bin/env python3
"""Driver for the lna-linearity bench (issue #57).

    python3 sim/lna-linearity/run.py check-plan
    python3 sim/lna-linearity/run.py controls
    python3 sim/lna-linearity/run.py build [--workdir DIR]
    python3 sim/lna-linearity/run.py collect [--backend batch] [--dry-run]
    python3 sim/lna-linearity/run.py verify [RECORD_ID ...]

``check-plan`` verifies, before anything is simulated, that every declared tone
placement is inside the draft band and coherent with the declared window for
every variant. ``controls`` runs the closed-form positive and negative controls
(no simulator). ``build`` writes the klt bodies and requests. ``collect``
submits them (one single-unit request per placement x variant plus the
analytic control) with an EXPLICIT ``--backend batch`` so even a single unit
goes to the Spot batch fleet, never a local loop; a failed submit stops the
collection, writes nothing and does not fall back to a local run. Only after
the controls and the log-integrity gate does it write ONE append-only record
(records/<id>.md, <id>.json, <id>-sweeps.json.gz, corners/<id>/*.log.gz,
netlist-snapshots/<id>/). ``verify`` re-parses the frozen logs of committed
records and fails unless the published verdicts reproduce.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
SIM_DIR = BENCH_DIR.parent
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(BENCH_DIR))

import analysis as A  # noqa: E402
import linearity as L  # noqa: E402
from harness import klt_driver  # noqa: E402
from harness.report import RecordExists, allocate_record_id, git_provenance  # noqa: E402

PLAN_PATH = BENCH_DIR / "testbench" / "plan.json"
DUT_PATH = REPO_ROOT / "design" / "netlist" / "lna_stage1.spice"
FIXTURE_PATH = SIM_DIR / "lna-sparam-nf" / "testbench" / "lna_stage1.spice"
SCRATCH = BENCH_DIR / "_build"
RECORDS = BENCH_DIR / "records"
LOGS = BENCH_DIR / "corners"
SNAPS = BENCH_DIR / "netlist-snapshots"
MODEL_FILES = ("cornerHBT.lib", "sg13g2_hbt_mod.lib")
CODE_FILES = ("linearity.py", "analysis.py", "run.py", "testbench/plan.json")

SCOPE = ("nominal-corner (hbt_typ, 27 C, 2.5 V) nonlinear characterization of design/lna_stage1 with IDEAL lossless "
         "L/C matching (placeholder circuit): two-tone IIP3 (spec row 7) and single-tone input P1dB (spec row 8) at "
         "three in-band placements; ratified targets unchanged; not compliance, not an all-corner statement, band "
         "(row 1) still a DRAFT")


class CollectionError(RuntimeError):
    pass


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def git_out(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()


# ---------------------------------------------------------------------------
# plan / controls (no simulator)
# ---------------------------------------------------------------------------


def plan_problems(plan: dict) -> list[str]:
    out = []
    for pl in plan["placements"]:
        out += L.band_problems(plan, pl)
        for v in L.VARIANTS:
            out += [f"{pl['name']}/{v}: {p}" for p in L.placement_coherence(plan, pl, v)]
    return out


def python_controls(plan: dict) -> dict:
    c = plan["controls"]
    pos = {}
    for kind in ("two", "one"):
        for fl in (1e-8, 1e-6):
            r = L.evaluate_control(plan, kind, L.synthetic_rows(plan, c["a1"], c["a3"], fl, kind=kind), c["a1"], c["a3"])
            pos[f"{kind}_floor_{fl:g}V"] = {k: r[k] for k in ("expected_dbm", "expected_gain_db", "error_db", "gain_error_db", "tol_db", "pass")}
    neg = L.negative_controls(plan)
    return {"positive": pos, "negative": neg,
            "pass": all(v["pass"] for v in pos.values()) and all(n["rejected"] for n in neg)}


def cmd_check_plan(args) -> int:
    plan = L.load_plan(PLAN_PATH)
    probs = plan_problems(plan)
    for p in probs:
        print("FAIL:", p, file=sys.stderr)
    if probs:
        return 1
    print(f"plan ok: {len(plan['placements'])} placements x {len(L.VARIANTS)} variants coherent and in band; "
          f"{len(L.sweep_pins(plan, 'two'))} two-tone and {len(L.sweep_pins(plan, 'one'))} single-tone sweep powers")
    return 0


def cmd_controls(args) -> int:
    plan = L.load_plan(PLAN_PATH)
    res = python_controls(plan)
    for n in res["negative"]:
        print(("rejected " if n["rejected"] else "ACCEPTED ") + n["name"] + ": " + n["observed"])
    for k, v in res["positive"].items():
        print(("pass " if v["pass"] else "FAIL ") + k + f": error {v['error_db']:.4f} dB, gain error {v['gain_error_db']:.4f} dB")
    return 0 if res["pass"] else 1


# ---------------------------------------------------------------------------
# bodies and requests
# ---------------------------------------------------------------------------


def body_for_key(plan: dict, key: str, dut_text: str) -> str:
    runs = A.runs_for_key(plan, key)
    who, kind = A.split_key(key)
    if who == A.CONTROL:
        c = plan["controls"]
        circuit = L.control_circuit(c["a1"], c["a3"])
    else:
        circuit = L.dut_circuit(dut_text, plan["nominal"]["vdd_v"])
    circuit += "\n" + L.options_line(plan, kind)
    return L.body_for_runs(f"lna-linearity {key}", circuit, runs)


def klt_request(plan: dict, body_name: str, backend: str, args) -> dict:
    n = plan["nominal"]
    return klt_driver.klt_request(body_name, [n["process"]], [float(n["temperature_c"])], backend, args.timeout_s,
                                  sentinel_name="lin_sentinel_v", sentinel_node="v(p2)",
                                  stage_models=not args.no_stage_models, runner_version_check=args.runner_version_check)


def write_requests(plan: dict, work: Path, backend: str, args) -> dict[str, Path]:
    dut_text = DUT_PATH.read_text()
    reqs = {}
    for key in A.request_keys(plan):
        body = work / f"body_{key}.spice"
        body.write_text(body_for_key(plan, key, dut_text))
        req = work / f"request_{key}.json"
        req.write_text(json.dumps(klt_request(plan, body.name, backend, args), indent=2) + "\n")
        reqs[key] = req
    return reqs


def submit(key: str, req: Path, work: Path, backend: str, args) -> Path:
    """One klt request on an explicit backend; reuses a complete report (resume).
    Any failure raises: there is no local fallback."""
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
    corner = data["corners"][0]
    log = (corner.get("artifacts") or {}).get("log")
    if not log:
        raise CollectionError(f"{report.name}: no log returned ({corner.get('diagnostics')})")
    path = Path(log)
    if not path.is_absolute():
        path = (report.parent / path).resolve()
    return data, path.read_text()


def cmd_build(args) -> int:
    plan = L.load_plan(PLAN_PATH)
    probs = plan_problems(plan)
    if probs:
        print("\n".join(probs), file=sys.stderr)
        return 1
    work = Path(args.workdir or SCRATCH / "build").resolve()
    work.mkdir(parents=True, exist_ok=True)
    reqs = write_requests(plan, work, args.backend, args)
    print(f"wrote {len(reqs)} bodies/requests under {work}")
    return 0


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------


def dirty_code() -> list[str]:
    st = git_out("status", "--porcelain", "--", "sim/lna-linearity", "design/netlist/lna_stage1.spice")
    return [ln for ln in st.splitlines() if "_build" not in ln]


def plan_provenance() -> dict:
    rel = PLAN_PATH.relative_to(REPO_ROOT).as_posix()
    return {"file": rel, "sha256": sha256_file(PLAN_PATH), "commit": git_out("log", "-1", "--format=%H", "--", rel),
            "dirty": bool(dirty_code())}


def dut_identity() -> dict:
    text = DUT_PATH.read_text()
    rel = DUT_PATH.relative_to(REPO_ROOT).as_posix()
    return {"file": rel, "sha256": sha256_file(DUT_PATH), "last_commit": git_out("log", "-1", "--format=%H", "--", rel),
            "export_header": [ln for ln in text.splitlines() if ln.startswith("* tools:")][:1],
            "fixture_embeds_verbatim": text.strip() in FIXTURE_PATH.read_text() if FIXTURE_PATH.is_file() else False,
            "matching": "IDEAL lossless L/C (Cshunt, Lin, Lfeed, Cm); no PDK inductor model exists"}


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------


def _f(x, fmt="{:.2f}") -> str:
    return "n/a" if x is None or isinstance(x, str) else fmt.format(x)


def render_md(rid: str, status: str, rec: dict) -> str:
    plan = rec["plan_declaration"]
    ctl = rec["controls"]
    lines = [
        f"# lna-linearity record {rid}",
        "",
        f"- **Status: {status}**",
        f"- **Experiment**: lna-linearity (issue #57)",
        f"- **Started (UTC)**: {rec['started_utc']}",
        "",
        f"**Claim**: {SCOPE}. The DUT is design/lna_stage1 (one cascode stage) with IDEAL lossless L/C matching, a "
        "placeholder circuit: no loss, Q or layout parasitic is represented. Nothing here relaxes a ratified target; a failing, "
        "unavailable, bounded or unconverged outcome is published as such.",
        "",
        "**Spec rows**: row 7 (LNA IIP3, target >= -15 dBm) and row 8 (LNA input P1dB, target >= -25 dBm), both referred "
        "to per-tone / single-tone AVAILABLE source power at the 50 ohm port.",
        "",
        "## Declaration",
        f"- Plan: `{rec['plan']['file']}` sha256 `{rec['plan']['sha256']}`, declared at commit `{rec['plan']['commit']}` "
        f"(dirty: {str(rec['plan']['dirty']).lower()}). The plan was committed before this collection.",
        f"- Corner: {plan['nominal']['process']}, {plan['nominal']['temperature_c']:g} C, {plan['nominal']['vdd_v']:g} V "
        "(nominal only; linearity corner dependence is not established here).",
        f"- Sweep (per-tone available power): two-tone {plan['sweep']['two']['start_dbm']:g} to {plan['sweep']['two']['stop_dbm']:g} dBm "
        f"in {plan['sweep']['two']['step_db']:g} dB steps ({len(L.sweep_pins(plan, 'two'))} points); single-tone "
        f"{plan['sweep']['one']['start_dbm']:g} to {plan['sweep']['one']['stop_dbm']:g} dBm in {plan['sweep']['one']['step_db']:g} dB steps "
        f"({len(L.sweep_pins(plan, 'one'))} points). Solver options: two-tone {plan['numerics']['two']}, single-tone {plan['numerics']['one']}.",
        f"- Time: step {plan['time']['step_s']:.3g} s, settling discard {plan['time']['settle_discard_s']:.3g} s, window "
        f"{plan['time']['window_s']:.3g} s (FFT bin spacing {1 / plan['time']['window_s']:.3g} Hz, rectangular, exactly coherent), "
        f"raised-cosine source ramp {plan['time']['ramp_s']:.3g} s, "
        "retained samples taken from a uniform `linearize` grid.",
        "- Ports: Thevenin 50 ohm source (available power Vs^2/(8 Z0) per tone), 50 ohm load; delivered power V^2/(2 Z0).",
        "- Numerical floor: larger of the delivered powers at two coherent bins carrying no product "
        "(2f1-f2 minus 50 MHz, 2f2-f1 plus 50 MHz; single tone: f0 -/+ 50 MHz), per run.",
        f"- Operating limits (spec row 17 + card box), instantaneous over the window: V_CE <= {plan['extraction']['operating_limits']['vce_max_v']} V, "
        f"V_CE in {plan['extraction']['operating_limits']['vce_window_v']}, V_BE in {plan['extraction']['operating_limits']['vbe_window_v']}; "
        "the card Ic box is not monitored. Points breaking a limit are classified and excluded, never fitted through.",
        "",
        "## DUT identity",
        f"- `{rec['dut']['file']}` sha256 `{rec['dut']['sha256']}`, last changed at commit `{rec['dut']['last_commit']}`; "
        f"{rec['dut']['export_header'][0] if rec['dut']['export_header'] else ''}",
        f"- Embedded verbatim in the sim/lna-sparam-nf fixture: {str(rec['dut']['fixture_embeds_verbatim']).lower()}. "
        f"Matching: {rec['dut']['matching']}.",
        "",
        "## Controls",
        f"- Python analytic controls (positive + negative, no simulator): {'PASS' if rec['python_controls']['pass'] else 'FAIL'} "
        f"({len(rec['python_controls']['negative'])} negative controls, all rejected: "
        f"{str(all(n['rejected'] for n in rec['python_controls']['negative'])).lower()}).",
    ]
    for n in rec["python_controls"]["negative"]:
        lines.append(f"  - {'rejected' if n['rejected'] else 'ACCEPTED'} `{n['name']}`: {n['fault']} -> {n['observed']}")
    nc = ctl
    lines += [
        f"- ngspice analytic control (memoryless cubic a1={nc['a1']:g}, a3={nc['a3']:g} between the same 50 ohm terminations, "
        f"the identical generated block and extractor, klt batch): {'PASS' if nc['pass'] else 'FAIL'}",
    ]
    for kind, ev in nc["evaluations"].items():
        name = "two-tone IIP3" if kind == "two" else "single-tone P1dB"
        lines.append(f"  - {name}: expected {ev['expected_dbm']:.3f} dBm, "
                     f"{'got ' + format(ev['expected_dbm'] + ev['error_db'], '.3f') + ' dBm (error ' + format(ev['error_db'], '+.3f') + ' dB, tol ' + str(ev['tol_db']) + ')' if ev['error_db'] is not None else 'estimator ' + ev['result']['status']}; "
                     f"small-signal gain expected {ev['expected_gain_db']:.3f} dB, error "
                     f"{_f(ev['gain_error_db'], '{:+.3f}')} dB (tol {ev['gain_tol_db']})")
    lines += ["", "## Results (base sweep; converged = both refinements agree)"]
    for name, pe in rec["placements"].items():
        fr = pe["frequencies_hz"]
        lines += ["", f"### Placement `{name}`: tones {fr['f1'] / 1e9:.3f} / {fr['f2'] / 1e9:.3f} GHz "
                      f"(IM3 {fr['im3l'] / 1e9:.3f} / {fr['im3h'] / 1e9:.3f} GHz), single tone {fr['f0'] / 1e9:.3f} GHz"]
        for kind, label in (("iip3", "IIP3 (two-tone)"), ("p1db", "P1dB (single-tone input-referred)")):
            fin = pe["final"][kind]
            res = pe["results"][kind]
            a = fin["assessment"]
            lines.append(f"- **{label}: {fin['status']}** (converged: {str(fin['converged']).lower()}; target verdict: "
                         f"**{a['verdict']}** against {a['target_dbm']:g} dBm, unchanged)")
            if kind == "iip3":
                for side, s in (res.get("sidebands") or {}).items():
                    if s["status"] == "ok":
                        lines.append(f"  - {side} sideband: interval {s['interval_dbm'][0]:g}..{s['interval_dbm'][1]:g} dBm "
                                     f"({s['n_points']} points), slopes {s['slope_fund']:.3f}/{s['slope_im3']:.3f}, residuals "
                                     f"{s['residual_fund_db']:.3f}/{s['residual_im3_db']:.3f} dB, IIP3 {s['iip3_dbm']:.2f} dBm "
                                     f"(free-slope intersection {s['iip3_free_slope_dbm']:.2f} dBm), extrapolated "
                                     f"{s['extrapolation_db']:.1f} dB above the highest fitted power; small-signal gain "
                                     f"{s['baseline']['gain_db']:.2f} dB")
                    else:
                        lines.append(f"  - {side} sideband: unavailable: {s['reason']}")
                if res["status"] == "ok":
                    lines.append(f"  - reported IIP3 (lower sideband estimate): **{res['iip3_dbm']:.2f} dBm**, sideband spread "
                                 f"{res['sideband_spread_db']:.2f} dB")
                else:
                    lines.append(f"  - unavailable: {res['reason']}")
            else:
                if res["status"] == "ok":
                    b = res["bracket"]
                    lines.append(f"  - baseline gain {res['baseline']['gain_db']:.2f} dB (steps {res['baseline']['pin_dbm']}, spread "
                                 f"{res['baseline']['spread_db']:.3f} dB); bracket {b['pin_dbm'][0]:g}..{b['pin_dbm'][1]:g} dBm, "
                                 f"drops {b['drop_db'][0]:.3f}..{b['drop_db'][1]:.3f} dB; input P1dB **{res['p1db_in_dbm']:.2f} dBm**, "
                                 f"output {res['p1db_out_dbm']:.2f} dBm")
                elif res["status"] == "bounded":
                    lines.append(f"  - baseline gain {res['baseline']['gain_db']:.2f} dB; P1dB > {res['p1db_in_dbm_gt']:g} dBm "
                                 f"(lower bound only): {res['reason']}")
                else:
                    lines.append(f"  - {res['reason']}")
            for c in pe["convergence"][kind]:
                est = c["estimator"]
                lines.append(f"  - convergence `{c['variant']}`: {'PASS' if c['ok'] else 'FAIL'}; estimator "
                             f"{est['base_status']}->{est['other_status']}, delta {_f(est.get('delta_db'), '{:+.3f}')} dB "
                             f"(tol {est['tol_db']}); max fundamental delta "
                             f"{max([v['max_abs_delta_db'] for v in c['pointwise_fundamental'].values()] or [0]):.3f} dB, max IM3 delta "
                             f"{max([v['max_abs_delta_db'] for v in c['pointwise_im3'].values()] or [0]):.3f} dB over the points used"
                             + (f" -- {est['reason']}" if est.get("reason") and not c["ok"] else ""))
        ur = pe["unrestricted_reference"]
        lines.append(f"- {ur['label']}: IIP3 {ur['iip3']['status']}"
                     + (f" {ur['iip3']['iip3_dbm']:.2f} dBm" if ur["iip3"]["status"] == "ok" else "")
                     + f"; P1dB {ur['p1db']['status']}"
                     + (f" {ur['p1db']['p1db_in_dbm']:.2f} dBm" if ur["p1db"]["status"] == "ok" else
                        f" (> {ur['p1db'].get('p1db_in_dbm_gt', float('nan')):g} dBm)" if ur["p1db"]["status"] == "bounded" else ""))
        fl = pe["first_limit_violation"]
        for k, label in (("two_tone", "two-tone"), ("single_tone", "single-tone")):
            v = fl[k]
            lines.append(f"- first swept power outside the DUT operating limits, {label}: "
                         + (f"{v['pin_dbm']:g} dBm ({'; '.join(v['violations'])})" if v else "none in the sweep"))
        lines += ["", "Rejected / excluded sweep points (base sweep):"]
        any_ex = False
        for kind, label in (("iip3", "two-tone"), ("p1db", "single-tone")):
            res = pe["results"][kind]
            groups = [("", res.get("excluded_points") or {})] if kind == "p1db" else \
                [(f"{s} sideband ", (v.get("excluded_points") or {})) for s, v in (res.get("sidebands") or {}).items()]
            for tag, ex in groups:
                for pin, why in ex.items():
                    any_ex = True
                    lines.append(f"  - {label} {tag}{pin} dBm: {why}")
        if not any_ex:
            lines.append("  - none")
    lines += ["", "## Rows 7 and 8"]
    for row, r in rec["rows"].items():
        lines.append(f"- row {row} ({'IIP3' if r['kind'] == 'iip3' else 'input P1dB'}, target >= {r['target_dbm']:g} dBm, unchanged): "
                     f"worst placement verdict **{r['worst_verdict']}**; "
                     + ", ".join(f"{n}: {v['status']}/{v['verdict']}" for n, v in r["per_placement"].items()))
    lines += [
        "- The DUT has ideal matching and is evaluated at one corner: these figures are placeholder-circuit, nominal-corner evidence "
        "and are not recorded as measured compliance for rows 7 or 8.",
        "",
        "## Provenance and raw artifacts",
        f"- Git: commit `{rec['environment']['git']['commit']}` (dirty: {str(rec['environment']['git']['dirty']).lower()}), "
        f"record minted by `python3 sim/lna-linearity/run.py collect`.",
        f"- Client: `{rec['environment']['klt_client']}`; PDK artifact pin sha256 `{rec['environment']['pdk_artifact_sha256']}`.",
    ]
    for r in rec["klt_requests"]:
        lines.append(f"- request `{r['key']}`: backend {r['backend']}, status {r['status']}, engine {r['engine']} {r['engine_version']}, "
                     f"models_lib_sha256 `{r['models_lib_sha256']}`, remote {json.dumps(r['remote'], sort_keys=True)}")
    lines += [
        f"- Raw logs: `corners/{rid}/<request>.log.gz`; frozen plan, DUT, bodies, requests and reports: "
        f"`netlist-snapshots/{rid}/`; complete sweeps (every point, both kinds, all variants): `records/{rid}-sweeps.json.gz`. "
        "Re-derive every verdict with `python3 sim/lna-linearity/run.py verify`.",
        "",
    ]
    return "\n".join(lines)


def collect(args) -> int:
    plan = L.load_plan(PLAN_PATH)
    probs = plan_problems(plan)
    if probs:
        print("\n".join(probs), file=sys.stderr)
        return 1
    dirty = dirty_code()
    if dirty and not args.dry_run and not args.allow_dirty:
        print("refusing to collect with uncommitted changes in sim/lna-linearity or the DUT (the plan and code must be "
              "committed before the collection):\n" + "\n".join(dirty), file=sys.stderr)
        return 1
    pyc = python_controls(plan)
    if not pyc["pass"]:
        print("python controls failed; no collection", file=sys.stderr)
        return 1
    started = _dt.datetime.now(_dt.timezone.utc)
    work = Path(args.workdir or SCRATCH / f"klt-{started.strftime('%Y%m%d-%H%M%S')}").resolve()
    work.mkdir(parents=True, exist_ok=True)
    reqs = write_requests(plan, work, args.backend, args)
    if args.dry_run:
        print(f"--dry-run: {len(reqs)} requests written under {work}; nothing submitted")
        return 0
    pdk = klt_driver.find_pdk_or_exit(SIM_DIR, require_artifact=True)
    texts, reports = {}, {}
    try:
        for key, req in reqs.items():
            rep = submit(key, req, work, args.backend, args)
            data, text = read_unit(rep)
            texts[key] = text
            reports[key] = data
    except CollectionError as exc:
        print(f"collect: {exc}\ncollect: NO record written, no local fallback. Requests/bodies kept under {work}", file=sys.stderr)
        return 1
    return finalize(plan, work, reqs, texts, reports, pyc, pdk, started, args)


def finalize(plan, work, reqs, texts, reports, pyc, pdk, started, args) -> int:
    res = A.analyze(plan, texts)
    if res["problems"]:
        for p in res["problems"][:40]:
            print("FAIL:", p, file=sys.stderr)
        print("collect: log integrity gate failed; NO record written", file=sys.stderr)
        return 1
    git = git_provenance(REPO_ROOT)
    git["dirty"] = bool(dirty_code())
    rid = allocate_record_id(REPO_ROOT, RECORDS, git=git)
    status = "COLLECTED" if res["ngspice_control"]["pass"] else "CONTROLS_FAILED"
    client = subprocess.run(shlex.split(args.klt_cmd) + ["--version"], capture_output=True, text=True)
    requests = []
    for key in A.request_keys(plan):
        d = reports[key]
        env = d.get("environment") or {}
        requests.append({"key": key, "backend": args.backend, "status": d.get("status"), "engine": env.get("engine"),
                         "engine_version": env.get("engine_version"), "models_lib_sha256": env.get("models_lib_sha256"),
                         "netlist_sha256": env.get("netlist_sha256"), "remote": env.get("remote"),
                         "klt_version": (d.get("provenance") or {}).get("klt_version")})
    sweeps = {n: p.pop("sweeps") for n, p in res["placements"].items()}
    rec = {
        "record_id": rid, "status": status, "scope": SCOPE, "started_utc": started.isoformat(),
        "spec_rows_claimed_met": [],
        "plan": plan_provenance(), "plan_declaration": plan, "dut": dut_identity(),
        "python_controls": pyc, "controls": res["ngspice_control"], "placements": res["placements"], "rows": res["rows"],
        "klt_requests": requests, "sweeps_file": f"{rid}-sweeps.json.gz",
        "environment": {"git": git, "klt_client": (client.stdout or client.stderr).strip(),
                        "pdk_artifact_sha256": sha256_file(SIM_DIR / "pdk-artifact.json"),
                        "pdk": klt_driver.pdk_provenance(pdk, MODEL_FILES),
                        "host_ngspice": subprocess.run(["ngspice", "--version"], capture_output=True, text=True).stdout.splitlines()[1:2]},
    }
    # verify before writing: the published verdicts must reproduce from the raw logs
    check = A.analyze(plan, texts)
    for n, p in check["placements"].items():
        p.pop("sweeps")
    if json.loads(json.dumps(A_roundtrip(check["placements"]))) != json.loads(json.dumps(A_roundtrip(res["placements"]))):
        raise CollectionError("analysis is not deterministic")
    for d in (RECORDS, LOGS / rid, SNAPS / rid):
        d.mkdir(parents=True, exist_ok=True)
    published = A_roundtrip({k: v for k, v in rec.items() if k != "plan_declaration"})
    published["plan_declaration"] = rec["plan_declaration"]  # verbatim: must equal the frozen plan.json
    (RECORDS / f"{rid}.json").write_text(json.dumps(published, indent=2) + "\n")
    with gzip.open(RECORDS / f"{rid}-sweeps.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(A_roundtrip(sweeps), fh)
    for key, text in texts.items():
        with gzip.open(LOGS / rid / f"{key}.log.gz", "wt", encoding="utf-8") as fh:
            fh.write(text)
    snap = SNAPS / rid
    (snap / "plan.json").write_bytes(PLAN_PATH.read_bytes())
    (snap / "lna_stage1.spice").write_bytes(DUT_PATH.read_bytes())
    for key in reqs:
        for stem in ("body_{}.spice", "request_{}.json", "report_{}.json"):
            (snap / stem.format(key)).write_bytes((work / stem.format(key)).read_bytes())
    (RECORDS / f"{rid}.md").write_text(render_md(rid, status, json.loads((RECORDS / f"{rid}.json").read_text())))
    print(f"record {rid}: {status}")
    for row, r in res["rows"].items():
        print(f"  row {row}: worst verdict {r['worst_verdict']}; " + ", ".join(f"{n}: {v['status']}/{v['verdict']}" for n, v in r["per_placement"].items()))
    return 0


def A_roundtrip(x):
    return A._round(x)


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def verify_record(rid: str) -> list[str]:
    plan = json.loads((SNAPS / rid / "plan.json").read_text())
    rec = json.loads((RECORDS / f"{rid}.json").read_text())
    texts = {}
    for key in A.request_keys(plan):
        with gzip.open(LOGS / rid / f"{key}.log.gz", "rt", encoding="utf-8") as fh:
            texts[key] = fh.read()
    res = A.analyze(plan, texts)
    if res["problems"]:
        return res["problems"]
    with gzip.open(RECORDS / rec["sweeps_file"], "rt", encoding="utf-8") as fh:
        stored_sweeps = json.load(fh)
    sweeps = {n: p.pop("sweeps") for n, p in res["placements"].items()}
    out = []
    if json.loads(json.dumps(A_roundtrip(res["placements"]))) != rec["placements"]:
        out.append("placements (fits, convergence, verdicts) do not reproduce from the frozen logs")
    if json.loads(json.dumps(A_roundtrip(sweeps))) != stored_sweeps:
        out.append("stored sweeps do not reproduce from the frozen logs")
    if json.loads(json.dumps(A_roundtrip(res["rows"]))) != rec["rows"]:
        out.append("row verdicts do not reproduce")
    if json.loads(json.dumps(A_roundtrip(res["ngspice_control"]))) != rec["controls"]:
        out.append("ngspice control does not reproduce")
    status = "COLLECTED" if res["ngspice_control"]["pass"] else "CONTROLS_FAILED"
    if rec["status"] != status:
        out.append(f"status {rec['status']} != {status}")
    dut_text = (SNAPS / rid / "lna_stage1.spice").read_text()
    for key in A.request_keys(plan):
        frozen = (SNAPS / rid / f"body_{key}.spice").read_text()
        if frozen != body_for_key(plan, key, dut_text):
            out.append(f"frozen body_{key}.spice does not regenerate from the frozen plan and DUT")
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
    return 1 if bad else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-plan").set_defaults(fn=cmd_check_plan)
    sub.add_parser("controls").set_defaults(fn=cmd_controls)
    for name, fn in (("build", cmd_build), ("collect", collect)):
        p = sub.add_parser(name)
        p.add_argument("--klt-cmd", default="klt")
        p.add_argument("--backend", default="batch", help="explicit backend for every request (default: batch)")
        p.add_argument("--timeout-s", type=int, default=7200)
        p.add_argument("--no-stage-models", action="store_true")
        p.add_argument("--runner-version-check", default="", choices=("", "enforce", "warn"))
        p.add_argument("--workdir", default="")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--allow-dirty", action="store_true", help=argparse.SUPPRESS)
        p.set_defaults(fn=fn)
    v = sub.add_parser("verify")
    v.add_argument("records", nargs="*")
    v.set_defaults(fn=cmd_verify)
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
