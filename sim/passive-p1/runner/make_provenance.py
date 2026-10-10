#!/usr/bin/env python3
"""Write <prefix>/provenance.json to stdout: pins, checksums, tool versions, per-phase cost.

Run with the runner environment active (so the venv python / openEMS / ngspice
are the ones found on PATH).  Stdlib only.
"""
import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd, **kw):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, **kw)
        return (r.stdout + r.stderr).strip()
    except Exception as exc:  # noqa: BLE001
        return "unavailable: %s" % exc


def parse_env(path):
    out = {}
    for line in open(path):
        line = line.split("#", 1)[0].strip() if not line.lstrip().startswith("#") else ""
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = " ".join(shlex.split(v.strip()))
    return out


def first_line(text, needle=None):
    for ln in text.splitlines():
        if needle is None or needle.lower() in ln.lower():
            return ln.strip(" |")
    return text.splitlines()[0] if text else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--lock", required=True)
    ap.add_argument("--requirements", required=True)
    ap.add_argument("--phases", required=True)
    ap.add_argument("--limits", required=True)
    ap.add_argument("--total-wall-s", type=float, required=True)
    a = ap.parse_args()
    p = a.prefix

    def gitrev(path):
        return run(["git", "-C", path, "rev-parse", "HEAD"]) if os.path.isdir(path) else None

    bins = {}
    for name, rel in (("openEMS", "openems/bin/openEMS"), ("ngspice", "ngspice/bin/ngspice")):
        f = os.path.join(p, rel)
        if os.path.isfile(f):
            bins[name] = {"path": f, "sha256": sha256(f)}
    dl = os.path.join(p, "dl", "ngspice.tar.gz")
    phases = [json.loads(l) for l in open(a.phases) if l.strip()]
    prov = {
        "schema": 1,
        "generated_by": "sim/passive-p1/runner/make_provenance.py",
        "prefix": p,
        "lock": parse_env(a.lock),
        "limits_declared": parse_env(a.limits),
        "requirements_lock_sha256": sha256(a.requirements),
        "lock_env_sha256": sha256(a.lock),
        "resolved_commits": {
            "openEMS-Project": gitrev(os.path.join(p, "src", "openEMS-Project")),
            "CSXCAD": gitrev(os.path.join(p, "src", "openEMS-Project", "CSXCAD")),
            "openEMS": gitrev(os.path.join(p, "src", "openEMS-Project", "openEMS")),
            "fparser": gitrev(os.path.join(p, "src", "openEMS-Project", "fparser")),
            "gds2openEMS": gitrev(os.path.join(p, "src", "openems_ihp_sg13g2")),
            "IHP-Open-PDK": gitrev(os.path.join(p, "pdk", "IHP-Open-PDK")),
        },
        "ngspice_tarball_sha256": sha256(dl) if os.path.isfile(dl) else None,
        "binaries": bins,
        "versions": {
            "python": sys.version.split()[0],
            "pip_freeze": run([sys.executable, "-m", "pip", "freeze", "--all"]).splitlines(),
            "openEMS": first_line(run(["openEMS", "--version"]), "version"),
            "ngspice": first_line(run(["ngspice", "--version"]), "ngspice-"),
            "klayout": first_line(run(["klayout", "-v"])),
            "gcc": first_line(run(["gcc", "--version"])),
            "cmake": first_line(run(["cmake", "--version"])),
            "os": first_line(run(["uname", "-sr"])),
        },
        "build_phases": phases,
        "build_total_wall_s": a.total_wall_s,
        "build_peak_tree_rss_mb": max([ph.get("peak_tree_rss_mb", 0) for ph in phases] or [0]),
        "prefix_size_kib": int(run(["du", "-sk", p]).split()[0]),
        "system_klayout_note": "headless KLayout is the system binary on PATH; it is not built or pinned by the runner",
    }
    json.dump(prov, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
