"""evidence_checks.artifact_manifests: stored-evidence manifests (issue #226).

New harness evidence no longer commits its raw bytes (per-point logs, frozen
snapshots). They go to the fleet artifact store through ``klt artifact put``
(sim/harness/evidence_store.py) and git keeps a manifest per run,
``manifests/artifacts/<bench>-<run-id>.manifest.json``, plus the run's Markdown
record carrying a ``## Stored evidence`` table. Evidence bytes are private and
manifests are public, so a manifest is safe to commit.

This module is the git-side half of that contract. It never contacts the broker
(schema-valid is not hash-verified; ``klt artifact verify <manifest>`` does
that, out of band). It checks, for the CURRENT tree:

* every file in ``manifests/artifacts/`` is ``<bench>-<run-id>.manifest.json``
  (or the README) and has the klt manifest schema, every ``uri`` is
  ``artifact:<key>`` (any other scheme, ``s3://`` included, is refused) with a
  key ending in the entry's sha256, every ``name`` a canonical ``sim/...`` path,
  no duplicate names;
* no text under ``manifests/`` names a bucket, account or ``s3://`` / ``arn:aws:``
  location;
* no stored object's bytes are also committed under ``sim/`` (a file whose
  sha256 matches an entry is the blob fallback this repo forbids);
* a harness-native record in the stored form (it has a ``## Stored evidence``
  section) names a manifest that exists, whose entries are exactly the table
  rows, cover every declared corner log, and include the frozen netlist (and,
  when the record declares one, the frozen testbench manifest with the
  declared digest).

Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
from pathlib import Path

from .common import Problems, compare_identities, header_field, rel, section_body

MANIFEST_DIR = "manifests/artifacts"
MANIFEST_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\.manifest\.json$")
DIR_FILES_ALLOWED = {"README.md"}
SCHEMA_VERSION = 1
REQUIRED = ("sha256", "size", "kind", "producer", "uri")
OPTIONAL = ("name", "media_type")
PRODUCER_FIELDS = ("tool", "version", "loom.repo", "commit")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
URI_RE = re.compile(r"^artifact:([^/\s]\S*)$")
#: A storage location in text (a bucket URI or an AWS ARN). Matches the
#: acceptance grep ``git grep -nE 's3://|arn:aws:' -- manifests/``.
STORAGE_LOCATION_RE = re.compile(r"s3://|arn:aws:")
STAGE_DIRNAME = ".work"
TABLE_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|\s*`([0-9a-f]{64})`")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _canonical_name(name) -> bool:
    return (isinstance(name, str) and name.startswith("sim/")
            and "\\" not in name and "\0" not in name
            and posixpath.normpath(name) == name
            and not {"", ".", ".."} & set(name.split("/")))


def entry_problems(entry) -> list[str]:
    if not isinstance(entry, dict):
        return ["entry is not an object"]
    problems = []
    missing = [f for f in REQUIRED if f not in entry]
    extra = sorted(set(entry) - set(REQUIRED) - set(OPTIONAL))
    if missing:
        problems.append(f"missing {', '.join(missing)}")
    if extra:
        problems.append(f"unknown field(s) {', '.join(extra)}")
    sha = entry.get("sha256")
    if not isinstance(sha, str) or not SHA256_RE.match(sha):
        problems.append("sha256 must be 64 lowercase hex digits")
    size = entry.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        problems.append("size must be a positive integer")
    if entry.get("kind") != "evidence":
        problems.append("kind must be 'evidence'")
    producer = entry.get("producer")
    if not isinstance(producer, dict) or set(producer) != set(PRODUCER_FIELDS):
        problems.append(f"producer must carry exactly {', '.join(PRODUCER_FIELDS)}")
    uri = entry.get("uri")
    m = URI_RE.match(uri) if isinstance(uri, str) else None
    if m is None:
        problems.append("uri must be artifact:<key> (no other scheme)")
    elif m.group(1).rsplit("/", 1)[-1] != sha:
        problems.append("uri key does not end in the entry's sha256")
    if "name" not in entry:
        problems.append("name is required (the logical sim/ path of the bytes)")
    elif not _canonical_name(entry["name"]):
        problems.append("name must be a canonical relative sim/... path")
    if "media_type" in entry and not isinstance(entry["media_type"], str):
        problems.append("media_type must be a string")
    return problems


def manifest_problems(manifest) -> list[str]:
    if (not isinstance(manifest, dict) or set(manifest) != {"schema_version", "entries"}
            or manifest.get("schema_version") != SCHEMA_VERSION
            or not isinstance(manifest.get("entries"), list)):
        return [f"not {{schema_version: {SCHEMA_VERSION}, entries: [...]}}"]
    if not manifest["entries"]:
        return ["has no entries"]
    problems = []
    seen: set[str] = set()
    for i, entry in enumerate(manifest["entries"]):
        problems += [f"entry {i}: {p}" for p in entry_problems(entry)]
        name = entry.get("name") if isinstance(entry, dict) else None
        if isinstance(name, str):
            if name in seen:
                problems.append(f"entry {i}: duplicate name {name!r}")
            seen.add(name)
    return problems


def load_manifest(problems: Problems, root: Path, path: Path) -> dict | None:
    """Parse and schema-check one manifest; ``None`` (with problems added) if bad."""
    where = rel(root, path)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.add(where, f"not valid JSON: {exc}")
        return None
    bad = manifest_problems(manifest)
    for p in bad:
        problems.add(where, p)
    return None if bad else manifest


def _sim_files_by_size(root: Path, sizes: set[int]) -> list[Path]:
    out = []
    sim = root / "sim"
    for dirpath, dirnames, filenames in os.walk(sim):
        dirnames[:] = [d for d in dirnames if d != STAGE_DIRNAME]
        for name in filenames:
            p = Path(dirpath) / name
            try:
                if p.stat().st_size in sizes:
                    out.append(p)
            except OSError:
                continue
    return out


def check_artifact_manifests(problems: Problems, root: Path) -> None:
    """Directory-wide checks over ``manifests/``. Silent when it has none."""
    mdir = root / "manifests"
    if not mdir.is_dir():
        return
    for dirpath, _dirs, filenames in os.walk(mdir):
        for name in sorted(filenames):
            p = Path(dirpath) / name
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if STORAGE_LOCATION_RE.search(line):
                    problems.add(f"{rel(root, p)}:{i}", "names a storage location (s3:// or arn:aws:); "
                                 "manifests carry artifact:<key> uris only")
    adir = root / MANIFEST_DIR
    if not adir.is_dir():
        return
    entries: list[tuple[str, dict]] = []
    for p in sorted(adir.iterdir()):
        if p.name in DIR_FILES_ALLOWED and p.is_file():
            continue
        if not MANIFEST_NAME_RE.match(p.name) or not p.is_file() or p.is_symlink():
            problems.add(rel(root, p), "only <bench>-<run-id>.manifest.json files (and README.md) "
                         "belong in manifests/artifacts/")
            continue
        manifest = load_manifest(problems, root, p)
        if manifest:
            entries += [(rel(root, p), e) for e in manifest["entries"]]
    by_size: dict[int, list[tuple[str, dict]]] = {}
    for where, e in entries:
        by_size.setdefault(e["size"], []).append((where, e))
        if (root / e["name"]).exists():
            problems.add(where, f"{e['name']} is committed beside its manifest; stored evidence "
                         "bytes must not also be committed (no blob fallback)")
    for p in _sim_files_by_size(root, set(by_size)):
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        for where, e in by_size[p.stat().st_size]:
            if e["sha256"] == h:
                problems.add(rel(root, p), f"its bytes are a stored object of {where} "
                             f"({e['name']}); stored evidence bytes must not also be committed")


def stored_table(text: str) -> dict[str, tuple[int, str]]:
    """``{name: (size, sha256)}`` rows of a record's ``## Stored evidence`` table."""
    rows = {}
    for line in section_body(text, "Stored evidence").splitlines():
        m = TABLE_ROW_RE.match(line)
        if m:
            rows[m.group(1)] = (int(m.group(2)), m.group(3))
    return rows


