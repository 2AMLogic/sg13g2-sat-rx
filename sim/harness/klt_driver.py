"""Shared plumbing for the per-study ``klt sim`` drivers.

The Ka-band, LNA S-parameter/NF and mixer-topology studies each express their
grid as ``klt sim`` requests and ingest the returned logs. The mechanical
helpers below were hand-copied into each driver; they live here once so a fix
(e.g. to ``stage_model_inputs`` / ``runner_version_check`` handling) cannot
drift between studies. Study-specific parts (the body text, the sentinel
name/node, ``MODEL_FILES``, how corners are named) stay in the drivers, which
keep their historical function names as thin call sites.

Generated request JSON and body text are evidence inputs (their hashes are
cited in ``records/``): changing anything here must keep them byte-identical.

The second half of this module (:func:`run_grid_klt` and its helpers, issue
#134) is the same pattern applied to ``harness.cli run`` itself: a
multi-point harness-native grid is expressed as ``klt sim`` requests (one per
supply value, every process x temperature corner in each), submitted to the
``batch`` fleet, and the returned per-corner logs are parsed back into the
ordinary :class:`runner.PointResult` list the local path produces. Nothing
here writes into the evidence tree; ``cli.cmd_run`` does that only after the
reports have passed the off-host model check.
"""

from __future__ import annotations

import json
import math
import re
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from . import pdkartifact
from .corners import require_unique_corner_ids
from .pdk import PdkConfigError, PdkNotFound, find_pdk
from .provenance import sha256_file


def body_supply(body: Path) -> float:
    """The ``.param vdd_val=`` supply a generated klt body was written for."""
    for line in body.read_text().splitlines():
        if line.startswith(".param vdd_val="):
            return float(line.split("=", 1)[1])
    raise SystemExit(f"error: no .param vdd_val in {body}")


def find_pdk_or_exit(sim_dir: Path, *, require_artifact: bool = False):
    """``find_pdk`` with a clean ``SystemExit``; optionally run the pinned-model
    integrity gate (``pdkartifact.require``) before any simulator launches."""
    try:
        pdk = find_pdk(sim_dir)
    except (PdkNotFound, PdkConfigError) as exc:
        raise SystemExit(f"error: {exc}")
    if require_artifact:
        pdkartifact.require(pdk, sim_dir)
    return pdk


def klt_request(body_name: str, corner_names: Iterable[str], temps: Iterable[float], backend: str,
                timeout_s: int, *, sentinel_name: str, sentinel_node: str,
                stage_models: bool = True, runner_version_check: str = "") -> dict:
    """One klt sim request. klt's own trailing analysis is a 2 ps transient
    whose only purpose is a sentinel ``.meas tran`` of the supply rail, so klt
    grades every corner on a real value (and the request stays valid for older
    klt clients/runners). The body's own deck does the study."""
    req = {
        "netlist": body_name,
        "backend": backend,
        "models": {"pdk": "ihp-sg13g2", "lib": "libs.tech/ngspice/models/cornerHBT.lib"},
        "corners": {"process": list(corner_names), "temperature_c": list(temps)},
        "analysis": {"kind": "tran", "args": "1p 2p"},
        "measurements": [
            {"name": sentinel_name,
             "spice": f".meas tran {sentinel_name} FIND {sentinel_node} AT=2p", "unit": "V"},
        ],
        "options": {"timeout_s": timeout_s, "keep_artifacts": True},
    }
    if stage_models:
        req["options"]["stage_model_inputs"] = True
    if backend == "batch" and runner_version_check:
        req["batch"] = {"runner_version_check": runner_version_check}
    return req


def pdk_provenance(pdk, model_files: Iterable[str]) -> dict:
    """Where the models came from: variant path, install marker, model hashes."""
    models_dir = pdk.model_lib.parent
    prov = {
        "variant_path": str(pdk.path),
        "fetched_version_file": None,
        "model_sha256": {name: sha256_file(models_dir / name) for name in model_files
                         if (models_dir / name).is_file()},
    }
    fv = pdk.path / ".fetched-version"
    if fv.is_file():
        prov["fetched_version_file"] = fv.read_text().strip()
    return prov


# ---------------------------------------------------------------------------
# harness.cli run --backend batch (issue #134)
# ---------------------------------------------------------------------------

