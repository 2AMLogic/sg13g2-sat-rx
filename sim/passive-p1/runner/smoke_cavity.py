#!/usr/bin/env python3
"""Known-answer openEMS control: resonant frequencies of a closed PEC box (issue #46).

Physics: a lossless rectangular PEC cavity a x b x d has resonances
    f_mnp = (c0/2) * sqrt((m/a)^2 + (n/b)^2 + (p/d)^2)
(c0 = 299792458 m/s, vacuum).  This script builds that cavity with the CSXCAD
Python bindings, writes the FDTD setup to XML, runs the real openEMS executable
on it (multithreaded engine, `--numThreads`), reads the recorded probe voltage
back, locates the lowest spectral peaks and compares them with the analytic
values.  Nothing about the expected numbers is fed to the peak finder.

Why this is a solver-execution control and not an import check: the answer is a
property of the time-stepped field.  A solver that did not advance, produced
NaN/zero output, or ran the wrong geometry cannot reproduce the frequencies.

It checks the *solver* (and the bindings/XML hand-off), not any passive family
or the p1 inductor.  It says nothing about EM convergence of p1.

Exit status (distinct on purpose; a harness can tell the failure modes apart):
    0   control passed
    10  prerequisite missing: the openEMS executable (or a thread bound outside 1..2)
    14  prerequisite missing: the python bindings (openEMS / CSXCAD)
    11  solver failure (nonzero exit, no output, or too few time steps written)
    13  numerical mismatch (non-finite output or outside the declared tolerance)
Timeouts and memory-limit kills (124/125) are imposed from outside by limited_run.py.

Run it with the interpreter that has the openEMS/CSXCAD bindings (OPENEMS_PYTHON).
"""
import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time

C0 = 299792458.0
# --- declared fixture (the known answer) -----------------------------------------
BOX_MM = (30.0, 20.0, 25.0)        # a (x), b (y), d (z)
CELL_MM = 1.0                      # uniform cubic cells -> 30 x 20 x 25 = 15 000 cells
N_STEPS = 20000                    # dt ~ 1.9 ps -> ~38 ns record, ~26 MHz raw bin
F_GAUSS = (7.0e9, 6.0e9)           # Gaussian pulse centre, 20 dB corner -> covers ~1-13 GHz
EXC_MM = (10.0, 7.0, 8.0)          # y-directed soft source cell (off-symmetry on purpose)
PROBE_MM = (21.0, 13.0, 16.0)      # y-directed voltage probe cell
MODES = [(1, 0, 1), (1, 1, 1), (2, 0, 1), (1, 0, 2)]   # four lowest peaks the y-directed source excites (m,n,p)
TOL_REL = 0.005                    # declared tolerance: 0.5 % of the analytic frequency
PEAK_REL_FLOOR = 0.05             # a spectral peak counts if >= 5 % of the largest (Hann sidelobes are ~2.7 %)


def analytic(mode):
    m, n, p = mode
    a, b, d = (x * 1e-3 for x in BOX_MM)
    return 0.5 * C0 * math.sqrt((m / a) ** 2 + (n / b) ** 2 + (p / d) ** 2)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(code, msg, report, path):
    report.update(result="FAIL", exit_status=code, reason=msg)
    print("smoke_cavity: FAIL(%d): %s" % (code, msg), file=sys.stderr)
    if path:
        with open(path, "w") as fh:
            json.dump(report, fh, indent=2, sort_keys=True); fh.write("\n")
    sys.exit(code)


