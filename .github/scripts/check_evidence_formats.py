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
       / ``Supply: ..`` / ``N point full-factorial grid ..``.

   Ka-band (sim/hbt-kaband-characterization/report_kaband.py)
       records/<id>.md, corners/<id>/<corner_id>.log.gz (gzip),
       netlist-snapshots/<id>/{body,request,klt-report}_<supply>v.* (one set
       per declared supply), records/<id>-{points.csv.gz,cells.csv,best.csv}.
       The record declares its matrix on the ``**PVT points**`` line.

   The declared matrix is expanded to corner identities and compared with the
   artifacts actually on disk (missing / unexpected / duplicated identities,
   unreadable compressed logs, missing snapshots and companion files, sidecar
   rows naming identities outside the matrix). Nothing is hardcoded to 27.

2. Append-only history (``--base`` / environment fallback, see
   :func:`resolve_base`): against the MERGE BASE of the base ref and HEAD
   (never only the last commit of a multi-commit branch) no committed file
   under ``sim/*/{records,corners,netlist-snapshots}/`` may be modified,
   deleted, renamed or type-changed, and no file may be ADDED to a record id
   that already existed at the base. New record ids are fine, as are
   independent testbench/harness changes.

   No base available (first push of a new branch with no ``origin/main``,
   all-zero ``before`` sha, ...): the append-only half is SKIPPED with a loud
   notice and the format half still runs; ``--require-base`` turns the skip
   into a failure (the pull_request job uses it).

Exit status: 0 clean, 1 problems found, 2 usage/environment error.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RECORD_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{7,40}$")
RECORD_ID_PREFIX_RE = re.compile(r"^(\d{8}-\d{6}-[0-9a-f]{7,40})")
PROTECTED_RE = re.compile(r"^sim/[^/]+/(records|corners|netlist-snapshots)/")
NATIVE_STATUSES = ("pass", "fail", "error")
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


def declared_native_matrix(text: str) -> tuple[list[str], list[float], list[float], int | None, int | None]:
    def line(label: str) -> str:
        m = re.search(rf"^\s*- {label}: (.+)$", text, re.MULTILINE)
        return m.group(1) if m else ""

    processes = [p.strip() for p in line("Process").split(",") if p.strip()]
    temps = numbers(line("Temperature"))
    supplies = numbers(line("Supply"))
    m = re.search(r"^\s*- (\d+) point full-factorial grid .*?, (\d+) completed", text, re.MULTILINE)
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
                     "('Process:', 'Temperature:', 'Supply:' and 'N point full-factorial grid' lines)")
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
        head = snap.read_text(encoding="utf-8", errors="replace")
        if not head.startswith(f"* Frozen netlist snapshot for record {rid}"):
            problems.add(rel(root, snap), f"snapshot header does not name record {rid}")
        if not re.search(r"^\* sha256\s*: [0-9a-f]{64}$", head, re.MULTILINE):
            problems.add(rel(root, snap), "snapshot is missing its '* sha256 :' provenance line")
    extra_snap_dir = exp_dir / "netlist-snapshots" / rid
    if extra_snap_dir.exists():
        problems.add(rel(root, extra_snap_dir), "directory-style snapshot in a harness-native bench")


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


def check_format(root: Path) -> Problems:
    problems = Problems()
    sim = root / "sim"
    exps = sorted(p.parent.parent for p in sim.glob("*/testbench/tb.json"))
    if not exps:
        problems.add("sim/", "no sim/*/testbench/tb.json benches found")
    for exp in exps:
        kaband = is_kaband(exp, problems, root)
        records = exp / "records"
        mds = sorted(records.glob("*.md")) if records.is_dir() else []
        ids = {p.stem for p in mds}
        for md in mds:
            if kaband:
                check_kaband_record(problems, root, exp, md)
            else:
                check_native_record(problems, root, exp, md)
        # evidence that no record claims
        if records.is_dir() and not kaband:
            for p in sorted(records.iterdir()):
                if p.suffix != ".md":
                    problems.add(rel(root, p), "unexpected file in a harness-native records/ directory")
        if records.is_dir() and kaband:
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
        for m in [RECORD_ID_PREFIX_RE.match(Path(f).name) or RECORD_ID_PREFIX_RE.match(Path(f).parent.name)]
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
