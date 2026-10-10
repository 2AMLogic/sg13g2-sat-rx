"""Collection half of the mixer-core topology feasibility study (issue #35).

Turns the declared study into ``klt sim`` requests, ingests the per-corner
logs they return, applies the acceptance gate (``mixfeas.validate_collection``)
and, only if the whole collection passes, writes one append-only record.

Stages (each stage's drive depends on the previous stage's selection):

1. ``lo_select`` -- per candidate, ONE klt request with ONE corner
   (hbt_typ / 27 C / 2.25 V; the declared reduction): 3 bands x 13 LO drives
   x RF {-60, -66} dBm.
2. selection -- ``mixfeas.select_lo_drive`` per candidate.
3. For every candidate with a selected drive:
   ``iip3`` (one corner, two-tone power sweep at the selected drive),
   ``main`` (per supply: 3 process x 3 temperature corners, RF -60 dBm) and
   ``leakage`` (per supply: 3 mismatch process x 3 temperature corners,
   RF off, fixed seed).
   Candidates without a selected drive get explicit
   ``not_applicable_no_drive`` cells; no trial-drive number is promoted to
   a main/leakage/IIP3 result.

Multi-unit requests (stage 3) are submitted with the caller's backend
(default ``batch``). Each request's backend and unit count is recorded and
the record's data-provenance text is derived from them
(``execution_provenance``): a record never claims an off-host or multi-unit
run that was not submitted. Nothing is ever simulated locally except what klt itself
keeps local (single-unit requests) and the one-corner convergence /
cross-check controls (``run.py``-style local runs, one process at a time).

A klt failure, a missing/duplicate log, an unparseable run or a gate failure
exits non-zero WITHOUT writing a record.
"""

from __future__ import annotations

import csv  # noqa: F401  (kept for sidecar tables)
import datetime as _dt
import gzip
import json
import math
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
SIM_DIR = BENCH_DIR.parent
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(BENCH_DIR))

import mixfeas as mf  # noqa: E402
from harness import klt_driver  # noqa: E402
from harness.report import RecordExists, allocate_record_id, git_provenance  # noqa: E402

TB_DIR = BENCH_DIR / "testbench"
SCRATCH = BENCH_DIR / "_build"
RECORDS = BENCH_DIR / "records"
CORNER_LOGS = BENCH_DIR / "corners"
SNAPSHOTS = BENCH_DIR / "netlist-snapshots"
MODEL_FILES = ("cornerHBT.lib", "sg13g2_hbt_mod.lib", "sg13g2_hbt_mod_mismatch.lib")

#: Agreement required of the cross-check between the collected (klt body
#: path) cells and the local harness path. Same deck, same models, same
#: simulator version should agree to rounding.
CROSSCHECK_TOL_DB = 1e-3

#: Stage names as the record states them.
STAGE_LABELS = {1: "Stage 1 (LO-selection sweep)", 2: "Stage 2 (IIP3 / main / leakage at the selected drive)"}


def is_local_backend(backend: str) -> bool:
    """klt backends that run on this host (``local``, ``local-parallel``).
    Anything else (``batch``) is off-host."""
    return str(backend).startswith("local")


class CollectionError(RuntimeError):
    """The collection is corrupt/incomplete: exit non-zero, write nothing."""


# ---------------------------------------------------------------------------
# Run lists per stage (shared by request generation and ingest)
# ---------------------------------------------------------------------------


def _tag(x: float) -> str:
    return f"{x:+g}".replace("+", "p").replace("-", "m").replace(".", "_")


def make_run(study, run_id, kind, band, vlo_dbm, rf_dbm) -> mf.RunSpec:
    t = study.timing
    window = t.window_two_tone_s if kind == "two_tone" else t.window_single_s
    return mf.RunSpec(run_id=run_id, kind=kind, band=band, vlo_dbm=vlo_dbm,
                      rf_dbm=None if kind == "rfoff" else rf_dbm, window_s=window, settle_s=t.settle_s,
                      tmax_s=t.tmax_s, tstep_s=t.tstep_s, if_hz=study.if_hz)


def stage_runs(study, matrix: str, drive_dbm: float | None = None) -> dict[str, mf.RunSpec]:
    """Run id -> RunSpec for one matrix's deck (every unit of the request
    runs this same list)."""
    m = study.matrices[matrix]
    runs: dict[str, mf.RunSpec] = {}
    for bname in m.bands:
        band = study.band(bname)
        if matrix == "lo_select":
            for d in study.lo_sweep_dbm:
                for tag, rf in (("rf60", study.rf_dbm), ("rf66", study.rf_check_dbm)):
                    rid = f"ls_{bname}_{_tag(d)}_{tag}"
                    runs[rid] = make_run(study, rid, "single", band, d, rf)
        elif matrix == "iip3":
            for p in study.iip3_pin_dbm:
                rid = f"ip_{bname}_{_tag(p)}"
                runs[rid] = make_run(study, rid, "two_tone", band, drive_dbm, p)
        elif matrix == "main":
            rid = f"mn_{bname}"
            runs[rid] = make_run(study, rid, "single", band, drive_dbm, study.rf_dbm)
        elif matrix == "leakage":
            rid = f"lk_{bname}"
            runs[rid] = make_run(study, rid, "rfoff", band, drive_dbm, None)
        else:
            raise ValueError(f"no run list for matrix {matrix!r}")
    return runs


# ---------------------------------------------------------------------------
# klt request / body generation
# ---------------------------------------------------------------------------


def fragment_text(cand: mf.Candidate) -> str:
    return (TB_DIR / "ports_common.spice").read_text() + "\n" + (TB_DIR / cand.fragment).read_text()


def klt_body(study, tb_options: list[str], cand: mf.Candidate, vdd: float, runs: list[mf.RunSpec],
             seed: int | None) -> str:
    """Self-contained klt sim circuit body for one candidate / supply: the
    candidate fragment plus the generated run list as the body's own
    .control block (the documented-unsupported-but-working path the Ka-band
    bench also uses; see README "klt friction")."""
    params = mf.deck_params(study, cand)
    lines = [f"* mixer-topology-feasibility: klt sim body, {cand.name}, supply {vdd:.3f} V -- "
             "GENERATED by collect.py, do not edit",
             f".param vdd_val={vdd!r}"]
    lines += [f".param {k}={float(v)!r}" for k, v in params.items()]
    lines += [f".options {o}" for o in tb_options]
    if seed is not None:
        lines.append(f".options seed={seed}")
    lines += ["", fragment_text(cand), "", ".control", "set numdgt=10", "set noaskquit",
              *mf.build_control_lines(runs, cand.devices, sink_nodes=cand.sink_nodes), ".endc", ""]
    return "\n".join(lines)


def klt_request(body_name: str, corners: list[str], temps: list[float], backend: str, timeout_s: int,
                runner_version_check: str = "", stage_models: bool = True) -> dict:
    """One klt sim request (corners are process-section names here)."""
    return klt_driver.klt_request(
        body_name, corners, temps, backend, timeout_s,
        sentinel_name="sentinel_rail_v", sentinel_node="v(vdd)",
        stage_models=stage_models, runner_version_check=runner_version_check)


