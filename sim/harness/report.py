"""Summaries, spec checks, and append-only evidence records.

GENERIC CORE: record-id minting, grid summaries, per-axis sensitivity (the
guard against a corner sweep that silently pins one axis to typical),
spec-check evaluation, and an append-only Markdown writer. None of this
reads a block-specific field by name -- it works over ``tb.measure`` /
``tb.checks`` (both generic, see testbench.py) and
``evidence.BaseExtensions.render_lines()`` (block-extensible, see
evidence.py).

Record id shape: ``<YYYYMMDD>-<HHMMSS>-<short-git-sha>``. A block's own
CLAUDE.md / evidence convention should state that sim/ results are
append-only evidence; this module makes that mechanical rather than a
manual promise: it never overwrites an existing record, minting a new
(still conforming) record-id on collision instead, and a correction is
expected to reference the prior record via ``supersedes`` rather than
editing it in place.

EXTENSION POINT: :func:`build_record` bundles ``evidence.as_dict()``
untouched into the record, so a block's replacement ``BaseExtensions``
subclass (see evidence.py) needs no change here. A block wanting additional
*record-level* sections beyond what is here (e.g. a bespoke plot or extra
provenance block) should post-process the dict :func:`build_record` returns
before calling :func:`render_markdown`, or fork that one function -- the
minting/summary/check machinery above it stays shared.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import platform
import socket
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from . import HARNESS_VERSION, UPSTREAM_PATTERN
from .corners import (
    DEFAULT_SUPPLY_TOLERANCE,
    DEFAULT_TEMPERATURES_C,
    resolve_corners,
    supply_points,
)
from .evidence import BaseExtensions
from .pdk import Pdk
from .pdkartifact import validate_identity
from .runner import PointResult
from .testbench import AXES, Testbench

#: Subdirectories of ``sim/<experiment-slug>/`` this module writes into.
SNAPSHOT_DIR = "netlist-snapshots"
RECORDS_DIR = "records"

_AXIS_GROUP_KEY = {
    "process": lambda p: (p["temp_c"], p["vdd"]),
    "temperature": lambda p: (p["corner"], p["vdd"]),
    "supply": lambda p: (p["corner"], p["temp_c"]),
}
_AXIS_LEVEL = {
    "process": lambda p: p["corner"],
    "temperature": lambda p: p["temp_c"],
    "supply": lambda p: p["vdd"],
}


def _git(*args: str, cwd: Path) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
        )
        return out.stdout.strip()
    except OSError:  # pragma: no cover - git always present in a scaffolded repo
        return ""


def git_provenance(repo_root: Path) -> dict:
    commit = _git("rev-parse", "HEAD", cwd=repo_root)
    dirty = bool(_git("status", "--porcelain", cwd=repo_root))
    return {
        "commit": commit or "unknown",
        "short": (commit[:7] if commit else "unknown"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_root) or "unknown",
        "dirty": dirty,
    }


def format_record_id(short_sha: str, when: _dt.datetime) -> str:
    """``<YYYYMMDD>-<HHMMSS>-<short-git-sha>``."""
    return f"{when.strftime('%Y%m%d-%H%M%S')}-{short_sha}"


def allocate_record_id(
    repo_root: Path,
    records_dir: Path,
    when: _dt.datetime | None = None,
    git: dict | None = None,
) -> str:
    """Mint a fresh, unused ``<record-id>``.

    Append-only: if a record with this id already exists (same second, same
    commit) the timestamp advances until the id is free, rather than
    overwriting anything.
    """
    when = when or _dt.datetime.now(_dt.timezone.utc)
    short_sha = (git or git_provenance(repo_root))["short"]
    while True:
        record_id = format_record_id(short_sha, when)
        if not (records_dir / f"{record_id}.md").exists():
            return record_id
        when += _dt.timedelta(seconds=1)


def summarize(results: list[PointResult], measure_names: list[str]) -> dict:
    """Min / max / mean / spread of each measurement across the PVT grid."""
    summary: dict[str, dict] = {}
    ok = [r for r in results if r.status == "ok"]
    for name in measure_names:
        samples = [(r.measurements[name], r.point.corner_id) for r in ok if name in r.measurements]
        if not samples:
            summary[name] = {"n": 0}
            continue
        values = [v for v, _ in samples]
        lo_value, lo_at = min(samples, key=lambda s: s[0])
        hi_value, hi_at = max(samples, key=lambda s: s[0])
        mean = sum(values) / len(values)
        spread_pct = (hi_value - lo_value) / abs(mean) * 100.0 if mean else None
        summary[name] = {
            "n": len(values),
            "min": lo_value,
            "min_at": lo_at,
            "max": hi_value,
            "max_at": hi_at,
            "mean": mean,
            "spread_pct": spread_pct,
        }
    return summary


def _spread_pct(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    if not mean:
        return None
    return (max(values) - min(values)) / abs(mean) * 100.0


def axis_sensitivity(results: list[PointResult], measure_names: list[str]) -> dict:
    """Per-axis spread: does *each* PVT axis move each measurement?

    For axis ``a``, the grid is sliced into groups in which the other two
    axes are held fixed, so the only thing varying inside a group is ``a``.
    ``min_pct`` is the weakest slice (what a ``min_spread_pct_by_axis`` floor
    is checked against, so a single stuck slice cannot hide behind the
    others); ``max_pct`` is the strongest. Fewer than two distinct levels
    means the axis was never swept -- reported as unverifiable, not a pass.
    """
    ok = [r for r in results if r.status == "ok"]
    points = [(r.point.as_dict(), r.measurements) for r in ok]

    out: dict[str, dict] = {}
    for name in measure_names:
        per_axis: dict[str, dict] = {}
        rows = [(p, m[name]) for p, m in points if name in m]
        for axis in AXES:
            levels = {_AXIS_LEVEL[axis](p) for p, _ in rows}
            groups: dict[tuple, list[float]] = defaultdict(list)
            for point, value in rows:
                groups[_AXIS_GROUP_KEY[axis](point)].append(value)
            spreads = [s for s in (_spread_pct(v) for v in groups.values()) if s is not None]
            per_axis[axis] = {
                "levels": len(levels),
                "groups": len(groups),
                "min_pct": min(spreads) if spreads else None,
                "max_pct": max(spreads) if spreads else None,
            }
        out[name] = per_axis
    return out


def evaluate_checks(
    checks: dict[str, dict],
    results: list[PointResult],
    summary: dict,
    sensitivity: dict | None = None,
    allow_unswept_axes: bool = False,
) -> list[dict]:
    """Return a list of check failures (empty list == everything passed).

    ``allow_unswept_axes`` downgrades "this axis was never swept, so its
    sensitivity is unverifiable" from a failure to a silent skip -- only set
    for runs already declared non-evidence (``--no-write``) or that carry a
    written subset justification.
    """
    sensitivity = sensitivity or {}
    failures: list[dict] = []
    for name, spec in checks.items():
        low = spec.get("min")
        high = spec.get("max")
        if low is not None or high is not None:
            for result in results:
                if result.status != "ok" or name not in result.measurements:
                    continue
                value = result.measurements[name]
                if low is not None and value < low:
                    failures.append(
                        {"measurement": name, "kind": "min", "limit": low, "value": value,
                         "at": result.point.corner_id}
                    )
                if high is not None and value > high:
                    failures.append(
                        {"measurement": name, "kind": "max", "limit": high, "value": value,
                         "at": result.point.corner_id}
                    )
        for kind, limit in (
            ("max_spread_pct", spec.get("max_spread_pct")),
            ("min_spread_pct", spec.get("min_spread_pct")),
        ):
            if limit is None:
                continue
            observed = (summary.get(name) or {}).get("spread_pct")
            violated = (
                observed is None
                or (kind == "max_spread_pct" and observed > limit)
                or (kind == "min_spread_pct" and observed < limit)
            )
            if violated:
                failures.append(
                    {"measurement": name, "kind": kind, "limit": limit, "value": observed, "at": "grid"}
                )
        for kind, key, reduce_key in (
            ("min_spread_pct_by_axis", "min_spread_pct_by_axis", "min_pct"),
            ("max_spread_pct_by_axis", "max_spread_pct_by_axis", "max_pct"),
        ):
            for axis, limit in (spec.get(key) or {}).items():
                stats = (sensitivity.get(name) or {}).get(axis) or {}
                if stats.get("levels", 0) < 2:
                    if allow_unswept_axes:
                        continue
                    failures.append(
                        {"measurement": name, "kind": kind, "axis": axis, "limit": limit,
                         "value": None, "at": f"axis:{axis}",
                         "note": "axis was never swept — sensitivity unverifiable"}
                    )
                    continue
                observed = stats.get(reduce_key)
                violated = (
                    observed is None
                    or (kind == "min_spread_pct_by_axis" and observed < limit)
                    or (kind == "max_spread_pct_by_axis" and observed > limit)
                )
                if violated:
                    failures.append(
                        {"measurement": name, "kind": kind, "axis": axis, "limit": limit,
                         "value": observed, "at": f"axis:{axis}"}
                    )
    return failures


def environment(
    pdk: Pdk,
    ngspice: str,
    repo_root: Path,
    git: dict | None = None,
    toolchain: dict | None = None,
    pdk_artifact: dict | None = None,
) -> dict:
    """Reproducibility provenance for the record.

    ``git`` should be sampled *before* the run starts -- the harness writes
    its own per-corner logs into the tracked evidence tree, so sampling
    afterwards would report every record as taken against a dirty tree.

    ``pdk_artifact`` is the identity returned by
    ``pdkartifact.verified_identity`` (upstream commit, manifest digest,
    verification result). It is required: a record without a verified
    artifact identity is refused (``ArtifactNotVerified``). ``pdk`` keeps the
    separate, best-effort installation version (``unknown`` on markerless
    installs); the two are never merged.
    """
    pdk_artifact = validate_identity(pdk_artifact)
    try:
        user = getpass.getuser()
    except Exception:  # pragma: no cover - unusual environments
        user = "unknown"
    return {
        "harness_version": HARNESS_VERSION,
        "harness_upstream": UPSTREAM_PATTERN,
        "ngspice": ngspice,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "host": socket.gethostname(),
        "user": user,
        "pdk": pdk.provenance(),
        "pdk_artifact": dict(pdk_artifact),
        "git": git if git is not None else git_provenance(repo_root),
        "toolchain": toolchain or {},
    }


#: Cap on how many missing / unexpected combinations are spelled out in the
#: human-readable ``missing`` strings (the full lists are in the record keys).
MAX_LISTED_COMBOS = 12


def _combo(corner: str, temp_c: float, vdd: float) -> tuple[str, float, float]:
    return (str(corner), round(float(temp_c), 6), round(float(vdd), 6))


def _fmt_combos(combos) -> str:
    combos = sorted(combos)
    shown = ", ".join(f"{c}/{t:g} C/{v:.2f} V" for c, t, v in combos[:MAX_LISTED_COMBOS])
    if len(combos) > MAX_LISTED_COMBOS:
        shown += f", ... (+{len(combos) - MAX_LISTED_COMBOS} more)"
    return shown


def required_matrix(tb: Testbench) -> set[tuple[str, float, float]]:
    """The mandated Cartesian product for ``tb``: its declared (resolved)
    process corners x the default temperatures x nominal supply +/-10 %."""
    return {
        _combo(c.name, t, v)
        for c in resolve_corners(list(tb.corners))
        for t in DEFAULT_TEMPERATURES_C
        for v in supply_points(tb.nominal_supply_v, DEFAULT_SUPPLY_TOLERANCE)
    }


def matrix_conformance(tb: Testbench, points, required=None) -> dict:
    """Is this run the full PVT matrix, or a subset?

    Coverage is judged on canonical (process, temperature, supply) tuples
    against the required Cartesian product, not on each axis independently:
    a diagonal of points can hit every axis level and still cover few of the
    required combinations. Duplicates collapse; tuples outside the required
    set (e.g. undeclared process names) are reported separately and never
    count toward coverage.

    ``required`` deliberately overrides the required set (an iterable of
    ``(process, temp_c, vdd)``); it is recorded under ``required_source`` /
    ``required_points`` so the record shows what was demanded. Otherwise the
    set derives from the testbench's declared corners.

    A block's evidence convention should require the "corner matrix run"
    field to state the full matrix unless the record states why a subset was
    used; ``missing`` lets the caller insist on a written justification.
    """
    if required is None:
        req = required_matrix(tb)
        source = "testbench"
    else:
        req = {_combo(*r) for r in required}
        source = "override"
    observed = {_combo(p.corner.name, p.temp_c, p.vdd) for p in points}
    covered = observed & req
    gaps = req - observed
    unexpected = observed - req

    missing: list[str] = []
    if gaps:
        missing.append(
            f"{len(covered)} of {len(req)} required process/temperature/supply "
            f"combinations covered; missing {_fmt_combos(gaps)}"
        )
    if unexpected:
        missing.append(
            f"{len(unexpected)} unexpected combination(s) not counted: {_fmt_combos(unexpected)}"
        )
    return {
        "full": not gaps,
        "missing": missing,
        "required_source": source,
        "required_points": len(req),
        "covered_points": len(covered),
        "missing_combinations": [list(c) for c in sorted(gaps)],
        "unexpected_combinations": [list(c) for c in sorted(unexpected)],
    }


def build_record(
    tb: Testbench,
    pdk: Pdk,
    points,
    results: list[PointResult],
    ngspice: str,
    repo_root: Path,
    record_id: str,
    started_utc: str,
    wall_seconds: float,
    claim: str = "",
    supersedes: str = "",
    statistical_convention: str = "",
    subset_reason: str = "",
    git: dict | None = None,
    extensions: BaseExtensions | None = None,
    allow_unswept_axes: bool = False,
    toolchain: dict | None = None,
    pdk_artifact: dict | None = None,
) -> dict:
    measure_names = list(tb.measure)
    summary = summarize(results, measure_names)
    sensitivity = axis_sensitivity(results, measure_names)
    failures = evaluate_checks(
        tb.checks, results, summary, sensitivity, allow_unswept_axes=allow_unswept_axes
    )
    n_ok = sum(1 for r in results if r.status == "ok")
    extensions = extensions if extensions is not None else tb.evidence

    if n_ok != len(results):
        status = "error"
    elif failures:
        status = "fail"
    else:
        status = "pass"

    corners = []
    seen = set()
    for point in points:
        if point.corner.name not in seen:
            seen.add(point.corner.name)
            corners.append(
                {"name": point.corner.name, "sections": list(point.corner.sections),
                 "description": point.corner.description}
            )

    return {
        "record_id": record_id,
        "experiment": tb.experiment,
        "status": status,
        "started_utc": started_utc,
        "wall_seconds": round(wall_seconds, 2),
        "claim": claim or tb.claim,
        "supersedes": supersedes,
        "statistical_convention": statistical_convention,
        "subset_reason": subset_reason,
        "matrix": matrix_conformance(tb, points),
        "testbench": tb.provenance(),
        "environment": environment(pdk, ngspice, repo_root, git, toolchain, pdk_artifact),
        "evidence": extensions.as_dict(),
        "grid": {
            "corners": corners,
            "temperatures_c": sorted({p.temp_c for p in points}),
            "supplies_v": sorted({p.vdd for p in points}),
            "points": len(points),
            "points_ok": n_ok,
        },
        "measure": dict(tb.measure),
        "checks": {"spec": tb.checks, "passed": not failures, "failures": failures},
        "summary": summary,
        "sensitivity": sensitivity,
        "points": [r.as_dict() for r in results],
        "_evidence_lines": extensions.render_lines(),
    }


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        if value != 0 and (abs(value) < 1e-3 or abs(value) >= 1e5):
            return f"{value:.6e}"
        return f"{value:.6g}"
    return str(value)


def describe_failure(failure: dict) -> str:
    axis = failure.get("axis")
    where = f" on the {axis} axis" if axis else ""
    note = failure.get("note")
    if note:
        return f"{failure['measurement']} {failure['kind']}{where}: {note}"
    return (
        f"{failure['measurement']} {failure['kind']}{where}="
        f"{_fmt(failure['limit'])} (got {_fmt(failure['value'])})"
    )


class RecordExists(RuntimeError):
    """Refused to overwrite an existing append-only record."""


def write_netlist_snapshot(tb: Testbench, experiment_dir: Path, record_id: str) -> Path:
    """Freeze the DUT netlist for this record, so a later edit under
    ``testbench/`` never changes what an existing record refers to."""
    out_dir = experiment_dir / SNAPSHOT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{record_id}.spice"
    if path.exists():
        raise RecordExists(f"{path} already exists; append-only evidence is never rewritten")
    header = "\n".join(
        [
            f"* Frozen netlist snapshot for record {record_id}",
            f"* sha256     : {tb.netlist_sha256}",
            "* This is a verbatim copy taken at record time. Do not edit.",
            "",
        ]
    )
    path.write_text(header + tb.netlist.read_text())
    return path


def render_markdown(record: dict) -> str:
    """Render a built record as a Markdown evidence record.

    Deliberately plain: a block-specific evidence convention typically wants
    a more elaborate layout (see gf180-sar-adc's harness/report.py for one
    example, with a toolchain-drift banner and a rendered sensitivity
    table). Replace this function once that convention is ratified; the
    dict :func:`build_record` returns already carries everything it needs.
    """
    lines = [
        f"# {record['record_id']}",
        "",
        f"**Status**: {record['status']}",
        f"**Experiment**: {record['experiment']}",
        f"**Started (UTC)**: {record['started_utc']}",
        f"**Wall time**: {record['wall_seconds']}s",
    ]
    if record.get("supersedes"):
        lines.append(f"**Supersedes**: {record['supersedes']}")
    lines += ["", f"**Claim**: {record['claim'] or '(none stated)'}", ""]

    if record["statistical_convention"]:
        lines.append(f"- **Statistical convention**: {record['statistical_convention']}")
    grid = record["grid"]
    lines += [
        "- **Corner matrix run**:",
        "  - Process: " + ", ".join(c["name"] for c in grid["corners"]),
        "  - Temperature: " + ", ".join(f"{t:g} C" for t in grid["temperatures_c"]),
        "  - Supply: " + ", ".join(f"{v:.2f} V" for v in grid["supplies_v"]),
        (f"  - {grid['points']} point "
         + ("full-factorial grid (process x temperature x supply)" if record["matrix"]["full"]
            else "grid (subset of the required process x temperature x supply product)")
         + f", {grid['points_ok']} completed"),
    ]
    if record["matrix"]["full"]:
        lines.append("  - Full PVT matrix.")
    else:
        lines.append("  - **Subset of the mandated PVT matrix.** Gaps: "
                     + "; ".join(record["matrix"]["missing"]) + ".")
        lines.append("  - Justification: " + (record["subset_reason"] or "(none given)"))

    lines += ["", "## Evidence"]
    lines += record.get("_evidence_lines", []) or ["- (no extension fields)"]

    lines += ["", "## Result"]
    if record["checks"]["passed"]:
        lines.append("**PASS** — all spec checks satisfied.")
    else:
        lines.append("**FAIL**")
        for failure in record["checks"]["failures"]:
            lines.append(f"- {describe_failure(failure)}")

    lines += ["", "## Summary"]
    for name, stats in record["summary"].items():
        if stats.get("n", 0) == 0:
            lines.append(f"- `{name}`: no successful measurements")
            continue
        lines.append(
            f"- `{name}`: min {_fmt(stats['min'])} (@{stats['min_at']}), "
            f"max {_fmt(stats['max'])} (@{stats['max_at']}), "
            f"mean {_fmt(stats['mean'])}, spread {_fmt(stats['spread_pct'])}%"
        )

    env = record["environment"]
    art = validate_identity(env.get("pdk_artifact"))
    lines += [
        "",
        "## Environment",
        f"- Harness: v{env['harness_version']} (upstream pattern: {env['harness_upstream']})",
        f"- ngspice: {env['ngspice']}",
        (f"- PDK: {env['pdk'].get('name')} {env['pdk'].get('variant')} "
         f"(install marker: {env['pdk'].get('version')}, via {env['pdk'].get('discovered_via')})"),
        (f"- PDK artifact: **{art['status']}** -- upstream "
         f"{art.get('upstream_repo') or 'unknown repo'} "
         f"{art.get('upstream_tag') or ''} commit `{art['upstream_commit']}`; "
         f"{art['manifest']} sha256 `{art['manifest_sha256']}`; "
         f"{art.get('files_verified')} model files hash-verified "
         + (("as the model inputs staged to off-host klt job(s) "
             + ", ".join(f"`{j.get('job_id')}`" for j in art.get("jobs") or [])
             + " (klt staged_model_inputs; runner klt build == client build); the runner's own "
             "install was not hashed")
            if art.get("verified_scope") == "offhost-job-model-inputs"
            else "in the simulating install before the run")),
        f"- Python: {env['python']} on {env['platform']}",
        f"- git: {env['git'].get('short')} on {env['git'].get('branch')}"
        + (" (dirty)" if env["git"].get("dirty") else ""),
    ]
    toolchain = env.get("toolchain") or {}
    if toolchain.get("pinned"):
        state = "satisfied" if toolchain.get("conforms") else "DRIFTED"
        lines.append(f"- Toolchain pins: **{state}**")
    lines.append("")
    return "\n".join(lines)


def write_record(record: dict, experiment_dir: Path) -> Path:
    """Append-only write of the Markdown record. Never overwrites."""
    records_dir = experiment_dir / RECORDS_DIR
    records_dir.mkdir(parents=True, exist_ok=True)
    path = records_dir / f"{record['record_id']}.md"
    if path.exists():
        raise RecordExists(f"{path} already exists; append-only evidence is never rewritten")
    path.write_text(render_markdown(record))
    return path