#: Sentinel klt grades every corner on (see :func:`klt_request`). Harness
#: fragments drive their supply from ``vdd_val`` on a ``vdd`` node (see
#: testbench.py); a fragment without one gets an explicit klt corner error,
#: never a silent pass.
HARNESS_SENTINEL_NAME = "harness_rail_v"
HARNESS_SENTINEL_NODE = "v(vdd)"
#: ``AVG`` rather than :func:`klt_request`'s ``FIND ... AT=2p``: ngspice
#: evaluates every ``.meas tran`` card after EVERY transient in the deck,
#: including a bench's own ``.control`` ``tran`` (whose saved window may start
#: well after 2 ps, e.g. ``tran 10p 100n 20n``). ``AT=2p`` is then "out of
#: interval" in that first evaluation and klt grades the corner ``error``
#: although the bench's own ``m_*`` values are all in the log. An average over
#: whatever window was saved is valid in both transients.
HARNESS_SENTINEL_SPICE = f".meas tran {HARNESS_SENTINEL_NAME} AVG {HARNESS_SENTINEL_NODE}"
DEFAULT_KLT_TIMEOUT_S = 1800
#: Concurrent ``klt sim`` CLIENT processes. Each only uploads, polls and
#: downloads; the simulation runs on the fleet, never on this host.
MAX_CONCURRENT_SUBMITS = 4

_TEMP_C_RE = re.compile(r"\btemp_c\b")


class KltGridError(RuntimeError):
    """The grid cannot be submitted, or a request returned no usable report.

    Raised before anything is written into the evidence tree. Never a cue to
    fall back to a local grid.
    """


@dataclass
class KltJob:
    """One ``klt sim`` request and what came back for it."""

    key: str
    supply_v: float
    temp_c: float | None
    request: Path
    body: Path
    report_path: Path
    report: dict = field(default_factory=dict)
    exit_code: int | None = None

    @property
    def environment(self) -> dict:
        env = self.report.get("environment") if isinstance(self.report, dict) else None
        return env if isinstance(env, dict) else {}

    def summary(self) -> dict:
        env = self.environment
        remote = env.get("remote") if isinstance(env.get("remote"), dict) else {}
        return {
            "request": self.request.name,
            "report": self.report_path.name,
            "supply_v": self.supply_v,
            "temp_c": self.temp_c,
            "exit_code": self.exit_code,
            "status": self.report.get("status"),
            "engine": env.get("engine"),
            "engine_version": env.get("engine_version"),
            "job_id": remote.get("job_id"),
            "provider": remote.get("provider"),
            "instance_type": remote.get("instance_type"),
            "runner_klt_version": remote.get("runner_klt_version"),
            "client_klt_version": remote.get("client_klt_version"),
            "runner_compatibility": remote.get("runner_compatibility"),
        }


@dataclass
class KltGridResult:
    results: list            # list[runner.PointResult], grid order
    logs: dict[str, str]     # corner_id -> log text (or an explicit stub)
    jobs: list[KltJob]
    workdir: Path

    def execution(self, backend: str, klt_client: str) -> dict:
        """The ``environment.execution`` block for a record."""
        return {
            "backend": backend,
            "via": "klt sim",
            "klt_client": klt_client,
            "workdir": str(self.workdir),
            "jobs": [job.summary() for job in self.jobs],
        }

    def engine_versions(self) -> list[str]:
        return sorted({str(j.environment.get("engine_version")) for j in self.jobs})


def harness_body(tb, vdd: float, temp_c: float | None = None, design_include: Path | None = None) -> str:
    """Self-contained klt circuit body for one supply (and, when the deck
    reads ``temp_c``, one temperature): the PVT params, the fragment text and
    the bench's own ``.control`` block -- the same ``.param``/``.options``/
    analyses/``let m_*``/``print m_*`` lines :func:`runner.compose_deck` emits.
    klt appends the corner's ``.lib`` section and ``.temp``."""
    lines = [
        f"* {tb.name}: klt sim body, supply {vdd:.2f} V"
        + (f", {temp_c:g} C" if temp_c is not None else "")
        + " -- GENERATED by sim/harness, do not edit",
        f".param vdd_nom={tb.nominal_supply_v!r}",
        f".param vdd_val={vdd!r}",
    ]
    if temp_c is not None:
        lines.append(f".param temp_c={temp_c!r}")
    lines += [f".param {k}={v}" for k, v in tb.params.items()]
    if design_include is not None:
        lines.append(f'.include "{design_include}"')
    lines += [f".options {o}" for o in tb.options]
    lines += ["", tb.netlist.read_text(), "", ".control", "set numdgt=10", "set noaskquit"]
    lines += [f"  {a}" for a in tb.analyses]
    lines += [f"  let m_{n} = {e}" for n, e in tb.measure.items()]
    lines += [f"  print m_{n}" for n in tb.measure]
    lines += [".endc", ""]
    return "\n".join(lines)


