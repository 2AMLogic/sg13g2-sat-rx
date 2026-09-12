"""Command-line entry point wiring the generic core together.

GENERIC CORE. Three subcommands, each a thin driver over the modules next to
this file:

    list      discover(sim/) and print every experiment with a testbench
    run       load a testbench, resolve the PDK, check toolchain pins,
              build the PVT grid, run it, and (unless --no-write) write an
              append-only Markdown record
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
import sys
from pathlib import Path

from . import HARNESS_VERSION
from . import toolchain as toolchain_mod
from .corners import build_grid, resolve_corners, sabotage, supply_points
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
    write_netlist_snapshot,
    write_record,
)
from .runner import NgspiceMissing, ngspice_version, run_grid
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
        return find_pdk(SIM_DIR)
    except (PdkNotFound, PdkConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return None


def cmd_run(args: argparse.Namespace) -> int:
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

    temperatures = tb.temperatures_c
    supplies = supply_points(tb.nominal_supply_v, tb.supply_tolerance)
    points = build_grid(corners, temperatures, supplies)

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
    results = run_grid(
        tb, pdk, points, workdir, jobs=args.jobs, log_dir=log_dir, num_threads=args.num_threads
    )

    n_ok = sum(1 for r in results if r.status == "ok")
    print(f"{n_ok}/{len(results)} points ok")

    measure_names = list(tb.measure)
    summary = summarize(results, measure_names)
    sensitivity = axis_sensitivity(results, measure_names)
    failures = evaluate_checks(tb.checks, results, summary, sensitivity)
    for failure in failures:
        print(f"FAIL: {describe_failure(failure)}", file=sys.stderr)

    if args.no_write:
        print("--no-write (or --sabotage): nothing recorded")
        return 1 if failures or n_ok != len(results) else 0

    wall_seconds = (_dt.datetime.now(_dt.timezone.utc) - started).total_seconds()
    record = build_record(
        tb, pdk, points, results, ngspice, SIM_DIR.parent, record_id,
        started.isoformat(), wall_seconds, claim=args.claim or tb.claim,
        supersedes=args.supersedes or "", git=git, toolchain=tc_summary,
    )
    try:
        write_netlist_snapshot(tb, tb.experiment_dir, record_id)
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
    p_run.add_argument("--jobs", type=int, default=1)
    p_run.add_argument("--num-threads", type=int, default=0)
    p_run.add_argument("--workdir", default="")
    p_run.add_argument("--claim", default="")
    p_run.add_argument("--supersedes", default="")
    p_run.add_argument("--no-write", action="store_true", help="simulate but write no record")
    p_run.add_argument("--sabotage", action="store_true",
                        help="force every corner to typical (implies --no-write)")
    p_run.add_argument("--allow-toolchain-drift", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_selftest = sub.add_parser("selftest", help="negative-control corner-switching self-test")
    p_selftest.add_argument("experiment")
    p_selftest.add_argument(
        "--corners", default="",
        help="comma-separated corner or corner-set names (default: the testbench's own tb.json 'corners' field)",
    )
    p_selftest.add_argument("--jobs", type=int, default=1)
    p_selftest.add_argument("--workdir", default="")
    p_selftest.set_defaults(func=cmd_selftest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