@dataclass
class RequestSpec:
    key: str                 # file stem, unique
    matrix: str
    candidate: str
    vdd: float
    corners: list[str]
    temps: list[float]
    drive_dbm: float | None
    seed: int | None

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def plan_requests(study, matrix: str, cand: mf.Candidate, drive_dbm: float | None) -> list[RequestSpec]:
    m = study.matrices[matrix]
    return [RequestSpec(key=f"{matrix}__{cand.name}__{v:.3f}v", matrix=matrix, candidate=cand.name, vdd=v,
                        corners=list(m.corners), temps=list(m.temperatures_c), drive_dbm=drive_dbm,
                        seed=m.seed) for v in m.supplies_v]


def backend_for(spec: RequestSpec, args) -> str:
    """Single-unit requests (the one-corner LO-selection and IIP3 sweeps) run
    locally, as klt itself would keep them and as the host rules allow for a
    single corner; every multi-unit request goes to the requested backend
    (default batch). A failed batch submit is an error, never a local
    fallback."""
    return "local" if len(spec.corners) * len(spec.temps) == 1 else args.backend


def write_request(study, tb_options, spec: RequestSpec, work: Path, args) -> tuple[Path, Path]:
    cand = study.candidate(spec.candidate)
    runs = list(stage_runs(study, spec.matrix, spec.drive_dbm).values())
    body = work / f"body_{spec.key}.spice"
    body.write_text(klt_body(study, tb_options, cand, spec.vdd, runs, spec.seed))
    req = work / f"request_{spec.key}.json"
    backend = backend_for(spec, args)
    req.write_text(json.dumps(klt_request(body.name, spec.corners, spec.temps, backend, args.timeout_s,
                                          runner_version_check=args.runner_version_check,
                                          stage_models=not args.no_stage_models), indent=2) + "\n")
    (work / f"spec_{spec.key}.json").write_text(json.dumps(spec.as_dict(), indent=2) + "\n")
    return req, body


def submit(spec: RequestSpec, req: Path, work: Path, args) -> Path:
    """Run one klt request (skipped when its report already exists, so an
    interrupted collection resumes). Returns the report path; raises
    CollectionError on any klt failure."""
    out = (work / f"out_{spec.key}").resolve()
    report = work / f"report_{spec.key}.json"
    if report.is_file():
        try:
            if "corners" in json.loads(report.read_text()):
                print(f"  reuse {report.name}", flush=True)
                return report
        except ValueError:
            pass
    backend = backend_for(spec, args)
    cmd = shlex.split(args.klt_cmd) + ["sim", str(req), "--backend", backend, "-o", str(out),
                                       "--format", "json"]
    print("$ " + " ".join(cmd), flush=True)
    with report.open("w") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, text=True)
    if proc.stderr:
        (work / f"stderr_{spec.key}.log").write_text(proc.stderr)
    if proc.returncode != 0:
        tail = proc.stderr[-3000:]
        report.rename(work / f"report_{spec.key}.failed.json")
        raise CollectionError(f"klt sim failed for {spec.key} (exit {proc.returncode}); "
                              f"backend {backend}: {tail}")
    return report


# ---------------------------------------------------------------------------
# Ingest: klt report -> cells
# ---------------------------------------------------------------------------


def read_units(report: Path) -> list[dict]:
    """The per-corner entries of a klt report with their log text."""
    data = json.loads(report.read_text())
    if "corners" not in data:
        raise CollectionError(f"{report.name}: no corners in klt report ({data.get('error')})")
    units = []
    for corner in data["corners"]:
        log = (corner.get("artifacts") or {}).get("log")
        if not log:
            raise CollectionError(f"{report.name}: {corner.get('process')}/{corner.get('temperature_c')}: "
                                  f"klt returned no log ({corner.get('diagnostics')})")
        path = Path(log)
        if not path.is_absolute():
            path = (report.parent / path).resolve()
        units.append({"process": corner["process"], "temp_c": float(corner["temperature_c"]),
                      "log_path": path, "text": path.read_text()})
    return units


def corner_id(process: str, temp: float, vdd: float) -> str:
    return f"{process}_{temp:g}c_{vdd:.2f}v"


def cells_from_unit(study, spec: RequestSpec, unit: dict) -> tuple[list[dict], list[str]]:
    """Analyse one unit's log into declared-cell dicts. Returns (cells,
    problems); problems are corruption (never evidence)."""
    cand = study.candidate(spec.candidate)
    runs = stage_runs(study, spec.matrix, spec.drive_dbm)
    parsed = mf.parse_log(unit["text"])
    cid = corner_id(unit["process"], unit["temp_c"], spec.vdd)
    problems = [f"{spec.key}/{cid}: {p}" for p in parsed.problems]
    extra = sorted(set(parsed.runs) - set(runs))
    if extra:
        problems.append(f"{spec.key}/{cid}: unexpected runs in log: {extra[:5]}")
    cells = []
    for rid, run in runs.items():
        values = parsed.runs.get(rid)
        if values is None:
            problems.append(f"{spec.key}/{cid}: run {rid} missing from the log")
            continue
        res = mf.analyze_run(run, values, cand.devices, study.stress, abs_floor_dbm=study.abs_floor_dbm,
                             floor_margin_db=study.floor_margin_db, sink_nodes=cand.sink_nodes)
        mf.with_dc_power(res, values, spec.vdd)
        if res["status"] == "invalid":
            problems.append(f"{spec.key}/{cid}/{rid}: invalid run: {res['problems']}")
            continue
        decl = dict(matrix=spec.matrix, candidate=spec.candidate, corner=unit["process"],
                    temp_c=unit["temp_c"], vdd_v=spec.vdd, band=run.band.name)
        if spec.matrix == "lo_select":
            decl.update(drive_dbm=run.vlo_dbm, rf_dbm=run.rf_dbm)
        elif spec.matrix == "iip3":
            decl.update(pin_dbm=run.rf_dbm)
        elif spec.matrix == "leakage":
            decl.update(seed=spec.seed)
        ident = {k: v for k, v in decl.items() if k != "seed"}
        cell = dict(decl, id=mf.cell_id(**ident), run_id=rid, corner_id=cid, model_section=unit["process"],
                    seed=spec.seed if spec.matrix == "leakage" else None, request=spec.key)
        if spec.matrix in ("main", "leakage", "iip3"):
            cell["lo_selected_dbm"] = spec.drive_dbm
        cell.update({k: v for k, v in res.items() if k not in ("problems",)})
        cells.append(cell)
    return cells, problems


