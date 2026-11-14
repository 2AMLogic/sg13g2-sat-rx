"""evidence_checks.common: split out of check_evidence_formats.py (issue #163); no rule changes."""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import subprocess
from collections.abc import Callable
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


def check_supersedes(problems: Problems, where: str, exp_dir: Path, value: str) -> None:
    ref = value.split()[0] if value.split() else ""
    if not RECORD_ID_RE.match(ref):
        problems.add(where, f"Supersedes must start with a record id, found {value[:40]!r}")
    elif not (exp_dir / "records" / f"{ref}.md").is_file():
        problems.add(where, f"Supersedes names record {ref!r} which does not exist in this experiment")


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
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


def need_record_commit(problems: Problems, where: str, env: dict, rid: str) -> object:
    git = env.get("git")
    commit = git.get("commit") if isinstance(git, dict) else None
    if not isinstance(commit, str) or not commit.startswith(rid.split("-")[2]):
        problems.add(where, f"environment.git.commit {commit!r} does not match the sha in the record id")
    return commit


# ---------------------------------------------------------------------------
# probe-log bench layout
# ---------------------------------------------------------------------------


# The frozen file set of a probe-log run package (peer of the contract below).
MIXER_PROBE_FILES = ("deck.spice", "stdout.txt", "stderr.txt", "inventory.json")


def check_probe_log_package(problems, root, exp_dir, rid, rec, md, where_js, where_md, claimed_logs):
    """Shared probe-log package contract; returns the package path, or None if the directory is missing."""
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
        return None
    # stderr may legitimately be empty
    present = {p.name for p in logs.iterdir() if p.is_file()}
    for name in MIXER_PROBE_FILES:
        if name not in present:
            problems.add(rel(root, logs), f"probe-log package is missing {name}")
        elif name != "stderr.txt" and (logs / name).stat().st_size == 0:
            problems.add(rel(root, logs / name), "probe-log file is empty")
    for name in sorted(present - set(MIXER_PROBE_FILES)):
        problems.add(rel(root, logs / name), "unexpected file in a probe-log package")
    for p in logs.iterdir():
        if p.is_dir():
            problems.add(rel(root, p), "unexpected directory in a probe-log package")
    return logs


def reject_foreign_dirs(problems: Problems, root: Path, exp_dir: Path, bench: str, subs: tuple[str, ...]) -> None:
    """Flag the evidence directories that are not part of ``bench``'s layout.

    Each bench passes its own forbidden tuple; a bench that inherited another
    bench's set would silently stop rejecting its own foreign directories.
    """
    for sub in subs:
        if (exp_dir / sub).exists():
            problems.add(rel(root, exp_dir / sub), f"{sub}/ is not part of the {bench} evidence layout")


def check_probe_log_bench(problems: Problems, root: Path, exp_dir: Path, bench: str,
                          check_record: Callable[..., None], foreign: tuple[str, ...]) -> None:
    """Layout of a probe-log bench: record pairs, ``probe-logs/`` run packages, foreign dirs.

    ``check_record(problems, root, exp_dir, stem, files, claimed)`` carries the
    per-record rules, which stay per-adapter (issue #109 step 3): their
    semantics intentionally differ. Only the layout around them is shared.
    """
    records = exp_dir / "records"
    claimed: set[str] = set()
    if records.is_dir():
        for stem, files in record_pairs(problems, root, records).items():
            check_record(problems, root, exp_dir, stem, files, claimed)
    logs_root = exp_dir / "probe-logs"
    if logs_root.is_dir():
        for p in sorted(logs_root.iterdir()):
            if not (p.is_dir() and RECORD_ID_RE.match(p.name)):
                problems.add(rel(root, p), "probe-logs entry is not a <YYYYMMDD>-<HHMMSS>-<git-sha>/ run directory")
            elif p.name not in claimed:
                problems.add(rel(root, p), "probe-log package belongs to no record (orphan or incomplete run)")
    reject_foreign_dirs(problems, root, exp_dir, bench, foreign)


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