def deck_reads_temp_c(tb) -> bool:
    """Does anything in the deck reference the ``temp_c`` parameter? If so a
    request cannot span temperatures (one body per supply x temperature)."""
    texts = [tb.netlist.read_text(), *tb.analyses, *tb.measure.values(),
             *(str(v) for v in tb.params.values()), *tb.options]
    return any(_TEMP_C_RE.search(t) for t in texts)


def klt_process_names(points) -> dict[str, object]:
    """klt process name (the corner's ``.lib`` section) -> harness Corner.

    klt selects one ``.lib`` section per process corner, so a corner with
    several sections, or two corners sharing a section (e.g. a
    ``corners.sabotage`` set), cannot be expressed: refused with
    :class:`KltGridError` rather than mislabelled."""
    by_section: dict[str, object] = {}
    for point in points:
        corner = point.corner
        if len(corner.sections) != 1:
            raise KltGridError(
                f"corner {corner.name!r} selects {len(corner.sections)} model sections "
                f"{list(corner.sections)}; a klt sim request selects exactly one per process "
                "corner. Run it with --backend local.")
        section = corner.sections[0]
        known = by_section.get(section)
        if known is not None and known.name != corner.name:
            raise KltGridError(
                f"corners {known.name!r} and {corner.name!r} both select section {section!r}; "
                "their klt results could not be told apart. Run it with --backend local.")
        by_section[section] = corner
    return by_section


class CollectionError(RuntimeError):
    """A study collection is corrupt or incomplete: exit non-zero, write nothing."""


def submit_request(req: Path, report: Path, key: str, backend: str, klt_cmd: str,
                   work: Path) -> Path:
    """Strict one-request ``klt sim`` for the per-study collect drivers.

    Reuses *report* when it already holds ``corners`` (an interrupted
    collection resumes). Otherwise runs the request on the explicit *backend*,
    writes ``stderr_<key>.log`` into *work*, and on any non-zero exit renames
    the report to ``report_<key>.failed.json`` and raises
    :class:`CollectionError` -- there is no local fallback. Unlike
    :func:`submit` (the grid runner) exit 3/4 is a failure here.
    """
    if report.is_file():
        try:
            if "corners" in json.loads(report.read_text()):
                print(f"  reuse {report.name}", flush=True)
                return report
        except ValueError:
            pass
    out = (work / f"out_{key}").resolve()
    cmd = shlex.split(klt_cmd) + ["sim", str(req), "--backend", backend, "-o", str(out),
                                  "--format", "json"]
    print("$ " + " ".join(cmd), flush=True)
    with report.open("w") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, text=True)
    if proc.stderr:
        (work / f"stderr_{key}.log").write_text(proc.stderr)
    if proc.returncode != 0:
        report.rename(work / f"report_{key}.failed.json")
        raise CollectionError(f"klt sim failed for {key} (exit {proc.returncode}, backend "
                              f"{backend}): {proc.stderr[-3000:]}")
    return report


def submit(job: KltJob, backend: str, klt_cmd: str = "klt") -> KltJob:
    """Run one ``klt sim`` request; fill ``job.report``/``job.exit_code``.

    Raises :class:`KltGridError` when klt did not run the request at all
    (exit 1/2, or no ``corners`` in the JSON). Exit 3/4 still carries a
    per-corner report; those corners are graded by :func:`collect`."""
    out = job.request.parent / f"out_{job.key}"
    cmd = shlex.split(klt_cmd) + ["sim", str(job.request), "--backend", backend,
                                  "-o", str(out), "--format", "json"]
    print("$ " + " ".join(cmd), flush=True)
    with job.report_path.open("w") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, text=True, check=False)
    job.exit_code = proc.returncode
    if proc.stderr:
        (job.request.parent / f"stderr_{job.key}.log").write_text(proc.stderr)
    try:
        job.report = json.loads(job.report_path.read_text() or "null")
    except ValueError:
        job.report = None
    if not isinstance(job.report, dict) or not isinstance(job.report.get("corners"), list):
        err = job.report.get("error") if isinstance(job.report, dict) else None
        raise KltGridError(
            f"klt sim returned no usable report for {job.key} (exit {proc.returncode}, backend "
            f"{backend}): {err or proc.stderr.strip()[-3000:] or 'empty output'}")
    print(f"  {job.key}: klt exit {proc.returncode}, status {job.report.get('status')}, "
          f"job {((job.report.get('environment') or {}).get('remote') or {}).get('job_id')}",
          flush=True)
    return job