def sweep_points(study, cells: list[dict], cand_name: str) -> list[dict]:
    """Pair the rf60/rf66 lo_select cells into select_lo_drive points."""
    by = {}
    for c in cells:
        if c["matrix"] == "lo_select" and c["candidate"] == cand_name:
            by[(c["band"], c["drive_dbm"], c["rf_dbm"])] = c
    points = []
    for b in study.matrices["lo_select"].bands:
        for d in study.lo_sweep_dbm:
            main, chk = by.get((b, d, study.rf_dbm)), by.get((b, d, study.rf_check_dbm))
            if main is None or chk is None:
                points.append({"band": b, "drive_dbm": d, "status": "missing"})
                continue
            ss = mf.small_signal_check(main.get("gain_db"), chk.get("gain_db"), study.small_signal_tol_db)
            status = main["status"]
            if status == "ok" and chk["status"] != "ok":
                status = chk["status"]
            points.append({"band": b, "drive_dbm": d, "status": status, "gain_db": main.get("gain_db"),
                           "gain_check_db": chk.get("gain_db"), "ss_ok": ss["ok"],
                           "ss_delta_db": ss["delta_db"]})
    return points


def iip3_fits(study, cells: list[dict], cand_name: str, selection: dict) -> dict:
    out = {}
    if selection.get("status") != "selected":
        reason = f"no selected LO drive ({selection.get('status')}); IIP3 is only defined at a selected drive"
        return {b: {"status": "IIP3 unavailable", "reason": reason} for b in study.matrices["iip3"].bands}
    rules = study.iip3_rules
    for b in study.matrices["iip3"].bands:
        pts = []
        for c in cells:
            if c["matrix"] == "iip3" and c["candidate"] == cand_name and c["band"] == b:
                pts.append(dict(pin_dbm=c["pin_dbm"], status=c["status"], p_if1_dbm=c.get("p_if1_dbm"),
                                p_if2_dbm=c.get("p_if2_dbm"), p_im3l_dbm=c.get("p_im3l_dbm"),
                                p_im3h_dbm=c.get("p_im3h_dbm"),
                                floor_dbm=(c.get("floor_dbm") or {}).get("im3")))
        out[b] = mf.fit_iip3(pts, slope_fund=tuple(rules["slope_fund"]), slope_im3=tuple(rules["slope_im3"]),
                             min_points=rules["min_points"], floor_margin_db=rules["floor_margin_db"],
                             compression_db=rules["compression_db"], max_residual_db=rules["max_residual_db"])
    return out


def not_applicable_cells(study, cand: mf.Candidate, matrices: tuple[str, ...], reason: str) -> list[dict]:
    cells = []
    for c in mf.expected_cells(study):
        if c["candidate"] == cand.name and c["matrix"] in matrices:
            cells.append(dict(c, model_section=c["corner"], status="not_applicable_no_drive",
                              reason=reason, seed=c.get("seed")))
    return cells


# ---------------------------------------------------------------------------
# The collection
# ---------------------------------------------------------------------------


_sha256 = klt_driver.sha256_file


def pdk_provenance(pdk) -> dict:
    return klt_driver.pdk_provenance(pdk, MODEL_FILES)


@dataclass
class Collected:
    cells: list[dict]
    selections: dict
    iip3: dict
    logs: dict               # archive name -> source path
    reports: list[Path]
    bodies: list[Path]
    requests: list[Path]
    specs: list[Path]
    klt_meta: list[dict]
    messages: dict


def run_collection(study, tb_options, work: Path, args) -> Collected:
    """Submit every stage, ingest, and return the cells. Raises
    CollectionError on any corruption. ``args.dry_run`` writes the
    first-stage requests only and returns None."""
    cells: list[dict] = []
    selections: dict = {}
    logs: dict = {}
    reports: list[Path] = []
    bodies: list[Path] = []
    requests: list[Path] = []
    specs: list[Path] = []
    klt_meta: list[dict] = []
    messages: dict = {}
    problems: list[str] = []

    def do(spec: RequestSpec):
        req, body = write_request(study, tb_options, spec, work, args)
        requests.append(req)
        bodies.append(body)
        specs.append(work / f"spec_{spec.key}.json")
        if args.dry_run:
            print(f"  dry-run: wrote {req.name}")
            return
        report = submit(spec, req, work, args)
        reports.append(report)
        data = json.loads(report.read_text())
        # what actually ran (backend and unit count per request) is recorded
        # here so the record's data-provenance text is derived, never assumed
        klt_meta.append({"request": spec.key, "report": report.name, "status": data.get("status"),
                         "matrix": spec.matrix, "candidate": spec.candidate,
                         "stage": 1 if spec.matrix == "lo_select" else 2,
                         "backend": backend_for(spec, args), "units": len(spec.corners) * len(spec.temps),
                         "environment": data.get("environment", {})})
        expected_units = {(c, t) for c in spec.corners for t in spec.temps}
        got = set()
        for unit in read_units(report):
            key = (unit["process"], unit["temp_c"])
            if key in got:
                problems.append(f"{spec.key}: duplicate unit {key}")
            got.add(key)
            new, probs = cells_from_unit(study, spec, unit)
            problems.extend(probs)
            cells.extend(new)
            name = f"{spec.key}__{corner_id(unit['process'], unit['temp_c'], spec.vdd)}"
            logs[name] = unit["log_path"]
            messages[name] = mf.parse_log(unit["text"]).messages
        for missing in sorted(expected_units - got):
            problems.append(f"{spec.key}: no unit returned for {missing}")
        for extra in sorted(got - expected_units):
            problems.append(f"{spec.key}: undeclared unit returned {extra}")
        if problems:
            raise CollectionError("\n".join(problems[:40]))

    print("[stage 1] LO-selection sweep (one corner per candidate)")
    for cand in study.candidates:
        for spec in plan_requests(study, "lo_select", cand, None):
            do(spec)
    if args.dry_run:
        return None
    iip3_out: dict = {}
    for cand in study.candidates:
        pts = sweep_points(study, cells, cand.name)
        sel = mf.select_lo_drive(pts, list(study.matrices["lo_select"].bands), list(study.lo_sweep_dbm),
                                 plateau_db=study.plateau_db, run_length=study.plateau_run)
        sel["points"] = pts
        selections[cand.name] = sel
        print(f"  {cand.name}: {sel['status']}" + (f" at {sel['drive_dbm']:g} dBm" if sel["status"] == "selected"
                                                    else f" ({sel.get('reason')})"))
    if getattr(args, "stage1_only", False):
        return None
    print("[stage 2] IIP3 / main / leakage at the selected drive")
    for cand in study.candidates:
        sel = selections[cand.name]
        if sel["status"] != "selected":
            cells.extend(not_applicable_cells(
                study, cand, ("main", "leakage", "iip3"),
                f"no selected LO drive ({sel['status']}): trial-drive numbers are diagnostics in the "
                "lo_select cells only"))
            continue
        drive = sel["drive_dbm"]
        for matrix in ("iip3", "main", "leakage"):
            for spec in plan_requests(study, matrix, cand, drive):
                do(spec)
        iip3_out[cand.name] = None
    for cand in study.candidates:
        iip3_out[cand.name] = iip3_fits(study, cells, cand.name, selections[cand.name])
    return Collected(cells=cells, selections=selections, iip3=iip3_out, logs=logs, reports=reports,
                     bodies=bodies, requests=requests, specs=specs, klt_meta=klt_meta, messages=messages)


