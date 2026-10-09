#!/usr/bin/env python3
"""Driver for the Ka-band npn13G2 device characterization bench (issue #17).

    python3 sim/hbt-kaband-characterization/run.py smoke
    python3 sim/hbt-kaband-characterization/run.py selftest
    python3 sim/hbt-kaband-characterization/run.py probe
    python3 sim/hbt-kaband-characterization/run.py characterize [--backend batch]
    python3 sim/hbt-kaband-characterization/run.py ingest REPORT.json [REPORT.json ...]

smoke / selftest / probe run LOCALLY, one PVT point per ngspice process, on
the REDUCED bias sweep (tb.json sweep.reduced) and never write evidence.
characterize expresses the full 27-point HBT x temperature x supply grid as
`klt sim` requests (one per supply value, 9 process x temperature corners
each; see README.md "Running the full grid") so it can go to an off-host
backend, then ingests the returned per-corner logs into one append-only
record. ingest builds the record from already-collected klt reports.

Exit status: 0 on success; 1 on any failure (missing measurement, failed
check, incomplete grid, klt error). A failure is never written as evidence.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as _dt
import gzip
import hashlib
import io
import json
import math
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
SIM_DIR = BENCH_DIR.parent
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(BENCH_DIR))

import kaband  # noqa: E402
from harness.corners import (  # noqa: E402
    CORNERS, PvtPoint, build_grid, resolve_corners, sabotage, supply_points,
)
from harness.pdk import PdkConfigError, PdkNotFound, find_pdk  # noqa: E402
from harness.report import RecordExists, allocate_record_id, git_provenance  # noqa: E402
from harness.runner import NgspiceMissing, ngspice_version, run_point  # noqa: E402
from harness.testbench import load  # noqa: E402

PROBE_NETLIST = BENCH_DIR / "testbench" / "resistor_noise_temp_probe.spice"
SCRATCH = BENCH_DIR / "_build"
RECORDS = BENCH_DIR / "records"
CORNER_LOGS = BENCH_DIR / "corners"
SNAPSHOTS = BENCH_DIR / "netlist-snapshots"
MODEL_FILES = ("cornerHBT.lib", "sg13g2_hbt_mod.lib")

#: Quantities every "ok" row must carry for smoke to count as a valid run.
REQUIRED_ROW_KEYS = (
    "ic_a", "jc_ma_um2", "pdc_mw", "ft_status", "k", "delta_mag", "gmax_db", "gmax_kind",
    "ropt_ohm", "xopt_ohm", "tmin_k", "nfmin_db_t290", "nfmin_db_t300.15",
    "nf50_db_t290", "nfmin_check",
)


# ---------------------------------------------------------------------------
# Shared plumbing
# ---------------------------------------------------------------------------


def _load():
    tb = load(BENCH_DIR)
    manifest = json.loads((tb.directory / "tb.json").read_text())
    return tb, manifest


def _pdk():
    try:
        return find_pdk(SIM_DIR)
    except (PdkNotFound, PdkConfigError) as exc:
        raise SystemExit(f"error: {exc}")


def _run_local(tb, pdk, point: PvtPoint, sweep, workdir: Path, *, sabotage_measurement=False,
               timeout_s=900):
    """One PVT point, one local ngspice process. Returns (rows, problems, log_text)."""
    tb_run = dataclasses.replace(
        tb,
        analyses=tuple(kaband.build_control_lines(sweep, sabotage_measurement=sabotage_measurement)),
        measure={},
    )
    result = run_point(tb_run, pdk, point, workdir, timeout_s=timeout_s, num_threads=1)
    log_text = (workdir / result.log).read_text() if result.log else ""
    problems = [] if result.status == "ok" else [f"runner: {result.status} {result.message}"]
    rows, log_problems = kaband.analyze_log(log_text, sweep, point.temp_c)
    for row in rows:
        row.update(corner=point.corner.name, temp_c=point.temp_c, vdd_v=point.vdd,
                   corner_id=point.corner_id)
    return rows, problems + log_problems, log_text


def row_failures(rows: list[dict], problems: list[str], sweep) -> list[str]:
    """Why a run is NOT a valid execution of the bench (empty list = valid).

    Used by smoke (must be empty) and by selftest's invalid-deck control
    (must NOT be empty)."""
    failures = list(problems)
    expected = sweep.n_bias_points * len(sweep.frequencies_hz)
    if len(rows) != expected:
        failures.append(f"expected {expected} rows, got {len(rows)}")
    for row in rows:
        tag = f"nx={row.get('nx')} vce={row.get('vce_set_v')} vbe={row.get('vbe_set_v')} f={row.get('freq_hz'):.4g}"
        if row.get("status") != "ok":
            failures.append(f"{tag}: excluded ({row.get('reason')})")
            continue
        missing = [k for k in REQUIRED_ROW_KEYS if row.get(k) is None]
        if missing:
            failures.append(f"{tag}: missing {','.join(missing)}")
        if row.get("ft_status") != "bracketed":
            failures.append(f"{tag}: fT not bracketed ({row.get('ft_status')})")
    return failures


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------


def cmd_smoke(args) -> int:
    tb, manifest = _load()
    sweep = kaband.sweep_from_manifest(manifest, "reduced")
    pdk = _pdk()
    point = build_grid(resolve_corners(["hbt_typ"]), [27.0], [tb.nominal_supply_v])[0]
    rows, problems, _ = _run_local(tb, pdk, point, sweep, SCRATCH / "smoke")
    failures = row_failures(rows, problems, sweep)
    for row in rows:
        if row.get("status") == "ok":
            print(f"  nx={row['nx']} vce={row['vce_v']:.3f} vbe={row['vbe_v']:.3f} "
                  f"f={row['freq_hz'] / 1e9:.2f}GHz Jc={row['jc_ma_um2']:.3g} mA/um2 "
                  f"NFmin(290K)={row['nfmin_db_t290']:.3f} dB NF50={row['nf50_db_t290']:.3f} dB "
                  f"fT={row['ft_hz'] / 1e9 if row.get('ft_hz') else float('nan'):.1f} GHz "
                  f"{row['gmax_kind']}={row['gmax_db']:.2f} dB K={row['k']:.3f}")
    if failures:
        for f in failures[:20]:
            print(f"FAIL: {f}", file=sys.stderr)
        print(f"smoke: FAILED ({len(failures)} problem(s)); nothing recorded", file=sys.stderr)
        return 1
    print(f"smoke: ok ({len(rows)} rows at {point.corner_id}, reduced sweep); nothing recorded")
    return 0


# ---------------------------------------------------------------------------
# probe (source-noise normalization regression check)
# ---------------------------------------------------------------------------

PROBE_TEMPS_C = (-40.0, 16.85, 27.0, 125.0)


def probe_control_lines() -> list[str]:
    lines = ["set numdgt=10"]
    for t in PROBE_TEMPS_C:
        lines += [f"option temp = {t:g}", f'echo "KP_TEMP {t:g}"']
        for name, out, src in (("ra", "oa", "vpa"), ("rb", "ob", "vpb"), ("rc", "oc", "vpc"),
                               ("qa", "oqa", "vsa"), ("qb", "oqb", "vsb")):
            lines += [
                "destroy all",
                f"noise v({out}) {src} lin 1 19.45e9 19.45e9",
                f"let kp_{name} = inoise_spectrum",
                f"print kp_{name}",
            ]
    return lines


def run_probe(tb, pdk) -> tuple[bool, list[str]]:
    probe_tb = dataclasses.replace(tb, netlist=PROBE_NETLIST, analyses=tuple(probe_control_lines()),
                                   measure={})
    point = build_grid(resolve_corners(["hbt_typ"]), [27.0], [tb.nominal_supply_v])[0]
    workdir = SCRATCH / "probe"
    result = run_point(probe_tb, pdk, point, workdir, num_threads=1)
    text = (workdir / result.log).read_text() if result.log else ""
    values: dict[float, dict[str, float]] = {}
    current = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("KP_TEMP "):
            current = float(line.split()[1])
            values[current] = {}
            continue
        m = kaband._VALUE_RE.match(line)
        if m and current is not None:
            values[current][m.group(1)] = float(m.group(2))
    report, ok = [], True
    k4r = 4 * kaband.K_BOLTZMANN * 50.0
    for t in PROBE_TEMPS_C:
        v = values.get(t, {})
        need = ("kp_ra", "kp_rb", "kp_rc", "kp_qa", "kp_qb")
        if any(n not in v for n in need):
            return False, [f"probe: missing values at {t:g} C ({sorted(v)})"]
        t_k = t + 273.15
        teff_a = v["kp_ra"] ** 2 / k4r
        teff_b = v["kp_rb"] ** 2 / k4r
        a_ok = abs(teff_a - t_k) <= 1e-6 * t_k
        c_ok = v["kp_rc"] == 0.0
        ok &= a_ok and c_ok
        # Part B: textbook (noisy source at ambient) vs this bench's method at T0 = ambient.
        f_text = v["kp_qa"] ** 2 / (k4r * t_k)
        f_anal = 1 + v["kp_qb"] ** 2 / (k4r * t_k)
        agree = abs(f_text - f_anal) <= 1e-6 * f_anal
        ok &= agree
        f_anal_290 = 1 + v["kp_qb"] ** 2 / (k4r * 290.0)
        f_text_as_290 = v["kp_qa"] ** 2 / (k4r * 290.0)
        report.append(
            f"T={t:g} C ({t_k:.2f} K): plain R T_eff={teff_a:.4f} K [{'ok' if a_ok else 'FAIL'}]; "
            f"temp=27 R T_eff={teff_b:.4f} K (observation, not relied on); "
            f"noisy=0 R inoise={v['kp_rc']:.3g} [{'ok' if c_ok else 'FAIL'}]; "
            f"DUT NF50 textbook(source at {t_k:.2f} K)={10 * math.log10(f_text):.6f} dB vs "
            f"analytic(T0={t_k:.2f} K)={10 * math.log10(f_anal):.6f} dB [{'ok' if agree else 'FAIL'}]; "
            f"analytic at T0=290 K={10 * math.log10(f_anal_290):.6f} dB vs textbook misread as 290 K="
            f"{10 * math.log10(f_text_as_290):.6f} dB"
        )
    return ok, report


def cmd_probe(args) -> int:
    tb, _ = _load()
    ok, report = run_probe(tb, _pdk())
    print(f"ngspice: {ngspice_version()}")
    for line in report:
        print("  " + line)
    print("probe: ok" if ok else "probe: FAILED")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# selftest (negative controls)
# ---------------------------------------------------------------------------

SENSITIVE_KEYS = ("ic_a", "ft_hz", "nfmin_db_t290", "gmax_db")


def _by_bias(rows):
    out = {}
    for r in rows:
        if r.get("status") == "ok":
            out.setdefault((r["nx"], r["vce_set_v"], r["vbe_set_v"], r["freq_index"]), {})[r["corner_id"]] = r
    return out


def process_spread(rows) -> dict[str, float]:
    """Max relative spread across process corners of each sensitive quantity
    at a fixed bias point and frequency."""
    spread = {k: 0.0 for k in SENSITIVE_KEYS}
    for per_corner in _by_bias(rows).values():
        for key in SENSITIVE_KEYS:
            vals = [r[key] for r in per_corner.values() if r.get(key) is not None]
            if len(vals) >= 2:
                mean = sum(vals) / len(vals)
                if mean:
                    spread[key] = max(spread[key], (max(vals) - min(vals)) / abs(mean))
    return spread


def cmd_selftest(args) -> int:
    tb, manifest = _load()
    sweep = kaband.sweep_from_manifest(manifest, "reduced")
    pdk = _pdk()
    failures: list[str] = []

    print("[1/4] source-noise normalization probe")
    ok, report = run_probe(tb, pdk)
    for line in report:
        print("      " + line)
    if not ok:
        failures.append("probe failed")

    normal = resolve_corners(list(tb.corners))
    temps, supply = [27.0], [tb.nominal_supply_v]
    for label, corners in (("normal", normal), ("sabotaged", sabotage(normal))):
        print(f"[{2 if label == 'normal' else 3}/4] {label} process corners "
              f"({', '.join(c.name for c in corners)}) @ 27 C / {tb.nominal_supply_v} V, reduced sweep")
        rows = []
        for point in build_grid(corners, temps, supply):
            r, problems, _ = _run_local(tb, pdk, point, sweep, SCRATCH / "selftest" / label)
            bad = row_failures(r, problems, sweep)
            if bad:
                failures.append(f"{label} run at {point.corner_id} invalid: {bad[0]}")
            rows += r
        spread = process_spread(rows)
        print("      max relative process spread: "
              + ", ".join(f"{k}={v:.3g}" for k, v in spread.items()))
        if label == "normal" and not all(v > 1e-3 for v in spread.values()):
            failures.append(f"normal run: process corners did not move every quantity {spread}")
        if label == "sabotaged" and any(v != 0.0 for v in spread.values()):
            failures.append(f"sabotaged run still shows process sensitivity {spread} -- "
                            "corner switching is not what makes the normal run differ")

    print("[4/4] deliberately invalid deck (a required op quantity reads a nonexistent field)")
    point = build_grid(resolve_corners(["hbt_typ"]), temps, supply)[0]
    r, problems, _ = _run_local(tb, pdk, point, sweep, SCRATCH / "selftest" / "invalid",
                                sabotage_measurement=True)
    bad = row_failures(r, problems, sweep)
    if bad:
        print(f"      rejected as expected: {bad[0]}")
    else:
        failures.append("invalid deck was NOT rejected -- missing measurements would pass silently")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print("selftest: ok (probe, process sensitivity, sabotage collapse, invalid-deck rejection)")
    return 0


# ---------------------------------------------------------------------------
# characterize (full grid via klt sim) / ingest
# ---------------------------------------------------------------------------


def klt_body(tb, sweep, vdd: float) -> str:
    """A self-contained klt sim circuit body for one supply value: the
    fixture text plus the generated sweep as the body's own .control block.

    NOTE: docs/cli/sim.md of klayout-tools states a body must carry no
    .control block of its own; ngspice nonetheless executes it (before
    klt's own block), and klt keeps the log. This is the documented-
    unsupported path the README's friction note describes."""
    lines = [
        f"* {tb.name}: klt sim body, supply {vdd:.2f} V -- GENERATED by run.py, do not edit",
        f".param vdd_val={vdd!r}",
        "",
        tb.netlist.read_text(),
        "",
        ".control",
        *kaband.build_control_lines(sweep),
        ".endc",
        "",
    ]
    return "\n".join(lines)


def klt_request(body_name: str, corners, temps, backend: str, timeout_s: int,
                stage_models: bool = True, runner_version_check: str = "") -> dict:
    """One klt sim request (9 process x temperature corners at one supply).

    klt's own trailing analysis is a 2 ps transient whose only purpose is a
    sentinel `.meas` of the supply rail (so klt grades every corner on a
    real value). A `.meas tran` card -- not an `expr` measurement -- keeps
    the request valid for older klt clients/runners too, and the body's
    sweep runs no transient, so the card never fires inside it."""
    req = {
        "netlist": body_name,
        "backend": backend,
        "models": {"pdk": "ihp-sg13g2", "lib": "libs.tech/ngspice/models/cornerHBT.lib"},
        "corners": {"process": [c.name for c in corners], "temperature_c": list(temps)},
        "analysis": {"kind": "tran", "args": "1p 2p"},
        "measurements": [
            {"name": "ka_rail_v", "spice": ".meas tran ka_rail_v FIND v(vsupply) AT=2p", "unit": "V"},
        ],
        "options": {"timeout_s": timeout_s, "keep_artifacts": True},
    }
    if stage_models:
        req["options"]["stage_model_inputs"] = True
    if backend == "batch" and runner_version_check:
        req["batch"] = {"runner_version_check": runner_version_check}
    return req


def cmd_characterize(args) -> int:
    tb, manifest = _load()
    sweep = kaband.sweep_from_manifest(manifest, args.profile)
    corners = resolve_corners(args.only_corner.split(",") if args.only_corner else list(tb.corners))
    supplies = supply_points(tb.nominal_supply_v, tb.supply_tolerance)
    temps = list(tb.temperatures_c)
    if args.only_supply:
        supplies = [float(v) for v in args.only_supply.split(",")]
    if args.only_temp:
        temps = [float(t) for t in args.only_temp.split(",")]
    if args.profile != "full" or args.only_corner or args.only_supply or args.only_temp:
        print("NOTE: subset/reduced run -- ingest will refuse to write a record for it "
              "(the record must cover the declared full grid).", flush=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    work = (SCRATCH / f"klt-{stamp}").resolve()
    work.mkdir(parents=True, exist_ok=True)
    reports = []
    for vdd in supplies:
        tag = f"{vdd:.2f}v"
        body = work / f"body_{tag}.spice"
        body.write_text(klt_body(tb, sweep, vdd))
        req = work / f"request_{tag}.json"
        req.write_text(json.dumps(klt_request(body.name, corners, temps, args.backend,
                                              args.timeout_s, stage_models=not args.no_stage_models,
                                              runner_version_check=args.runner_version_check),
                                  indent=2) + "\n")
        out = work / f"out_{tag}"  # absolute: klt runs ngspice with cwd=<corner dir>
        resp = work / f"report_{tag}.json"
        cmd = shlex.split(args.klt_cmd) + ["sim", str(req), "--backend", args.backend, "-o", str(out),
                                           "--format", "json"]
        print("$ " + " ".join(cmd), flush=True)
        if args.dry_run:
            continue
        with resp.open("w") as fh:
            proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, text=True)
        if proc.stderr:
            (work / f"stderr_{tag}.log").write_text(proc.stderr)
        print(f"  klt exit {proc.returncode}; report {resp}", flush=True)
        if proc.returncode not in (0,):
            print(proc.stderr[-4000:], file=sys.stderr)
            print(f"characterize: klt sim failed for supply {tag} (exit {proc.returncode}); "
                  "no record written. Requests/bodies kept under " + str(work), file=sys.stderr)
            return 1
        reports.append((vdd, resp))
    if args.dry_run:
        print(f"--dry-run: requests and bodies written under {work}; nothing submitted")
        return 0
    return ingest(tb, sweep, reports, args, work)


def cmd_ingest(args) -> int:
    tb, manifest = _load()
    sweep = kaband.sweep_from_manifest(manifest, "full")
    reports = []
    for path in args.reports:
        path = Path(path).resolve()
        body = path.with_name(path.name.replace("report_", "body_").replace(".json", ".spice"))
        vdd = _body_supply(body)
        reports.append((vdd, path))
    return ingest(tb, sweep, reports, args, Path(args.reports[0]).resolve().parent)


def _body_supply(body: Path) -> float:
    for line in body.read_text().splitlines():
        if line.startswith(".param vdd_val="):
            return float(line.split("=", 1)[1])
    raise SystemExit(f"error: no .param vdd_val in {body}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pdk_provenance(pdk) -> dict:
    models_dir = pdk.model_lib.parent
    prov = {
        "variant_path": str(pdk.path),
        "fetched_version_file": None,
        "model_sha256": {name: _sha256(models_dir / name) for name in MODEL_FILES
                         if (models_dir / name).is_file()},
    }
    fv = pdk.path / ".fetched-version"
    if fv.is_file():
        prov["fetched_version_file"] = fv.read_text().strip()
    return prov


#: Agreement required between the off-host result and a local re-simulation
#: of the same nominal PVT point. Same deck + same model files + same
#: ngspice major version should agree to rounding; a different PDK revision
#: on the runner would not.
CROSSCHECK_TOL = {"nfmin_db_t290": 1e-6, "gmax_db": 1e-6, "ic_rel": 1e-9, "ft_rel": 1e-9}


def local_crosscheck(tb, sweep, pdk, rows: list[dict]) -> dict:
    """Re-simulate the nominal PVT point (one local ngspice process) and
    compare it, bias point by bias point, with the off-host rows for the same
    point. This is what ties the off-host data to THIS host's recorded model
    files: klt's runner may resolve the PDK from its own image."""
    point = build_grid(resolve_corners(["hbt_typ"]), [27.0], [tb.nominal_supply_v])[0]
    local, problems, _ = _run_local(tb, pdk, point, sweep, SCRATCH / "crosscheck")
    remote = {(r["nx"], r["vce_set_v"], r["vbe_set_v"], r["freq_index"]): r
              for r in rows if r["corner_id"] == point.corner_id}
    worst = {"nfmin_db_t290": 0.0, "gmax_db": 0.0, "ic_rel": 0.0, "ft_rel": 0.0}
    compared = 0
    for r in local:
        o = remote.get((r["nx"], r["vce_set_v"], r["vbe_set_v"], r["freq_index"]))
        if o is None:
            problems.append(f"no off-host row for {r['nx']}/{r['vce_set_v']}/{r['vbe_set_v']}")
            continue
        if o["status"] != r["status"]:
            problems.append(f"status differs at {r['nx']}/{r['vce_set_v']}/{r['vbe_set_v']}: "
                            f"{o['status']} vs local {r['status']}")
            continue
        if r["status"] != "ok":
            continue
        compared += 1
        worst["nfmin_db_t290"] = max(worst["nfmin_db_t290"], abs(o["nfmin_db_t290"] - r["nfmin_db_t290"]))
        worst["gmax_db"] = max(worst["gmax_db"], abs(o["gmax_db"] - r["gmax_db"]))
        worst["ic_rel"] = max(worst["ic_rel"], abs(o["ic_a"] - r["ic_a"]) / r["ic_a"])
        if o.get("ft_hz") and r.get("ft_hz"):
            worst["ft_rel"] = max(worst["ft_rel"], abs(o["ft_hz"] - r["ft_hz"]) / r["ft_hz"])
    for key, tol in CROSSCHECK_TOL.items():
        if worst[key] > tol:
            problems.append(f"off-host vs local max |d{key}| = {worst[key]:.3g} > {tol:g}")
    summary = (f"{compared} rows compared; max |dNFmin| {worst['nfmin_db_t290']:.3g} dB, "
               f"max |dGmax| {worst['gmax_db']:.3g} dB, max |dIc|/Ic {worst['ic_rel']:.3g}, "
               f"max |dfT|/fT {worst['ft_rel']:.3g}")
    return {"corner_id": point.corner_id, "compared": compared, "worst": worst,
            "summary": summary, "problems": problems, "tolerances": CROSSCHECK_TOL}


def ingest(tb, sweep, reports: list[tuple[float, Path]], args, work: Path) -> int:
    pdk = _pdk()
    started = _dt.datetime.now(_dt.timezone.utc)
    git = git_provenance(REPO_ROOT)
    all_rows: list[dict] = []
    problems: list[str] = []
    logs: dict[str, Path] = {}
    messages: dict[str, dict[str, int]] = {}
    klt_meta = []
    expected_ids = {
        p.corner_id for p in build_grid(resolve_corners(list(tb.corners)), tb.temperatures_c,
                                        supply_points(tb.nominal_supply_v, tb.supply_tolerance))
    }
    for vdd, resp_path in reports:
        report = json.loads(resp_path.read_text())
        if "corners" not in report:
            problems.append(f"{resp_path.name}: no corners in klt report ({report.get('error')})")
            continue
        klt_meta.append({
            "supply_v": vdd,
            "report": resp_path.name,
            "status": report.get("status"),
            "environment": report.get("environment", {}),
        })
        for corner in report["corners"]:
            point = PvtPoint(corner=CORNERS[corner["process"]], temp_c=float(corner["temperature_c"]),
                             vdd=float(vdd))
            log = (corner.get("artifacts") or {}).get("log")
            if not log:
                problems.append(f"{point.corner_id}: klt returned no log ({corner.get('diagnostics')})")
                continue
            log_path = Path(log)
            if not log_path.is_absolute():
                log_path = (resp_path.parent / log_path).resolve()
            text = log_path.read_text()
            rows, log_problems = kaband.analyze_log(text, sweep, point.temp_c)
            problems += [f"{point.corner_id}: {p}" for p in log_problems]
            for row in rows:
                row.update(corner=point.corner.name, temp_c=point.temp_c, vdd_v=point.vdd,
                           corner_id=point.corner_id)
            all_rows += rows
            logs[point.corner_id] = log_path
            messages[point.corner_id] = kaband.log_messages(text)
    missing = sorted(expected_ids - set(logs))
    if missing:
        problems.append("missing PVT points: " + ", ".join(missing))
    if problems:
        for p in problems[:40]:
            print(f"FAIL: {p}", file=sys.stderr)
        print("ingest: grid incomplete or invalid; NO record written", file=sys.stderr)
        return 1

    crosscheck = local_crosscheck(tb, sweep, pdk, all_rows)
    print(f"local cross-check at {crosscheck['corner_id']}: {crosscheck['summary']}")
    if crosscheck["problems"]:
        for p in crosscheck["problems"]:
            print(f"FAIL: {p}", file=sys.stderr)
        print("ingest: the off-host results do not reproduce on this host's model files/simulator; "
              "NO record written (the record's PDK provenance would be wrong)", file=sys.stderr)
        return 1
    client = subprocess.run(shlex.split(args.klt_cmd) + ["--version"], capture_output=True, text=True)
    for m in klt_meta:
        m["client"] = f"{args.klt_cmd} -> {(client.stdout or client.stderr).strip()}"

    record_id = allocate_record_id(REPO_ROOT, RECORDS, started, git)
    for path in (RECORDS / f"{record_id}.md", CORNER_LOGS / record_id, SNAPSHOTS / record_id):
        if path.exists():
            raise RecordExists(f"{path} exists; append-only evidence is never rewritten")
    (CORNER_LOGS / record_id).mkdir(parents=True)
    for corner_id, path in sorted(logs.items()):
        # ~3 MB of ngspice text per PVT point; gzip keeps the full log (zcat
        # to read) at ~1/9 the size. mtime=0 makes the archive reproducible.
        with path.open("rb") as src, (CORNER_LOGS / record_id / f"{corner_id}.log.gz").open("wb") as raw, \
                gzip.GzipFile(filename=f"{corner_id}.log", mode="wb", fileobj=raw, mtime=0) as dst:
            shutil.copyfileobj(src, dst)
    (SNAPSHOTS / record_id).mkdir(parents=True)
    for vdd, resp_path in reports:
        tag = f"{vdd:.2f}v"
        for name in (f"body_{tag}.spice", f"request_{tag}.json"):
            src = resp_path.parent / name
            if src.is_file():
                shutil.copyfile(src, SNAPSHOTS / record_id / name)
        shutil.copyfile(resp_path, SNAPSHOTS / record_id / f"klt-report_{tag}.json")

    import report_kaband  # local module: record rendering

    md, sidecars = report_kaband.render(
        record_id=record_id, tb=tb, sweep=sweep, rows=all_rows, started=started, git=git,
        ngspice=ngspice_version(), pdk_prov=pdk_provenance(pdk), klt_meta=klt_meta,
        claim=args.claim or tb.claim, supersedes=args.supersedes or "", crosscheck=crosscheck,
        messages=messages,
    )
    RECORDS.mkdir(parents=True, exist_ok=True)
    for name, (header, table) in sidecars.items():
        if name == "points":  # every row of the sweep: ~28k rows, gzip-compressed
            raw = (RECORDS / f"{record_id}-{name}.csv.gz").open("wb")
            fh = io.TextIOWrapper(gzip.GzipFile(filename=f"{record_id}-{name}.csv", mode="wb",
                                                fileobj=raw, mtime=0), newline="")
        else:
            raw, fh = None, (RECORDS / f"{record_id}-{name}.csv").open("w", newline="")
        with fh:
            writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(table)
        if raw is not None:
            raw.close()
    (RECORDS / f"{record_id}.md").write_text(md)
    print(f"wrote {RECORDS / f'{record_id}.md'} (+ sidecars, corners/{record_id}/, "
          f"netlist-snapshots/{record_id}/)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("smoke").set_defaults(func=cmd_smoke)
    sub.add_parser("selftest").set_defaults(func=cmd_selftest)
    sub.add_parser("probe").set_defaults(func=cmd_probe)
    pc = sub.add_parser("characterize")
    pc.add_argument("--klt-cmd", default="klt",
                    help='klt client command, e.g. "uvx --from klayout-tools==0.5.0 klt" to match the '
                         "batch fleet runner's klt version (a runner/client mismatch is refused)")
    pc.add_argument("--backend", default="batch",
                    help="klt sim backend (default batch; local/local-parallel for a workstation)")
    pc.add_argument("--timeout-s", type=int, default=3600, help="klt per-corner timeout")
    pc.add_argument("--no-stage-models", action="store_true",
                    help="do not set options.stage_model_inputs (a runner older than the client cannot "
                         "resolve staged model names); the runner then uses its image's PDK, and "
                         "ingest's local cross-check decides whether that matches this host's")
    pc.add_argument("--runner-version-check", default="", choices=("", "enforce", "warn"),
                    help="request.batch.runner_version_check (klt default: enforce). 'warn' runs on a "
                         "fleet runner whose klt differs from the client's and records the skew; the "
                         "record is still gated on the local cross-check (see README)")
    pc.add_argument("--claim", default="")
    pc.add_argument("--supersedes", default="")
    pc.add_argument("--dry-run", action="store_true", help="write requests/bodies, submit nothing")
    pc.add_argument("--profile", default="full", choices=("full", "reduced"),
                    help="bias sweep profile (anything but full can never become a record)")
    pc.add_argument("--only-corner", default="", help="debug subset (never a record)")
    pc.add_argument("--only-temp", default="", help="debug subset (never a record)")
    pc.add_argument("--only-supply", default="", help="debug subset (never a record)")
    pc.set_defaults(func=cmd_characterize)
    pi = sub.add_parser("ingest")
    pi.add_argument("reports", nargs="+", help="klt report_<supply>.json files from characterize")
    pi.add_argument("--klt-cmd", default="klt", help="client that produced the reports (version recorded)")
    pi.add_argument("--claim", default="")
    pi.add_argument("--supersedes", default="")
    pi.set_defaults(func=cmd_ingest)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except NgspiceMissing as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
