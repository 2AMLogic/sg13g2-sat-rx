#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Freeze the solver artifacts behind one passive-p1 record (issue #58).

The working directories (results/, fit/, run_log/) are mutable scratch and are
reused by every run.  A new campaign record therefore names a *frozen copy*:

    sim/passive-p1/solver-artifacts/<YYYYMMDD>-<HHMMSS>-<git-sha>/
        manifest.json     package-relative path + sha256 + size of every file
        settings.json     stages, commands and solver settings of the run
        results/ fit/ run_log/   byte copies of the working files (same layout
                                 as the working tree, so the analysis scripts
                                 can be pointed at a package copy unchanged)

Publication rules (all enforced here, mirrored by
.github/scripts/check_evidence_formats.py):
  * the run directory is created with a plain mkdir: an existing directory of
    that id (complete OR interrupted) is refused, never reused or merged;
  * the outcome decides which files are REQUIRED (required_paths()); a missing
    required file refuses publication BEFORE anything is created;
  * every copy is created exclusively and re-hashed against the source hash
    taken just before the copy (a file that changes mid-copy aborts);
  * `.INCOMPLETE` marks the directory until manifest.json is written last; any
    exception removes the directory this call created;
  * no symlinks are followed, only the declared layouts are copied.

A package proves that the bytes are the ones the record was derived from
(hash INTEGRITY).  It says nothing about whether those numbers are right or
qualified -- that is the record's status, produced by the analysis and its
declared limits.  Standard library only.

CLI:
  freeze_package.py publish --dir D --run-id ID --status S --stages "..." [--has-compare]
  freeze_package.py verify  PACKAGE_DIR
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys

SCHEMA = "passive-p1-solver-artifacts/1"
INCOMPLETE = ".INCOMPLETE"
PACKAGES_DIRNAME = "solver-artifacts"
RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{7,40}$")
SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")
ALLOWED_TOP = ("results", "fit", "run_log")
SOLVES = ("results/inductor_p1", "results/convergence/p1_mesh0p5", "results/convergence/p1_margin400")
GEOMETRY_LOGS = ("run_log/geometry_overlay.txt", "run_log/geometry_p1.txt", "run_log/geometry_xor.txt")
EM_LOGS = {"em": ("run_log/em_p1.txt",),
           "convergence": ("run_log/em_conv_p1_mesh0p5.txt", "run_log/em_conv_p1_margin400.txt")}
STAGE_LOGS = {"post": "run_log/postprocess.txt", "fit": "run_log/fit.txt", "compare": "run_log/compare.txt"}
SOLVER_FILES = tuple(p for b in SOLVES for p in (b + ".s2p", b + "/port_information.json", b + "/run_meta.json"))
POST_FILES = ("results/p1_metrics.json", "results/p1_lq.csv", "results/p1_deembedded.s2p")
FIT_FILES = ("fit/p1_fit_parameters.json", "fit/p1_fit_candidate.spice")
COMPARE_FILES = ("results/p1_compare.json",)
STATUSES = ("QUALIFIED", "UNCONVERGED", "FIT_FAILED", "CAPABILITY_UNAVAILABLE")


class PublishError(Exception):
    pass


def safe_relpath(p):
    """True for a normalised package-relative POSIX path made of plain components."""
    if not isinstance(p, str) or not p or p.startswith("/") or "\\" in p or "\x00" in p:
        return False
    parts = p.split("/")
    return all(SAFE_COMPONENT_RE.match(c) and c not in (".", "..") for c in parts)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stage_list(stages):
    return stages.split() if isinstance(stages, str) else list(stages)


def required_paths(status, stages, has_compare):
    """(required, optional) working-relative paths implied by the outcome.

    The files are chosen by what the OUTCOME consumed, not by what happens to
    sit in the working tree (which may be stale from an earlier run):
      CAPABILITY_UNAVAILABLE  no solver data is invented; only diagnostics that
                              exist are kept (all optional).
      UNCONVERGED             the three solves + post-processing outputs.
      FIT_FAILED              the above + the fit log; the fit parameters are
                              kept if present; with a comparison, fit and
                              comparison outputs are required too.
      QUALIFIED               everything.
    Stage logs are required only for stages this invocation requested.
    """
    if status not in STATUSES:
        raise PublishError("unknown status %r" % (status,))
    st = set(stage_list(stages))
    logs = []
    if "geometry" in st:
        logs += GEOMETRY_LOGS
    for s, names in EM_LOGS.items():
        if s in st:
            logs += names
    if status == "CAPABILITY_UNAVAILABLE":
        every = logs + [v for k, v in STAGE_LOGS.items() if k in st]
        return [], sorted(every)
    req = list(SOLVER_FILES) + list(POST_FILES)
    opt = []
    if "post" in st:
        logs.append(STAGE_LOGS["post"])
    if status == "FIT_FAILED":
        if "fit" in st:
            logs.append(STAGE_LOGS["fit"])
        if has_compare:
            req += list(FIT_FILES) + list(COMPARE_FILES)
            if "compare" in st:
                logs.append(STAGE_LOGS["compare"])
        else:
            opt += list(FIT_FILES)
    elif status == "QUALIFIED":
        req += list(FIT_FILES) + list(COMPARE_FILES)
        logs += [STAGE_LOGS[k] for k in ("fit", "compare") if k in st]
    # geometry logs are diagnostics of a stage that may have been skipped by an earlier crash
    return sorted(set(req) | set(logs)), sorted(set(opt))