def per_candidate(study, col: Collected) -> dict:
    out = {}
    for cand in study.candidates:
        out[cand.name] = {
            "lo_selection": col.selections[cand.name],
            "main_cells": [c for c in col.cells if c["matrix"] == "main" and c["candidate"] == cand.name],
            "leakage_cells": [c for c in col.cells if c["matrix"] == "leakage" and c["candidate"] == cand.name],
        }
    return out


# ---------------------------------------------------------------------------
# Record rendering and writing
# ---------------------------------------------------------------------------


def _f(x, fmt="{:.2f}"):
    return "n/a" if not (isinstance(x, (int, float)) and math.isfinite(x)) else fmt.format(x)


def summarize_main(study, cells: list[dict], cand: str) -> dict:
    main = [c for c in cells if c["matrix"] == "main" and c["candidate"] == cand]
    if not main or any(c["status"] == "not_applicable_no_drive" for c in main):
        return {"n": len(main), "applicable": False}
    ok = [c for c in main if c["status"] == "ok"]
    rej = [c for c in main if c["status"] == "rejected_stress"]
    out = {"n": len(main), "applicable": True, "n_ok": len(ok), "n_rejected": len(rej)}
    if ok:
        out["gain_min_db"] = min(c["gain_db"] for c in ok)
        out["gain_max_db"] = max(c["gain_db"] for c in ok)
        out["rail_power_mw_max"] = max(c["rail_power_mw"] for c in ok)
        out["dc_rail_power_mw_max"] = max(c["dc_rail_power_mw"] for c in ok)
        out["lo_vdiff_loaded_peak_v"] = [min(c["lo_vdiff_loaded_peak_v"] for c in ok),
                                         max(c["lo_vdiff_loaded_peak_v"] for c in ok)]
    viol: dict = {}
    for c in rej:
        for v in c["stress"]["rejecting"]:
            key = f"{v['device']} {v['interval']} {v['quantity']} {v['kind']}"
            viol[key] = viol.get(key, 0) + 1
    out["rejecting_violations"] = viol
    return out


def summarize_leakage(cells: list[dict], cand: str) -> dict:
    lk = [c for c in cells if c["matrix"] == "leakage" and c["candidate"] == cand]
    if not lk or any(c["status"] == "not_applicable_no_drive" for c in lk):
        return {"applicable": False}
    out = {"applicable": True, "n": len(lk), "n_rejected": sum(c["status"] != "ok" for c in lk)}
    for key, rkey in (("lo_if_dbm", "loif"), ("lo_rf_dbm", "lorf")):
        vals = [c for c in lk if c["status"] == "ok"]
        resolved = [c[key] for c in vals if c["resolved"][rkey]]
        out[key + "_max_resolved"] = max(resolved) if resolved else None
        out[key + "_n_unresolved"] = sum(1 for c in vals if not c["resolved"][rkey])
        out[key + "_upper_bound_max"] = max((c["floor_dbm"][rkey] + c["floor_margin_db"]) for c in vals) \
            if vals else None
    return out


def sweep_stress_digest(cells: list[dict], cand: str) -> dict:
    """Per rejected LO-sweep drive (RF -60 dBm cells, all bands): each
    distinct rejecting violation with its worst value across bands."""
    out: dict = {}
    for c in cells:
        if c["matrix"] != "lo_select" or c["candidate"] != cand or c["status"] != "rejected_stress":
            continue
        if c["rf_dbm"] != -60.0:
            continue
        per = out.setdefault(f"{c['drive_dbm']:g}", {})
        for v in c["stress"]["rejecting"]:
            key = (v["device"], v["interval"], v["quantity"], v["kind"])
            cur = per.get(key)
            worse = v["value"] is not None and (cur is None or (
                v["value"] < cur["worst_value"] if v["kind"] == "below" else v["value"] > cur["worst_value"]))
            if cur is None or worse:
                per[key] = {"device": v["device"], "interval": v["interval"], "quantity": v["quantity"],
                            "kind": v["kind"], "worst_value": v["value"], "limit": v["limit"]}
    return {d: sorted(per.values(), key=lambda x: (x["device"], x["interval"], x["quantity"]))
            for d, per in out.items()}


def build_summary(study, col: Collected, concl: dict) -> dict:
    return {
        "lo_sweep_stress": {c.name: sweep_stress_digest(col.cells, c.name) for c in study.candidates},
        "selections": {k: {kk: vv for kk, vv in v.items() if kk != "points"} for k, v in col.selections.items()},
        "iip3": col.iip3,
        "conclusion": concl,
        "main": {c.name: summarize_main(study, col.cells, c.name) for c in study.candidates},
        "leakage": {c.name: summarize_leakage(col.cells, c.name) for c in study.candidates},
    }


REDUCTIONS = (
    "LO-selection sweep and IIP3 sweep run at hbt_typ / 27 C / 2.25 V only (all three band points); the "
    "selected drive is then HELD FIXED across the main and leakage matrices.",
    "No MOS, capacitor or resistor corner axes: the fixtures use no PDK model of those families. Ideal "
    "passives do not cover the open passive/EM axis.",
    "Ideal baluns, ideal R/C, ideal bias sources and ideal current sinks; one fixed sizing per topology; the "
    "RF input is unmatched. No inductor model exists in the PDK, none is used.",
    "The 2.25 V +/- 10 % supply axis (2.025 / 2.25 / 2.475 V) is an exploratory nominal wholly below the "
    "2.5 V ceiling; it ratifies no rail. The legacy 2.5 V +/- 10 % grid is not used.",
    "Mismatch leakage cells use ONE deterministic realization per cell (fixed ngspice seed, applied to every "
    "cell; draw order follows instance order so realizations differ between candidates). This is card "
    "coverage, not Monte Carlo yield evidence.",
    "No all-corner linearity, yield or compliance claim. SSB noise figure is out of scope (#27).",
)

SIMULATED_WITH = "simulated (ngspice, real npn13G2 VBIC card, cornerHBT.lib sections)"