def lowest_peaks(freq, mag, count):
    """Frequencies of the `count` lowest local maxima above the relative floor, with
    3-point parabolic refinement.  Uses only the spectrum."""
    floor = PEAK_REL_FLOOR * max(mag)
    peaks = []
    for i in range(1, len(mag) - 1):
        if mag[i] >= floor and mag[i] > mag[i - 1] and mag[i] >= mag[i + 1]:
            a, b, c = mag[i - 1], mag[i], mag[i + 1]
            den = a - 2 * b + c
            off = 0.5 * (a - c) / den if den != 0 else 0.0
            peaks.append(freq[i] + off * (freq[1] - freq[0]))
            if len(peaks) == count:
                break
    return peaks


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workdir", required=True, help="scratch directory (must be outside the repo)")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--report", required=True, help="JSON result path")
    ap.add_argument("--expect-scale", type=float, default=1.0,
                    help="negative control: multiply the analytic expectation (1.0 = honest)")
    ap.add_argument("--inject", choices=["none", "corrupt-xml", "no-excitation"], default="none",
                    help="negative control: sabotage the solver input")
    a = ap.parse_args()

    report = {"control": "pec-cavity-resonance", "tolerance_rel": TOL_REL,
              "fixture": {"box_mm": BOX_MM, "cell_mm": CELL_MM, "n_steps": N_STEPS,
                          "gauss_f0_fc_hz": F_GAUSS, "excitation_mm": EXC_MM,
                          "probe_mm": PROBE_MM, "modes_mnp": MODES},
              "threads": a.threads, "inject": a.inject, "expect_scale": a.expect_scale}

    # ---- prerequisites ----------------------------------------------------------
    exe = shutil.which("openEMS")
    if not exe:
        fail(10, "executable 'openEMS' not on PATH", report, a.report)
    try:
        import numpy as np
        from CSXCAD import ContinuousStructure
        from openEMS import openEMS
    except Exception as exc:  # noqa: BLE001
        fail(14, "python binding import failed: %s: %s" % (type(exc).__name__, exc), report, a.report)
    if not (1 <= a.threads <= 2):
        fail(10, "threads=%d outside the declared bound 1..2" % a.threads, report, a.report)

    os.makedirs(a.workdir, exist_ok=True)
    work = os.path.abspath(a.workdir)
    xml = os.path.join(work, "cavity.xml")
    vers = subprocess.run([exe, "--version"], capture_output=True, text=True)
    report["versions"] = {
        "openEMS_executable": exe,
        "openEMS": next((l.strip(" |") for l in (vers.stdout + vers.stderr).splitlines() if "version" in l.lower()), "unknown"),
        "openEMS_python": getattr(__import__("openEMS"), "__version__", "unknown"),
        "numpy": np.__version__, "python": sys.version.split()[0],
    }

    # ---- build the cavity --------------------------------------------------------
    fdtd = openEMS(NrTS=N_STEPS, EndCriteria=0)    # EndCriteria 0: never stop early on a lossless box
    fdtd.SetGaussExcite(*F_GAUSS)
    fdtd.SetBoundaryCond(["PEC"] * 6)
    csx = ContinuousStructure()
    fdtd.SetCSX(csx)
    mesh = csx.GetGrid()
    mesh.SetDeltaUnit(1e-3)
    for axis, size in enumerate(BOX_MM):
        mesh.AddLine(axis, [i * CELL_MM for i in range(int(round(size / CELL_MM)) + 1)])
    if a.inject != "no-excitation":
        exc = csx.AddExcitation("exc", 0, [0, 1, 0])
        exc.AddBox([EXC_MM[0], EXC_MM[1], EXC_MM[2]], [EXC_MM[0] + CELL_MM, EXC_MM[1] + CELL_MM, EXC_MM[2] + CELL_MM])
    prb = csx.AddProbe("ut", 0)
    prb.AddBox([PROBE_MM[0], PROBE_MM[1], PROBE_MM[2]], [PROBE_MM[0], PROBE_MM[1] + CELL_MM, PROBE_MM[2]])
    fdtd.Write2XML(xml)
    if not os.path.isfile(xml):
        fail(11, "bindings did not write the solver input XML", report, a.report)
    if a.inject == "corrupt-xml":
        with open(xml, "r+") as fh:
            txt = fh.read()
            fh.seek(0); fh.truncate(); fh.write(txt[: len(txt) // 2])
    report["input_sha256"] = {"cavity.xml": sha256(xml),
                              "smoke_cavity.py": sha256(os.path.abspath(__file__))}

    # ---- run the real solver executable ------------------------------------------
    cmd = [exe, xml, "--numThreads=%d" % a.threads, "--disable-dumps"]
    report["command"] = " ".join(cmd)
    env = dict(os.environ, OMP_NUM_THREADS=str(a.threads))
    t0 = time.monotonic()
    log_path = os.path.join(work, "openEMS.log")
    with open(log_path, "w") as log:
        rc = subprocess.run(cmd, cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    report["solver_wall_s"] = round(time.monotonic() - t0, 3)
    report["solver_exit_status"] = rc
    with open(log_path) as fh:
        log_text = fh.read()
    report["solver_log_tail"] = log_text.strip().splitlines()[-6:]
    if rc != 0:
        fail(11, "solver exited with status %d" % rc, report, a.report)

    # ---- read back the probe, check the solver really advanced -------------------
    probe_file = os.path.join(work, "ut")
    if not os.path.isfile(probe_file):
        fail(11, "solver exited 0 but wrote no probe file 'ut'", report, a.report)
    try:
        data = np.loadtxt(probe_file, comments="%")
    except Exception as exc:  # noqa: BLE001
        fail(11, "probe file unreadable: %s" % exc, report, a.report)
    import re
    m_dt = re.search(r"FDTD timestep is:\s*([0-9.eE+-]+)\s*s", log_text)
    m_it = re.search(r"Time for\s+(\d+)\s+iterations", log_text)
    if not m_dt or not m_it:
        fail(11, "solver log lacks the timestep / iteration-count lines: the FDTD loop did not report completion", report, a.report)
    dt_solver, iterations = float(m_dt.group(1)), int(m_it.group(1))
    report["solver_reported"] = {"timestep_s": dt_solver, "iterations": iterations}
    if iterations != N_STEPS:
        fail(11, "solver ran %d iterations, expected %d" % (iterations, N_STEPS), report, a.report)
    if data.ndim != 2 or data.shape[0] < 100 or abs(data[-1, 0] - N_STEPS * dt_solver) > 0.01 * N_STEPS * dt_solver:
        fail(11, "probe record does not span the %d solver steps: solver did not advance" % N_STEPS, report, a.report)
    t, v = data[:, 0], data[:, 1]
    report["timesteps_recorded"] = int(len(t))
    if not (np.all(np.isfinite(t)) and np.all(np.isfinite(v))):
        fail(13, "non-finite values in the probe record", report, a.report)
    if float(np.max(np.abs(v))) <= 0.0:
        fail(13, "probe record is identically zero (nothing was excited)", report, a.report)

    # ---- spectrum, independent peak search, comparison -------------------------------
    dt = float(t[1] - t[0])
    nfft = 1 << 18
    spec = np.abs(np.fft.rfft((v - v.mean()) * np.hanning(len(v)), nfft))
    freq = np.fft.rfftfreq(nfft, dt)
    band = (freq > 1e9) & (freq < 15e9)
    found = lowest_peaks(freq[band], spec[band], len(MODES))
    report["dt_s"] = dt
    report["found_peaks_hz"] = found
    rows, worst = [], 0.0
    for k, mode in enumerate(MODES):
        expect = analytic(mode) * a.expect_scale
        got = found[k] if k < len(found) else float("nan")
        rel = abs(got - expect) / expect if math.isfinite(got) else float("inf")
        worst = max(worst, rel)
        rows.append({"mode_mnp": mode, "analytic_hz": expect, "measured_hz": got, "rel_err": rel})
    report["modes"] = rows
    report["worst_rel_err"] = worst
    if len(found) < len(MODES) or not all(math.isfinite(f) for f in found):
        fail(13, "found only %d of %d expected spectral peaks" % (len(found), len(MODES)), report, a.report)
    if worst > TOL_REL:
        fail(13, "worst relative frequency error %.4f exceeds the declared tolerance %.4f" % (worst, TOL_REL), report, a.report)

    report.update(result="PASS", exit_status=0)
    with open(a.report, "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True); fh.write("\n")
    print("smoke_cavity: PASS worst_rel_err=%.5f (tol %.4f) peaks_GHz=%s"
          % (worst, TOL_REL, ["%.4f" % (f / 1e9) for f in found]))


if __name__ == "__main__":
    main()
