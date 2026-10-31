"""Shared provenance helpers for the probe drivers (and the harness).

One home for the per-driver copies of the append-only provenance plumbing:
file hashing, git commit/dirty sampling, simulator and PDK identity,
exclusive-create writes, and probe record-id minting. The three mixer probe
drivers (and the lna-linearity CI assertion) previously carried byte-identical
(or trivially drifted) copies of every one of these; they import them from
here instead, so the copies cannot drift apart again.

COMPATIBILITY CONTRACT: these helpers feed append-only evidence records, so
their output shape is frozen -- a record's ``git`` is exactly
``{"commit", "dirty"}``, ``ngspice`` exactly ``{"path", "version", "major",
"sha256"}``, and a probe record id exactly
``<YYYYMMDD>-<HHMMSS>-<short-git-sha>``. Existing keys are never renamed or
reformatted; the id-minting collision checks (records glob, extra log
directories) keep the probe semantics of ``report.allocate_record_id``, which
only guards the harness's own ``records/`` Markdown path. ``pdk_info``'s
``fetched_version`` deliberately keeps the pre-#155 probe read (parent-dir
marker, then variant-dir marker, then ``"unknown"`` -- no ``SOURCES``
fallback) rather than ``Pdk.version``; see its docstring.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

__all__ = [
    "sha256",
    "sha256_file",
    "git_out",
    "git_info",
    "ngspice_info",
    "pdk_info",
    "pinned_major",
    "new_record_id",
    "write_excl",
    "MARK_RE",
    "KV_RE",
    "finite_float",
    "parse_marks",
    "pdk_integrity",
]


def sha256_file(path: Path) -> str:
    """Streaming sha256 of *path* (chunked; identical digest to whole-file hashing)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


#: Driver-facing alias: the probe drivers have always called this ``sha256``.
sha256 = sha256_file


def git_out(*args: str, cwd: Path) -> str:
    """Stripped stdout of one ``git`` invocation in *cwd* (empty on failure)."""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).stdout.strip()


def git_info(repo_root: Path) -> dict:
    """``{"commit": <full sha>, "dirty": <bool>}`` -- the probe-record git block."""
    return {"commit": git_out("rev-parse", "HEAD", cwd=repo_root),
            "dirty": bool(git_out("status", "--porcelain", cwd=repo_root))}


def ngspice_info(exe: str) -> dict:
    out = subprocess.run([exe, "-v"], capture_output=True, text=True, check=False).stdout
    line = next((ln.strip(" *") for ln in out.splitlines() if "ngspice-" in ln), "unknown")
    m = re.search(r"ngspice-(\d+)", line)
    return {"path": exe, "version": line.strip(), "major": int(m.group(1)) if m else None,
            "sha256": sha256_file(Path(exe).resolve())}


def pdk_info(sim_dir: Path) -> dict:
    """PDK identity block for probe records (frozen shape, frozen version read).

    ``fetched_version`` keeps the probe drivers' pre-#155 read -- the install
    marker looked up in the *parent* of the variant dir first, then the
    variant dir itself, else the literal ``"unknown"``. It deliberately does
    NOT delegate to ``Pdk.version``: that centralized reader only looks in
    the variant dir and additionally falls back to a ``SOURCES`` first line,
    so delegating would silently change ``fetched_version`` values recorded
    into append-only records for installs where the marker sits at the
    parent (volare/ciel layouts) or is absent while ``SOURCES`` exists.
    Byte-compatibility with the existing records wins; harness consumers
    that want the richer resolution use ``Pdk.version`` directly. Pinned by
    ``test_pdk_info_fetched_version_read_is_frozen``.
    """
    from harness.pdk import find_pdk  # noqa: WPS433 (kept function-local like the drivers')
    p = find_pdk(sim_dir)
    fv = p.path.parent / ".fetched-version"
    fv2 = p.path / ".fetched-version"
    ver = (fv.read_text().strip() if fv.is_file() else
           fv2.read_text().strip() if fv2.is_file() else "unknown")
    models = p.model_lib.parent
    return {"path": str(p.path), "fetched_version": ver, "model_lib": str(p.model_lib),
            "section": "hbt_typ",
            "sha256": {"cornerHBT.lib": sha256_file(p.model_lib),
                       "sg13g2_hbt_mod.lib": sha256_file(models / "sg13g2_hbt_mod.lib")},
            "device": "npn13G2 (subckt) -> npn13G2_NX_vbic, VBIC level=9, Nx=4 in the placeholder"}


def pinned_major(artifact_path: Path) -> int:
    """The pinned ngspice major declared by ``sim/pdk-artifact.json``."""
    return int(json.loads(artifact_path.read_text())["ngspice"]["major"])


def new_record_id(
    short: str,
    records_dir: Path,
    *extra_dirs: Path,
    when: _dt.datetime | None = None,
) -> str:
    """Mint a fresh probe record id ``<YYYYMMDD>-<HHMMSS>-<short>``.

    Append-only like :func:`harness.report.allocate_record_id`, but with the
    probe drivers' wider collision set: no file prefixed with the id may exist
    under *records_dir* (``<id>-<STATUS>.md/.json`` records) and no directory
    named exactly ``<id>`` may exist in any of *extra_dirs* (the per-run
    probe-log directories). On collision the timestamp advances one second.
    """
    when = when or _dt.datetime.now(_dt.timezone.utc)
    while True:
        rid = f"{when.strftime('%Y%m%d-%H%M%S')}-{short}"
        if not list(records_dir.glob(f"{rid}*")) and not any((d / rid).exists() for d in extra_dirs):
            return rid
        when += _dt.timedelta(seconds=1)


def write_excl(path: Path, text: str) -> None:
    """Exclusive-create write: an existing record file is never touched."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x") as fh:
        fh.write(text)


# ---- MARK-log parsing and PDK integrity gate (shared by the probe drivers) ------------

MARK_RE = re.compile(r"^MARK\s+(.*)$")
KV_RE = re.compile(r"(\w+)=(\S*)")


def finite_float(s: str | None) -> float | None:
    """``float(s)``, or ``None`` when *s* is missing, non-numeric or not finite."""
    if s is None or s == "":
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def parse_marks(stdout: str) -> dict[str, float | None]:
    """All ``MARK key=value`` pairs of an ngspice log (later keys win)."""
    marks: dict[str, float | None] = {}
    for line in stdout.splitlines():
        m = MARK_RE.match(line.strip())
        if m:
            for k, v in KV_RE.findall(m.group(1)):
                marks[k] = finite_float(v)
    return marks


def pdk_integrity(sim_dir: Path, banner: str | None = None, *, require_ngspice: bool) -> dict:
    """Run the harness model-integrity gate against ``sim/pdk-artifact.json``."""
    from harness import pdkartifact  # noqa: WPS433
    from harness.pdk import find_pdk  # noqa: WPS433
    rep = pdkartifact.verify(find_pdk(sim_dir), sim_dir, banner, require_ngspice=require_ngspice)
    return {"gate": f"sim/harness/pdkartifact.py verify(require_ngspice={require_ngspice})",
            "ok": rep.ok, "problems": list(rep.problems), "notes": list(rep.notes)}