def execution_provenance(klt_meta: list[dict], cells: list[dict]) -> dict:
    """What actually ran, derived from the per-request metadata (backend and
    unit count recorded at submit time) and the cells. The record's data
    provenance text comes from here and nowhere else: it may only claim an
    off-host or multi-unit run when such a request was submitted."""
    for m in klt_meta:
        missing = [k for k in ("backend", "units", "matrix", "stage") if k not in m]
        if missing:
            raise CollectionError(f"klt request {m.get('request')}: no {missing} recorded; provenance underivable")
    stages: dict = {}
    for m in klt_meta:
        st = stages.setdefault(int(m["stage"]), {})
        b = st.setdefault(m["backend"], {"requests": 0, "units": 0, "max_units": 0})
        b["requests"] += 1
        b["units"] += int(m["units"])
        b["max_units"] = max(b["max_units"], int(m["units"]))
    off_host = [m["request"] for m in klt_meta if not is_local_backend(m["backend"])]
    multi = [m["request"] for m in klt_meta if int(m["units"]) > 1]
    not_sim: dict = {}
    for c in cells:
        if c.get("status") == "not_applicable_no_drive":
            not_sim[c["matrix"]] = not_sim.get(c["matrix"], 0) + 1
    backends = sorted({m["backend"] for m in klt_meta})
    parts = []
    for s in sorted(stages):
        per = "; ".join(f"backend `{b}`: {v['requests']} request(s), {v['units']} unit(s), largest request "
                        f"{v['max_units']} unit(s)" for b, v in sorted(stages[s].items()))
        parts.append(f"{STAGE_LABELS.get(s, f'stage {s}')}: {per}")
    if not klt_meta:
        where = "no `klt sim` request was submitted"
    elif off_host:
        where = (f"{len(klt_meta)} `klt sim` request(s); {len(off_host)} ran off-host "
                 f"(backend(s) {', '.join(f'`{b}`' for b in backends if not is_local_backend(b))})")
    else:
        where = f"on this host only: {len(klt_meta)} `klt sim` request(s), all with a local backend"
    text = f"{SIMULATED_WITH}, {where}. " + (". ".join(parts) + ". " if parts else "")
    if not multi:
        text += "No multi-unit request was submitted. "
    if not off_host:
        text += ("No batch/off-host request was submitted: the batch path was NOT exercised against the real "
                 "fleet by this record. ")
    if 2 not in stages:
        text += "No stage-2 request was submitted (no candidate selected an LO drive). "
    if not_sim:
        text += ("Not simulated (no LO drive selected; recorded as `not_applicable_no_drive` cells, no numbers): "
                 + ", ".join(f"{k} {v}" for k, v in sorted(not_sim.items(), key=lambda kv: (
                     ["main", "leakage", "iip3"].index(kv[0]) if kv[0] in ("main", "leakage", "iip3") else 9,
                     kv[0]))) + " cell(s).")
    return {"requests": len(klt_meta), "stages": {str(k): v for k, v in sorted(stages.items())},
            "backends": backends, "off_host_requests": off_host, "multi_unit_requests": multi,
            "fleet_exercised": bool(off_host), "not_simulated_cells": not_sim, "text": text.strip()}


def crosscheck_summary(compared: int, worst: float, tol: float, ref_backends: list[str]) -> str:
    """The cross-check sentence, stating which paths were compared. The
    reference cells' backend comes from the request that produced them."""
    refs = sorted(set(ref_backends))
    if refs and all(is_local_backend(b) for b in refs):
        kind = ("LOCAL-vs-LOCAL: the reference cells came from local single-host `klt sim` requests (backend "
                + ", ".join(f"`{b}`" for b in refs) + ") and were re-simulated through the local harness path; "
                "this validates the klt-body path against the harness path, both local. It is NOT a fleet-vs-local "
                "check")
    elif refs:
        kind = ("collected cells from backend(s) " + ", ".join(f"`{b}`" for b in refs)
                + " re-simulated through the local harness path")
    else:
        kind = "no reference cell compared"
    return (f"{kind}; {compared} nominal value(s) compared (one ngspice process at a time); max |delta| "
            f"{worst:.2e} dB (tolerance {tol:g} dB)")


