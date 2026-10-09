"""Integrity check of the installed IHP model files against a committed manifest.

``sim/pdk-artifact.json`` pins the immutable upstream revision (a full git
commit id of IHP-GmbH/IHP-Open-PDK) and the SHA-256 of every model file in the
dependency closure of ``sim/pdk.json``'s ``model_lib``. :func:`verify` is run
BEFORE any simulator is launched (``harness.cli`` run/selftest, the Ka-band
bench, ``sim/characterize.sh`` and the hosted CI job all call it).

What establishes a match: ONLY the file hashes. The install's own version
marker (``.fetched-version``) is provenance. It is reported, and a marker that
disagrees with the manifest is a failure, but a marker that is absent,
unreadable or equal to the pin never makes an install "match" -- an install
whose hashes differ fails whatever it claims to be, and an install with no
marker is judged by its hashes alone and says so.

The closure is also checked structurally: every ``.include`` / ``.lib`` target
reachable from ``model_lib`` must be listed in the manifest, so a model file
that starts including a new, unhashed file fails instead of slipping through.

stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .pdk import Pdk

MANIFEST_FILENAME = "pdk-artifact.json"
MARKER_FILENAME = ".fetched-version"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
# `.include file`, `.inc "file"`, `.lib "file" section` (a bare `.lib NAME` that
# opens a section has no file operand beyond the section name and is skipped).
_INCLUDE_RE = re.compile(r'^\s*\.(?:include|inc)\s+(?:"([^"]+)"|(\S+))', re.IGNORECASE)
_LIB_FILE_RE = re.compile(r'^\s*\.lib\s+(?:"([^"]+)"|(\S+))\s+\S+', re.IGNORECASE)


class ArtifactManifestError(RuntimeError):
    """The manifest is missing or malformed (never a passing check)."""


@dataclass
class Report:
    ok: bool = True
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.ok = False
        self.problems.append(msg)

    def format(self) -> str:
        lines = [f"note: {n}" for n in self.notes]
        lines += [f"FAIL: {p}" for p in self.problems]
        return "\n".join(lines)


def load_manifest(sim_dir: Path) -> dict:
    path = sim_dir / MANIFEST_FILENAME
    if not path.is_file():
        raise ArtifactManifestError(f"{path} is missing: no committed IHP model pin to verify against")
    try:
        m = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ArtifactManifestError(f"{path} is not valid JSON: {exc}") from exc
    commit = m.get("upstream", {}).get("commit") if isinstance(m, dict) else None
    files = m.get("files") if isinstance(m, dict) else None
    if not isinstance(commit, str) or not _COMMIT_RE.match(commit):
        raise ArtifactManifestError(f"{path}: upstream.commit must be a full 40-hex git commit id")
    if not isinstance(files, dict) or not files:
        raise ArtifactManifestError(f"{path}: 'files' must map relative paths to sha256")
    for rel, digest in files.items():
        if not isinstance(digest, str) or not _SHA256_RE.match(digest):
            raise ArtifactManifestError(f"{path}: files[{rel!r}] is not a lowercase sha256")
    return m


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def include_closure(model_lib: Path, root: Path) -> set[str]:
    """Paths (relative to ``root``) of ``model_lib`` and everything it includes."""
    seen: set[Path] = set()
    todo = [model_lib]
    while todo:
        cur = todo.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if not cur.is_file():
            continue
        for line in cur.read_text(errors="replace").splitlines():
            m = _INCLUDE_RE.match(line) or _LIB_FILE_RE.match(line)
            if m:
                target = Path(m.group(1) or m.group(2))
                todo.append(target if target.is_absolute() else cur.parent / target)
    out = set()
    for p in seen:
        try:
            out.add(p.resolve().relative_to(root.resolve()).as_posix())
        except ValueError:
            out.add(str(p))  # outside the install tree: can never be in the manifest
    return out


def verify(pdk: Pdk, sim_dir: Path, ngspice_banner: str | None = None,
           require_ngspice: bool = False) -> Report:
    rep = Report()
    try:
        m = load_manifest(sim_dir)
    except ArtifactManifestError as exc:
        rep.fail(str(exc))
        return rep
    root = pdk.path
    files: dict[str, str] = m["files"]

    for rel, want in sorted(files.items()):
        p = root / rel
        if not p.is_file():
            rep.fail(f"model file missing: {rel}")
            continue
        got = sha256_file(p)
        if got != want:
            rep.fail(f"model file differs from the pin: {rel} (sha256 {got}, pinned {want})")

    closure = include_closure(pdk.model_lib, root)
    for rel in sorted(closure - set(files)):
        rep.fail(f"model file reachable from model_lib but not in the manifest: {rel}")
    for rel in sorted(set(files) - closure):
        rep.fail(f"manifest lists {rel} but model_lib does not reach it (stale pin)")

    marker_path = root / MARKER_FILENAME
    marker = marker_path.read_text().strip() if marker_path.is_file() else ""
    want_marker = m.get("install_marker", {}).get("value")
    if not marker:
        rep.notes.append(
            f"install has no {MARKER_FILENAME}; marker unknown. Match is judged by file hashes only."
        )
    elif want_marker and marker != want_marker:
        rep.fail(f"install marker {marker!r} != pinned {want_marker!r}")
    else:
        rep.notes.append(f"install marker {marker!r} recorded as provenance (not an integrity check)")

    want_ng = m.get("ngspice", {}).get("major")
    if ngspice_banner is not None and want_ng is not None:
        mt = re.search(r"ngspice-(\d+)", ngspice_banner)
        if not mt:
            msg = f"cannot parse ngspice version from {ngspice_banner!r}; tested major is {want_ng}"
            rep.fail(msg) if require_ngspice else rep.notes.append(msg)
        elif int(mt.group(1)) != int(want_ng):
            msg = f"ngspice major {mt.group(1)} != tested major {want_ng}"
            rep.fail(msg) if require_ngspice else rep.notes.append(msg)
    elif require_ngspice and ngspice_banner is None:
        rep.fail("ngspice required but not found")

    if rep.ok:
        rep.notes.append(
            f"IHP model closure ({len(files)} files) matches the pin at "
            f"{m['upstream']['commit'][:12]} ({m['upstream'].get('repo', '')})"
        )
    return rep


REFUSAL = (
    "\nNothing was simulated: the installed IHP models are not the pinned artifact "
    "(sim/pdk-artifact.json). See sim/README.md 'IHP model artifact' to reinstall the "
    "pinned revision, or to deliberately update the pin."
)


def require(pdk: Pdk, sim_dir: Path) -> None:
    """Raise SystemExit(3) with a loud message unless the install matches the pin."""
    rep = verify(pdk, sim_dir)
    if not rep.ok:
        raise SystemExit(rep.format() + REFUSAL)
