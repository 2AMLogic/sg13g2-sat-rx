#!/usr/bin/env python3
"""CI control assertion for the LNA cubic linearity bench (issue #122).

    python3 sim/lna-linearity/ci_assert.py

Generates ONE reduced cubic-only deck through the bench's own generator
(``linearity.control_circuit`` + ``options_line`` + ``body_for_runs`` over a
reduced copy of ``testbench/plan.json``) and runs it in ONE pinned ngspice
process: no DUT, no PDK models, no grid. The measured log is evaluated by the
bench's own extractor (``analysis.summaries_for_key`` ->
``linearity.points_from_summaries`` -> ``linearity.evaluate_control``) against
the plan's closed-form known answers.

It asserts, from structured results rather than exit codes:

* the pinned executable ran (present, major == sim/pdk-artifact.json, the log
  reached ``LNLIN_DONE`` and every run's marks are present and finite -- a
  missing simulator, a wrong version or truncated output fails);
* the unsabotaged measured log recovers all three known-answer quantities
  (two-tone IIP3, single-tone input P1dB, small-signal gain) within the
  plan's control tolerances on the reduced subset;
* the extraction-side amplitude sabotage (every measured bin amplitude
  scaled) fails its intended measured check -- the gain -- on both kinds,
  exactly the normalization fault IIP3/P1dB cannot see (differences only);
* the extraction-side available-power sabotage (swept power axis shifted)
  fails its intended measured check -- the input-referred dB known answers --
  on both kinds.

The deck-wide solver setting is the plan's TIGHT two-tone numerics
(``reltol`` 1e-7, ``trtol`` 1). The plan's looser single-tone setting exists
because the DUT's high-drive transients abort under a tight solver
(method-development observation); the memoryless cubic control has no such
stress, and the tighter setting only reduces truncation error here. The
reduced subset (same step, same time grid, so coherence is inherited) keeps
what the estimators need: a flat small-signal baseline at the bottom (where
the cubic's own compression is < 0.01 dB), at least ``min_points`` 1:3-region
steps with the IM3 far above the measured floor, and a bracketed 1 dB
crossing.

Green is evidence about the METHOD only: the deck generator netlists, the
pinned simulator projects the cubic fixture, and the extractor recovers the
closed forms on this subset. It is not a record (the work dir is a temp
directory; nothing under ``records/`` is touched), it says nothing about the
DUT, and it claims nothing about spec rows 7 or 8 -- the full collection
stays on the fleet.

Exit status 0 only when every assertion holds; 1 otherwise (problems on
stderr).
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
SIM_DIR = BENCH_DIR.parent
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(BENCH_DIR))

import analysis as A  # noqa: E402
import linearity as L  # noqa: E402

PLAN_PATH = BENCH_DIR / "testbench" / "plan.json"
PDK_ARTIFACT = SIM_DIR / "pdk-artifact.json"

# The reduced sweep subset (step and time grid unchanged from testbench/plan.json):
#   two-tone -50..-36 dBm, 15 points: flat baseline at the bottom, every point
#     uncompressed (gain drop <= 0.1 dB at -36) with the IM3 80+ dB above the
#     measured floor, so the whole range is a 1:3 region (min_points = 4);
#   single-tone -48..-16 dBm, 17 points: flat baseline at the bottom (cubic
#     compression < 0.01 dB there) and the 1 dB crossing bracketed at -22/-20.
REDUCED_SWEEP = {
    "two": {"start_dbm": -50.0, "stop_dbm": -36.0, "step_db": 1.0},
    "one": {"start_dbm": -48.0, "stop_dbm": -16.0, "step_db": 2.0},
}
# 20*log10(2) = +6.02 dB gain error, far above gain_tol_db = 0.05; the
# input-referred answers are insensitive to it, which is the point.
AMP_SABOTAGE_SCALE = 2.0
# Shifts the input-referred known answers by ~3 dB, far above iip3_tol_db = 0.15
# and p1db_tol_db = 0.1.
POWER_SABOTAGE_SHIFT_DB = 3.0


def reduced_plan() -> dict:
    plan = L.load_plan(PLAN_PATH)
    red = copy.deepcopy(plan)
    red["sweep"].update(REDUCED_SWEEP)
    return red


def compose_deck(red: dict) -> str:
    """One body with both control kinds' reduced runs (per-run ``alterparam``
    sets the frequencies, so mixed kinds in one body are the generator's own
    construction), exactly as ``run.body_for_key`` composes a control body."""
    c = red["controls"]
    runs = A.runs_for_key(red, "control_two") + A.runs_for_key(red, "control_one")
    circuit = L.control_circuit(c["a1"], c["a3"]) + "\n" + L.options_line(red, "two")
    return L.body_for_runs("lna-linearity ci control (reduced cubic)", circuit, runs)


def pinned_major() -> int:
    return int(json.loads(PDK_ARTIFACT.read_text())["ngspice"]["major"])


def ngspice_info(exe: str) -> dict:
    out = subprocess.run([exe, "-v"], capture_output=True, text=True, check=False).stdout
    line = next((ln.strip(" *") for ln in out.splitlines() if "ngspice-" in ln), "unknown")
    m = re.search(r"ngspice-(\d+)", line)
    return {"path": exe, "version": line.strip(), "major": int(m.group(1)) if m else None}


def sabotage_amplitude(summaries: list[dict], scale: float) -> list[dict]:
    """Every measured bin amplitude -- tone AND floor bins -- scaled by ``scale``:
    the wrong-DFT-normalization fault, applied to the real extracted marks."""
    out = []
    for s in summaries:
        s2 = dict(s)
        s2["amp_v"] = {k: v * scale for k, v in s["amp_v"].items()}
        s2["p_dbm"] = {k: L.delivered_dbm(a) for k, a in s2["amp_v"].items()}
        s2["floor_dbm"] = max(s2["p_dbm"]["fl_lo"], s2["p_dbm"]["fl_hi"])
        out.append(s2)
    return out


def assess(red: dict, info: dict | None, pinned: int, log: str) -> tuple[list[str], dict[str, dict]]:
    """Problems with the measured log (empty = every assertion holds) and the
    per-kind evaluations behind them. Pure: no simulator, no filesystem."""
    if info is None:
        return ["ngspice executable not found; the pinned executable did not run"], {}
    if info.get("major") != pinned:
        return [f"ngspice major {info.get('major')!r} ({info.get('version')!r}) is not the pinned "
                f"{pinned} (sim/pdk-artifact.json); the pinned executable did not run"], {}
    c = red["controls"]
    problems: list[str] = []
    summ: dict[str, list[dict]] = {}
    for kind in ("two", "one"):
        s, pr = A.summaries_for_key(red, f"control_{kind}", log)
        summ[kind] = s
        problems += pr
    if problems:
        return problems, {}
    evs: dict[str, dict] = {}
    for kind in ("two", "one"):
        rows = L.points_from_summaries(summ[kind], kind)
        ev = L.evaluate_control(red, kind, rows, c["a1"], c["a3"])
        evs[kind] = ev
        what = "IIP3" if kind == "two" else "P1dB"
        if not ev["pass"]:
            problems.append(f"positive control ({kind}-tone): did not recover the closed-form {what}/gain on the "
                            f"pinned ngspice (error {ev['error_db']}, gain error {ev['gain_error_db']}; tolerances "
                            f"{ev['tol_db']} / {ev['gain_tol_db']} dB)")
        ev_amp = L.evaluate_control(red, kind, L.points_from_summaries(
            sabotage_amplitude(summ[kind], AMP_SABOTAGE_SCALE), kind), c["a1"], c["a3"])
        if ev_amp["gain_error_db"] is None or abs(ev_amp["gain_error_db"]) <= ev_amp["gain_tol_db"]:
            problems.append(f"amplitude sabotage ({kind}-tone): gain error {ev_amp['gain_error_db']} is within "
                            f"{ev_amp['gain_tol_db']} dB; the gain check cannot catch a wrong amplitude normalization")
        ev_shift = L.evaluate_control(red, kind, [dict(r, pin_dbm=r["pin_dbm"] + POWER_SABOTAGE_SHIFT_DB)
                                                  for r in rows], c["a1"], c["a3"])
        if ev_shift["error_db"] is None or abs(ev_shift["error_db"]) <= ev_shift["tol_db"]:
            problems.append(f"available-power sabotage ({kind}-tone): {what} error {ev_shift['error_db']} is within "
                            f"{ev_shift['tol_db']} dB; the known-answer check cannot catch a wrong power convention")
    return problems, evs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ngspice", default=os.environ.get("NGSPICE", "ngspice"))
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args(argv)
    red = reduced_plan()
    pinned = pinned_major()
    exe = shutil.which(args.ngspice)
    info = ngspice_info(exe) if exe else None
    log = ""
    problems: list[str] = []
    if info is not None and info.get("major") == pinned:
        print(f"pinned executable: {info['version']} ({info['path']})")
        with tempfile.TemporaryDirectory(prefix="lnl-ci-assert-") as work:
            Path(work, "deck.spice").write_text(compose_deck(red))
            try:
                proc = subprocess.run([exe, "-b", "deck.spice"], cwd=work, capture_output=True, text=True,
                                      timeout=args.timeout, check=False)
            except subprocess.TimeoutExpired:
                proc = None
                problems.append(f"ngspice did not finish the deck within {args.timeout} s (bounded timeout)")
            if proc is not None:
                if proc.returncode != 0:
                    problems.append(f"ngspice exited {proc.returncode}: {proc.stderr[-500:]}")
                log = proc.stdout
    ass_problems, evs = assess(red, info, pinned, log)
    problems += ass_problems
    for p in problems:
        print(f"ERROR: {p}", file=sys.stderr)
    print("cubic control + sabotages: " + ("ok" if not problems else "FAILED"))
    if not problems:
        exp = L.cubic_expectations(red["controls"]["a1"], red["controls"]["a3"],
                                   drop_db=red["extraction"]["p1db"]["drop_db"])
        for kind, what, key in (("two", "IIP3", "iip3_dbm"), ("one", "P1dB", "p1db_in_dbm")):
            ev = evs[kind]
            print(f"{what} {ev['result'][key]:.3f} dBm vs closed form {exp[key]:.3f} dBm "
                  f"(error {ev['error_db']:+.3f} dB, tol {ev['tol_db']}); gain error {ev['gain_error_db']:+.3f} dB "
                  f"(tol {ev['gain_tol_db']})")
        print("green qualifies the extraction method on the pinned simulator only: "
              "not a record, not a DUT result, not a row-7/8 claim")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