def build_jobs(tb, pdk, points, workdir: Path, backend: str, timeout_s: int,
               runner_version_check: str = "", stage_models: bool = True) -> list[KltJob]:
    """Write one body + request per supply (per supply x temperature when the
    deck reads ``temp_c``). Returns the jobs; submits nothing."""
    # Artifact-identity gate (issue #150): before any body/request/report
    # file is written, let alone submitted -- see corners.require_unique_corner_ids.
    require_unique_corner_ids(points)
    by_section = klt_process_names(points)
    sections = list(by_section)
    per_temp = deck_reads_temp_c(tb)
    groups: dict[tuple, list] = {}
    for point in points:
        key = (point.vdd, point.temp_c if per_temp else None)
        groups.setdefault(key, []).append(point)
    try:
        model_lib = str(pdk.model_lib.relative_to(pdk.path))
    except ValueError:
        model_lib = str(pdk.model_lib)
    workdir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for (vdd, temp), group in groups.items():
        key = f"{vdd:.2f}v" + (f"_{temp:g}c" if temp is not None else "")
        body = workdir / f"body_{key}.spice"
        body.write_text(harness_body(tb, vdd, temp, pdk.design_include))
        group_sections = [s for s in sections if any(p.corner.sections[0] == s for p in group)]
        temps = sorted({p.temp_c for p in group})
        req = klt_request(body.name, group_sections, temps, backend, timeout_s,
                          sentinel_name=HARNESS_SENTINEL_NAME, sentinel_node=HARNESS_SENTINEL_NODE,
                          stage_models=stage_models, runner_version_check=runner_version_check)
        req["models"]["lib"] = model_lib
        req["measurements"][0]["spice"] = HARNESS_SENTINEL_SPICE
        request = workdir / f"request_{key}.json"
        request.write_text(json.dumps(req, indent=2) + "\n")
        jobs.append(KltJob(key=key, supply_v=vdd, temp_c=temp, request=request, body=body,
                           report_path=workdir / f"report_{key}.json"))
    return jobs


def _corner_log(corner: dict, report_path: Path) -> str | None:
    log = (corner.get("artifacts") or {}).get("log")
    if not log:
        return None
    path = Path(log)
    if not path.is_absolute():
        path = (report_path.parent / path).resolve()
    return path.read_text() if path.is_file() else None