def _plan(workdir, status, stages, has_compare):
    req, opt = required_paths(status, stages, has_compare)
    chosen, missing = [], []
    for rel in req:
        p = os.path.join(workdir, rel)
        if os.path.islink(p) or not os.path.isfile(p):
            missing.append(rel)
        else:
            chosen.append(rel)
    for rel in opt:
        p = os.path.join(workdir, rel)
        if os.path.isfile(p) and not os.path.islink(p):
            chosen.append(rel)
    if missing:
        raise PublishError("missing required stage output(s) for a %s record with stages [%s]: %s"
                           % (status, " ".join(stage_list(stages)), ", ".join(missing)))
    return sorted(set(chosen))


def _write_new(path, data):
    with open(path, "xb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def publish(workdir, packages_dir, run_id, status, stages, settings=None, has_compare=False,
            commands="", failed_command="", _after_copy=None):
    """Create <packages_dir>/<run_id>/ exclusively and fill it.  Returns
    {"dir", "manifest_path", "manifest_sha256", "files"}.  On any failure the
    directory this call created is removed and PublishError/the error is raised."""
    if not RUN_ID_RE.match(run_id):
        raise PublishError("run id %r is not <YYYYMMDD>-<HHMMSS>-<git-sha>" % (run_id,))
    chosen = _plan(workdir, status, stages, has_compare)  # refuses incomplete BEFORE reserving
    os.makedirs(packages_dir, exist_ok=True)
    pkg = os.path.join(packages_dir, run_id)
    try:
        os.mkdir(pkg)  # exclusive reservation: an existing run id (even interrupted) is refused
    except FileExistsError:
        raise PublishError("package %s already exists; packages are never overwritten or merged" % pkg)
    try:
        _write_new(os.path.join(pkg, INCOMPLETE), b"publication in progress\n")
        entries = []
        for rel in chosen:
            src = os.path.join(workdir, rel)
            want = sha256_file(src)
            dst = os.path.join(pkg, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(src, "rb") as fi, open(dst, "xb") as fo:
                shutil.copyfileobj(fi, fo)
                fo.flush()
                os.fsync(fo.fileno())
            got = sha256_file(dst)
            if got != want:
                raise PublishError("%s changed while it was being copied" % rel)
            entries.append({"path": rel, "sha256": got, "bytes": os.path.getsize(dst)})
            if _after_copy:
                _after_copy(rel)
        sett = {"schema": SCHEMA, "run_id": run_id, "status": status, "stages": stage_list(stages),
                "commands": commands, "failed_command": failed_command, "has_compare": bool(has_compare),
                "solver_settings": settings or {}}
        data = (json.dumps(sett, indent=2, sort_keys=True) + "\n").encode()
        _write_new(os.path.join(pkg, "settings.json"), data)
        entries.append({"path": "settings.json", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        entries.sort(key=lambda e: e["path"])
        manifest = {"schema": SCHEMA, "run_id": run_id, "status": status, "stages": stage_list(stages),
                    "files": entries}
        mdata = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        _write_new(os.path.join(pkg, "manifest.json"), mdata)  # last: its presence = complete
        os.remove(os.path.join(pkg, INCOMPLETE))
    except BaseException:
        shutil.rmtree(pkg, ignore_errors=True)
        raise
    return {"dir": pkg, "manifest_path": os.path.join(pkg, "manifest.json"),
            "manifest_sha256": hashlib.sha256(mdata).hexdigest(), "files": len(entries)}


def verify(pkg):
    """Return a list of problems (empty = every listed file present with the recorded hash,
    nothing else in the directory).  Integrity only; no numerical judgement."""
    problems = []
    mp = os.path.join(pkg, "manifest.json")
    if os.path.exists(os.path.join(pkg, INCOMPLETE)):
        problems.append("package is marked %s (interrupted publication)" % INCOMPLETE)
    try:
        with open(mp) as fh:
            man = json.load(fh)
    except (OSError, ValueError) as exc:
        return problems + ["manifest.json unreadable: %s" % exc]
    files = man.get("files") if isinstance(man, dict) else None
    if man.get("schema") != SCHEMA or not isinstance(files, list) or not files:
        return problems + ["manifest.json has wrong schema or no files"]
    listed = set()
    for e in files:
        p = e.get("path") if isinstance(e, dict) else None
        if not safe_relpath(p):
            problems.append("unsafe path in manifest: %r" % (p,))
            continue
        if p in listed:
            problems.append("duplicate path in manifest: %s" % p)
        listed.add(p)
        fp = os.path.join(pkg, *p.split("/"))
        if os.path.islink(fp) or not os.path.isfile(fp):
            problems.append("listed file missing: %s" % p)
        elif sha256_file(fp) != e.get("sha256"):
            problems.append("sha256 mismatch: %s" % p)
    actual = set()
    for root, dirs, fnames in os.walk(pkg):
        for f in fnames:
            actual.add(os.path.relpath(os.path.join(root, f), pkg).replace(os.sep, "/"))
    for extra in sorted(actual - listed - {"manifest.json"}):
        problems.append("file not in manifest: %s" % extra)
    return problems


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("publish")
    p.add_argument("--dir", required=True)
    p.add_argument("--packages-dir")
    p.add_argument("--run-id", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--stages", default="")
    p.add_argument("--has-compare", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("package")
    a = ap.parse_args()
    if a.cmd == "verify":
        probs = verify(a.package)
        for x in probs:
            print("PROBLEM:", x, file=sys.stderr)
        print("package integrity: %s (hash integrity only; says nothing about numerical qualification)"
              % ("FAILED" if probs else "ok"))
        return 1 if probs else 0
    try:
        r = publish(a.dir, a.packages_dir or os.path.join(a.dir, PACKAGES_DIRNAME), a.run_id, a.status,
                    a.stages, has_compare=a.has_compare)
    except PublishError as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2
    print("published %s (%d files, manifest sha256 %s)" % (r["dir"], r["files"], r["manifest_sha256"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
