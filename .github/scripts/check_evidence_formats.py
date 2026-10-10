#!/usr/bin/env python3
"""Evidence-format and append-only checker for sim/*/ evidence trees.

Standard library only; needs no PDK, no simulator, no third-party package.

What it checks (it validates FORMAT and PROVENANCE only -- it never
reinterprets a historical scientific claim; corrections go in a later record):

1. Format, for every ``sim/<bench>/testbench/tb.json`` bench and every
   ``sim/<bench>/records/*.md`` record in the CURRENT tree. Two committed
   layouts exist and both are recognised; the bench's ``tb.json`` selects
   which (a ``"sweep"`` block means the Ka-band layout):

   harness-native (sim/harness/report.py ``render_markdown``)
       records/<id>.md, corners/<id>/<corner_id>.log (plain text),
       netlist-snapshots/<id>.spice (one frozen file).
       The record declares its matrix as ``Process: ..`` / ``Temperature: ..``
       / ``Supply: ..`` / ``N point full-factorial grid .., M completed`` (a
       run covering the bench's whole required product) or ``N point grid
       (subset of ..), M completed`` (an intentional subset, issue #81). Both
       wordings go through the same expansion and artifact checks.

   Ka-band (sim/hbt-kaband-characterization/report_kaband.py)
       records/<id>.md, corners/<id>/<corner_id>.log.gz (gzip),
       netlist-snapshots/<id>/{body,request,klt-report}_<supply>v.* (one set
       per declared supply), records/<id>-{points.csv.gz,cells.csv,best.csv}.
       The record declares its matrix on the ``**PVT points**`` line.

   The declared matrix is expanded to corner identities and compared with the
   artifacts actually on disk (missing / unexpected / duplicated identities,
   unreadable compressed logs, missing snapshots and companion files, sidecar
   rows naming identities outside the matrix). Nothing is hardcoded to 27.

   mixer-topology-feasibility (sim/mixer-topology-feasibility/collect.py)
       a bench whose ``tb.json`` has a ``"study"`` block: records/<id>.md +
       <id>.json + <id>-cells.json.gz, corners/<id>/*.log.gz, and
       netlist-snapshots/<id>/ with the generated klt bodies/requests/reports
       and the frozen fragments. The sidecar must say the acceptance gate
       passed, declared == accepted cells, every cell id unique and in a
       scientific status, leakage cells carrying the declared seed. It checks
       completeness and consistency only, never the science.

   Three further campaigns have no PVT testbench manifest (``tb.json``) and
   are NOT harness PVT benches; each is registered explicitly in
   :data:`ADAPTERS` (never inferred) and validated for identity, status,
   paired Markdown/JSON consistency, provenance and declared companions only:

   lna-match-tradeoff (sim/lna-match-tradeoff/collect.py, issue #74)
       declared by testbench/study.json (not tb.json); records/<id>.md +
       <id>.json + <id>-cells.json.gz, corners/<id>/*.log.gz (one per klt
       unit) and netlist-snapshots/<id>/ (frozen study.json declaration and
       DUT, generated klt bodies/requests/reports/specs). The cell ids must
       be exactly those the FROZEN declaration and the record's shortlist
       imply; ok cells need finite summaries, a passing refined-grid control
       and full per-frequency band data; the sidecar must say the gate
       passed and no spec row is claimed, and its hashes must match the
       frozen declaration and DUT. Completeness and consistency only.


   passive-p1 (sim/passive-p1/scripts/make_record.py, controls.py)
       records/<id>-<STATUS>.{md,json} pairs, where <STATUS> is a campaign
       outcome (QUALIFIED, UNCONVERGED, FIT_FAILED, CAPABILITY_UNAVAILABLE)
       or CONTROLS-PASS / CONTROLS-FAIL. The permanent evidence package is
       the record pair plus the INPUTS.json-hashed input files it names;
       results/, run_log/ and fit/ are mutable solver working output and
       are deliberately NOT protected. SYNTHETIC-* smoke records are not
       campaign evidence and are rejected inside records/.

   mixer-nf-method (sim/mixer-nf-method/run_probe.py)
       records/<id>-<STATUS>.{md,json} (METHOD_VALIDATION, MODEL_ABSENT,
       UNCONVERGED, CAPABILITY_UNAVAILABLE) plus, for every run that reached
       the simulator, the frozen probe-logs/<id>/{deck.spice,stdout.txt,
       stderr.txt,inventory.json} package named by the JSON ``probe_logs``.

   Passive records of ``record_schema`` 2 (issue #58) additionally name a frozen
   ``sim/passive-p1/solver-artifacts/<id>/`` package: ``manifest.json`` lists
   every package-relative file with sha256 and size; the checker verifies the
   outcome-required files are present (completeness), every path is a safe
   relative path (no absolute, ``..``, symlink, dot-file), the bytes match the
   hashes, nothing unlisted is present, no interrupted-publication marker is
   left, the manifest hash agrees with the record, and the record's metrics /
   compare equal the packaged JSON. Legacy records (the two committed before
   #58, listed in :data:`LEGACY_PASSIVE_RECORDS`) stay valid without a package.
   This is hash INTEGRITY and record/package agreement only; it never judges
   whether the numbers are correct or qualified.

   Any other ``sim/<dir>/`` that has records/, corners/, netlist-snapshots/,
   probe-logs/ or solver-artifacts/ but is neither a testbench bench nor a registered adapter
   fails visibly instead of being skipped.

2. Append-only history (``--base`` / environment fallback, see
   :func:`resolve_base`): against the MERGE BASE of the base ref and HEAD
   (never only the last commit of a multi-commit branch) no committed file
   under ``sim/*/{records,corners,netlist-snapshots,probe-logs,solver-artifacts}/`` may be modified,
   deleted, renamed or type-changed, and no file may be ADDED to a record id
   that already existed at the base. New record ids are fine, as are
   independent testbench/harness changes.

   No base available (first push of a new branch with no ``origin/main``,
   all-zero ``before`` sha, ...): the append-only half is SKIPPED with a loud
   notice and the format half still runs; ``--require-base`` turns the skip
   into a failure (the pull_request job uses it).

3. Spec-row coverage (``spec/row-coverage.json``, issue #50): the hand-kept
   manifest must list exactly the rows of the table in ``spec/target-spec.md``
   with the same status and binding corner, every cited bench dir / record
   must exist, a ``measured_*`` verdict may not cite a record whose Claim line
   says placeholder / device-level, and a row without a bench must say what
   blocks it. A row's ``latest_record`` must also not be stale: no
   lexicographically newer ``*.md`` in the same bench's ``records/`` may mention
   the row (``row N``, ``rows A-B``, ``rows A, B and C``). A mention is not a
   claim; resolve a false positive by pointing ``latest_record`` at the newer
   record. It records bookkeeping only and never changes a spec value.

Exit status: 0 clean, 1 problems found, 2 usage/environment error.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RECORD_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{7,40}$")
RECORD_ID_PREFIX_RE = re.compile(r"^(\d{8}-\d{6}-[0-9a-f]{7,40})")
PROTECTED_RE = re.compile(r"^sim/[^/]+/(records|corners|netlist-snapshots|probe-logs|solver-artifacts)/")
NATIVE_STATUSES = ("pass", "fail", "error")
NATIVE_SNAPSHOT_NOTE = b"* This is a verbatim copy taken at record time. Do not edit."
NATIVE_SECTIONS = ("Evidence", "Result", "Summary", "Environment")
KABAND_SECTIONS = ("Grid", "Provenance", "Data quality", "Limitations", "Sidecars")
KABAND_SIDECAR_SUFFIXES = ("-points.csv.gz", "-cells.csv", "-best.csv")
NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


class Problems:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, where: Path | str, message: str) -> None:
        self.items.append(f"{where}: {message}")

    def __bool__(self) -> bool:
        return bool(self.items)


def rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# small parsers
# ---------------------------------------------------------------------------


def header_field(text: str, name: str) -> str | None:
    m = re.search(rf"^\*\*{re.escape(name)}\*\*: (.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def has_section(text: str, title: str) -> bool:
    return re.search(rf"^## {re.escape(title)}\s*$", text, re.MULTILINE) is not None


def section_body(text: str, title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return m.group(1) if m else ""


def corner_id(process: str, temp: float, supply: float) -> str:
    # Mirrors sim/harness/corners.py PvtPoint.corner_id.
    return f"{process}_{temp:g}c_{supply:.2f}v"


def expand_matrix(processes: list[str], temps: list[float], supplies: list[float]) -> list[str]:
    return [corner_id(p, t, v) for p in processes for t in temps for v in supplies]


def numbers(text: str) -> list[float]:
    return [float(x) for x in NUM_RE.findall(text)]


def duplicates(items: list) -> list:
    seen: set = set()
    dup: list = []
    for item in items:
        if item in seen and item not in dup:
            dup.append(item)
        seen.add(item)
    return dup


def compare_identities(
    problems: Problems, where: Path | str, what: str, expected: list[str], actual: list[str]
) -> None:
    for dup in duplicates(expected):
        problems.add(where, f"declared matrix lists corner identity {dup!r} more than once")
    for dup in duplicates(actual):
        problems.add(where, f"{what} contains corner identity {dup!r} more than once")
    exp, act = set(expected), set(actual)
    for missing in sorted(exp - act):
        problems.add(where, f"{what} is missing declared corner identity {missing!r}")
    for extra in sorted(act - exp):
        problems.add(where, f"{what} has unexpected corner identity {extra!r} (not in the declared matrix)")


def read_gzip_text(problems: Problems, root: Path, path: Path) -> str | None:
    try:
        with gzip.open(path, "rb") as fh:
            data = fh.read()
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        problems.add(rel(root, path), f"unreadable gzip file ({exc})")
        return None
    if not data.strip():
        problems.add(rel(root, path), "decompressed log is empty")
        return None
    return data.decode("utf-8", errors="replace")


def csv_corner_ids(problems: Problems, root: Path, path: Path) -> list[str] | None:
    """Distinct-in-order list of the ``corner_id`` column of a (maybe gz) CSV."""
    try:
        if path.name.endswith(".gz"):
            with gzip.open(path, "rb") as fh:
                raw = fh.read()
        else:
            raw = path.read_bytes()
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
        if reader.fieldnames is None or "corner_id" not in reader.fieldnames:
            problems.add(rel(root, path), "CSV has no 'corner_id' column")
            return None
        ids: list[str] = []
        seen: set[str] = set()
        nrows = 0
        for row in reader:
            nrows += 1
            cid = row["corner_id"]
            if cid not in seen:
                seen.add(cid)
                ids.append(cid)
        if nrows == 0:
            problems.add(rel(root, path), "CSV has a header but no data rows")
            return None
        return ids
    except (OSError, EOFError, gzip.BadGzipFile, UnicodeDecodeError, csv.Error) as exc:
        problems.add(rel(root, path), f"unreadable CSV ({exc})")
        return None


# ---------------------------------------------------------------------------
# harness-native layout
# ---------------------------------------------------------------------------


#: The harness-native grid-size line, in either wording ``render_markdown``
#: emits: ``- N point full-factorial grid (...), M completed`` for a run that
#: covers the required process x temperature x supply product, or
#: ``- N point grid (subset of ...), M completed`` for an intentional subset.
NATIVE_GRID_LINE_RE = re.compile(
    r"^\s*- (\d+) point (?:full-factorial grid|grid \(subset of)[^\n]*?, (\d+) completed",
    re.MULTILINE,
)


def declared_native_matrix(text: str) -> tuple[list[str], list[float], list[float], int | None, int | None]:
    """Return (processes, temperatures, supplies, n_total, n_done) as declared
    by a harness-native record.

    The grid-size line may use the full-factorial or the subset wording (see
    :data:`NATIVE_GRID_LINE_RE`). The wording only says whether the run met the
    bench's required product; either way N must equal the expansion of the
    Process/Temperature/Supply lists and the corner logs must match that
    expansion, so accepting a subset relaxes none of the other checks.
    """
    def line(label: str) -> str:
        m = re.search(rf"^\s*- {label}: (.+)$", text, re.MULTILINE)
        return m.group(1) if m else ""

    processes = [p.strip() for p in line("Process").split(",") if p.strip()]
    temps = numbers(line("Temperature"))
    supplies = numbers(line("Supply"))
    m = NATIVE_GRID_LINE_RE.search(text)
    n_total = int(m.group(1)) if m else None
    n_done = int(m.group(2)) if m else None
    return processes, temps, supplies, n_total, n_done


def check_native_record(problems: Problems, root: Path, exp_dir: Path, md: Path) -> None:
    rid = md.stem
    where = rel(root, md)
    text = md.read_text(encoding="utf-8", errors="replace")

    if not RECORD_ID_RE.match(rid):
        problems.add(where, "record file name is not <YYYYMMDD>-<HHMMSS>-<git-sha>.md")
    first = text.splitlines()[0] if text.strip() else ""
    if first != f"# {rid}":
        problems.add(where, f"first line must be '# {rid}', found {first!r}")
    for name in ("Status", "Experiment", "Started (UTC)", "Wall time"):
        if header_field(text, name) is None:
            problems.add(where, f"missing required header field '**{name}**:'")
    if header_field(text, "Claim") is None:
        problems.add(where, "missing required header field '**Claim**:'")
    status = header_field(text, "Status")
    if status is not None and status not in NATIVE_STATUSES:
        problems.add(where, f"Status {status!r} is not one of {', '.join(NATIVE_STATUSES)}")
    experiment = header_field(text, "Experiment")
    if experiment is not None and experiment != exp_dir.name:
        problems.add(where, f"Experiment {experiment!r} does not match its directory {exp_dir.name!r}")
    for title in NATIVE_SECTIONS:
        if not has_section(text, title):
            problems.add(where, f"missing required section '## {title}'")
    sup = header_field(text, "Supersedes")
    if sup is not None:
        check_supersedes(problems, where, exp_dir, sup)

    processes, temps, supplies, n_total, n_done = declared_native_matrix(text)
    if not (processes and temps and supplies) or n_total is None:
        problems.add(where, "cannot find the declared corner matrix "
                     "('Process:', 'Temperature:', 'Supply:' and an 'N point full-factorial grid ..., M completed' "
                     "or 'N point grid (subset of ...), M completed' line)")
        expected: list[str] | None = None
    else:
        expected = expand_matrix(processes, temps, supplies)
        if n_total != len(expected):
            problems.add(where, f"declares {n_total} grid points but its process x temperature x supply "
                         f"lists expand to {len(expected)}")
        if n_done is not None and n_done > n_total:
            problems.add(where, f"declares {n_done} completed points out of {n_total}")
        if status == "pass" and n_done is not None and n_done != n_total:
            problems.add(where, f"Status is pass but only {n_done}/{n_total} points are declared completed")

    corners_dir = exp_dir / "corners" / rid
    if not corners_dir.is_dir():
        problems.add(where, f"missing corner directory {rel(root, corners_dir)}/")
    elif expected is not None:
        logs = sorted(p for p in corners_dir.iterdir() if p.is_file())
        names = [p.name for p in logs]
        bad = [n for n in names if not n.endswith(".log")]
        for n in bad:
            problems.add(rel(root, corners_dir / n), "unexpected non-.log file in a harness-native corner directory")
        compare_identities(problems, rel(root, corners_dir), "corner directory", expected,
                           [n[: -len(".log")] for n in names if n.endswith(".log")])
        for p in logs:
            if p.name.endswith(".log") and p.stat().st_size == 0:
                problems.add(rel(root, p), "corner log is empty")

    snap = exp_dir / "netlist-snapshots" / f"{rid}.spice"
    if not snap.is_file():
        problems.add(where, f"missing netlist snapshot {rel(root, snap)}")
    else:
        check_native_snapshot(problems, rel(root, snap), snap.read_bytes(), rid)
    extra_snap_dir = exp_dir / "netlist-snapshots" / rid
    if extra_snap_dir.exists():
        problems.add(rel(root, extra_snap_dir), "directory-style snapshot in a harness-native bench")


def check_native_snapshot(problems: Problems, where: str, data: bytes, rid: str) -> None:
    """Verify a harness-native frozen netlist snapshot (issue #93).

    Writer convention (sim/harness/report.py ``write_netlist_snapshot``): exactly
    three header lines, each terminated by ``\\n``::

        * Frozen netlist snapshot for record <rid>
        * sha256     : <hex digest of the payload bytes>
        * This is a verbatim copy taken at record time. Do not edit.

    followed immediately by the verbatim DUT bytes. The payload is everything
    after the third newline, so comment lines inside it that look like
    metadata are payload, not provenance. The digest is recomputed over those
    bytes; the current DUT is never consulted.
    """
    parts = data.split(b"\n", 3)
    if len(parts) < 4:
        problems.add(where, "snapshot is truncated: it lacks the three-line provenance header")
        return
    first, digest_line, note, payload = parts
    if first.decode("utf-8", "replace") != f"* Frozen netlist snapshot for record {rid}":
        problems.add(where, f"snapshot header does not name record {rid}")
    m = re.fullmatch(rb"\* sha256\s*: ([0-9a-f]{64})", digest_line)
    if not m:
        problems.add(where, "snapshot is missing its '* sha256 :' provenance line "
                     "(must be the second line)")
        return
    if note != NATIVE_SNAPSHOT_NOTE:
        problems.add(where, "snapshot third header line is not the writer's "
                     "'* This is a verbatim copy ...' note")
    # Ambiguity: a second provenance header inside the header region is
    # impossible by construction; one at the start of the payload would be a
    # duplicated header, which the writer never emits.
    if re.match(rb"\* (Frozen netlist snapshot for record|sha256\s*:)", payload):
        problems.add(where, "snapshot has a duplicate provenance header at the start of its payload")
    actual = hashlib.sha256(payload).hexdigest()
    declared = m.group(1).decode()
    if actual != declared:
        problems.add(where, f"snapshot payload sha256 {actual} does not match declared {declared}")


# ---------------------------------------------------------------------------
# Ka-band layout
# ---------------------------------------------------------------------------


def check_supersedes(problems: Problems, where: str, exp_dir: Path, value: str) -> None:
    ref = value.split()[0] if value.split() else ""
    if not RECORD_ID_RE.match(ref):
        problems.add(where, f"Supersedes must start with a record id, found {value[:40]!r}")
    elif not (exp_dir / "records" / f"{ref}.md").is_file():
        problems.add(where, f"Supersedes names record {ref!r} which does not exist in this experiment")


def check_kaband_record(problems: Problems, root: Path, exp_dir: Path, md: Path) -> None:
    rid = md.stem
    where = rel(root, md)
    text = md.read_text(encoding="utf-8", errors="replace")

    if not RECORD_ID_RE.match(rid):
        problems.add(where, "record file name is not <YYYYMMDD>-<HHMMSS>-<git-sha>.md")
    first = text.splitlines()[0] if text.strip() else ""
    if first != f"# {rid}":
        problems.add(where, f"first line must be '# {rid}', found {first!r}")
    for name in ("Status", "Experiment", "Started (UTC)", "Claim"):
        if header_field(text, name) is None:
            problems.add(where, f"missing required header field '**{name}**:'")
    experiment = header_field(text, "Experiment")
    if experiment is not None and experiment != exp_dir.name:
        problems.add(where, f"Experiment {experiment!r} does not match its directory {exp_dir.name!r}")
    for title in KABAND_SECTIONS:
        if not has_section(text, title):
            problems.add(where, f"missing required section '## {title}'")
    sup = header_field(text, "Supersedes")
    if sup is not None:
        check_supersedes(problems, where, exp_dir, sup)

    grid = section_body(text, "Grid")
    m = re.search(
        r"\*\*PVT points\*\*: (\d+) = process (.+?) x temperature (.+?) x supply (.+?)\.\s*$",
        grid, re.MULTILINE)
    expected: list[str] | None = None
    supplies: list[float] = []
    if not m:
        problems.add(where, "'## Grid' has no parseable '**PVT points**: N = process .. x temperature .. "
                     "x supply ..' line")
    else:
        processes = [p.strip() for p in m.group(2).split(",") if p.strip()]
        temps = numbers(m.group(3))
        supplies = numbers(m.group(4))
        expected = expand_matrix(processes, temps, supplies)
        if int(m.group(1)) != len(expected):
            problems.add(where, f"declares {m.group(1)} PVT points but its lists expand to {len(expected)}")

    prov = section_body(text, "Provenance")
    for label, what in (("netlist-snapshots", "snapshot"), ("corners", "corner-log")):
        ids = set(re.findall(rf"`{label}/([^/`<]+)/", prov))
        if not ids:
            problems.add(where, f"'## Provenance' does not reference its {what} directory `{label}/<id>/`")
        elif ids != {rid}:
            problems.add(where, f"'## Provenance' {what} reference(s) {sorted(ids)} do not match this record id")
    for v in supplies:
        if not re.search(rf"klt sim request at supply {v:.2f} V", prov):
            problems.add(where, f"'## Provenance' has no 'klt sim request at supply {v:.2f} V' line")

    # per-corner compressed logs
    corners_dir = exp_dir / "corners" / rid
    if not corners_dir.is_dir():
        problems.add(where, f"missing corner directory {rel(root, corners_dir)}/")
    elif expected is not None:
        files = sorted(p for p in corners_dir.iterdir() if p.is_file())
        for p in files:
            if not p.name.endswith(".log.gz"):
                problems.add(rel(root, p), "unexpected non-.log.gz file in a Ka-band corner directory")
        compare_identities(problems, rel(root, corners_dir), "corner directory", expected,
                           [p.name[: -len(".log.gz")] for p in files if p.name.endswith(".log.gz")])
        for p in files:
            if p.name.endswith(".log.gz"):
                read_gzip_text(problems, root, p)

    # snapshot directory
    snap_dir = exp_dir / "netlist-snapshots" / rid
    if not snap_dir.is_dir():
        problems.add(where, f"missing netlist snapshot directory {rel(root, snap_dir)}/")
    elif supplies:
        want: dict[str, bool] = {}
        for v in supplies:
            want[f"body_{v:.2f}v.spice"] = False
            want[f"request_{v:.2f}v.json"] = True
            want[f"klt-report_{v:.2f}v.json"] = True
        have = {p.name for p in snap_dir.iterdir() if p.is_file()}
        for name, is_json in sorted(want.items()):
            p = snap_dir / name
            if name not in have:
                problems.add(rel(root, snap_dir), f"missing snapshot file {name}")
                continue
            if p.stat().st_size == 0:
                problems.add(rel(root, p), "snapshot file is empty")
            elif is_json:
                try:
                    json.loads(p.read_text(encoding="utf-8"))
                except (ValueError, UnicodeDecodeError) as exc:
                    problems.add(rel(root, p), f"not valid JSON ({exc})")
        for name in sorted(have - set(want)):
            problems.add(rel(root, snap_dir), f"unexpected snapshot file {name} (no declared supply for it)")

    # sidecars
    listed = set(re.findall(r"`records/([^`]+)`", section_body(text, "Sidecars")))
    for suffix in KABAND_SIDECAR_SUFFIXES:
        name = f"{rid}{suffix}"
        if name not in listed:
            problems.add(where, f"'## Sidecars' does not list required companion `records/{name}`")
        side = exp_dir / "records" / name
        if not side.is_file():
            problems.add(where, f"missing companion file {rel(root, side)}")
        elif expected is not None:
            ids = csv_corner_ids(problems, root, side)
            if ids is not None:
                compare_identities(problems, rel(root, side), "CSV corner_id column", expected, ids)
    for name in sorted(listed):
        if not (exp_dir / "records" / name).is_file():
            problems.add(where, f"'## Sidecars' lists `records/{name}` which does not exist")
    prefix = f"{rid}-"
    for p in sorted((exp_dir / "records").iterdir()):
        if p.name.startswith(prefix) and p.name not in listed:
            problems.add(rel(root, p), "companion file is not listed in its record's '## Sidecars' section")


# ---------------------------------------------------------------------------
# explicit adapters for non-PVT campaign layouts
# ---------------------------------------------------------------------------

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PASSIVE_STATUSES = ("QUALIFIED", "UNCONVERGED", "FIT_FAILED", "CAPABILITY_UNAVAILABLE")
PASSIVE_CONTROLS_STATUSES = ("CONTROLS-PASS", "CONTROLS-FAIL")
MIXER_STATUSES = ("METHOD_VALIDATION", "MODEL_ABSENT", "UNCONVERGED", "CAPABILITY_UNAVAILABLE")
MIXER_PROBE_FILES = ("deck.spice", "stdout.txt", "stderr.txt", "inventory.json")
PASSIVE_SCHEMA = "passive-p1-solver-artifacts/1"
PASSIVE_PACKAGES = "solver-artifacts"
PASSIVE_INCOMPLETE = ".INCOMPLETE"
# Campaign records committed before #58 froze nothing; they stay valid as legacy. Any other
# non-controls passive record must be record_schema 2 with a package (explicit set, not a clock).
LEGACY_PASSIVE_RECORDS = frozenset({"20261009-141515-0e10117-CAPABILITY_UNAVAILABLE"})
_SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")
_PKG_TOP = ("results", "fit", "run_log")
_SOLVES = ("results/inductor_p1", "results/convergence/p1_mesh0p5", "results/convergence/p1_margin400")
_SOLVER_FILES = tuple(p for b in _SOLVES for p in (b + ".s2p", b + "/port_information.json", b + "/run_meta.json"))
_POST_FILES = ("results/p1_metrics.json", "results/p1_lq.csv", "results/p1_deembedded.s2p")
_FIT_FILES = ("fit/p1_fit_parameters.json", "fit/p1_fit_candidate.spice")
_COMPARE_FILES = ("results/p1_compare.json",)
PAIR_RE = re.compile(r"^(\d{8}-\d{6}-[0-9a-f]{7,40})-([A-Za-z_-]+)\.(md|json)$")


def load_json_object(problems: Problems, root: Path, path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.add(rel(root, path), f"not valid JSON ({exc})")
        return None
    if not isinstance(data, dict):
        problems.add(rel(root, path), "JSON top level is not an object")
        return None
    return data


def record_pairs(problems: Problems, root: Path, records: Path) -> dict[str, dict[str, Path]]:
    """Group ``records/<id>-<STATUS>.{md,json}`` by stem; flag everything else."""
    pairs: dict[str, dict[str, Path]] = {}
    for p in sorted(records.iterdir()):
        m = PAIR_RE.match(p.name) if p.is_file() else None
        if not m:
            problems.add(rel(root, p), "not a <YYYYMMDD>-<HHMMSS>-<git-sha>-<STATUS>.md/.json record file")
            continue
        pairs.setdefault(p.stem, {})[m.group(3)] = p
    for stem, files in sorted(pairs.items()):
        for ext in ("md", "json"):
            if ext not in files:
                other = next(iter(files.values()))
                problems.add(rel(root, other), f"record has no paired .{ext} file ({stem}.{ext})")
    return pairs


def need_str(problems: Problems, where: str, obj: dict, key: str, label: str | None = None) -> str | None:
    val = obj.get(key)
    if not isinstance(val, str) or not val.strip():
        problems.add(where, f"JSON field {label or key!r} is missing or not a non-empty string")
        return None
    return val


def need_sha256(problems: Problems, where: str, value: object, label: str) -> None:
    if not isinstance(value, str) or not SHA256_RE.match(value):
        problems.add(where, f"{label} is missing or not a 64-hex sha256")


def check_passive_input_hashes(problems: Problems, root: Path, exp_dir: Path, where: str, rec: dict) -> None:
    ih = rec.get("input_hashes")
    files = ih.get("files") if isinstance(ih, dict) else None
    if not isinstance(files, dict) or not files:
        problems.add(where, "JSON 'input_hashes.files' is missing or empty (no input provenance)")
        return
    if not (exp_dir / "INPUTS.json").is_file():
        problems.add(where, f"declared input manifest {rel(root, exp_dir / 'INPUTS.json')} does not exist")
    for name, entry in sorted(files.items()):
        need_sha256(problems, where, entry.get("sha256") if isinstance(entry, dict) else None,
                    f"input_hashes.files[{name!r}].sha256")
        if not (exp_dir / name).is_file():
            problems.add(where, f"declared input {name!r} does not exist under {rel(root, exp_dir)}/")


def safe_package_path(p: object) -> bool:
    if not isinstance(p, str) or not p or p.startswith("/") or "\\" in p or "\x00" in p:
        return False
    return all(_SAFE_COMPONENT_RE.match(c) and c not in (".", "..") for c in p.split("/"))


def passive_required_paths(status: str, stages: list[str], has_compare: bool) -> list[str]:
    """Mirror of sim/passive-p1/scripts/freeze_package.py required_paths() (a test asserts they agree)."""
    st = set(stages)
    if status == "CAPABILITY_UNAVAILABLE":
        return []
    req = list(_SOLVER_FILES) + list(_POST_FILES)
    if "geometry" in st:
        req += ["run_log/geometry_overlay.txt", "run_log/geometry_p1.txt", "run_log/geometry_xor.txt"]
    if "em" in st:
        req.append("run_log/em_p1.txt")
    if "convergence" in st:
        req += ["run_log/em_conv_p1_mesh0p5.txt", "run_log/em_conv_p1_margin400.txt"]
    if "post" in st:
        req.append("run_log/postprocess.txt")
    if status == "FIT_FAILED":
        if "fit" in st:
            req.append("run_log/fit.txt")
        if has_compare:
            req += list(_FIT_FILES) + list(_COMPARE_FILES)
            if "compare" in st:
                req.append("run_log/compare.txt")
    elif status == "QUALIFIED":
        req += list(_FIT_FILES) + list(_COMPARE_FILES)
        req += [f"run_log/{k}.txt" for k in ("fit", "compare") if k in st]
    return sorted(set(req))


def _sha256_of(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_passive_package(problems: Problems, root: Path, exp_dir: Path, pid: str, status: str, rec: dict,
                          md: str, where_js: str, where_md: str) -> None:
    """record_schema 2: validate the frozen package named by the record (see module docstring)."""
    ap = rec.get("artifact_package")
    expected = f"sim/{exp_dir.name}/{PASSIVE_PACKAGES}/{pid}/"
    if not isinstance(ap, dict):
        problems.add(where_js, "record_schema 2 needs an 'artifact_package' object")
        return
    if ap.get("path") != expected:
        problems.add(where_js, f"artifact_package.path {ap.get('path')!r} must be {expected!r} "
                     "(relative, no traversal, this record's own run id)")
        return
    if ap.get("schema") != PASSIVE_SCHEMA:
        problems.add(where_js, f"artifact_package.schema {ap.get('schema')!r} must be {PASSIVE_SCHEMA!r}")
    if ap.get("manifest") != "manifest.json":
        problems.add(where_js, "artifact_package.manifest must be 'manifest.json'")
    need_sha256(problems, where_js, ap.get("manifest_sha256"), "artifact_package.manifest_sha256")
    if expected not in md:
        problems.add(where_md, f"Markdown does not name its frozen package {expected}")
    if isinstance(ap.get("manifest_sha256"), str) and f"`{ap['manifest_sha256']}`" not in md:
        problems.add(where_md, "Markdown does not carry the JSON artifact_package.manifest_sha256")
    pkg = exp_dir / PASSIVE_PACKAGES / pid
    where_pkg = rel(root, pkg)
    if pkg.is_symlink() or not pkg.is_dir():
        problems.add(where_js, f"declared artifact package {where_pkg}/ does not exist")
        return
    if (pkg / PASSIVE_INCOMPLETE).exists():
        problems.add(where_pkg, f"package carries {PASSIVE_INCOMPLETE}: interrupted/incomplete publication")
    mpath = pkg / "manifest.json"
    if not mpath.is_file() or mpath.is_symlink():
        problems.add(where_pkg, "package has no manifest.json (incomplete publication)")
        return
    if isinstance(ap.get("manifest_sha256"), str) and _sha256_of(mpath) != ap["manifest_sha256"]:
        problems.add(rel(root, mpath), "manifest sha256 does not match the record's artifact_package.manifest_sha256")
    man = load_json_object(problems, root, mpath)
    if man is None:
        return
    where_man = rel(root, mpath)
    if man.get("schema") != PASSIVE_SCHEMA:
        problems.add(where_man, f"manifest schema {man.get('schema')!r} must be {PASSIVE_SCHEMA!r}")
    if man.get("run_id") != pid:
        problems.add(where_man, f"manifest run_id {man.get('run_id')!r} does not match {pid!r}")
    if man.get("status") != status:
        problems.add(where_man, f"manifest status {man.get('status')!r} does not match record status {status!r}")
    stages = rec.get("stages")
    stage_list = stages.split() if isinstance(stages, str) else []
    if man.get("stages") != stage_list:
        problems.add(where_man, "manifest stages disagree with the record's 'stages'")
    files = man.get("files")
    if not isinstance(files, list) or not files:
        problems.add(where_man, "manifest 'files' is missing or empty")
        return
    listed: dict[str, dict] = {}
    for e in files:
        path = e.get("path") if isinstance(e, dict) else None
        if not safe_package_path(path):
            problems.add(where_man, f"unsafe or malformed package path {path!r} (must be a relative, "
                         "traversal-free path of plain components)")
            continue
        if path in listed:
            problems.add(where_man, f"duplicate manifest path {path!r}")
            continue
        if path != "settings.json" and path.split("/")[0] not in _PKG_TOP:
            problems.add(where_man, f"path {path!r} is outside settings.json/{'/'.join(_PKG_TOP)}/")
            continue
        listed[path] = e
        need_sha256(problems, where_man, e.get("sha256"), f"files[{path!r}].sha256")
        if not isinstance(e.get("bytes"), int) or isinstance(e.get("bytes"), bool):
            problems.add(where_man, f"files[{path!r}].bytes is not an integer")
        fp = pkg.joinpath(*path.split("/"))
        if fp.is_symlink() or not fp.is_file():
            problems.add(where_man, f"listed file {path} is missing from the package")
            continue
        if isinstance(e.get("sha256"), str) and _sha256_of(fp) != e["sha256"]:
            problems.add(rel(root, fp), "sha256 does not match the manifest (package bytes were altered)")
        elif isinstance(e.get("bytes"), int) and fp.stat().st_size != e["bytes"]:
            problems.add(rel(root, fp), "size does not match the manifest")
    on_disk = set()
    for p in sorted(pkg.rglob("*")):
        if p.is_symlink():
            problems.add(rel(root, p), "symlink inside a frozen package")
        elif p.is_file():
            on_disk.add(p.relative_to(pkg).as_posix())
    for extra in sorted(on_disk - set(listed) - {"manifest.json", PASSIVE_INCOMPLETE}):
        problems.add(rel(root, pkg / extra), "file in the package is not listed in manifest.json")
    if "settings.json" not in listed:
        problems.add(where_man, "manifest does not list settings.json (stage settings are required)")
    has_compare = isinstance(rec.get("compare"), dict)
    for need in passive_required_paths(status, stage_list, has_compare):
        if need not in listed:
            problems.add(where_man, f"package is incomplete: required stage output {need} is not in the "
                         f"manifest for a {status} record with stages [{' '.join(stage_list)}]")
    if status == "CAPABILITY_UNAVAILABLE":
        solver = [p for p in listed if p.startswith("results/") or p.startswith("fit/")]
        if solver:
            problems.add(where_man, f"CAPABILITY_UNAVAILABLE package carries solver/analysis data ({solver[0]}); "
                         "diagnostics (logs) only")
    # record <-> frozen bytes agreement (the record was derived from the frozen copy)
    for key, relname in (("metrics", "results/p1_metrics.json"), ("compare", "results/p1_compare.json")):
        fp = pkg.joinpath(*relname.split("/"))
        if relname in listed and fp.is_file():
            try:
                frozen = json.loads(fp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                problems.add(rel(root, fp), "packaged JSON is not valid JSON")
                continue
            if frozen != rec.get(key):
                problems.add(where_js, f"record '{key}' differs from the packaged {relname}")
        elif rec.get(key) is not None and relname not in listed:
            problems.add(where_js, f"record carries '{key}' numbers but the package has no {relname}")


def check_passive_record(problems: Problems, root: Path, exp_dir: Path, stem: str, files: dict[str, Path],
                         claimed_packages: set[str]) -> None:
    md_path, js_path = files.get("md"), files.get("json")
    if md_path is None or js_path is None:
        return  # the missing half is already reported by record_pairs
    where_md, where_js = rel(root, md_path), rel(root, js_path)
    m = PAIR_RE.match(md_path.name)
    assert m is not None
    rid, status = m.group(1), m.group(2)
    md = md_path.read_text(encoding="utf-8", errors="replace")
    rec = load_json_object(problems, root, js_path)

    if status.startswith("SYNTHETIC-") or md.lstrip().startswith("> **SYNTHETIC") or (
            rec is not None and rec.get("synthetic") is True):
        problems.add(where_md, "synthetic smoke record inside records/ (SYNTHETIC-* pipeline output is not "
                     "campaign evidence and must be kept out of records/)")
        return
    controls = status in PASSIVE_CONTROLS_STATUSES
    if not controls and status not in PASSIVE_STATUSES:
        problems.add(where_md, f"status {status!r} is not one of "
                     f"{', '.join(PASSIVE_STATUSES + PASSIVE_CONTROLS_STATUSES)}")
        return

    kind = "controls record" if controls else "record"
    first = md.splitlines()[0] if md.strip() else ""
    if first != f"# passive-p1 {kind} {stem}":
        problems.add(where_md, f"first line must be '# passive-p1 {kind} {stem}', found {first[:80]!r}")
    if rec is None:
        return
    if rec.get("record_id") != stem:
        problems.add(where_js, f"JSON record_id {rec.get('record_id')!r} does not match its file name {stem!r}")

    if controls:
        want_pass = status == "CONTROLS-PASS"
        if not isinstance(rec.get("all_pass"), bool):
            problems.add(where_js, "JSON 'all_pass' is missing or not a boolean")
        groups = rec.get("groups")
        if not isinstance(groups, dict) or not groups:
            problems.add(where_js, "JSON 'groups' is missing or empty")
            groups = {}
        results = {}
        for name, grp in groups.items():
            if not isinstance(grp, dict) or not isinstance(grp.get("pass"), bool):
                problems.add(where_js, f"control group {name!r} has no boolean 'pass'")
            else:
                results[name] = grp["pass"]
        if isinstance(rec.get("all_pass"), bool):
            if rec["all_pass"] != want_pass:
                problems.add(where_js, f"all_pass={rec['all_pass']} contradicts status suffix {status}")
            if results and rec["all_pass"] != all(results.values()):
                problems.add(where_js, "all_pass is not the conjunction of the control group results")
        need_str(problems, where_js, rec, "kind")
        need_sha256(problems, where_js, rec.get("fixture_sha256"), "fixture_sha256")
        fixture = rec.get("fixture")
        if not isinstance(fixture, str) or not (exp_dir / fixture).is_file():
            problems.add(where_js, f"declared fixture {fixture!r} does not exist under {rel(root, exp_dir)}/")
        for field in ("ngspice", "numpy"):
            need_str(problems, where_js, rec, field)
        if isinstance(rec.get("limits"), dict) is False:
            problems.add(where_js, "JSON 'limits' is missing")
        overall = "ALL CONTROLS BEHAVED AS REQUIRED" if want_pass else "FAILURE"
        if f"- Overall: **{overall}**" not in md:
            problems.add(where_md, f"Markdown does not state '- Overall: **{overall}**' for status {status}")
        md_groups = dict(re.findall(r"^## (.+?) -- (PASS|FAIL)\s*$", md, re.MULTILINE))
        if set(md_groups) != set(results) or any(md_groups[g] != ("PASS" if results[g] else "FAIL")
                                                   for g in md_groups if g in results):
            problems.add(where_md, "Markdown control sections disagree with the JSON groups/results")
        sha = rec.get("fixture_sha256")
        if isinstance(sha, str) and f"`{sha}`" not in md:
            problems.add(where_md, "Markdown does not carry the JSON fixture_sha256")
        if "**Scope**:" not in md:
            problems.add(where_md, "missing '**Scope**:' statement (controls make no EM claim)")
        return

    # campaign record
    if rec.get("status") != status:
        problems.add(where_js, f"JSON status {rec.get('status')!r} does not match file name status {status!r}")
    if rec.get("synthetic") is not False:
        problems.add(where_js, "JSON 'synthetic' must be false for a campaign record")
    if f"- **Status: {status}**" not in md:
        problems.add(where_md, f"Markdown does not state '- **Status: {status}**'")
    reasons = rec.get("reasons")
    if not isinstance(reasons, list) or not reasons or not all(isinstance(r, str) and r for r in reasons):
        problems.add(where_js, "JSON 'reasons' must be a non-empty list of strings")
    utc = need_str(problems, where_js, rec, "utc")
    if utc is not None:
        mt = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", utc)
        if not mt or "".join(mt.groups()[:3]) + "-" + "".join(mt.groups()[3:]) != rid[:15]:
            problems.add(where_js, f"JSON utc {utc!r} does not match the record id timestamp {rid[:15]!r}")
    digest = rec.get("numerical_digest")
    need_sha256(problems, where_js, digest, "numerical_digest")
    if isinstance(digest, str) and f"`{digest}`" not in md:
        problems.add(where_md, "Markdown does not carry the JSON numerical_digest")
    env = rec.get("environment")
    if not isinstance(env, dict):
        problems.add(where_js, "JSON 'environment' is missing")
    else:
        commit = env.get("git_commit")
        if not isinstance(commit, str) or not commit.startswith(rid.split("-")[2]):
            problems.add(where_js, f"environment.git_commit {commit!r} does not match the sha in the record id")
        for field in ("host", "platform", "python"):
            need_str(problems, where_js, env, field, f"environment.{field}")
        if isinstance(commit, str) and f"`{commit}`" not in md:
            problems.add(where_md, "Markdown '## Provenance' does not carry the JSON environment.git_commit")
    for title in ("Provenance", "Limitations (stated beside the claims)"):
        if not has_section(md, title):
            problems.add(where_md, f"missing required section '## {title}'")
    if "Claim scope:" not in md:
        problems.add(where_md, "missing the 'Claim scope:' statement")
    check_passive_input_hashes(problems, root, exp_dir, where_js, rec)
    if status == "CAPABILITY_UNAVAILABLE":
        need_str(problems, where_js, rec, "failed_command")
        if rec.get("metrics") is not None or rec.get("compare") is not None:
            problems.add(where_js, "CAPABILITY_UNAVAILABLE record carries metrics/compare numbers "
                         "(an unavailable capability establishes no number)")
        if not has_section(md, "Failed capability check"):
            problems.add(where_md, "missing required section '## Failed capability check'")
    else:
        if not isinstance(rec.get("metrics"), dict):
            problems.add(where_js, f"{status} record has no 'metrics' object")
        if status in ("QUALIFIED", "FIT_FAILED") and rec.get("compare") is not None and not isinstance(
                rec.get("compare"), dict):
            problems.add(where_js, "JSON 'compare' is neither null nor an object")
        if status == "QUALIFIED" and not isinstance(rec.get("compare"), dict):
            problems.add(where_js, "QUALIFIED record has no 'compare' (fit validation) object")
    schema = rec.get("record_schema")
    if schema is None:
        if stem not in LEGACY_PASSIVE_RECORDS:
            problems.add(where_js, "record has no 'record_schema': only the pre-#58 legacy records "
                         "may omit the frozen solver-artifact package; new records must be record_schema 2")
        elif "artifact_package" in rec:
            problems.add(where_js, "legacy record unexpectedly carries an artifact_package")
        # legacy: run_log/ files named by the record must exist (existence only: working output)
        for ref in sorted(set(re.findall(r"\(?`?(run_log/[A-Za-z0-9_.\-]+)", md))):
            if not (exp_dir / ref).is_file():
                problems.add(where_md, f"declared companion {ref} does not exist under {rel(root, exp_dir)}/")
    elif schema == 2:
        claimed_packages.add(rid)
        check_passive_package(problems, root, exp_dir, rid, status, rec, md, where_js, where_md)
    else:
        problems.add(where_js, f"unknown record_schema {schema!r} (known: absent=legacy, 2)")


def check_passive_p1(problems: Problems, root: Path, exp_dir: Path) -> None:
    records = exp_dir / "records"
    if not records.is_dir():
        return
    claimed: set[str] = set()
    for stem, files in record_pairs(problems, root, records).items():
        check_passive_record(problems, root, exp_dir, stem, files, claimed)
    pk = exp_dir / PASSIVE_PACKAGES
    if pk.exists():
        if not pk.is_dir():
            problems.add(rel(root, pk), f"{PASSIVE_PACKAGES} must be a directory of <id>/ run packages")
        else:
            for p in sorted(pk.iterdir()):
                if p.is_symlink() or not (p.is_dir() and RECORD_ID_RE.match(p.name)):
                    problems.add(rel(root, p), f"{PASSIVE_PACKAGES} entry is not a <YYYYMMDD>-<HHMMSS>-<git-sha>/ "
                                 "run directory")
                elif p.name not in claimed:
                    problems.add(rel(root, p), "solver-artifact package belongs to no record "
                                 "(orphan or interrupted publication)")
    for sub in ("corners", "netlist-snapshots", "probe-logs"):
        if (exp_dir / sub).exists():
            problems.add(rel(root, exp_dir / sub), f"{sub}/ is not part of the passive-p1 evidence layout")


def check_mixer_record(problems: Problems, root: Path, exp_dir: Path, stem: str, files: dict[str, Path],
                       claimed_logs: set[str]) -> None:
    md_path, js_path = files.get("md"), files.get("json")
    if md_path is None or js_path is None:
        return
    where_md, where_js = rel(root, md_path), rel(root, js_path)
    m = PAIR_RE.match(md_path.name)
    assert m is not None
    rid, status = m.group(1), m.group(2)
    if status not in MIXER_STATUSES:
        problems.add(where_md, f"status {status!r} is not one of {', '.join(MIXER_STATUSES)}")
        return
    md = md_path.read_text(encoding="utf-8", errors="replace")
    first = md.splitlines()[0] if md.strip() else ""
    if first != f"# mixer-nf-method record {stem}":
        problems.add(where_md, f"first line must be '# mixer-nf-method record {stem}', found {first[:80]!r}")
    if f"- **Status: {status}**" not in md:
        problems.add(where_md, f"Markdown does not state '- **Status: {status}**'")
    rec = load_json_object(problems, root, js_path)
    if rec is None:
        return
    if rec.get("record_id") != rid:
        problems.add(where_js, f"JSON record_id {rec.get('record_id')!r} does not match the record id {rid!r}")
    if rec.get("status") != status:
        problems.add(where_js, f"JSON status {rec.get('status')!r} does not match file name status {status!r}")
    reasons = rec.get("reasons")
    if status != "METHOD_VALIDATION" and (
            not isinstance(reasons, list) or not reasons or not all(isinstance(r, str) and r for r in reasons)):
        problems.add(where_js, "JSON 'reasons' must be a non-empty list of strings")
    env = rec.get("environment")
    if not isinstance(env, dict):
        problems.add(where_js, "JSON 'environment' is missing")
        env = {}
    git = env.get("git")
    commit = git.get("commit") if isinstance(git, dict) else None
    if not isinstance(commit, str) or not commit.startswith(rid.split("-")[2]):
        problems.add(where_js, f"environment.git.commit {commit!r} does not match the sha in the record id")
    for field in ("host", "platform", "python"):
        need_str(problems, where_js, env, field, f"environment.{field}")

    if status == "CAPABILITY_UNAVAILABLE":
        need_str(problems, where_js, rec, "failed_check")
        if "inventory" in rec or "probe_logs" in rec:
            problems.add(where_js, "CAPABILITY_UNAVAILABLE record carries probe results/logs "
                         "(no simulator ran; it cannot establish model absence)")
        if "Failed check:" not in md:
            problems.add(where_md, "missing the 'Failed check:' statement")
        return

    # a probe record: scope statement, provenance and the frozen log package
    if "Scope:" not in md:
        problems.add(where_md, "missing the '**Scope: ...**' statement (methodology evidence only)")
    scope = need_str(problems, where_js, rec, "scope")
    if scope is not None and "no active-mixer NF number" not in scope:
        problems.add(where_js, "JSON 'scope' does not disclaim an active-mixer NF number")
    if not has_section(md, "Provenance"):
        problems.add(where_md, "missing required section '## Provenance'")
    for field in ("placeholder_sha256", "template_sha256"):
        need_sha256(problems, where_js, env.get(field), f"environment.{field}")
    ng, pdk = env.get("ngspice"), env.get("pdk")
    need_sha256(problems, where_js, ng.get("sha256") if isinstance(ng, dict) else None, "environment.ngspice.sha256")
    if not isinstance(pdk, dict) or not pdk.get("fetched_version"):
        problems.add(where_js, "environment.pdk.fetched_version is missing")
    if isinstance(commit, str) and f"`{commit}`" not in md:
        problems.add(where_md, "Markdown '## Provenance' does not carry the JSON environment.git.commit")
    if not isinstance(rec.get("inventory"), dict):
        problems.add(where_js, "JSON 'inventory' is missing")

    declared = rec.get("probe_logs")
    expected = f"sim/{exp_dir.name}/probe-logs/{rid}/"
    if declared != expected:
        problems.add(where_js, f"JSON probe_logs {declared!r} must be {expected!r}")
    logs = exp_dir / "probe-logs" / rid
    claimed_logs.add(rid)
    if f"probe-logs/{rid}/" not in md:
        problems.add(where_md, f"Markdown does not reference its probe-logs/{rid}/ package")
    if not logs.is_dir():
        problems.add(where_js, f"declared probe-log package {rel(root, logs)}/ does not exist")
        return
    present = {p.name for p in logs.iterdir() if p.is_file()}
    for name in MIXER_PROBE_FILES:
        if name not in present:
            problems.add(rel(root, logs), f"probe-log package is missing {name}")
        elif name != "stderr.txt" and (logs / name).stat().st_size == 0:
            problems.add(rel(root, logs / name), "probe-log file is empty")  # stderr may legitimately be empty
    for name in sorted(present - set(MIXER_PROBE_FILES)):
        problems.add(rel(root, logs / name), "unexpected file in a probe-log package")
    for p in logs.iterdir():
        if p.is_dir():
            problems.add(rel(root, p), "unexpected directory in a probe-log package")
    inv_path = logs / "inventory.json"
    if inv_path.is_file():
        inv = load_json_object(problems, root, inv_path)
        if inv is not None:
            if not isinstance(inv.get("parsed"), dict) or not isinstance(inv.get("inventory"), dict):
                problems.add(rel(root, inv_path), "inventory.json needs 'parsed' and 'inventory' objects")
            elif inv["inventory"] != rec.get("inventory"):
                problems.add(rel(root, inv_path), "inventory.json 'inventory' differs from the record's "
                             "JSON 'inventory' (record and frozen log disagree)")


def check_mixer_nf_method(problems: Problems, root: Path, exp_dir: Path) -> None:
    records = exp_dir / "records"
    claimed: set[str] = set()
    if records.is_dir():
        for stem, files in record_pairs(problems, root, records).items():
            check_mixer_record(problems, root, exp_dir, stem, files, claimed)
    logs_root = exp_dir / "probe-logs"
    if logs_root.is_dir():
        for p in sorted(logs_root.iterdir()):
            if not (p.is_dir() and RECORD_ID_RE.match(p.name)):
                problems.add(rel(root, p), "probe-logs entry is not a <YYYYMMDD>-<HHMMSS>-<git-sha>/ run directory")
            elif p.name not in claimed:
                problems.add(rel(root, p), "probe-log package belongs to no record (orphan or incomplete run)")
    for sub in ("corners", "netlist-snapshots", PASSIVE_PACKAGES):
        if (exp_dir / sub).exists():
            problems.add(rel(root, exp_dir / sub), f"{sub}/ is not part of the mixer-nf-method evidence layout")


# ---------------------------------------------------------------------------
# lna-match-tradeoff (sim/lna-match-tradeoff/collect.py, issue #74)
# ---------------------------------------------------------------------------

LNAMATCH_STATUSES = ("ok", "rejected_invalid")
LNAMATCH_RECORD_FILE_RE = re.compile(r"^(\d{8}-\d{6}-[0-9a-f]{7,40})(\.md|\.json|-cells\.json\.gz)$")
LNAMATCH_MD_MARKERS = (
    "**Spec rows claimed met**: none",
    "## Method",
    "## Intentional reductions",
    "## Controls",
    "## Nominal screen",
    "## Shortlist",
    "## Network-independent bound",
    "## Corner campaign",
    "## Conclusion",
    "## Provenance and raw artifacts",
)
LNAMATCH_PROVENANCE = ("git", "ngspice", "klt", "pdk", "klt_requests", "frozen_inputs")


def _lnamatch_cid(process: str, temp: float, vdd: float) -> str:
    return f"{process}_{temp:g}c_{vdd:.2f}v"


def lnamatch_expected_ids(decl: dict, shortlist: list) -> list[str]:
    """Declared cell ids from the FROZEN declaration (the record's own
    netlist-snapshots/<id>/study.json) and the record's shortlist: every
    declared network at the nominal screen point, and the shortlist plus every
    probe at every PVT point. Mirrors matchstudy.expected_cells."""
    n, pvt = decl["nominal"], decl["pvt"]
    nom = _lnamatch_cid(n["process"], float(n["temp_c"]), float(n["vdd"]))
    ids = [f"screen__{c['name']}__{nom}" for c in decl["candidates"]]
    probes = [c["name"] for c in decl["candidates"] if c.get("role") == "probe"]
    for name in list(shortlist) + probes:
        for p in pvt["processes"]:
            for t in pvt["temperatures_c"]:
                for v in pvt["supplies_v"]:
                    ids.append(f"corners__{name}__{_lnamatch_cid(p, float(t), float(v))}")
    return ids


def _all_numbers(values) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)


def check_lnamatch_cells(problems: Problems, root: Path, path: Path, cells: object, decl: dict | None,
                         shortlist: list, accepted: object) -> None:
    wc = rel(root, path)
    if not isinstance(cells, list):
        problems.add(wc, "cells file is not a JSON list")
        return
    if len(cells) != accepted:
        problems.add(wc, f"{len(cells)} cells on disk, sidecar says accepted_cells {accepted!r}")
    ids = [c.get("id") if isinstance(c, dict) else None for c in cells]
    for dup in duplicates(ids):
        problems.add(wc, f"duplicate cell id {dup!r}")
    if decl is not None:
        try:
            want = lnamatch_expected_ids(decl, shortlist)
        except (KeyError, TypeError, ValueError) as exc:
            problems.add(wc, f"cannot expand the frozen declaration ({exc!r})")
            want = None
        if want is not None:
            for missing in sorted(set(want) - set(ids)):
                problems.add(wc, f"missing declared cell {missing!r}")
            for extra in sorted(set(i for i in ids if i is not None) - set(want)):
                problems.add(wc, f"undeclared cell {extra!r}")
    dense_n = ((decl or {}).get("grid") or {}).get("dense_points")
    for c in cells:
        if not isinstance(c, dict):
            problems.add(wc, "cell is not an object")
            continue
        cid = c.get("id")
        status = c.get("status")
        if status not in LNAMATCH_STATUSES:
            problems.add(wc, f"{cid}: status {status!r} is not a scientific outcome")
            continue
        if c.get("model_section") != c.get("process"):
            problems.add(wc, f"{cid}: model_section {c.get('model_section')!r} != process {c.get('process')!r}")
        if status == "rejected_invalid":
            if not c.get("reason"):
                problems.add(wc, f"{cid}: rejected cell without a reason")
            continue
        sm = c.get("summary")
        if not isinstance(sm, dict) or not sm or not _all_numbers(sm.values()):
            problems.add(wc, f"{cid}: ok cell with a missing or non-finite summary")
        if c.get("role") == "probe":
            continue
        if not (c.get("refined") or {}).get("ok"):
            problems.add(wc, f"{cid}: ok cell without a passing refined-grid control")
        band = c.get("band")
        if not isinstance(band, dict) or not isinstance(band.get("f_hz"), list):
            problems.add(wc, f"{cid}: ok cell without per-frequency band data")
            continue
        n = len(band["f_hz"])
        if dense_n is not None and n != dense_n:
            problems.add(wc, f"{cid}: band grid has {n} points, the declaration says {dense_n}")
        for key in ("s11_db", "s21_db", "s22_db", "s12_db", "nf_db", "k", "delta"):
            arr = band.get(key)
            if not isinstance(arr, list) or len(arr) != n or not _all_numbers(arr):
                problems.add(wc, f"{cid}: band.{key} missing, wrong length or non-finite")
        wide = c.get("wide")
        if not isinstance(wide, dict) or not wide.get("k") or not _all_numbers(wide["k"]):
            problems.add(wc, f"{cid}: ok cell without a finite wide stability sweep")
        if not isinstance(c.get("screen"), dict) or "pass" not in c["screen"]:
            problems.add(wc, f"{cid}: ok cell without a screen outcome")


def check_lnamatch_record(problems: Problems, root: Path, exp_dir: Path, rid: str) -> None:
    md = exp_dir / "records" / f"{rid}.md"
    where = rel(root, md)
    text = md.read_text(encoding="utf-8", errors="replace")
    first = text.splitlines()[0] if text.strip() else ""
    if first != f"# lna-match-tradeoff record {rid}":
        problems.add(where, f"first line must be '# lna-match-tradeoff record {rid}', found {first[:80]!r}")
    for marker in LNAMATCH_MD_MARKERS:
        if marker not in text:
            problems.add(where, f"record lacks required content {marker!r}")
    snap = exp_dir / "netlist-snapshots" / rid
    decl = None
    decl_path = snap / "study.json"
    if not snap.is_dir():
        problems.add(rel(root, snap), "netlist-snapshots/<id>/ directory missing")
    elif not decl_path.is_file():
        problems.add(rel(root, snap), "snapshot lacks the frozen declaration study.json")
    else:
        decl = load_json_object(problems, root, decl_path)
    if snap.is_dir() and not (snap / "lna_stage1.spice").is_file():
        problems.add(rel(root, snap), "snapshot lacks the frozen DUT lna_stage1.spice")
    js = exp_dir / "records" / f"{rid}.json"
    if not js.is_file():
        problems.add(where, f"record has no JSON sidecar {rid}.json")
        return
    data = load_json_object(problems, root, js)
    if data is None:
        return
    wj = rel(root, js)
    if data.get("record_id") != rid:
        problems.add(wj, f"JSON record_id {data.get('record_id')!r} != {rid!r}")
    if "no spec row" not in str(data.get("scope", "")) or data.get("spec_rows_claimed_met") != []:
        problems.add(wj, "JSON must state that no spec row is claimed met (scope + empty spec_rows_claimed_met)")
    gate = data.get("gate")
    if not (isinstance(gate, dict) and gate.get("validate_collection") == "passed" and not gate.get("problems")):
        problems.add(wj, "acceptance gate result is not recorded as passed")
    dc, ac = data.get("declared_cells"), data.get("accepted_cells")
    if not (isinstance(dc, int) and dc > 0 and dc == ac):
        problems.add(wj, f"declared_cells {dc!r} != accepted_cells {ac!r}")
    prov = data.get("provenance") if isinstance(data.get("provenance"), dict) else {}
    if not prov:
        problems.add(wj, "no provenance object")
    for key in LNAMATCH_PROVENANCE:
        if prov.get(key) in (None, "", {}, []):
            problems.add(wj, f"provenance.{key} missing or empty")
    if isinstance(prov.get("pdk"), dict) and not prov["pdk"].get("model_sha256"):
        problems.add(wj, "provenance.pdk.model_sha256 missing or empty")
    decl_sha = (data.get("declaration") or {}).get("sha256")
    if decl_path.is_file() and decl_sha != _sha256_of(decl_path):
        problems.add(wj, "declaration.sha256 does not match the frozen netlist-snapshots/<id>/study.json")
    fi = prov.get("frozen_inputs") if isinstance(prov.get("frozen_inputs"), dict) else {}
    dut = snap / "lna_stage1.spice"
    if dut.is_file() and fi.get("design_netlist_sha256") != _sha256_of(dut):
        problems.add(wj, "frozen_inputs.design_netlist_sha256 does not match the frozen DUT snapshot")
    sl = data.get("shortlist") if isinstance(data.get("shortlist"), dict) else {}
    names = sl.get("names") if isinstance(sl.get("names"), list) else []
    if decl is not None:
        roles = {c.get("name"): c.get("role") for c in decl.get("candidates", []) if isinstance(c, dict)}
        if not names or roles.get(names[0]) != "baseline":
            problems.add(wj, "shortlist must start with the declared baseline")
        for n in names:
            if roles.get(n) not in ("baseline", "candidate"):
                problems.add(wj, f"shortlist names {n!r}, which is not a declared selectable network")
    reqs = prov.get("klt_requests") if isinstance(prov.get("klt_requests"), list) else []
    units = 0
    for r in reqs:
        if not isinstance(r, dict) or not r.get("key") or not isinstance(r.get("units"), int):
            problems.add(wj, "malformed provenance.klt_requests entry")
            continue
        units += r["units"]
        if snap.is_dir():
            for prefix, suffix in (("body_", ".spice"), ("request_", ".json"), ("report_", ".json"), ("spec_", ".json")):
                if not (snap / f"{prefix}{r['key']}{suffix}").is_file():
                    problems.add(rel(root, snap), f"snapshot lacks {prefix}{r['key']}{suffix}")
    if data.get("cells_file") != f"{rid}-cells.json.gz":
        problems.add(wj, f"cells_file {data.get('cells_file')!r} != {rid + '-cells.json.gz'!r}")
    cells_gz = exp_dir / "records" / f"{rid}-cells.json.gz"
    if not cells_gz.is_file():
        problems.add(where, f"record has no cells file {cells_gz.name}")
    else:
        raw = read_gzip_text(problems, root, cells_gz)
        if raw is not None:
            try:
                cells = json.loads(raw)
            except ValueError as exc:
                problems.add(rel(root, cells_gz), f"cells file is not valid JSON ({exc})")
            else:
                check_lnamatch_cells(problems, root, cells_gz, cells, decl, names, ac)
    logs = exp_dir / "corners" / rid
    if not logs.is_dir() or not any(logs.glob("*.log.gz")):
        problems.add(rel(root, logs), "no corners/<id>/*.log.gz raw logs for this record")
    else:
        n_logs = 0
        for p in sorted(logs.iterdir()):
            if not p.name.endswith(".log.gz"):
                problems.add(rel(root, p), "unexpected file in an lna-match-tradeoff corners directory")
            else:
                n_logs += 1
                read_gzip_text(problems, root, p)
        if reqs and n_logs != units:
            problems.add(rel(root, logs), f"{n_logs} raw logs, but the requests ran {units} units")


def check_lna_match_tradeoff(problems: Problems, root: Path, exp_dir: Path) -> None:
    decl = exp_dir / "testbench" / "study.json"
    if not decl.is_file():
        problems.add(rel(root, exp_dir), "lna-match-tradeoff has no testbench/study.json declaration")
    records = exp_dir / "records"
    ids: set[str] = set()
    if records.is_dir():
        groups: dict[str, set[str]] = {}
        for p in sorted(records.iterdir()):
            m = LNAMATCH_RECORD_FILE_RE.match(p.name)
            if not m:
                problems.add(rel(root, p), "unexpected file in lna-match-tradeoff records/ "
                             "(only <id>.md, <id>.json, <id>-cells.json.gz)")
                continue
            groups.setdefault(m.group(1), set()).add(m.group(2))
        for rid, parts in sorted(groups.items()):
            if ".md" not in parts:
                problems.add(rel(root, records), f"evidence for {rid} belongs to no record (no {rid}.md)")
                continue
            ids.add(rid)
            check_lnamatch_record(problems, root, exp_dir, rid)
    for sub in ("corners", "netlist-snapshots"):
        d = exp_dir / sub
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.name not in ids:
                    problems.add(rel(root, p), f"{sub} entry belongs to no record in this experiment (orphan evidence)")
    for sub in ("probe-logs", PASSIVE_PACKAGES):
        if (exp_dir / sub).exists():
            problems.add(rel(root, exp_dir / sub), f"{sub}/ is not part of the lna-match-tradeoff evidence layout")


# Explicit registry of the non-PVT campaign layouts. A sim/<dir> with evidence
# directories that is neither a testbench bench nor listed here is an error.
ADAPTERS = {
    "passive-p1": check_passive_p1,
    "mixer-nf-method": check_mixer_nf_method,
    "lna-match-tradeoff": check_lna_match_tradeoff,
}
EVIDENCE_DIRS = ("records", "corners", "netlist-snapshots", "probe-logs", "solver-artifacts")


# ---------------------------------------------------------------------------
# tree walk
# ---------------------------------------------------------------------------


def is_kaband(exp_dir: Path, problems: Problems, root: Path) -> bool:
    tb = exp_dir / "testbench" / "tb.json"
    try:
        manifest = json.loads(tb.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.add(rel(root, tb), f"manifest unreadable ({exc})")
        return False
    if not isinstance(manifest, dict):
        problems.add(rel(root, tb), "manifest is not a JSON object")
        return False
    return "sweep" in manifest


MIXFEAS_STATUSES = ("ok", "rejected_stress", "not_applicable_no_drive")
MIXFEAS_SNAPSHOT_REQUIRED = ("tb.json", "ports_common.spice")
MIXFEAS_MD_MARKERS = (
    "Spec rows claimed met**: none",
    "## Intentional reductions",
    "## LO-drive selection",
    "## Conclusion",
    "## Provenance and raw artifacts",
)


def is_mixfeas(exp_dir: Path) -> bool:
    try:
        manifest = json.loads((exp_dir / "testbench" / "tb.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(manifest, dict) and "study" in manifest and "sweep" not in manifest


def check_mixfeas_record(problems: Problems, root: Path, exp_dir: Path, md: Path) -> None:
    stem = md.stem
    where = rel(root, md)
    text = md.read_text(encoding="utf-8")
    first = text.splitlines()[0] if text.strip() else ""
    if first != f"# mixer-topology-feasibility record {stem}":
        problems.add(where, f"first line must be '# mixer-topology-feasibility record {stem}', found {first[:80]!r}")
    if not RECORD_ID_RE.match(stem):
        problems.add(where, "record id is not <YYYYMMDD>-<HHMMSS>-<git-sha>")
    for marker in MIXFEAS_MD_MARKERS:
        if marker not in text:
            problems.add(where, f"record lacks required content {marker!r}")
    js = exp_dir / "records" / f"{stem}.json"
    cells_gz = exp_dir / "records" / f"{stem}-cells.json.gz"
    data = load_json_object(problems, root, js) if js.is_file() else None
    if data is None:
        if not js.is_file():
            problems.add(where, f"record has no JSON sidecar {stem}.json")
    else:
        wj = rel(root, js)
        if data.get("record_id") != stem:
            problems.add(wj, f"JSON record_id {data.get('record_id')!r} != {stem!r}")
        if "no spec row" not in str(data.get("scope", "")):
            problems.add(wj, "JSON 'scope' does not state that no spec row is claimed met")
        gate = data.get("gate")
        if not (isinstance(gate, dict) and gate.get("validate_collection") == "passed" and not gate.get("problems")):
            problems.add(wj, "acceptance gate result is not recorded as passed")
        dc, ac = data.get("declared_cells"), data.get("accepted_cells")
        if not (isinstance(dc, int) and dc > 0 and dc == ac):
            problems.add(wj, f"declared_cells {dc!r} != accepted_cells {ac!r}")
        prov = data.get("provenance")
        if not isinstance(prov, dict):
            problems.add(wj, "no provenance object")
            prov = {}
        for key in ("git", "ngspice", "klt", "pdk", "klt_requests", "converge", "crosscheck", "mismatch_seed"):
            if prov.get(key) in (None, "", {}, []):
                problems.add(wj, f"provenance.{key} missing or empty")
        pdk = prov.get("pdk")
        if isinstance(pdk, dict) and not pdk.get("model_sha256"):
            problems.add(wj, "provenance.pdk.model_sha256 missing or empty")
        if data.get("cells_file") != cells_gz.name:
            problems.add(wj, f"cells_file {data.get('cells_file')!r} != {cells_gz.name!r}")
        seed = prov.get("mismatch_seed")
        if not cells_gz.is_file():
            problems.add(where, f"record has no cells file {cells_gz.name}")
        else:
            raw = read_gzip_text(problems, root, cells_gz)
            cells = None
            if raw is not None:
                try:
                    cells = json.loads(raw)
                except ValueError as exc:
                    problems.add(rel(root, cells_gz), f"cells file is not valid JSON ({exc})")
            if cells is not None:
                wc = rel(root, cells_gz)
                if not isinstance(cells, list):
                    problems.add(wc, "cells file is not a JSON list")
                else:
                    ids = [c.get("id") if isinstance(c, dict) else None for c in cells]
                    if len(cells) != ac:
                        problems.add(wc, f"{len(cells)} cells on disk, sidecar says accepted_cells {ac!r}")
                    for dup in duplicates(ids):
                        problems.add(wc, f"duplicate cell id {dup!r}")
                    for c in cells:
                        if not isinstance(c, dict):
                            problems.add(wc, "cell is not an object")
                            continue
                        cid = c.get("id")
                        if c.get("status") not in MIXFEAS_STATUSES:
                            problems.add(wc, f"{cid}: status {c.get('status')!r} is not a scientific outcome")
                        if c.get("model_section") != c.get("corner"):
                            problems.add(wc, f"{cid}: model_section {c.get('model_section')!r} != corner {c.get('corner')!r}")
                        if c.get("matrix") == "leakage" and c.get("seed") != seed:
                            problems.add(wc, f"{cid}: leakage cell seed {c.get('seed')!r} != declared {seed!r}")
                        if c.get("status") in ("ok", "rejected_stress"):
                            rejecting = (c.get("stress") or {}).get("rejecting")
                            if rejecting is None:
                                problems.add(wc, f"{cid}: no stress classification")
                            elif (c["status"] == "ok") == bool(rejecting):
                                problems.add(wc, f"{cid}: status {c['status']} contradicts its stress violations")
    logs = exp_dir / "corners" / stem
    if not logs.is_dir() or not any(logs.glob("*.log.gz")):
        problems.add(rel(root, logs), "no corners/<id>/*.log.gz raw logs for this record")
    else:
        for p in sorted(logs.iterdir()):
            if not p.name.endswith(".log.gz"):
                problems.add(rel(root, p), "unexpected file in a mixer-topology-feasibility corners directory")
            else:
                read_gzip_text(problems, root, p)
    snap = exp_dir / "netlist-snapshots" / stem
    if not snap.is_dir():
        problems.add(rel(root, snap), "netlist-snapshots/<id>/ directory missing")
    else:
        names = [p.name for p in snap.iterdir()]
        for need in MIXFEAS_SNAPSHOT_REQUIRED:
            if need not in names:
                problems.add(rel(root, snap), f"snapshot lacks {need}")
        for prefix in ("body_", "request_", "report_", "spec_"):
            if not any(n.startswith(prefix) for n in names):
                problems.add(rel(root, snap), f"snapshot has no {prefix}* file")
        if not any(n.startswith("cand_") for n in names):
            problems.add(rel(root, snap), "snapshot has no frozen cand_* fragment")


# ---------------------------------------------------------------------------
# bench cold-start READMEs and PDK naming (T1 item 9 preconditions, issue #85)
# ---------------------------------------------------------------------------

#: Heading titles that count as a bench's documented invocation section.
INVOCATION_HEADING_RE = re.compile(
    r"^#{2,3}\s+(?:Cold start|Running it|Reproduce|Stages and commands)\b[^\n]*$", re.M | re.I)
FENCE_RE = re.compile(r"^\s*(?:```|~~~)", re.M)

#: Records that name the PDK as ``unknown`` (the harness's ``Pdk.version`` read a
#: ``SOURCES`` file that IHP-Open-PDK does not ship). Records are append-only,
#: so these are grandfathered BY ID and the set is closed: any record not listed
#: here that names the PDK ``unknown`` fails. Note the last entry post-dates the
#: model-artifact pin (sim/pdk-artifact.json); that is the remaining T1 item 9
#: gap and is why item 9 is not attested (signoff/README.md).
LEGACY_UNKNOWN_PDK = frozenset({
    "sim/lna-sparam-nf/records/20260912-034726-9204518.md",
    "sim/mixer-conversion-iip3/records/20260912-034727-9204518.md",
    "sim/lna-sparam-nf/records/20261009-134024-57e1898.md",
    "sim/lna-sparam-nf/records/20261010-012923-6cad7fc.md",
})
PDK_UNKNOWN_RE = re.compile(r"^- PDK:.*\(unknown\b", re.M)


def readme_invocation_problem(readme: Path) -> str | None:
    """Why ``readme`` is not a cold-start README, or None if it is one."""
    if not readme.is_file() or readme.stat().st_size == 0:
        return "missing or empty README.md"
    text = readme.read_text(errors="replace")
    heads = list(INVOCATION_HEADING_RE.finditer(text))
    if not heads:
        return ("no invocation section (a '## Cold start', '## Running it', '## Reproduce' "
                "or '## Stages and commands' heading)")
    for m in heads:
        nxt = re.search(r"^#{1,3}\s", text[m.end():], re.M)
        body = text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():]
        if FENCE_RE.search(body):
            return None
    return "invocation section contains no fenced command block"


def check_bench_readmes(problems: Problems, root: Path) -> None:
    """Every sim/<dir> holding records/ has a README with a runnable invocation,
    and no un-grandfathered record names the PDK ``unknown``."""
    sim = root / "sim"
    for d in sorted(p for p in sim.iterdir() if p.is_dir()):
        records = d / "records"
        if not records.is_dir():
            continue
        why = readme_invocation_problem(d / "README.md")
        if why:
            problems.add(rel(root, d / "README.md"),
                         f"bench has records/ but no cold-start README: {why}")
        for md in sorted(records.glob("*.md")):
            r = rel(root, md)
            if PDK_UNKNOWN_RE.search(md.read_text(errors="replace")) and r not in LEGACY_UNKNOWN_PDK:
                problems.add(r, "record names the PDK as 'unknown' and is not a grandfathered legacy record; "
                             "cite the pinned artifact (sim/pdk-artifact.json) instead")


def check_format(root: Path) -> Problems:
    problems = Problems()
    sim = root / "sim"
    exps = sorted(p.parent.parent for p in sim.glob("*/testbench/tb.json"))
    if not exps:
        problems.add("sim/", "no sim/*/testbench/tb.json benches found")
    check_bench_readmes(problems, root)
    bench_names = {e.name for e in exps}
    for d in sorted(p for p in sim.iterdir() if p.is_dir()):
        if d.name in bench_names:
            continue
        if d.name in ADAPTERS:
            ADAPTERS[d.name](problems, root, d)
        else:
            present = [n for n in EVIDENCE_DIRS if (d / n).exists()]
            if present:
                problems.add(rel(root, d), f"unrecognised evidence layout (has {', '.join(n + '/' for n in present)} "
                             "but no testbench/tb.json bench and no registered adapter in ADAPTERS); "
                             "refusing to skip it")
    for exp in exps:
        kaband = is_kaband(exp, problems, root)
        mixfeas = is_mixfeas(exp)
        records = exp / "records"
        mds = sorted(records.glob("*.md")) if records.is_dir() else []
        ids = {p.stem for p in mds}
        for md in mds:
            if mixfeas:
                check_mixfeas_record(problems, root, exp, md)
            elif kaband:
                check_kaband_record(problems, root, exp, md)
            else:
                check_native_record(problems, root, exp, md)
        # evidence that no record claims
        if records.is_dir() and not kaband and not mixfeas:
            for p in sorted(records.iterdir()):
                if p.suffix != ".md":
                    problems.add(rel(root, p), "unexpected file in a harness-native records/ directory")
        if records.is_dir() and (kaband or mixfeas):
            for p in sorted(records.iterdir()):
                m = RECORD_ID_PREFIX_RE.match(p.name)
                if p.suffix != ".md" and not (m and m.group(1) in ids):
                    problems.add(rel(root, p), "evidence file belongs to no record in this experiment")
        for sub in ("corners", "netlist-snapshots"):
            d = exp / sub
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                m = RECORD_ID_PREFIX_RE.match(p.name)
                if not (m and m.group(1) in ids):
                    problems.add(rel(root, p), f"{sub} entry belongs to no record in this experiment (orphan evidence)")
    return problems


# ---------------------------------------------------------------------------
# append-only history
# ---------------------------------------------------------------------------


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def resolve_base(root: Path, base: str | None) -> tuple[str | None, str]:
    """Return ``(merge_base_sha_or_None, note)``.

    Order: explicit ``--base``; ``origin/$GITHUB_BASE_REF`` (pull_request);
    ``origin/main``; ``main``. An all-zero sha (new branch push) or an
    unresolvable ref means "no base". The merge base with HEAD is always used,
    so a multi-commit branch is compared as a whole.
    """
    candidates: list[str] = []
    if base and not set(base) <= {"0"}:
        candidates.append(base)
    elif base:
        candidates.append("")  # explicit all-zero: fall through to the defaults below
    if os.environ.get("GITHUB_BASE_REF"):
        candidates.append(f"origin/{os.environ['GITHUB_BASE_REF']}")
    candidates += ["origin/main", "main"]
    for ref in candidates:
        if not ref:
            continue
        if git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode != 0:
            continue
        mb = git(root, "merge-base", ref, "HEAD")
        if mb.returncode == 0 and mb.stdout.strip():
            return mb.stdout.strip(), f"comparing against merge base of {ref} and HEAD ({mb.stdout.strip()[:12]})"
    return None, "no comparison base could be resolved"


def check_append_only(root: Path, base: str | None, require_base: bool) -> tuple[Problems, str]:
    problems = Problems()
    if git(root, "rev-parse", "--git-dir").returncode != 0:
        if require_base:
            problems.add("git", "not a git work tree; append-only history cannot be checked")
        return problems, "append-only check SKIPPED: not a git work tree"
    mb, note = resolve_base(root, base)
    if mb is None:
        shallow = git(root, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
        hint = " (shallow clone: use actions/checkout fetch-depth: 0)" if shallow else ""
        msg = (f"append-only check SKIPPED: {note}{hint}. Current-tree format validation still ran. "
               "First push of a new branch with no origin/main, or an all-zero 'before' sha, lands here.")
        if require_base:
            problems.add("append-only", f"{note}{hint} but --require-base was given")
        return problems, msg

    diff = git(root, "diff", "--name-status", "--no-renames", mb, "--", "sim")
    if diff.returncode != 0:
        problems.add("append-only", f"git diff against {mb[:12]} failed: {diff.stderr.strip()}")
        return problems, note
    base_files = git(root, "ls-tree", "-r", "--name-only", mb, "--", "sim").stdout.splitlines()
    base_ids = {
        m.group(1)
        for f in base_files
        if PROTECTED_RE.match(f)
        for m in [RECORD_ID_PREFIX_RE.match(f.split("/")[3])]
        if m
    }
    for line in diff.stdout.splitlines():
        status, _, path = line.partition("\t")
        if not PROTECTED_RE.match(path):
            continue
        if status == "A":
            parts = path.split("/")
            m = RECORD_ID_PREFIX_RE.match(parts[3]) if len(parts) > 3 else None
            if m and m.group(1) in base_ids:
                problems.add(path, f"adds a file to record {m.group(1)}, which is already committed "
                             "(evidence is append-only; add a new record instead)")
            continue
        verb = {"M": "modified", "D": "deleted or renamed away", "T": "type-changed"}.get(status[0], f"changed ({status})")
        problems.add(path, f"committed evidence was {verb} since the merge base {mb[:12]} "
                     "(append-only: supersede with a later record, never edit or remove)")
    return problems, note


# ---------------------------------------------------------------------------
# Spec-row coverage manifest (issue #50)

COVERAGE_PATH = "spec/row-coverage.json"
SPEC_PATH = "spec/target-spec.md"
VERDICTS = {"no_bench", "placeholder_circuit", "device_level_only", "method_absent",
            "measured_pass", "measured_fail"}
NEEDS_RECORD = VERDICTS - {"no_bench"}
OVERCLAIM_RE = re.compile(r"placeholder|device-level|device level|not a matched|not spec", re.I)
SPEC_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|")
# Deliberately simple: "row 5", "rows 2-5", "rows 2, 3 and 6". Case-insensitive.
ROW_MENTION_RE = re.compile(r"\brows?\s+(\d+)(?:\s*[-\u2013]\s*(\d+))?((?:\s*(?:,|and)\s*\d+)*)", re.I)


def rows_mentioned(text: str) -> set[int]:
    """Spec row numbers named in a record (a mention is not a claim)."""
    found: set[int] = set()
    for m in ROW_MENTION_RE.finditer(text):
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        if lo <= hi <= lo + 30:
            found.update(range(lo, hi + 1))
        found.update(int(x) for x in re.findall(r"\d+", m.group(3) or ""))
    return found


def spec_table_rows(text: str) -> dict[int, tuple[str, str]]:
    """{row: (status, binding-corner cell)} parsed from the target-spec table."""
    rows: dict[int, tuple[str, str]] = {}
    for line in text.splitlines():
        m = SPEC_ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(cells) < 7:
            continue
        st = re.search(r"\*\*(RATIFIED|OPEN)", cells[2])
        if st:
            rows[int(m.group(1))] = ("ratified-target" if st.group(1) == "RATIFIED" else "open", cells[6])
    return rows


def check_row_coverage(root: Path) -> Problems:
    problems = Problems()
    spec = root / SPEC_PATH
    man = root / COVERAGE_PATH
    if not spec.is_file():
        problems.add(SPEC_PATH, "missing; cannot check spec-row coverage")
        return problems
    if not man.is_file():
        problems.add(COVERAGE_PATH, "missing row-coverage manifest")
        return problems
    try:
        doc = json.loads(man.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.add(COVERAGE_PATH, f"unreadable JSON: {exc}")
        return problems
    entries = doc.get("rows") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        problems.add(COVERAGE_PATH, "top level must be an object with a 'rows' list")
        return problems
    table = spec_table_rows(spec.read_text(encoding="utf-8"))
    if not table:
        problems.add(SPEC_PATH, "no spec table rows parsed")
        return problems

    by_row: dict[int, dict] = {}
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or not isinstance(e.get("row"), int):
            problems.add(COVERAGE_PATH, f"rows[{i}] is not an object with an integer 'row'")
            continue
        if e["row"] in by_row:
            problems.add(COVERAGE_PATH, f"row {e['row']} listed more than once")
        by_row[e["row"]] = e
    for n in sorted(set(table) - set(by_row)):
        what = "RATIFIED row silently absent" if table[n][0] == "ratified-target" else "row missing"
        problems.add(COVERAGE_PATH, f"row {n}: {what} from the manifest")
    for n in sorted(set(by_row) - set(table)):
        problems.add(COVERAGE_PATH, f"row {n}: not in the {SPEC_PATH} table")

    for n in sorted(set(by_row) & set(table)):
        e = by_row[n]
        where = f"{COVERAGE_PATH} row {n}"
        status, corner = table[n]
        if e.get("status") != status:
            problems.add(where, f"status {e.get('status')!r} disagrees with the spec table ({status!r})")
        if e.get("bound_corner") != corner:
            problems.add(where, f"bound_corner {e.get('bound_corner')!r} disagrees with the spec table ({corner!r})")
        verdict = e.get("verdict")
        if verdict not in VERDICTS:
            problems.add(where, f"verdict {verdict!r} not one of {sorted(VERDICTS)}")
            continue
        bench, rec = e.get("bench"), e.get("latest_record")
        if bench is not None:
            if not isinstance(bench, str) or not bench.startswith("sim/") or not (root / bench).is_dir():
                problems.add(where, f"bench {bench!r} is not an existing sim/<experiment> directory")
        if rec is not None:
            rp = root / rec if isinstance(rec, str) else None
            if rp is None or not rp.is_file():
                problems.add(where, f"latest_record {rec!r} does not exist")
        if verdict == "no_bench":
            if bench is not None or rec is not None:
                problems.add(where, "verdict no_bench but a bench or record is cited")
            if not (isinstance(e.get("blocked_by"), str) and e["blocked_by"].strip()):
                problems.add(where, "no bench: 'blocked_by' (issue or DR id) is required")
            continue
        if bench is None or rec is None:
            problems.add(where, f"verdict {verdict} needs both a bench and a latest_record")
            continue
        if isinstance(rec, str) and not rec.startswith(str(bench) + "/records/"):
            problems.add(where, f"latest_record {rec!r} is not under {bench}/records/")
        if isinstance(rec, str) and isinstance(bench, str) and (root / bench / "records").is_dir():
            latest_name = Path(rec).name
            for newer in sorted((root / bench / "records").glob("*.md")):
                if newer.name > latest_name and n in rows_mentioned(
                        newer.read_text(encoding="utf-8", errors="replace")):
                    problems.add(where, f"stale latest_record {rec!r}: newer record {bench}/records/{newer.name} "
                                 f"mentions row {n} (point latest_record at it; a mention is not a claim)")
        if verdict.startswith("measured_") and isinstance(rec, str) and (root / rec).is_file():
            text = (root / rec).read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                if line.startswith("**Claim**") and OVERCLAIM_RE.search(line):
                    problems.add(where, f"overclaimed: {verdict} cites {rec}, whose Claim line says "
                                 "placeholder/device-level")
                    break
    return problems


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".", help="repository root (default: cwd)")
    ap.add_argument("--base", help="base ref/sha for the append-only comparison")
    ap.add_argument("--require-base", action="store_true",
                    help="fail instead of skipping the append-only check when no base resolves")
    ap.add_argument("--skip-history", action="store_true", help="format validation only")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if not (root / "sim").is_dir():
        print(f"error: {root} has no sim/ directory", file=sys.stderr)
        return 2

    problems = check_format(root)
    print(f"format: {'FAILED' if problems else 'ok'} ({len(problems.items)} problem(s))")
    cov = check_row_coverage(root)
    print(f"row-coverage: {'FAILED' if cov else 'ok'} ({len(cov.items)} problem(s))")
    problems.items += cov.items
    if not args.skip_history:
        hist, note = check_append_only(root, args.base, args.require_base)
        print(f"append-only: {note}")
        print(f"append-only: {'FAILED' if hist else 'ok'} ({len(hist.items)} problem(s))")
        problems.items += hist.items
    for item in problems.items:
        print(f"ERROR {item}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