def check_stored_native_record(problems: Problems, root: Path, exp_dir: Path, rid: str,
                               where: str, text: str, expected: list[str] | None) -> None:
    """Validate the stored form of a harness-native record (no corners/ dir, no
    committed snapshot: both are manifest entries)."""
    bench = exp_dir.name
    prefix = f"sim/{bench}"
    mpath = root / MANIFEST_DIR / f"{bench}-{rid}.manifest.json"
    if not mpath.is_file():
        problems.add(where, f"stored-evidence record but {rel(root, mpath)} is missing")
        return
    manifest = load_manifest(problems, root, mpath)
    if manifest is None:
        return
    mwhere = rel(root, mpath)
    table = stored_table(text)
    names = {e["name"]: e for e in manifest["entries"]}
    for name, e in names.items():
        if not name.startswith(f"{prefix}/"):
            problems.add(mwhere, f"entry {name!r} is outside {prefix}/")
        row = table.get(name)
        if row is None:
            problems.add(where, f"Stored evidence table has no row for manifest entry {name!r}")
        elif row != (e["size"], e["sha256"]):
            problems.add(where, f"Stored evidence row for {name!r} disagrees with the manifest size/sha256")
    empty = {n for n, (size, sha) in table.items() if size == 0 and sha == EMPTY_SHA256}
    for name in sorted(set(table) - set(names) - empty):
        problems.add(where, f"Stored evidence row {name!r} has no manifest entry")
    snap = f"{prefix}/netlist-snapshots/{rid}.spice"
    if snap not in names:
        problems.add(mwhere, f"no entry for the frozen netlist snapshot {snap}")
    manifest_line = header_field(text, "Manifest")
    if manifest_line is not None:
        m = re.fullmatch(r"`netlist-snapshots/([^`]+)` sha256 `([0-9a-f]{64})`", manifest_line)
        if m and m.group(1) == f"{rid}.tb.json":
            e = names.get(f"{prefix}/netlist-snapshots/{rid}.tb.json")
            if e is None:
                problems.add(mwhere, "no entry for the frozen testbench manifest the record declares")
            elif e["sha256"] != m.group(2):
                problems.add(where, f"frozen testbench manifest sha256 {e['sha256']} in {mwhere} "
                             f"does not match declared {m.group(2)}")
        # a malformed Manifest line is reported by the shared native check
    if expected is not None:
        log_prefix = f"{prefix}/corners/{rid}/"
        listed = [n[len(log_prefix):-len(".log")] for n in list(names) + sorted(empty)
                  if n.startswith(log_prefix) and n.endswith(".log")]
        compare_identities(problems, where, "stored corner logs", expected, listed)
    for sub in ("corners", "netlist-snapshots"):
        d = exp_dir / sub
        for p in ([d / rid, d / f"{rid}.spice", d / f"{rid}.tb.json"]):
            if p.exists():
                problems.add(rel(root, p), "stored-evidence record also commits this path; "
                             "its bytes live in the artifact store only")


def check_manifest_append_only(problems: Problems, diff_lines: list[str], mb: str) -> None:
    """Flag a manifest modified/deleted since the merge base ``mb`` (additions are fine)."""
    for line in diff_lines:
        status, _, path = line.partition("\t")
        if not path.startswith(MANIFEST_DIR + "/") or not MANIFEST_NAME_RE.match(path.rsplit("/", 1)[-1]):
            continue
        if status != "A":
            verb = {"M": "modified", "D": "deleted or renamed away", "T": "type-changed"}.get(
                status[:1], f"changed ({status})")
            problems.add(path, f"committed stored-evidence manifest was {verb} since the merge base "
                         f"{mb[:12]} (append-only: supersede with a later record, never edit or remove)")
