"""Command-line entry point wiring the generic core together.

GENERIC CORE. Three subcommands, each a thin driver over the modules next to
this file:

    list      discover(sim/) and print every experiment with a testbench
    run       load a testbench, resolve the PDK, check toolchain pins,
              build the PVT grid, run it, and (unless --no-write) write an
              append-only Markdown record. --backend picks where the points
              simulate: a multi-point grid defaults to `batch` (klt sim
              requests through harness/klt_driver.py, the same path the study
              drivers use), a single point to `local` (this host's ngspice).
    selftest  run a testbench's default corner set twice -- once normally,
              once sabotaged (corners.sabotage) -- and fail if the sabotaged
              run's per-axis sensitivity does not collapse. This is the
              harness's own negative control; see corners.sabotage's
              docstring for what it catches.

EXTENSION POINT: a block wanting additional CLI flags (e.g.
``--allow-toolchain-drift``'s sibling for a block-specific override, or a
flag surfacing an extension corner set by name) should add a subparser here
that imports and calls into this module's functions rather than duplicating
them -- see gf180-sar-adc's harness/cli.py, which is this file's fuller,
block-specific descendant.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import shutil
import sys
from pathlib import Path

from . import HARNESS_VERSION
from . import toolchain as toolchain_mod
from .corners import (
    CornerIdCollision,
    build_grid,
    require_unique_corner_ids,
    resolve_corners,
    sabotage,
    supply_points,
)
from . import klt_driver
from . import pdkartifact
from .pdk import Pdk, PdkConfigError, PdkNotFound, find_pdk
from .report import (
    RecordExists,
    allocate_record_id,
    axis_sensitivity,
    build_record,
    describe_failure,
    evaluate_checks,
    git_provenance,
    summarize,
    write_manifest_snapshot,
    write_netlist_snapshot,
    write_record,
)
from .runner import DEFAULT_TIMEOUT_S, NgspiceMissing, ngspice_version, run_grid
from .testbench import discover, load

SIM_DIR = Path(__file__).resolve().parent.parent


def cmd_list(args: argparse.Namespace) -> int:
    experiments = discover(SIM_DIR)
    if not experiments:
        print("no experiments with a testbench/tb.json under sim/ yet")
        return 0
    for path in experiments:
        print(path.name)
    return 0


def _resolve_pdk() -> Pdk | None:
    try:
        pdk = find_pdk(SIM_DIR)
    except (PdkNotFound, PdkConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return None
    # Integrity gate: BEFORE any simulator process is launched.
    rep = pdkartifact.verify(pdk, SIM_DIR)
    if not rep.ok:
        print(rep.format() + pdkartifact.REFUSAL, file=sys.stderr)
        return None
    return pdk


def cmd_verify_pdk(args: argparse.Namespace) -> int:
    """Verify the installed IHP models (and optionally ngspice) against the pin."""
    try:
        pdk = find_pdk(SIM_DIR)
    except (PdkNotFound, PdkConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    banner = None
    try:
        banner = ngspice_version()
    except NgspiceMissing:
        pass
    rep = pdkartifact.verify(pdk, SIM_DIR, banner, require_ngspice=args.require_ngspice)
    print(f"pdk: {pdk.path} (via {pdk.source})")
    print(f"ngspice: {banner or 'not found'}")
    print(rep.format())
    print("verify-pdk: OK" if rep.ok else "verify-pdk: FAILED", file=sys.stderr if not rep.ok else sys.stdout)
    return 0 if rep.ok else 1


#: ``--jobs`` above this is refused for a multi-point LOCAL grid: this harness
#: runs on shared hosts, and a wider grid belongs on the batch fleet.
MAX_LOCAL_JOBS = 2
BACKENDS = ("local", "batch")


def resolve_backend(requested: str | None, n_points: int) -> str:
    """``--backend`` as given, else ``batch`` for a multi-point grid and
    ``local`` for a single point (issue #134)."""
    if requested:
        return requested
    return "batch" if n_points > 1 else "local"


def local_jobs_problem(jobs: int, n_points: int) -> str | None:
    """Why ``--jobs`` is refused for a local grid of ``n_points``, or None."""
    if n_points > 1 and jobs > MAX_LOCAL_JOBS:
        return (f"error: --jobs {jobs} would run {min(jobs, n_points)} ngspice processes at once "
                f"on this host; a local multi-point grid allows at most --jobs {MAX_LOCAL_JOBS}. "
                "Send the grid to the batch fleet instead (--backend batch, the default for "
                "more than one point).")
    return None


def select_axis(declared: list[float], requested: str, axis: str) -> list[float]:
    """``--temperatures``/``--supplies``: narrow one PVT axis to a subset of
    the testbench's OWN declared levels (empty ``requested`` keeps them all).

    A level the testbench does not declare is refused (ValueError), so a
    subset run can only drop points of the bench's grid, never invent one.
    """
    if not requested.strip():
        return list(declared)
    chosen: list[float] = []
    for raw in requested.split(","):
        raw = raw.strip()
        try:
            value = float(raw)
        except ValueError:
            raise ValueError(f"--{axis}: {raw!r} is not a number") from None
        match = [d for d in declared if abs(d - value) <= 1e-9 * max(1.0, abs(d))]
        if not match:
            raise ValueError(f"--{axis}: {raw} is not one of the testbench's declared levels "
                             f"({', '.join(f'{d:g}' for d in declared)})")
        if match[0] not in chosen:
            chosen.append(match[0])
    return chosen


SUBSET_REASON_REQUIRED = (
    "error: --temperatures/--supplies narrow the grid to a subset of the testbench's matrix; "
    "an evidence-writing subset run needs --subset-reason saying why (it is printed as the "
    "record's subset Justification)"
)


SMOKE_SUBSET_REJECTION = (
    "error: --smoke-subset only applies to non-recording runs; it requires "
    "--no-write and cannot be combined with an evidence-writing run"
)


def cmd_run(args: argparse.Namespace) -> int:
    # An evidence-writing run must keep every complete-axis check. --sabotage
    # forces --no-write later, but it is not a smoke subset, so require the
    # explicit flag here, before anything is loaded or simulated.
    if args.smoke_subset and not args.no_write:
        print(SMOKE_SUBSET_REJECTION, file=sys.stderr)
        return 2
    try:
        tb = load(args.experiment)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    pdk = _resolve_pdk()
    if pdk is None:
        return 1

    try:
        ngspice = ngspice_version()
    except NgspiceMissing as exc:
        print(str(exc), file=sys.stderr)
        return 1

    pins = toolchain_mod.load_pins(SIM_DIR)
    drifts = toolchain_mod.check(pdk.version, ngspice, sys.version.split()[0], pins)
    if drifts and not args.allow_toolchain_drift:
        print(toolchain_mod.format_drifts(drifts), file=sys.stderr)
        return 3
    tc_summary = toolchain_mod.summary(drifts, pins, allowed=args.allow_toolchain_drift)

    # --corners defaults to the testbench's OWN declared corner set (tb.json's
    # "corners" field), exactly as cmd_selftest below does, NOT to the generic
    # core's global default_corner_set. A block registering its own corner set
    # (see corners.py's SG13G2 HBT extension) would otherwise have a bare
    # `run <experiment>` resolve the built-in five MOS corners, whose .LIB
    # sections its own model fragment does not define -- every point errors out
    # and a status:error record with zero successful measurements is written
    # into the append-only evidence tree.
    corner_names = args.corners.split(",") if args.corners else list(tb.corners)
    corners = resolve_corners(corner_names)
    if args.sabotage:
        corners = sabotage(corners)
        args.no_write = True  # a sabotaged run must never enter the evidence tree

    # An evidence-writing run records the hash-verified artifact identity, and
    # is refused (before any simulation) if the install does not match the pin.
    # --no-write/--sabotage record nothing, so they need no identity.
    pdk_artifact = None
    if not args.no_write:
        try:
            pdk_artifact = pdkartifact.verified_identity(pdk, SIM_DIR)
        except pdkartifact.ArtifactNotVerified as exc:
            print(str(exc), file=sys.stderr)
            return 3

    try:
        temperatures = select_axis(list(tb.temperatures_c), args.temperatures, "temperatures")
        supplies = select_axis(supply_points(tb.nominal_supply_v, tb.supply_tolerance),
                               args.supplies, "supplies")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    narrowed = bool(args.temperatures.strip() or args.supplies.strip())
    if narrowed and not args.no_write and not args.subset_reason.strip():
        print(SUBSET_REASON_REQUIRED, file=sys.stderr)
        return 2
    points = build_grid(corners, temperatures, supplies)

    # Artifact-identity gate (issue #150): distinct points whose corner_id
    # formats to the same string would overwrite each other's decks and logs.
    # Refused before anything is allocated, written or submitted; the local
    # and batch grid paths re-check so their direct callers are covered too.
    try:
        require_unique_corner_ids(points)
    except CornerIdCollision as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    backend = resolve_backend(args.backend, len(points))
    if backend != "local" and args.no_stage_models and not args.no_write:
        # Without staging the runner simulates with its image-baked models and
        # the reports carry no hash of them: the record would be refused after
        # the fleet time was spent, so refuse before submitting anything.
        print("error: --no-stage-models leaves the runner's models unhashed, so no record could "
              "be written; use it only with --no-write", file=sys.stderr)
        return 3
    if backend == "local":
        problem = local_jobs_problem(args.jobs, len(points))
        if problem:
            print(problem, file=sys.stderr)
            return 2
    else:
        try:  # refuse an unexpressible corner set before anything is submitted
            klt_driver.klt_process_names(points)
        except klt_driver.KltGridError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.jobs != 1 or args.num_threads:
            print("note: --jobs/--num-threads are local-only knobs; ignored for --backend "
                  f"{backend}", file=sys.stderr)
    print(f"backend: {backend} ({len(points)} point(s))")

    started = _dt.datetime.now(_dt.timezone.utc)
    git = git_provenance(SIM_DIR.parent)

    # Allocate the record id BEFORE running the grid (not after, as a prior
    # version of this function did) so a real (write) run can log each PVT
    # point straight into sim/<slug>/corners/<record-id>/ -- the directory
    # runner.py's own module docstring already names as "the sim/<slug>/
    # corners/<record-id>/ directory a block's evidence convention should
    # use", and .gitignore already carves an exception out for
    # sim/*/corners/**/*.log on that same assumption. Without this, a real
    # run's raw ngspice logs landed in the disposable `_build` workdir and
    # were never preserved as evidence at all -- only the --no-write/
    # --sabotage scratch path (corners/_scratch) ever populated corners/.
    record_id = allocate_record_id(SIM_DIR.parent, tb.experiment_dir / "records", started, git)

    workdir = Path(args.workdir) if args.workdir else tb.experiment_dir / "_build"
    log_dir = (
        tb.experiment_dir / "corners" / "_scratch" if args.no_write
        else tb.experiment_dir / "corners" / record_id
    )
    execution = {"backend": "local"}
    record_ngspice = ngspice
    if backend == "local":
        timeout_s = args.timeout_s or DEFAULT_TIMEOUT_S
        results = run_grid(
            tb, pdk, points, workdir, jobs=args.jobs, timeout_s=timeout_s, log_dir=log_dir,
            num_threads=args.num_threads,
        )
    else:
        klt_work = (workdir / f"klt-{started.strftime('%Y%m%d-%H%M%S')}").resolve()
        try:
            grid = klt_driver.run_grid_klt(
                tb, pdk, points, klt_work, backend=backend,
                timeout_s=args.timeout_s or klt_driver.DEFAULT_KLT_TIMEOUT_S,
                klt_cmd=args.klt_cmd, runner_version_check=args.runner_version_check,
                stage_models=not args.no_stage_models,
            )
        except klt_driver.KltGridError as exc:
            print(f"error: {exc}", file=sys.stderr)
            print(f"klt sim ({backend}) did not complete; nothing recorded, no local fallback",
                  file=sys.stderr)
            return 1
        results = grid.results
        engines = grid.engine_versions()
        record_ngspice = (f"{', '.join('ngspice-' + e for e in engines)} via klt sim {backend} "
                          f"(recording host: {ngspice})")
        execution = grid.execution(backend, klt_driver.klt_client_version(args.klt_cmd))
        # The off-host engine is the one that produced the numbers: it must
        # satisfy the same pins the local one was checked against.
        remote_drifts = [d for e in engines for d in toolchain_mod.check(
            pdk.version, f"ngspice-{e}", sys.version.split()[0], pins) if d.tool == "ngspice"]
        if remote_drifts and not args.allow_toolchain_drift:
            print(toolchain_mod.format_drifts(remote_drifts), file=sys.stderr)
            print("off-host engine drifts from the pins; nothing recorded", file=sys.stderr)
            return 3
        if not args.no_write:
            # The record's artifact identity is that of the models the off-host
            # jobs received, proven from the reports (issue #103) -- checked
            # BEFORE a single log is copied into corners/<record-id>/.
            try:
                pdk_artifact = pdkartifact.offhost_identity(
                    [(j.report_path.name, j.environment) for j in grid.jobs], SIM_DIR)
            except pdkartifact.ArtifactNotVerified as exc:
                print(str(exc), file=sys.stderr)
                return 3
        log_dir.mkdir(parents=True, exist_ok=True)
        for cid, text in grid.logs.items():
            (log_dir / f"{cid}.log").write_text(text)

    n_ok = sum(1 for r in results if r.status == "ok")
    print(f"{n_ok}/{len(results)} points ok")

    measure_names = list(tb.measure)
    summary = summarize(results, measure_names)
    sensitivity = axis_sensitivity(results, measure_names)
    failures = evaluate_checks(
        tb.checks, results, summary, sensitivity, allow_unswept_axes=args.smoke_subset
    )
    for failure in failures:
        print(f"FAIL: {describe_failure(failure)}", file=sys.stderr)
    for result in results:
        if result.status != "ok":
            print(f"POINT {result.status.upper()}: {result.point.corner_id}: {result.message}",
                  file=sys.stderr)

    if args.no_write:
        print("--no-write (or --sabotage): nothing recorded")
        return 1 if failures or n_ok != len(results) else 0

    # Publication gate: the grid was simulated from the input state captured
    # at load time. If the working manifest or fragment changed (or vanished)
    # meanwhile, refuse to record at all rather than attach a later manifest
    # -- or a mismatched frozen snapshot -- to earlier results.
    drift = tb.working_input_drift()
    if drift:
        print(f"error: {drift}", file=sys.stderr)
        print("refusing to record: the inputs these results were simulated from are no longer "
              "the working ones; restore them (or start a fresh run) so the frozen manifest "
              "snapshot describes the simulated state", file=sys.stderr)
        # corners/<record-id>/ was minted by this run and holds only its
        # per-point logs: on a refusal it was never evidence, and leaving it
        # behind would publish an orphan log package the evidence checker
        # flags. (The _scratch no-write path returns before this gate.)
        shutil.rmtree(log_dir, ignore_errors=True)
        return 1

    wall_seconds = (_dt.datetime.now(_dt.timezone.utc) - started).total_seconds()
    record = build_record(
        tb, pdk, points, results, record_ngspice, SIM_DIR.parent, record_id,
        started.isoformat(), wall_seconds, claim=args.claim or tb.claim,
        supersedes=args.supersedes or "", subset_reason=args.subset_reason.strip(), git=git, toolchain=tc_summary,
        pdk_artifact=pdk_artifact, execution=execution,
    )
    try:
        write_netlist_snapshot(tb, tb.experiment_dir, record_id)
        write_manifest_snapshot(tb, tb.experiment_dir, record_id)
        path = write_record(record, tb.experiment_dir)
    except RecordExists as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {path}")
    return 1 if failures or n_ok != len(results) else 0


def cmd_selftest(args: argparse.Namespace) -> int:
    """Negative-control self-test: sabotaged corners must fail sensitivity."""
    tb = load(args.experiment)
    pdk = _resolve_pdk()
    if pdk is None:
        return 1

    # --corners defaults to the testbench's OWN declared corner set (tb.json's
    # "corners" field) rather than the global default_corner_set -- a block
    # that registers its own corner set (see corners.py's SG13G2 HBT
    # extension) would otherwise always be self-tested against the built-in
    # five-MOS-corner set, which its own fragment does not use at all.
    corner_names = args.corners.split(",") if args.corners else list(tb.corners)
    normal = resolve_corners(corner_names)
    sabotaged = sabotage(normal)
    temperatures = tb.temperatures_c
    supplies = supply_points(tb.nominal_supply_v, tb.supply_tolerance)

    normal_points = build_grid(normal, temperatures, supplies)
    sabotaged_points = build_grid(sabotaged, temperatures, supplies)
    problem = local_jobs_problem(args.jobs, len(normal_points))
    if problem:  # selftest is local-only (a sabotage set has no klt form)
        print(problem, file=sys.stderr)
        return 2

    workdir = Path(args.workdir) if args.workdir else tb.experiment_dir / "_selftest"
    normal_results = run_grid(tb, pdk, normal_points, workdir / "normal", jobs=args.jobs)
    sabotaged_results = run_grid(tb, pdk, sabotaged_points, workdir / "sabotaged", jobs=args.jobs)

    measure_names = list(tb.measure)
    normal_sensitivity = axis_sensitivity(normal_results, measure_names)
    sabotaged_sensitivity = axis_sensitivity(sabotaged_results, measure_names)

    process_moved_normally = any(
        (normal_sensitivity.get(name) or {}).get("process", {}).get("max_pct") not in (None, 0)
        for name in measure_names
    )
    process_moved_sabotaged = any(
        (sabotaged_sensitivity.get(name) or {}).get("process", {}).get("max_pct") not in (None, 0)
        for name in measure_names
    )

    if not process_moved_normally:
        print("FAIL: process corner had no measurable effect even without sabotage — "
              "the corner sweep may not be taking effect at all", file=sys.stderr)
        return 1
    if process_moved_sabotaged:
        print("FAIL: sabotaged run still shows process-corner sensitivity — corner "
              "switching is not taking effect (every corner simulated as typical)",
              file=sys.stderr)
        return 1
    print("ok: corner switching demonstrably changes the simulated result")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sim-harness", description=__doc__)
    parser.add_argument("--version", action="version", version=f"sim-harness-core {HARNESS_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list experiments with a testbench")
    p_list.set_defaults(func=cmd_list)

    p_run = sub.add_parser("run", help="run a testbench's PVT grid")
    p_run.add_argument("experiment", help="sim/<experiment-slug>/ (or its testbench/ dir)")
    p_run.add_argument(
        "--corners", default="",
        help="comma-separated corner or corner-set names (default: the testbench's own tb.json 'corners' field)",
    )
    p_run.add_argument(
        "--backend", choices=BACKENDS, default=None,
        help="where the points simulate: 'batch' submits klt sim requests (default for a "
             "multi-point grid; a failed submit records nothing and never falls back to local), "
             "'local' runs ngspice -b on this host (default for a single point; debug probes)",
    )
    p_run.add_argument("--jobs", type=int, default=1,
                       help=f"local backend only: concurrent ngspice processes (max "
                            f"{MAX_LOCAL_JOBS} for a multi-point grid)")
    p_run.add_argument("--num-threads", type=int, default=0, help="local backend only")
    p_run.add_argument("--timeout-s", type=int, default=0,
                       help=f"per-point timeout (default {DEFAULT_TIMEOUT_S} s local, "
                            f"{klt_driver.DEFAULT_KLT_TIMEOUT_S} s per klt corner)")
    p_run.add_argument("--runner-version-check", default="", choices=("", "enforce", "warn"),
                       help="batch only: klt runner/client version-skew policy for the requests. "
                            "'warn' runs on a skewed runner, but an evidence-writing run is then "
                            "refused (the staged models cannot be proven), so use it with --no-write")
    p_run.add_argument("--no-stage-models", action="store_true",
                       help="batch only, requires --no-write: do not ship this host's models with "
                            "the requests (the runner uses its image's own, unhashed)")
    p_run.add_argument("--temperatures", default="",
                       help="comma-separated subset of the testbench's temperatures_c (default: all)")
    p_run.add_argument("--supplies", default="",
                       help="comma-separated subset of the testbench's supply points in V "
                            "(default: all)")
    p_run.add_argument("--subset-reason", default="",
                       help="why the grid is a subset of the testbench's matrix; required for an "
                            "evidence-writing run with --temperatures/--supplies")
    p_run.add_argument("--klt-cmd", default="klt",
                       help="klt client command (e.g. 'uvx --from klayout-tools==X klt')")
    p_run.add_argument("--workdir", default="")
    p_run.add_argument("--claim", default="")
    p_run.add_argument("--supersedes", default="")
    p_run.add_argument("--no-write", action="store_true", help="simulate but write no record")
    p_run.add_argument("--smoke-subset", action="store_true",
                        help="requires --no-write: skip only the 'axis never swept' sensitivity "
                             "check (single-process-corner smoke); all other checks still fail the run")
    p_run.add_argument("--sabotage", action="store_true",
                        help="force every corner to typical (implies --no-write)")
    p_run.add_argument("--allow-toolchain-drift", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_verify = sub.add_parser("verify-pdk", help="check installed IHP models against sim/pdk-artifact.json")
    p_verify.add_argument("--require-ngspice", action="store_true",
                          help="also fail if ngspice is missing or not the tested major version")
    p_verify.set_defaults(func=cmd_verify_pdk)

    p_selftest = sub.add_parser("selftest", help="negative-control corner-switching self-test")
    p_selftest.add_argument("experiment")
    p_selftest.add_argument(
        "--corners", default="",
        help="comma-separated corner or corner-set names (default: the testbench's own tb.json 'corners' field)",
    )
    p_selftest.add_argument("--jobs", type=int, default=1,
                            help=f"concurrent local ngspice processes (max {MAX_LOCAL_JOBS})")
    p_selftest.add_argument("--workdir", default="")
    p_selftest.set_defaults(func=cmd_selftest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