def render_md(*, record_id, study, tb, col: Collected, summary: dict, started, git, ngspice, klt_version,
              pdk_prov, crosscheck, converge, claim, supersedes) -> str:
    L = []
    w = L.append
    w(f"# mixer-topology-feasibility record {record_id}")
    w("")
    w(f"- **Experiment**: {tb['name']} (issue #35, part 2: collection)")
    w(f"- **Record kind**: characterization (topology feasibility, device-level)")
    w(f"- **Claim**: {claim}")
    w("- **Spec rows claimed met**: none. No schematic, layout or target-spec change is part of this record.")
    w(f"- **Supersedes**: {supersedes or 'none'}")
    w(f"- **Started (UTC)**: {started.isoformat(timespec='seconds')}")
    w(f"- **Git**: {git['commit']} ({git['branch']}, {'dirty' if git['dirty'] else 'clean'})")
    exe = execution_provenance(col.klt_meta, col.cells)
    w(f"- **Simulator**: {ngspice}; " + ("off-host runs cross-checked against the local harness path"
                                         if exe["off_host_requests"] else
                                         "every run on this host; the cross-check is local-vs-local")
      + " (see Data provenance and the cross-check controls)")
    w(f"- **klt client**: {klt_version}")
    w(f"- **PDK**: {pdk_prov.get('fetched_version_file')}; model files "
      + ", ".join(f"{k} sha256 {v[:12]}" for k, v in pdk_prov["model_sha256"].items()))
    w(f"- **Data provenance**: {exe['text']}")
    w(f"- **Declared cells**: {len(mf.expected_cells(study))}; accepted cells: {len(col.cells)}; every declared "
      "cell is accounted for exactly once (acceptance gate `mixfeas.validate_collection` passed)")
    w("")
    w("## Intentional reductions and exclusions (read first)")
    w("")
    for r in REDUCTIONS:
        w(f"- {r}")
    w("")
    w("## Conventions")
    w("")
    w("- RF: single-ended 50 ohm Thevenin; available power per tone `vrf^2/(8*50)`; -60 dBm (small-signal), "
      "-66 dBm check (|dG| <= 0.2 dB).")
    w("- LO: differential 100 ohm reference port, TOTAL available power `Vdiff_open_peak^2/(8*100)`, swept "
      f"{study.lo_sweep_dbm[0]:g}..{study.lo_sweep_dbm[-1]:g} dBm in 3 dB steps (exploratory bounds, not a row-15 "
      "commitment). Low-side LO = RF - 1 GHz.")
    w("- IF: physical 50 ohm termination; gain = IF fundamental power delivered into it / RF available power. "
      "Balanced outputs through an ideal 200 ohm diff to 50 ohm balun; the placeholder floor uses a DC block "
      "and an ideal 200:50 transformer.")
    w("- Stress: V_CE in [0.4, 1.4] V, V_BE in [0.65, 0.96] V, Ic >= 0.003*Nx A flagged; DC point and retained "
      "window violations reject the run; startup-only violations are flags.")
    w("- Extraction: 20 ns settle, 20 ns (single) / 80 ns (two-tone) rectangular coherent window, 1 ps "
      "maximum timestep and resampling, `reltol=1e-5`, single-bin DFT; floor = larger of the strongest empty "
      "neighbouring bin and -140 dBm; values < 10 dB above floor are upper bounds only.")
    w("")
    w("## LO-drive selection (hbt_typ / 27 C / 2.25 V, all three bands)")
    w("")
    w("| topology | outcome | selected LO (dBm total avail.) | detail |")
    w("|---|---|---|---|")
    for cand in study.candidates:
        s = col.selections[cand.name]
        det = s.get("reason") or "; ".join(
            f"{b}: max valid gain {_f(i.get('max_valid_gain_db'))} dB, qualifying {i.get('qualifying_dbm')}"
            for b, i in s.get("per_band", {}).items())
        w(f"| {cand.name} [{cand.role}] | {s['status']} | "
          f"{_f(s.get('drive_dbm'), '{:g}')} | {det} |")
    w("")
    w("Sweep detail (gain at RF -60 dBm; `R` = rejected on device limits, `x` = fails small-signal check):")
    w("")
    for cand in study.candidates:
        pts = col.selections[cand.name]["points"]
        w(f"### {cand.name}")
        w("")
        w("| LO dBm | " + " | ".join(b.name for b in study.bands) + " |")
        w("|---|" + "---|" * len(study.bands))
        for d in study.lo_sweep_dbm:
            row = []
            for b in study.bands:
                p = next(q for q in pts if q["band"] == b.name and q["drive_dbm"] == d)
                tag = _f(p.get("gain_db"))
                if p["status"] == "rejected_stress":
                    tag += " R"
                if p.get("ss_ok") is False:
                    tag += " x"
                row.append(tag)
            w(f"| {d:g} | " + " | ".join(row) + " |")
        w("")
    w("### Reading the sweep (nominal corner)")
    w("")
    for cand in study.candidates:
        pts = [q for q in col.selections[cand.name]["points"] if q["band"] == study.smoke["band"]]
        valid = [q for q in pts if q["status"] == "ok"]
        rej = [q for q in pts if q["status"] == "rejected_stress"]
        if not valid:
            w(f"- {cand.name}: no stress-valid point at {study.smoke['band']}.")
            continue
        last = valid[-1]
        prev = valid[-2] if len(valid) > 1 else None
        txt = (f"- {cand.name}: at {study.smoke['band']} the last stress-valid drive is {last['drive_dbm']:g} dBm "
               f"(gain {_f(last['gain_db'])} dB"
               + (f"; {_f(last['gain_db'] - prev['gain_db'])} dB above the previous 3 dB step" if prev else "")
               + ")")
        if rej:
            txt += (f"; the first rejected drive is {rej[0]['drive_dbm']:g} dBm (gain {_f(rej[0]['gain_db'])} dB, "
                    f"{_f(rej[0]['gain_db'] - last['gain_db'])} dB further). The stress window closes while the gain "
                    "is still rising, so the plateau rule finds no run of three qualifying stress-valid drives.")
        w(txt)
    w("")
    w("These are findings at the declared sizing (one fixed bias and load per topology), not statements about "
      "the topologies in general. The rule, the sweep bounds and the stress limits were not adjusted to change "
      "the outcome.")
    w("")
    w("### Stress rejections in the sweep (RF -60 dBm cells, worst value across the three bands)")
    w("")
    w("A rejected point is excluded from the plateau; it is an explicit outcome, not an averaged one. Lowest "
      "rejected drive and the highest swept drive are shown per topology.")
    w("")
    for cand in study.candidates:
        dig = summary["lo_sweep_stress"][cand.name]
        w(f"**{cand.name}**")
        w("")
        if not dig:
            w("- no sweep point rejected")
            w("")
            continue
        drives = sorted(dig, key=float)
        for d in sorted({drives[0], drives[-1]}, key=float):
            items = "; ".join(
                f"{v['device']} {v['interval']} {v['quantity']} {v['kind']} {_f(v['worst_value'], '{:.3g}')} "
                f"(limit {_f(v['limit'], '{:.3g}')})" for v in dig[d])
            w(f"- LO {d} dBm: {items or 'none recorded'}")
        w(f"- rejected drives: {', '.join(drives)} dBm")
        w("")
    w("## Main matrix at the selected drive (gain, stress, mixer-only DC rail power)")
    w("")
    w("| topology | applicable | cells ok / rejected | gain min..max dB | max rail P mW (retained) | "
      "max DC rail P mW | rail P margin to 40 mW (mixer alone) | LO Vdiff loaded pk (V) |")
    w("|---|---|---|---|---|---|---|---|")
    for cand in study.candidates:
        m = summary["main"][cand.name]
        if not m["applicable"]:
            w(f"| {cand.name} | no selected drive | - | - | - | - | - | - |")
            continue
        dc = m.get("dc_rail_power_mw_max")
        w(f"| {cand.name} | yes | {m['n_ok']} / {m['n_rejected']} | "
          f"{_f(m.get('gain_min_db'))}..{_f(m.get('gain_max_db'))} | {_f(m.get('rail_power_mw_max'))} | "
          f"{_f(dc)} | {_f(40.0 - dc if dc is not None else None)} mW of the whole LNA+mixer budget | "
          f"{_f((m.get('lo_vdiff_loaded_peak_v') or [None, None])[0], '{:.3f}')}.."
          f"{_f((m.get('lo_vdiff_loaded_peak_v') or [None, None])[1], '{:.3f}')} |")
    w("")
    w("Mixer-only DC rail power is not a demonstrated cascade budget allocation; the 40 mW row-18 budget is "
      "the entire LNA + mixer.")
    w("")
    for cand in study.candidates:
        m = summary["main"][cand.name]
        if m.get("applicable") and m.get("rejecting_violations"):
            w(f"Rejecting stress violations, {cand.name} (violation: number of main cells):")
            w("")
            for k, n in sorted(m["rejecting_violations"].items()):
                w(f"- {k}: {n}")
            w("")
    w("## LO leakage (mismatch cards, fixed seed, RF off, at the selected drive)")
    w("")
    w("| topology | applicable | cells rejected | worst resolved LO->IF (dBm) | unresolved LO->IF cells | "
      "worst resolved LO->RF (dBm) | unresolved LO->RF cells |")
    w("|---|---|---|---|---|---|---|")
    for cand in study.candidates:
        k = summary["leakage"][cand.name]
        if not k["applicable"]:
            w(f"| {cand.name} | no selected drive | - | - | - | - | - |")
            continue
        w(f"| {cand.name} | yes | {k['n_rejected']} | {_f(k['lo_if_dbm_max_resolved'], '{:.1f}')} | "
          f"{k['lo_if_dbm_n_unresolved']} | {_f(k['lo_rf_dbm_max_resolved'], '{:.1f}')} | "
          f"{k['lo_rf_dbm_n_unresolved']} |")
    w("")
    w("Unresolved cells are upper bounds (extraction floor + 10 dB) and are listed per cell in the JSON "
      "sidecar. Mismatch semantics: see Reductions.")
    w("")
    w("## IIP3 (hbt_typ / 27 C / 2.25 V, swept two-tone, only from a verified 1:3-slope region)")
    w("")
    w("| topology | band | result |")
    w("|---|---|---|")
    for cand in study.candidates:
        for b in study.bands:
            fit = col.iip3[cand.name][b.name]
            if fit["status"] == "ok":
                lo, hi = fit["sidebands"]["low"], fit["sidebands"]["high"]
                res = (f"{fit['iip3_dbm']:.2f} dBm per-tone input (conservative; sidebands "
                       f"{lo['iip3_dbm']:.2f} / {hi['iip3_dbm']:.2f}; fit interval "
                       f"{lo['interval_dbm']} dBm, slopes {lo['slope_fund']:.2f}/{lo['slope_im3']:.2f}, "
                       f"residuals <= {max(lo['residual_fund_db'], lo['residual_im3_db']):.2f} dB)")
            else:
                res = f"IIP3 unavailable: {fit.get('reason')}"
            w(f"| {cand.name} | {b.name} | {res} |")
    w("")
    w("## Convergence and cross-check controls (local, one corner at a time)")
    w("")
    for name, c in converge.items():
        base = c.get("baseline", {})
        w(f"- {name} at {c['drive_dbm']:g} dBm ({c['drive_kind']}): " + ("PASS" if c["ok"] else "FAIL") + " -- "
          + "; ".join(f"{k['variant']} {k['quantity']} {_f(k.get('delta_db'), '{:+.4f}')} dB" for k in c["checks"])
          + f". Baseline: gain {_f(base.get('gain_db'))} dB ({base.get('status_on')}); RF-off LO->IF "
          f"{_f(base.get('lo_if_dbm'), '{:.1f}')} dBm, LO->RF {_f(base.get('lo_rf_dbm'), '{:.1f}')} dBm "
          f"({base.get('status_off')})")
    w("")
    w(f"- Cross-check (klt-body path vs local harness path): {crosscheck['summary']}")
    w("")
    w("## Conclusion")
    w("")
    w("| topology | verdict | detail |")
    w("|---|---|---|")
    for name, v in summary["conclusion"]["verdicts"].items():
        det = v.get("reason") or f"worst-case gain {_f(v.get('worst_gain_db'))} dB at {_f(v.get('drive_dbm'), '{:g}')} dBm"
        w(f"| {name} | {v['verdict']} | {det} |")
    w("")
    rec = summary["conclusion"]["recommendation"]
    w(f"**Recommendation (conditional, device-level)**: draw first: **{rec['draw_first'] or 'none'}**. {rec['basis']}.")
    w("")
    w("This record claims no spec row is met. A completed comparison may conclude infeasible or "
      "inconclusive; neither extends the sweep bounds nor forces a recommendation. A recorded "
      "infeasible/no-acceptable-drive verdict is a finding about the declared sizing and sweep, not about "
      "the topology in general.")
    w("")
    w("## Provenance and raw artifacts")
    w("")
    w(f"- Raw per-unit ngspice logs: `corners/{record_id}/` (gzip).")
    w(f"- Generated bodies, klt requests, klt reports, candidate fragments, tb.json: `netlist-snapshots/{record_id}/`.")
    w(f"- Every cell (stress tables per device and interval, spectra, floors): `records/{record_id}-cells.json.gz`.")
    w(f"- Summary and gate result: `records/{record_id}.json`.")
    w("- klt environment per request: " + "; ".join(
        f"{m['request']}: {json.dumps(m['environment'].get('remote', m['environment']), sort_keys=True)[:160]}"
        for m in col.klt_meta[:3]) + (" ..." if len(col.klt_meta) > 3 else ""))
    w("")
    return "\n".join(L)


