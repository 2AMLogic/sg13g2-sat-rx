#!/usr/bin/env python3
"""Monte Carlo mismatch-card method probe for a matched npn13G2 pair (issue 186).

    python3 sim/hbt-mismatch-pair/run_probe.py --no-write
                                            # all legs, print only
    python3 sim/hbt-mismatch-pair/run_probe.py
                                            # all legs, write a record
    python3 sim/hbt-mismatch-pair/run_probe.py --skip-rerun --skip-local --no-write
                                            # primary fleet leg only
    python3 sim/hbt-mismatch-pair/run_probe.py --reparse probe-logs/<id>
                                            # re-derive the status from committed
                                            # reports (no simulator, no submit)
    python3 sim/hbt-mismatch-pair/run_probe.py --sabotage stat_noise --reparse probe-logs/<id>
                                            # negative control: classification MUST
                                            # degrade (never writes a record)

Legs (in order; each reuses its report when it already exists, so an
interrupted probe resumes):

  mc      the primary Monte Carlo request (``monte_carlo: {n, seed, vary}``
          over hbt_typ_mismatch / hbt_typ_stat / hbt_typ at 27 C) on the
          explicit backend (default batch -- the shared fleet path; a failed
          submit records nothing and never falls back to a local grid).
  rerun   the same request bytes a second time: fixed-seed reproducibility.
  local   the same corners, same order, n=1 on the local backend: the
          local-vs-batch agreement unit (same seed schedule -- klt derives
          sample seeds from the request, so unit 0 of each corner is the
          same draw fleet-side and locally).

Known-answer gates (see mcpair.py): the nominal corner must be exactly
symmetric (ratio 1, offset 0); the stat corner must CANCEL in the matched
pair (its gauss() draws are global -- one value per run shared by both
instances) while its absolute currents still move; only the mismatch corner
(per-instance agauss area) may spread the ratio. A fixed-seed rerun must
reproduce the primary leg per sample; the local unit must agree with the
fleet unit drawn from the same seed, and the record states the agreement as
a number.

Writes, append-only (exclusive create; an existing record is never touched):
  probe-logs/<id>/pair_body.spice     the netlist exactly as submitted
  probe-logs/<id>/request_mc.json     the primary request (n x corners)
  probe-logs/<id>/request_local.json  the local agreement request (n=1)
  probe-logs/<id>/report_{mc,rerun,local}.json
  probe-logs/<id>/logs/               sample 0-2 logs per corner (each leg)
                                      and every local log
  probe-logs/<id>/stats.json          the gate/distribution findings
  records/<id>-<STATUS>.md/.json      the record

Exit status: 0 when a record (any status) was produced or --no-write printed;
1 on an ingestion/parse defect or an unavailable klt; 2 when a sabotaged
control unexpectedly PASSES; 3 when a klt submit failed (nothing recorded --
per host rules a failed batch submit is reported, not retried locally).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO = SIM_DIR.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SIM_DIR))

import mcpair as M  # noqa: E402
from harness.provenance import (  # noqa: E402
    git_info,
    new_record_id,
    pdk_integrity as _pdk_integrity,
    sha256_file,
    write_excl,
)

BODY = HERE / "bench" / "pair_body.spice"
PROBE_LOGS = HERE / "probe-logs"
RECORDS = HERE / "records"
BENCH = M.BENCH


# ---------------------------------------------------------------------------
# klt plumbing (thin; every decision lives in mcpair)
# ---------------------------------------------------------------------------


def klt_version(klt_cmd: str) -> str:
    try:
        proc = subprocess.run(shlex.split(klt_cmd) + ["--version"], capture_output=True,
                              text=True, check=False)
    except OSError as exc:
        return f"unavailable ({exc})"
    return (proc.stdout or proc.stderr).strip() or "unknown"


def run_leg(req_path: Path, out_dir: Path, report_path: Path, backend: str,
            klt_cmd: str, env_extra: dict[str, str] | None = None) -> dict:
    """One ``klt sim`` submission; returns the report dict.

    A non-zero exit or a report without a corners list raises SystemExit(3):
    there is no local fallback, and nothing is recorded from a failed submit
    (host rules; the error text lands in the raised message for the caller
    to report). An existing complete report is reused (resume).
    """
    if report_path.is_file():
        try:
            data = json.loads(report_path.read_text())
            if isinstance(data, dict) and data.get("corners"):
                print(f"  reuse {report_path.name}", flush=True)
                return data
        except ValueError:
            pass
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = shlex.split(klt_cmd) + ["sim", str(req_path), "--backend", backend,
                                  "-o", str(out_dir), "--format", "json"]
    print("$ " + " ".join(cmd), flush=True)
    env = {**os.environ, **(env_extra or {})}
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    if proc.stdout.strip():
        (out_dir / "klt_stdout.txt").write_text(proc.stdout)
    if proc.stderr.strip():
        (out_dir / "klt_stderr.txt").write_text(proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(
            f"3\nklt sim failed (exit {proc.returncode}, backend {backend}): "
            f"{proc.stderr.strip()[-3000:] or 'no stderr'}\n"
            "nothing recorded -- report this error; do NOT rerun the grid locally")
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        raise SystemExit(f"3\nklt sim printed no JSON report (backend {backend}); "
                         f"stdout head: {proc.stdout.strip()[:500]!r}")
    if not isinstance(data, dict) or not isinstance(data.get("corners"), list):
        raise SystemExit(f"3\nklt sim report carries no corners list (backend {backend}); "
                         f"error={data.get('error')!r}")
    report_path.write_text(json.dumps(data, indent=2) + "\n")
    return data


def report_environment(report: dict) -> dict:
    env = report.get("environment") if isinstance(report.get("environment"), dict) else {}
    remote = env.get("remote") if isinstance(env.get("remote"), dict) else {}
    return {
        "engine": env.get("engine"),
        "engine_version": env.get("engine_version"),
        "status": report.get("status"),
        "job_id": remote.get("job_id"),
        "provider": remote.get("provider"),
        "instance_type": remote.get("instance_type"),
        "runner_klt_version": remote.get("runner_klt_version"),
        "client_klt_version": remote.get("client_klt_version"),
        "runner_compatibility": remote.get("runner_compatibility"),
        "monte_carlo": env.get("monte_carlo"),
    }


def keep_logs(report: dict, out_dir: Path, dest: Path, tag: str, limit: int = 3) -> list[str]:
    """Copy the first ``limit`` per-unit logs of every corner into ``dest``."""
    dest.mkdir(parents=True, exist_ok=True)
    kept = []
    corners = report.get("corners") or []
    seen: dict[str, int] = {}
    for corner in corners:
        proc = str(corner.get("process"))
        n = seen.get(proc, 0)
        log = (corner.get("artifacts") or {}).get("log")
        if log and n < limit:
            src = Path(log)
            if not src.is_absolute():
                src = (out_dir / src).resolve()
            if src.is_file():
                idx = (corner.get("monte_carlo") or {}).get("sample_index")
                d = dest / f"{tag}__{proc}__mc{idx}.log"
                shutil.copyfile(src, d)
                kept.append(d.name)
        seen[proc] = n + 1
    return kept


def pdk_integrity() -> dict:
    """Model-artifact gate BEFORE any submit. The gate does NOT require the
    pinned local ngspice: the fleet leg runs the runner image's engine and the
    local agreement leg is deliberately cross-build (the #165 precedent) --
    both engine majors are stated in the record instead."""
    return _pdk_integrity(SIM_DIR, require_ngspice=False)


# ---------------------------------------------------------------------------
# record rendering
# ---------------------------------------------------------------------------

_CARDS = [
    ("sg13g2_hbt_mod_mismatch.lib", "per-instance local mismatch",
     "`agauss(1, 0.1, (mm_ok != 1 ? 0 : 1))` -- independent Gaussian per device instance, "
     "mean 1, 10% 1-sigma, on the VBIC instance `area` (`qarea`); `mm_ok=1` in this card "
     "enables the draw",
     "device area (scales is, ikf/ikr, cje/cjc/cjcp, re/rcx/rbx/rbi, itf, cth, rth, ...)",
     "`hbt_typ_mismatch` / `hbt_bcs_mismatch` / `hbt_wcs_mismatch`"),
    ("sg13g2_hbt_stat.lib", "global process variation",
     "`gauss(<norm>, <rel sigma>, num_sigmas=1)` -- ONE draw per run at file scope, shared "
     "by every instance of the run (perfectly correlated across devices)",
     "vbic_cje 5.8%, vbic_cjc 4.3%, vbic_cjcp 3.7%, vbic_is 8.7%, vbic_ibei 11%, "
     "vbic_re 9%, vbic_rcx 6.9%, vbic_rbx 4.1%; pnpMPA: sgp_mpa_cje 1.5%, cjc 0.7%, "
     "is 4.3%, bf 7.9%, re 1.6%, rb 0.8%, rc 1.7%; vbic_tf commented OUT",
     "`hbt_typ_stat` (+ nominal `sg13g2_hbt_mod.lib`, which has NO mm_ok/area draw)"),
]


def render_cards_md() -> list[str]:
    lines = [
        "## Cards read (what varies, and its distribution form)",
        "",
        "Both cards read in full from the pinned install (hashes under Provenance); the corner",
        "sections live in `cornerHBT.lib` (`hbt_typ_mismatch`, `hbt_typ_stat`).",
        "",
        "| card | mechanism | distribution form | what varies | corner sections |",
        "|---|---|---|---|---|",
    ]
    for card, mech, form, params, sections in _CARDS:
        lines.append(f"| `{card}` | {mech} | {form} | {params} | {sections} |")
    lines += [
        "",
        "Consequences this probe verifies empirically:",
        "",
        "- `hbt_typ_stat` cannot spread a matched pair: its draws are per-RUN, not per-instance,",
        "  so both devices move together -- the ratio must stay 1 while the absolute currents move.",
        "- `hbt_typ_mismatch` only moves device area (no global axis): its ratio spread is the",
        "  per-instance observable, of order 10%*sqrt(2) ~ 14% 1-sigma at fixed-Vbe drive.",
        "- Neither card references klt's `mc_process_seed`/`mc_mismatch_seed` params: with these",
        "  cards the per-sample randomness is ngspice's ONE RNG stream (`.options seed=`), so",
        "  klt's `vary:` axis separation cannot decorrelate card draws -- only its seed",
        "  bookkeeping reports per-axis seeds. Recorded as a method note, not a bench defect.",
    ]
    return lines


def fmt_g(x) -> str:
    return f"{float(x):.6g}"


def render_record(rid_status: str, status: str, ev: dict, args, provenance: dict) -> tuple[str, dict]:
    f = ev["findings"]
    d = f["distributions"]
    g = f["gates"]
    md = [f"# {BENCH} record {rid_status}", ""]
    md.append(f"- **Status: {status}**")
    md.append("- **Scope: METHOD only.** This record qualifies the `klt sim monte_carlo` method on "
              "the pinned PDK with a known-answer matched pair. It is NOT evidence for "
              "`spec/target-spec.md` row 15 (LO leakage) or any other row; `spec/row-coverage.json` "
              "row 15 keeps its verdict and cites this bench as a note only. The pair is a method "
              "observable, not a mixer, and no number here is a design figure.")
    md.append(f"- Request: `monte_carlo {{n: {args.n}, seed: {args.seed}, vary: {M.MC_VARY!r}}}` over "
              f"`{', '.join(M.CORNERS)}` at {M.TEMPERATURE_C} C; primary backend `{args.backend}`; "
              f"body sha256 `{provenance['body_sha256']}`.")
    md.append("")

    md += render_cards_md()
    md.append("")

    md.append("## Result")
    md.append("")
    if d:
        md.append("| corner | units | mean m_ratio | sigma m_ratio | max abs(m_ratio-1) | mean m_off (V) | sigma m_off (V) | mean m_ic1 (A) |")
        md.append("|---|---|---|---|---|---|---|---|")
        for corner, label in (("hbt_typ_mismatch", "mismatch (per-instance)"),
                              ("hbt_typ_stat", "stat (global)"),
                              ("hbt_typ", "nominal")):
            c = d.get(corner) or {}
            r = c.get("m_ratio")
            if not r:
                continue
            o = c.get("m_off")
            ic1 = c.get("m_ic1")
            md.append(f"| {label} | {r['n']} | {fmt_g(r['mean'])} | {fmt_g(r['sigma'])} | "
                      f"{fmt_g((g.get('max_abs_ratio_dev') or {}).get(corner, float('nan')))} | "
                      f"{fmt_g(o['mean']) if o else '-'} | {fmt_g(o['sigma']) if o else '-'} | "
                      f"{fmt_g(ic1['mean']) if ic1 else '-'} |")
    else:
        md.append(f"(no distributions -- {ev.get('reason')})")
    md.append("")

    md.append("## Gates")
    md.append("")
    for k, v in g.items():
        md.append(f"- {k}: `{json.dumps(v, sort_keys=True)}`")
    for note in f["notes"]:
        md.append(f"- Note: {note}")
    md.append("")

    md.append("## Seed handling and reproducibility")
    md.append("")
    md.append(f"- klt derives each sample's seeds from the request (`seed {args.seed}`, per-axis "
              "seeds keyed on corner_index/sample_index) and seeds ngspice with "
              "`.options seed=<rndseed>` BEFORE the model cards parse; every returned unit echoes "
              "its `monte_carlo` seed block. The derived-seed schedule is version-stable between "
              "the client and the fleet runner (klt 0.5.0 and 0.7.0 carry the same "
              "`_derive_mc_seed`; diffed across the two tag tarballs before this run).")
    if g.get("reproducibility_max_rel") is not None:
        verdict = "REPRODUCES" if g["reproducibility_max_rel"] <= M.REPRO_TOL else "FAILS"
        md.append(f"- Fixed-seed rerun (same request bytes, second fleet submit): per-sample max "
                  f"rel difference {fmt_g(g['reproducibility_max_rel'])} "
                  f"(gate {M.REPRO_TOL:.0e}) -> **{verdict}**.")
    else:
        md.append("- Fixed-seed rerun: skipped by flag; NOT shown by this record.")
    md.append("")

    md.append("## Local vs batch")
    md.append("")
    if g.get("local_vs_batch_max_rel") is not None:
        verdict = "AGREE" if g["local_vs_batch_max_rel"] <= M.LOCAL_AGREEMENT_TOL else "DISAGREE"
        md.append(f"- Sample-0 unit of the same seed schedule, local backend vs fleet: per-observable "
                  f"max rel difference {fmt_g(g['local_vs_batch_max_rel'])} "
                  f"(gate {M.LOCAL_AGREEMENT_TOL:.0e}) -> **{verdict}**.")
        md.append(f"- Per corner: `{json.dumps(g.get('local_vs_batch_per_corner_rel'), sort_keys=True)}`")
        md.append("- Cross-build by construction: the local unit runs this host's ngspice, the fleet "
                  "unit runs the runner image's engine (both versions under Provenance) -- the same "
                  "shape of backend-agreement number the iip3 benches record (#135, #181).")
    else:
        md.append("- Local agreement leg skipped by flag; NOT shown by this record.")
    md.append("")

    md.append("## Provenance")
    md.append("")
    rid = rid_status.rsplit("-", 1)[0]
    md.append(f"- Probe logs: `probe-logs/{rid}/` (body, requests, klt reports, per-sample values, kept logs)")
    for line in provenance["lines"]:
        md.append(f"- {line}")
    md.append(f"- Command: `python3 sim/{BENCH}/run_probe.py "
              + " ".join(provenance["cmd_args"]) + "`")
    md.append("")

    record_json = {
        "bench": BENCH,
        "record": rid_status,
        "status": status,
        "scope": "method-only; no spec-row evidence",
        "request": {"n": args.n, "seed": args.seed, "vary": M.MC_VARY,
                    "corners": list(M.CORNERS), "temperature_c": M.TEMPERATURE_C,
                    "backend": args.backend},
        "gates": g,
        "distributions": d,
        "notes": f["notes"],
        "reason": ev.get("reason"),
        "provenance": provenance["structured"],
    }
    return "\n".join(md) + "\n", record_json


def collect_provenance(args, reports: dict, run_dir: Path | None) -> dict:
    integ = pdk_integrity()
    structured: dict = {"pdk_integrity": integ, "legs": {}, "klt_client_cmd": args.klt_cmd,
                        "git": git_info(REPO), "host": platform.node(),
                        "run_dir": str(run_dir) if run_dir else None}
    lines = [
        "Model integrity gate (`sim/harness/pdkartifact.py`, before any submit): "
        f"{'OK' if integ['ok'] else 'FAILED ' + str(integ['problems'])}; local install models "
        f"hash-verified against the pin; notes {integ['notes']}",
    ]
    for leg, report in reports.items():
        e = report_environment(report)
        structured["legs"][leg] = e
        engine = e.get("engine_version") or "unknown"
        job = f", job {e.get('job_id')}" if e.get("job_id") else ""
        lines.append(f"{leg}: engine {e.get('engine')}/{engine}{job}, status {e.get('status')}, "
                     f"runner klt {e.get('runner_klt_version')}, client klt "
                     f"{e.get('client_klt_version')}, runner_compatibility "
                     f"{e.get('runner_compatibility')}")
    return {"lines": lines, "structured": structured,
            "body_sha256": sha256_file(BODY),
            "cmd_args": ["--n", str(args.n), "--seed", str(args.seed),
                         *(["--skip-rerun"] if args.skip_rerun else []),
                         *(["--skip-local"] if args.skip_local else []),
                         *(["--no-write"] if args.no_write else [])]}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def ingest_leg(report: dict, *, expected_n: int, label: str, samples_path: Path,
               out_dir: Path) -> dict[str, list[dict]]:
    """Report -> per-corner units with the m_* observables parsed from the logs.

    The compact per-sample values are also written to ``samples_path`` -- the
    committed artifact ``--reparse`` reads back, so the full distribution
    stays auditable without committing every raw log.
    """
    legs = M.samples_from_report(report, expected_n=expected_n, label=label)

    def read_log(u):
        log = u.get("log")
        if not log:
            return None
        p = Path(log)
        if not p.is_absolute():
            p = (out_dir / p).resolve()
        return p.read_text() if p.is_file() else None

    M.attach_log_measurements(legs, read_text=read_log)
    payload = {"leg": label, "n": expected_n,
               "corners": {name: [{k: u[k] for k in ("corner_id", "process", "status",
                                                     "sample_index", "seeds",
                                                     "measurements", "diagnostics")}
                                   for u in units]
                           for name, units in legs.items()}}
    samples_path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    return legs


def legs_from_samples_file(path: Path) -> dict[str, list[dict]]:
    """`--reparse` source: the compact per-sample JSON a live leg wrote."""
    data = json.loads(path.read_text())
    corners = data.get("corners") if isinstance(data, dict) else None
    if not isinstance(corners, dict) or set(corners) != set(M.CORNERS):
        raise SystemExit(f"1\n{path}: samples.json must carry exactly {list(M.CORNERS)}")
    out = {}
    for name, units in corners.items():
        for i, u in enumerate(units):
            u.setdefault("where", f"{path.name}:{name}[{i}]")
            u.setdefault("runtime_s", None)
            u.setdefault("log", None)
        out[name] = units
    return out


def load_run_dir(run_dir: Path) -> tuple[dict[str, list[dict]], int]:
    """(legs by name, n) from a committed probe-logs dir (samples.json files)."""
    legs = {}
    n = None
    for name in ("mc", "rerun", "local"):
        p = run_dir / f"samples_{name}.json"
        if p.is_file():
            legs[name] = legs_from_samples_file(p)
    req = run_dir / "request_mc.json"
    if not req.is_file():
        raise SystemExit(f"1\n{run_dir}: no request_mc.json to reparse")
    mc = (json.loads(req.read_text()).get("monte_carlo") or {})
    n = mc.get("n")
    if not isinstance(n, int) or n < 1:
        raise SystemExit(f"1\n{run_dir}: request_mc.json has no usable monte_carlo.n")
    if "mc" not in legs:
        raise SystemExit(f"1\n{run_dir}: no samples_mc.json to reparse")
    return legs, n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=M.N_DEFAULT)
    ap.add_argument("--seed", type=int, default=M.SEED_DEFAULT)
    ap.add_argument("--timeout-s", type=int, default=1800)
    ap.add_argument("--backend", default="batch")
    ap.add_argument("--local-backend", default="local")
    ap.add_argument("--klt-cmd", default="klt")
    ap.add_argument("--skip-rerun", action="store_true")
    ap.add_argument("--skip-local", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--reparse", default="")
    ap.add_argument("--sabotage", default="", choices=("", "stat_noise", "mismatch_flat"))
    args = ap.parse_args(argv)

    if args.sabotage and not args.reparse:
        print("--sabotage works on a committed run dir: pass --reparse probe-logs/<id>",
              file=sys.stderr)
        return 1

    if args.reparse:
        legs, n = load_run_dir(Path(args.reparse))
        if args.sabotage:
            sabotaged = M.sabotage(legs["mc"], args.sabotage)
            degraded = sabotaged["status"] != "MC_METHOD_WORKS"
            print(f"sabotage {args.sabotage}: status {sabotaged['status']} "
                  f"({'degraded as expected' if degraded else 'UNEXPECTEDLY STILL WORKS'})")
            return 0 if degraded else 2
        ev = M.evaluate(batch=legs["mc"],
                        rerun=legs.get("rerun"),
                        local=legs.get("local"))
        print(f"[reparse] status {ev['status']}")
        print(json.dumps(ev["findings"], indent=2, sort_keys=True))
        return 0

    # ---- live legs ---------------------------------------------------------
    klt_v = klt_version(args.klt_cmd)
    print(f"klt client: {klt_v}", flush=True)
    if klt_v.startswith("unavailable"):
        print(f"status CAPABILITY_UNAVAILABLE: {klt_v}", file=sys.stderr)
        return 1
    if not BODY.is_file():
        raise SystemExit(f"1\nmissing {BODY}")

    PROBE_LOGS.mkdir(parents=True, exist_ok=True)
    git = git_info(REPO)
    rid = new_record_id((git.get("commit") or "unknown")[:7], RECORDS, PROBE_LOGS)
    run_dir = PROBE_LOGS / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BODY, run_dir / BODY.name)
    req = M.build_request(BODY.name, n=args.n, seed=args.seed, backend=args.backend,
                          timeout_s=args.timeout_s)
    req_local = M.build_request(BODY.name, n=1, seed=args.seed, backend=args.local_backend,
                                timeout_s=args.timeout_s)
    (run_dir / "request_mc.json").write_text(json.dumps(req, indent=2) + "\n")
    (run_dir / "request_local.json").write_text(json.dumps(req_local, indent=2) + "\n")

    reports: dict[str, dict] = {}
    try:
        print(f"leg mc: n={args.n} x {len(M.CORNERS)} corners on {args.backend}", flush=True)
        reports["mc"] = run_leg(run_dir / "request_mc.json", run_dir / "out_mc",
                                run_dir / "report_mc.json", args.backend, args.klt_cmd)
        if not args.skip_rerun:
            print("leg rerun: same request bytes, second submit", flush=True)
            reports["rerun"] = run_leg(run_dir / "request_mc.json", run_dir / "out_rerun",
                                       run_dir / "report_rerun.json", args.backend, args.klt_cmd)
        if not args.skip_local:
            print(f"leg local: n=1 on {args.local_backend}", flush=True)
            # The local backend resolves `models.pdk` on THIS host: point klt's
            # PDK_ROOT/PDK env at the same verified install the harness gate
            # just checked (resolved at runtime; the record's provenance
            # carries the path).
            from harness.pdk import find_pdk
            pdk = find_pdk(SIM_DIR)
            reports["local"] = run_leg(run_dir / "request_local.json", run_dir / "out_local",
                                       run_dir / "report_local.json", args.local_backend,
                                       args.klt_cmd,
                                       env_extra={"PDK_ROOT": str(pdk.path.parent),
                                                  "PDK": pdk.path.name})
    except SystemExit as exc:
        # A failed submit: print the message, keep the run dir for inspection,
        # record nothing.
        print(str(exc), file=sys.stderr)
        return 3

    legs: dict[str, list] = {}
    expected = {"mc": args.n, "rerun": args.n, "local": 1}
    try:
        for name, report in reports.items():
            legs[name] = ingest_leg(report, expected_n=expected[name], label=name,
                                    samples_path=run_dir / f"samples_{name}.json",
                                    out_dir=run_dir / f"out_{name}")
    except M.ReportError as exc:
        # Keep what came back under the run dir for inspection; record nothing
        # from a leg that cannot be fully parsed.
        (run_dir / "ingest_error.txt").write_text(str(exc) + "\n")
        print(f"ingest failed; nothing recorded: {exc}", file=sys.stderr)
        return 1

    ev = M.evaluate(batch=legs["mc"], rerun=legs.get("rerun"), local=legs.get("local"))
    status = ev["status"]
    print(f"status {status}")

    keep_logs(reports["mc"], run_dir / "out_mc", run_dir / "logs", "mc")
    if "rerun" in reports:
        keep_logs(reports["rerun"], run_dir / "out_rerun", run_dir / "logs", "rerun")
    if "local" in reports:
        keep_logs(reports["local"], run_dir / "out_local", run_dir / "logs", "local", limit=1)
    (run_dir / "stats.json").write_text(json.dumps(ev["findings"], indent=2, sort_keys=True) + "\n")

    if args.no_write:
        print(json.dumps(ev, indent=2, sort_keys=True))
        shutil.rmtree(run_dir, ignore_errors=True)
        return 0

    prov = collect_provenance(args, reports, run_dir)
    rid_status = f"{rid}-{status}"
    md, rj = render_record(rid_status, status, ev, args, prov)
    md_path = RECORDS / f"{rid_status}.md"
    write_excl(md_path, md)
    write_excl(RECORDS / f"{rid_status}.json", json.dumps(rj, indent=2, sort_keys=True) + "\n")
    print(f"record: {md_path}")
    print(f"logs:   {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
