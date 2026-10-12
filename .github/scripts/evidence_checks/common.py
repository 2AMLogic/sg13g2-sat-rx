"""evidence_checks.common: split out of check_evidence_formats.py (issue #163); no rule changes."""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import subprocess
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


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