def write_record(study, tb_manifest, col: Collected, summary: dict, *, pdk_prov, ngspice, klt_version,
                 crosscheck, converge, claim, supersedes, started, git) -> str:
    record_id = allocate_record_id(REPO_ROOT, RECORDS, started, git)
    md_path = RECORDS / f"{record_id}.md"
    for path in (md_path, CORNER_LOGS / record_id, SNAPSHOTS / record_id):
        if path.exists():
            raise RecordExists(f"{path} exists; append-only evidence is never rewritten")
    md = render_md(record_id=record_id, study=study, tb=tb_manifest, col=col, summary=summary, started=started,
                   git=git, ngspice=ngspice, klt_version=klt_version, pdk_prov=pdk_prov, crosscheck=crosscheck,
                   converge=converge, claim=claim, supersedes=supersedes)
    (CORNER_LOGS / record_id).mkdir(parents=True)
    for name, path in sorted(col.logs.items()):
        with path.open("rb") as src, (CORNER_LOGS / record_id / f"{name}.log.gz").open("wb") as raw, \
                gzip.GzipFile(filename=f"{name}.log", mode="wb", fileobj=raw, mtime=0) as dst:
            shutil.copyfileobj(src, dst)
    snap = SNAPSHOTS / record_id
    snap.mkdir(parents=True)
    for p in col.bodies + col.requests + col.reports + col.specs:
        shutil.copyfile(p, snap / p.name)
    for cand in study.candidates:
        shutil.copyfile(TB_DIR / cand.fragment, snap / cand.fragment)
    shutil.copyfile(TB_DIR / "ports_common.spice", snap / "ports_common.spice")
    shutil.copyfile(TB_DIR / "tb.json", snap / "tb.json")
    RECORDS.mkdir(parents=True, exist_ok=True)
    cells_path = RECORDS / f"{record_id}-cells.json.gz"
    with cells_path.open("wb") as raw, gzip.GzipFile(filename=f"{record_id}-cells.json", mode="wb", fileobj=raw,
                                                      mtime=0) as gz:
        gz.write(json.dumps(col.cells, indent=0, sort_keys=True, default=str).encode())
    sidecar = {
        "record_id": record_id, "experiment": tb_manifest["name"], "issue": 35, "part": "collection",
        "scope": "device-level topology feasibility; no spec row claimed met",
        "declared_cells": len(mf.expected_cells(study)), "accepted_cells": len(col.cells),
        "gate": {"validate_collection": "passed", "problems": []},
        "summary": summary, "reductions": list(REDUCTIONS),
        "provenance": {"git": git, "ngspice": ngspice, "klt": klt_version, "pdk": pdk_prov,
                       "klt_requests": col.klt_meta,
                       "execution": execution_provenance(col.klt_meta, col.cells),
                       "converge": converge, "crosscheck": crosscheck,
                       "mismatch_seed": study.matrices["leakage"].seed,
                       "tb_json_sha256": _sha256(TB_DIR / "tb.json")},
        "cells_file": cells_path.name, "supersedes": supersedes or None,
    }
    (RECORDS / f"{record_id}.json").write_text(json.dumps(sidecar, indent=2, sort_keys=True, default=str) + "\n")
    md_path.write_text(md)
    return record_id


# ---------------------------------------------------------------------------
# Cross-check and convergence at the selected drive (local, one corner)
# ---------------------------------------------------------------------------


def _near(c: dict, **kw) -> bool:
    return all((abs(c[k] - v) < 1e-9 if isinstance(v, float) else c[k] == v) for k, v in kw.items())


