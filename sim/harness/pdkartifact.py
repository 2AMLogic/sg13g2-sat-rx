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


class ArtifactNotVerified(RuntimeError):
    """Verified artifact identity was requested but the install does not match the pin."""


def verified_identity(pdk: Pdk, sim_dir: Path) -> dict:
    """Run :func:`verify` and, ONLY on success, return the identity to record.

    The returned dict is what native evidence records carry: the immutable
    upstream commit, the SHA-256 of the committed manifest bytes, and the
    verification result. It is never built from the manifest alone -- a
    missing, tampered or unlisted model raises :class:`ArtifactNotVerified`,
    so no record can claim a verified identity merely because a manifest
    exists. The install's own marker is NOT part of this identity (it lives
    under ``pdk.version`` / the install provenance and may be ``unknown``).
    """
    rep = verify(pdk, sim_dir)
    if not rep.ok:
        raise ArtifactNotVerified(rep.format() + REFUSAL)
    m = load_manifest(sim_dir)  # already parsed once by verify(); re-read for the bytes' digest
    up = m["upstream"]
    return {
        "status": "verified",
        "upstream_repo": up.get("repo", ""),
        "upstream_tag": up.get("tag", ""),
        "upstream_commit": up["commit"],
        "manifest": f"sim/{MANIFEST_FILENAME}",
        "manifest_sha256": sha256_file(sim_dir / MANIFEST_FILENAME),
        "files_verified": len(m["files"]),
        "method": "sha256 of every model file in the include closure of model_lib, "
                  "re-derived from the install (harness/pdkartifact.py verify)",
    }


def validate_identity(identity: object) -> dict:
    """Reject anything that is not a well-formed verified identity (no overclaiming)."""
    if not isinstance(identity, dict) or identity.get("status") != "verified":
        raise ArtifactNotVerified("record requires a verified PDK artifact identity (status 'verified')")
    if not _COMMIT_RE.match(str(identity.get("upstream_commit", ""))):
        raise ArtifactNotVerified("verified identity lacks a full 40-hex upstream_commit")
    if not _SHA256_RE.match(str(identity.get("manifest_sha256", ""))):
        raise ArtifactNotVerified("verified identity lacks a sha256 manifest_sha256")
    return identity