def collect(tb, points, jobs: list[KltJob], parse: Callable[[str], dict]) -> tuple[list, dict]:
    """Grade every requested PVT point from the klt reports.

    Every point gets a :class:`runner.PointResult` and a log text. A point
    the reports do not cover, a corner klt graded ``error``, a missing log,
    or a missing / non-finite measurement is an explicit ``error``/``failed``
    result with a message -- never dropped. A PVT identity the reports
    return more than once -- inside one report, or across two jobs claiming
    the same point -- is refused as ambiguous rather than graded, so entry
    order can never change the verdict (issue #139). A returned corner whose
    ``temperature_c`` does not parse as a finite number has no gradeable
    identity at all: :class:`KltGridError` names the request and the
    malformed identity before anything is published.
    """
    from .runner import PointResult  # local import: runner has no klt dependency

    by_section = klt_process_names(points)
    found: dict[str, list[tuple[KltJob, dict]]] = {}
    stray: list[tuple[float, str]] = []  # (supply, identity) the requests never asked for
    for job in jobs:
        for corner in job.report.get("corners") or []:
            if not isinstance(corner, dict):
                raise KltGridError(
                    f"{job.report_path.name} (request {job.key}) returned a corner entry that "
                    f"is not an object ({corner!r}); its PVT identity cannot be graded")
            c = by_section.get(str(corner.get("process")))
            if c is None:
                stray.append((job.supply_v,
                              f"process {corner.get('process')!r} in {job.report_path.name}"))
                continue
            try:
                temp = float(corner.get("temperature_c"))
            except (TypeError, ValueError):
                temp = math.nan
            if not math.isfinite(temp):
                raise KltGridError(
                    f"{job.report_path.name} (request {job.key}) returned a corner with process "
                    f"{c.name!r} whose temperature_c {corner.get('temperature_c')!r} is not a "
                    f"finite number (supply {job.supply_v:.2f} V); its PVT identity cannot "
                    "be graded")
            cid = f"{c.name}_{temp:g}c_{job.supply_v:.2f}v"
            found.setdefault(cid, []).append((job, corner))

    results, logs = [], {}
    for point in points:
        cid = point.corner_id
        hits = found.get(cid)
        if not hits:
            msg = "klt sim returned no result for this point"
            stray_here = [what for supply, what in stray if supply == point.vdd]
            if stray_here:
                msg += ("; the reports also carried corners matching no requested process ("
                        + ", ".join(stray_here[:3]) + ")")
            logs[cid] = f"KLT SIM: {msg}\n"
            results.append(PointResult(point=point, status="error", log=f"{cid}.log", message=msg))
            continue
        if len(hits) > 1:
            detail = "; ".join(f"{j.report_path.name} status {str(c.get('status'))!r}"
                               for j, c in hits)
            msg = (f"klt sim returned {len(hits)} corners for PVT identity {cid} ({detail}); "
                   "the identity is repeated, so which entry is this point's result would "
                   "be ambiguous -- refusing to grade it")
            logs[cid] = f"KLT SIM: {msg}\n"
            results.append(PointResult(point=point, status="error", log=f"{cid}.log", message=msg))
            continue
        job, corner = hits[0]
        seconds = float(corner.get("runtime_s") or 0.0)
        text = _corner_log(corner, job.report_path)
        diag = corner.get("diagnostics")
        if text is None:
            msg = f"klt sim returned no log (corner status {corner.get('status')!r}; diagnostics {diag})"
            logs[cid] = f"KLT SIM: {msg}\n"
            results.append(PointResult(point=point, status="error", seconds=seconds,
                                       deck=job.body.name, log=f"{cid}.log", message=msg))
            continue
        logs[cid] = text
        meas = parse(text)
        missing = [n for n in tb.measure if n not in meas or not math.isfinite(meas[n])]
        measurements = {n: meas[n] for n in tb.measure if n in meas and math.isfinite(meas[n])}
        if corner.get("status") == "error":
            results.append(PointResult(
                point=point, status="error", measurements=measurements, missing=missing,
                seconds=seconds, deck=job.body.name, log=f"{cid}.log",
                message=f"klt sim graded this corner 'error' (diagnostics {diag})"))
        elif missing:
            results.append(PointResult(
                point=point, status="failed", measurements=measurements, missing=missing,
                seconds=seconds, deck=job.body.name, log=f"{cid}.log",
                message=f"missing or non-finite measurements {missing} in the klt log"))
        else:
            results.append(PointResult(point=point, status="ok", measurements=measurements,
                                       seconds=seconds, deck=job.body.name, log=f"{cid}.log"))
    return results, logs


def run_grid_klt(tb, pdk, points, workdir: Path, backend: str = "batch",
                 timeout_s: int = DEFAULT_KLT_TIMEOUT_S, klt_cmd: str = "klt",
                 runner_version_check: str = "", stage_models: bool = True,
                 submit_fn: Callable[..., KltJob] | None = None) -> KltGridResult:
    """Run a harness PVT grid through ``klt sim`` and parse it back.

    Writes bodies/requests/reports only under ``workdir`` (scratch). Raises
    :class:`KltGridError` if any request returns no usable report; the caller
    must then record nothing (no local fallback).

    ``runner_version_check`` is passed through to the request's ``batch``
    block (klt's runner/client skew policy). ``warn`` lets a skewed runner
    run the grid, but its results then fail ``pdkartifact.verify_job_models``
    (runner_compatibility != match), so only a ``--no-write`` method check
    can use them. ``stage_models=False`` likewise leaves the runner's models
    unhashed (method checks only; ``cli.cmd_run`` refuses it for a record)."""
    from .runner import parse_measurements

    submit_fn = submit_fn or submit  # looked up at call time (tests patch it)
    jobs = build_jobs(tb, pdk, points, workdir, backend, timeout_s, runner_version_check, stage_models)
    with ThreadPoolExecutor(max_workers=max(1, min(MAX_CONCURRENT_SUBMITS, len(jobs)))) as pool:
        futures = [pool.submit(submit_fn, job, backend, klt_cmd) for job in jobs]
        errors = []
        for future in futures:
            try:
                future.result()
            except KltGridError as exc:
                errors.append(str(exc))
    if errors:
        raise KltGridError("\n".join(errors) + f"\n(requests, bodies and any reports kept under {workdir})")
    results, logs = collect(tb, points, jobs, parse_measurements)
    return KltGridResult(results=results, logs=logs, jobs=jobs, workdir=workdir)


def klt_client_version(klt_cmd: str = "klt") -> str:
    try:
        proc = subprocess.run(shlex.split(klt_cmd) + ["--version"], capture_output=True,
                              text=True, check=False)
    except OSError as exc:
        return f"unavailable ({exc})"
    return (proc.stdout or proc.stderr).strip() or "unknown"