def local_controls(study, col: Collected) -> tuple[dict, dict, list[str]]:
    """Convergence control per candidate (local, one corner at a time) and
    the cross-check against the collected cells. Returns (crosscheck,
    converge, problems).

    With a selected drive the control runs AT that drive and the reference
    cells are the collected nominal main cell and the seeded nominal leakage
    cell. With no selected drive the control runs at the labelled smoke trial
    drive (a diagnostic, NOT a selected drive; the issue allows no more) and
    the reference is the lo_select cell at that same drive. Either way it
    ties the klt body path to the local harness path."""
    import run as drv  # the local single-corner driver

    tb, study_ = drv._load()
    pdk = drv._pdk()
    problems: list[str] = []
    converge: dict = {}
    worst = 0.0
    compared = 0
    ref_backends: list[str] = []
    meta_by_key = {m["request"]: m for m in col.klt_meta}

    def ref_backend(matrix: str, cand_name: str) -> str:
        m = meta_by_key.get(f"{matrix}__{cand_name}__2.250v")
        return m.get("backend", "unrecorded") if m else "unrecorded"

    band = study.band(study.smoke["band"])
    trial = float(study.smoke["trial_lo_dbm"])
    leak = study.matrices["leakage"]
    for cand in study.candidates:
        sel = col.selections[cand.name]
        selected = sel["status"] == "selected"
        drive = sel["drive_dbm"] if selected else trial
        out = drv.converge_candidate(tb, study_, pdk, cand, drive, quiet=True)
        loc_on, loc_off = out["results"].get("base_on", {}), out["results"].get("base_off", {})
        converge[cand.name] = {
            "drive_dbm": drive, "drive_kind": "selected" if selected else "trial (diagnostic, NOT a selected drive)",
            "ok": not out["failures"], "checks": out["checks"], "failures": out["failures"],
            "baseline": {"status_on": loc_on.get("status"), "gain_db": loc_on.get("gain_db"),
                         "status_off": loc_off.get("status"), "lo_if_dbm": loc_off.get("lo_if_dbm"),
                         "lo_rf_dbm": loc_off.get("lo_rf_dbm"), "resolved_off": loc_off.get("resolved")}}
        problems += [f"convergence control {cand.name}: {f}" for f in out["failures"]]
        if selected:
            ref = next((c for c in col.cells if c["matrix"] == "main" and c["candidate"] == cand.name
                        and _near(c, corner="hbt_typ", temp_c=27.0, vdd_v=2.25, band=band.name)), None)
        else:
            ref = next((c for c in col.cells if c["matrix"] == "lo_select" and c["candidate"] == cand.name
                        and _near(c, band=band.name, drive_dbm=trial, rf_dbm=study.rf_dbm)), None)
        if ref is None or "gain_db" not in ref or "gain_db" not in loc_on:
            problems.append(f"cross-check {cand.name}: reference cell or local gain unavailable")
            continue
        d = abs(ref["gain_db"] - loc_on["gain_db"])
        compared += 1
        ref_backends.append(ref_backend(ref["matrix"], cand.name))
        worst = max(worst, d)
        if d > CROSSCHECK_TOL_DB:
            problems.append(f"cross-check {cand.name}: collected gain {ref['gain_db']:.5f} dB vs local "
                            f"{loc_on['gain_db']:.5f} dB (|d| {d:.2e} > {CROSSCHECK_TOL_DB:g})")
        if not selected:
            continue
        # the seeded mismatch realization must reproduce too: the nominal
        # leakage cell (first mismatch card, band centre) re-simulated locally
        lcell = next((c for c in col.cells if c["matrix"] == "leakage" and c["candidate"] == cand.name
                      and _near(c, corner=leak.corners[0], temp_c=27.0, vdd_v=2.25, band=band.name)), None)
        if lcell is None or lcell.get("status") == "not_applicable_no_drive" or "lo_if_dbm" not in loc_off:
            problems.append(f"cross-check {cand.name}: nominal leakage cell or local leakage unavailable")
            continue
        for key, rkey in (("lo_if_dbm", "loif"), ("lo_rf_dbm", "lorf")):
            if lcell["resolved"][rkey] != loc_off["resolved"][rkey]:
                problems.append(f"cross-check {cand.name}: {key} resolved flag differs collected vs local")
            elif lcell["resolved"][rkey]:
                d = abs(lcell[key] - loc_off[key])
                compared += 1
                ref_backends.append(ref_backend("leakage", cand.name))
                worst = max(worst, d)
                if d > CROSSCHECK_TOL_DB:
                    problems.append(f"cross-check {cand.name}: collected {key} {lcell[key]:.4f} vs local "
                                    f"{loc_off[key]:.4f} dBm (|d| {d:.2e} > {CROSSCHECK_TOL_DB:g})")
    refs = sorted(set(ref_backends))
    crosscheck = {"compared": compared, "worst_delta_db": worst, "tolerance_db": CROSSCHECK_TOL_DB,
                  "reference_backends": refs,
                  "kind": "local-vs-local" if refs and all(is_local_backend(b) for b in refs)
                  else ("off-host-vs-local" if refs else "none"),
                  "summary": crosscheck_summary(compared, worst, CROSSCHECK_TOL_DB, refs)}
    return crosscheck, converge, problems


def klt_version_text(klt_cmd: str) -> str:
    proc = subprocess.run(shlex.split(klt_cmd) + ["--version"], capture_output=True, text=True)
    return (proc.stdout or proc.stderr).strip()


def collect(args) -> int:
    import run as drv

    tb, study = drv._load()
    manifest = json.loads((tb.directory / "tb.json").read_text())
    pdk = drv._pdk()
    started = _dt.datetime.now(_dt.timezone.utc)
    git = git_provenance(REPO_ROOT)
    work = Path(args.workdir).resolve() if args.workdir else \
        (SCRATCH / f"klt-{started.strftime('%Y%m%d-%H%M%S')}").resolve()
    work.mkdir(parents=True, exist_ok=True)
    print(f"working directory: {work}")
    try:
        col = run_collection(study, list(tb.options), work, args)
        if col is None:
            what = ("--dry-run: first-stage requests and bodies written; nothing submitted" if args.dry_run else
                    "--stage1-only: LO-selection sweep collected; diagnostic only")
            print(f"{what} (work under {work}); NO record written")
            return 0
        problems = mf.validate_collection(study, col.cells)
        if problems:
            for p in problems[:40]:
                print(f"FAIL: {p}", file=sys.stderr)
            print(f"collect: acceptance gate failed ({len(problems)} problem(s)); NO record written",
                  file=sys.stderr)
            return 1
        crosscheck, converge, cprobs = local_controls(study, col)
        if cprobs:
            for p in cprobs:
                print(f"FAIL: {p}", file=sys.stderr)
            print("collect: convergence/cross-check controls failed; NO record written", file=sys.stderr)
            return 1
    except CollectionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        print(f"collect: incomplete or corrupt collection; NO record written (work kept under {work})",
              file=sys.stderr)
        return 1
    per = per_candidate(study, col)
    concl = mf.conclude(study, per)
    summary = build_summary(study, col, concl)
    ngspice = drv.ngspice_version()
    record_id = write_record(study, manifest, col, summary, pdk_prov=pdk_provenance(pdk), ngspice=ngspice,
                             klt_version=klt_version_text(args.klt_cmd), crosscheck=crosscheck,
                             converge=converge, claim=args.claim or manifest["claim"],
                             supersedes=args.supersedes, started=started, git=git)
    print(f"wrote {RECORDS / f'{record_id}.md'} (+ sidecars, corners/{record_id}/, netlist-snapshots/{record_id}/)")
    return 0