def verify_job_models(env: object, sim_dir: Path) -> Report:
    """Check the MODEL CLOSURE AN OFF-HOST ``klt sim`` JOB USED against the pin.

    ``env`` is the ``environment`` block of one ``klt sim`` JSON report. This
    is deliberately independent of whatever install the ingesting host has:
    a local install that matches the pin says nothing about the models the
    runner simulated with. What the report can prove, and what is required:

    - ``environment.remote.runner_compatibility == "match"``: the runner ran
      the client's own klt build. Any other value means the runner "may have
      ignored" request options, including ``options.stage_model_inputs``,
      and then simulated with its image-baked models, which no hash in the
      report covers.
    - ``environment.staged_model_inputs``: one entry per model file shipped
      to the worker. Each entry's digest must be a pinned file hash -- the
      entry's ``sha256`` for a file staged byte-for-byte, its
      ``source_sha256`` for a file whose include paths staging rewrote (the
      ``sha256`` of rewritten bytes cannot equal the pin). A rewritten entry
      without ``source_sha256`` is NOT evidence.
    - Every pinned file is accounted for, and nothing unpinned was staged.

    ``environment.models_lib_sha256`` is NOT runner evidence: klt computes it
    on the submitting client from the client's own resolution of
    ``models.lib``, and it covers the top-level library only. It is checked
    for consistency (a mismatch fails) but never establishes a match.
    """
    rep = Report()
    try:
        m = load_manifest(sim_dir)
    except ArtifactManifestError as exc:
        rep.fail(str(exc))
        return rep
    pinned: dict[str, str] = m["files"]
    by_digest = {digest: rel for rel, digest in pinned.items()}
    if not isinstance(env, dict):
        rep.fail("report has no environment block; the models that produced it are unknown")
        return rep

    remote = env.get("remote")
    if not isinstance(remote, dict):
        rep.fail("report has no environment.remote: not an off-host job report (local runs are "
                 "recorded by `harness.cli run`, which hashes the install it simulates with)")
    elif remote.get("runner_compatibility") != "match":
        rep.fail(f"runner_compatibility is {remote.get('runner_compatibility')!r} (runner klt "
                 f"{remote.get('runner_klt_version')} vs client {remote.get('client_klt_version')}): "
                 "the runner may have ignored options.stage_model_inputs and simulated with its "
                 "image-baked models, which no hash in the report covers")

    want_lib = pinned.get(m.get("model_lib", ""))
    lib_sha = env.get("models_lib_sha256")
    if lib_sha is not None and want_lib and lib_sha != want_lib:
        rep.fail(f"submitting client resolved model_lib with sha256 {lib_sha}, pinned {want_lib}")

    assets = env.get("staged_model_inputs")
    if not isinstance(assets, list) or not assets:
        rep.fail("report has no environment.staged_model_inputs: no hash of the model bytes the "
                 "runner read (environment.models_lib_sha256 is the submitting client's top-level "
                 "library only, not runner evidence)")
        return rep
    seen: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            rep.fail(f"malformed staged_model_inputs entry: {asset!r}")
            continue
        name = asset.get("name")
        if asset.get("rewritten"):
            digest = asset.get("source_sha256")
            if not isinstance(digest, str) or not _SHA256_RE.match(digest):
                rep.fail(f"staged model {name!r} was rewritten by staging and the report carries only "
                         "the rewritten bytes' sha256 (no source_sha256), so it cannot be compared "
                         "with the pin")
                continue
        else:
            digest = asset.get("sha256")
        rel = by_digest.get(digest) if isinstance(digest, str) else None
        if rel is None:
            rep.fail(f"staged model {name!r} (sha256 {digest}) is not a pinned file of {MANIFEST_FILENAME}")
            continue
        seen.add(rel)
    for rel in sorted(set(pinned) - seen):
        rep.fail(f"pinned model file {rel} is not among the job's staged model inputs")
    return rep


def offhost_identity(jobs: list[tuple[str, object]], sim_dir: Path) -> dict:
    """Verified artifact identity for results produced OFF-HOST, or raise.

    ``jobs`` is ``[(label, report_environment), ...]``, one per ``klt sim``
    report. Every job must pass :func:`verify_job_models`; otherwise
    :class:`ArtifactNotVerified` lists every problem. The identity has the
    same required fields as :func:`verified_identity` but says what was
    actually verified (``verified_scope``): the model inputs the jobs
    received, not the ingesting host's install and not the runner's own
    filesystem.
    """
    problems: list[str] = []
    if not jobs:
        problems.append("no klt job reports to verify")
    for label, env in jobs:
        rep = verify_job_models(env, sim_dir)
        problems += [f"{label}: {p}" for p in rep.problems]
    if problems:
        raise ArtifactNotVerified("\n".join(f"FAIL: {p}" for p in problems) + OFFHOST_REFUSAL)
    m = load_manifest(sim_dir)
    up = m["upstream"]
    return {
        "status": "verified",
        "verified_scope": "offhost-job-model-inputs",
        "upstream_repo": up.get("repo", ""),
        "upstream_tag": up.get("tag", ""),
        "upstream_commit": up["commit"],
        "manifest": f"sim/{MANIFEST_FILENAME}",
        "manifest_sha256": sha256_file(sim_dir / MANIFEST_FILENAME),
        "files_verified": len(m["files"]),
        "jobs": [
            {"report": label, "job_id": ((env.get("remote") or {}).get("job_id")),
             "runner_klt_version": ((env.get("remote") or {}).get("runner_klt_version"))}
            for label, env in jobs
        ],
        "method": "every pinned model file matched by sha256 among each off-host job's klt "
                  "environment.staged_model_inputs (source_sha256 for rewritten files), runner klt "
                  "build == client build (harness/pdkartifact.py verify_job_models); the runner's "
                  "own install was not hashed",
    }


OFFHOST_REFUSAL = (
    "\nNothing was recorded: the klt reports do not prove that the models which produced these "
    "results are the pinned artifact (sim/pdk-artifact.json). A matching install on the ingesting "
    "host is not evidence about an off-host runner."
)


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
