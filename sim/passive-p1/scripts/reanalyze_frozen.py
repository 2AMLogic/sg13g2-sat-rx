#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Re-run the passive-p1 analysis against a FROZEN solver-artifact package.

    python3 sim/passive-p1/scripts/reanalyze_frozen.py \\
        sim/passive-p1/solver-artifacts/<id> --out /tmp/p1-reanalysis-<id> \\
        [--python /path/to/python-with-numpy-scipy] [--stages "post fit compare"]

What it does
  1. verifies the package against its manifest (any missing/extra/altered byte
     refuses the run -- hash integrity is a precondition, not a result);
  2. copies ONLY the solver numerical artifacts (the three Touchstone files and
     their port_information.json / run_meta.json) into a fresh work tree under
     --out/work (never into the package, never into the shared working dirs);
  3. runs postprocess_p1.py, fit_p1.py and compare_p1.py on that work tree;
  4. writes --out/reanalysis.json: package id + manifest hash, commands, exit
     codes, sha256 of every produced file, and whether the re-derived
     p1_metrics.json / p1_compare.json equal the frozen ones.

What it deliberately does not do
  * It writes no record, nothing under records/ or solver-artifacts/, and never
    edits the original record or package.  --out inside the package, inside a
    records/ or solver-artifacts/ directory, or an existing non-empty directory
    is refused.  A reanalysis is a separate artifact; if it changes the
    scientific picture, supersede by a NEW record that says why.
  * "equal to the frozen result" is hash/JSON equality of derived files, not a
    qualification.  Numerical qualification is the record status produced by
    the analysis against the declared limits (limits.py).

Needs numpy/scipy only for the analysis steps (pass --python); --dry-run
verifies and stages the work tree without running them.  Standard library only
otherwise.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import freeze_package as FZ  # noqa: E402

STEPS = (("post", "postprocess_p1.py"), ("fit", "fit_p1.py"), ("compare", "compare_p1.py"))
DERIVED = ("results/p1_metrics.json", "results/p1_lq.csv", "results/p1_deembedded.s2p",
           "fit/p1_fit_parameters.json", "fit/p1_fit_candidate.spice", "results/p1_compare.json")


class ReanalysisError(Exception):
    pass


def _inside(child, parent):
    c, p = os.path.realpath(child), os.path.realpath(parent)
    return c == p or c.startswith(p + os.sep)


def _check_out(package, out):
    if _inside(out, package) or _inside(package, out):
        raise ReanalysisError("--out must be outside the frozen package (and not contain it)")
    parts = set(os.path.realpath(out).split(os.sep))
    if parts & {"records", FZ.PACKAGES_DIRNAME}:
        raise ReanalysisError("--out may not live under records/ or %s/: a reanalysis is not a record"
                              % FZ.PACKAGES_DIRNAME)
    if os.path.exists(out) and (not os.path.isdir(out) or os.listdir(out)):
        raise ReanalysisError("--out %s exists and is not an empty directory (results are never overwritten)" % out)


def reanalyze(package, out, python=None, stages="post fit compare", scripts_dir=HERE, dry_run=False):
    package = os.path.abspath(package)
    out = os.path.abspath(out)
    problems = FZ.verify(package)
    if problems:
        raise ReanalysisError("package fails integrity verification: " + "; ".join(problems))
    _check_out(package, out)
    with open(os.path.join(package, "manifest.json"), "rb") as fh:
        import hashlib
        manifest_sha = hashlib.sha256(fh.read()).hexdigest()
    man = json.load(open(os.path.join(package, "manifest.json")))
    work = os.path.join(out, "work")
    os.makedirs(work)
    staged = []
    for rel in FZ.SOLVER_FILES:
        src = os.path.join(package, *rel.split("/"))
        if os.path.isfile(src):
            dst = os.path.join(work, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            staged.append(rel)
    if not staged:
        shutil.rmtree(out, ignore_errors=True)
        raise ReanalysisError("package has no solver numerical artifacts (a CAPABILITY_UNAVAILABLE package "
                              "establishes no number and cannot be reanalysed)")
    want = set(stages.split())
    runs = []
    if not dry_run:
        py = python or sys.executable
        for name, script in STEPS:
            if name not in want:
                continue
            r = subprocess.run([py, os.path.join(scripts_dir, script), "--dir", work],
                               capture_output=True, text=True)
            runs.append({"step": name, "script": script, "exit": r.returncode,
                         "stdout_tail": r.stdout.strip().splitlines()[-3:], "stderr_tail": r.stderr.strip().splitlines()[-3:]})
            if r.returncode != 0:
                break  # later steps depend on this one
    produced, same = {}, {}
    frozen = {e["path"]: e["sha256"] for e in man["files"]}
    for rel in DERIVED:
        p = os.path.join(work, *rel.split("/"))
        if os.path.isfile(p):
            produced[rel] = FZ.sha256_file(p)
    for rel in ("results/p1_metrics.json", "results/p1_compare.json"):
        if rel in produced and rel in frozen:
            try:
                same[rel] = json.load(open(os.path.join(work, *rel.split("/")))) == \
                    json.load(open(os.path.join(package, *rel.split("/"))))
            except ValueError:
                same[rel] = False
    summary = {"kind": "passive-p1 reanalysis (NOT a campaign record)",
               "package": os.path.relpath(package, os.getcwd()), "run_id": man.get("run_id"),
               "original_status": man.get("status"), "manifest_sha256": manifest_sha, "package_integrity": "ok",
               "dry_run": dry_run, "staged_inputs": staged, "runs": runs, "produced_sha256": produced,
               "equals_frozen_json": same,
               "note": "Integrity of the package was verified before the run. Equality with the frozen JSON "
                       "is a reproducibility observation only; it does not qualify or disqualify the original "
                       "record, which is unchanged."}
    with open(os.path.join(out, "reanalysis.json"), "x") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("package")
    ap.add_argument("--out", required=True)
    ap.add_argument("--python", help="interpreter with numpy+scipy (default: this one)")
    ap.add_argument("--stages", default="post fit compare")
    ap.add_argument("--scripts-dir", default=HERE)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        s = reanalyze(a.package, a.out, a.python, a.stages, a.scripts_dir, a.dry_run)
    except ReanalysisError as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2
    print("reanalysis written to %s (original record and package untouched)" % os.path.join(a.out, "reanalysis.json"))
    for r in s["runs"]:
        print("  %-8s exit %d" % (r["step"], r["exit"]))
    for k, v in s["equals_frozen_json"].items():
        print("  %s %s the frozen file" % (k, "equals" if v else "DIFFERS from"))
    return 1 if any(r["exit"] for r in s["runs"]) else 0


if __name__ == "__main__":
    sys.exit(main())
