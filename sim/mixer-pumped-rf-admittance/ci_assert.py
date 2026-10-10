#!/usr/bin/env python3
"""CI control assertion for the pumped RF-port admittance probe (issue #111).

    python3 sim/mixer-pumped-rf-admittance/ci_assert.py

Runs the controls-only deck (passive RC + ideal modulated known answers, no DUT, no PDK)
ONCE on the PINNED ngspice and evaluates the same log unsabotaged and under every
extraction sabotage (current_sign, omit_image, no_baseline). One ngspice process, no grid.
It writes nothing under the repository (the work dir is a temp directory) and records
nothing.

It asserts, from structured results rather than exit codes:
  * the pinned executable ran (present, major == sim/pdk-artifact.json, deck reached
    `MARK done`);
  * the unsabotaged controls pass (known-answer magnitude/phase, RC cross-term null,
    numerical checks, RC -> SCALAR_ADEQUATE and modulated -> MATRIX_REQUIRED);
  * each sabotage makes at least one of its expected measured checks fail.
It asserts nothing about the DUT. A pass is evidence about the extraction's
discrimination only: not a record, not a row-5 claim.

Exit status 0 only when every assertion holds; 1 otherwise (problems on stderr).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pumped as P  # noqa: E402
import run_probe as R  # noqa: E402


def assess(info: dict | None, pinned: int, stdout: str, stderr: str, thr: dict) -> list[str]:
    """Problems for the controls-only log (empty = every assertion holds). Pure function."""
    if info is None:
        return ["ngspice executable not found; the pinned executable did not run"]
    if info.get("major") != pinned:
        return [f"ngspice major {info.get('major')!r} ({info.get('version')!r}) is not the pinned "
                f"{pinned} (sim/pdk-artifact.json); the pinned executable did not run"]
    parsed = P.parse_log(stdout, stderr)
    if not parsed["completed"]:
        return ["deck did not reach 'MARK done'; the control block did not run to completion"]
    problems: list[str] = []
    for sab in (None, *sorted(P.SABOTAGES)):
        label = f"sabotage {sab}" if sab else "positive control"
        try:
            ev = P.evaluate(parsed, thr, sab)
        except P.ProbeError as exc:
            problems.append(f"{label}: control marks missing or broken: {exc}")
            continue
        failing = {n for n, c in ev["controls"]["checks"].items() if not c["pass"]}
        if sab is None:
            if failing:
                problems.append(f"{label}: known-answer controls did not pass on the pinned ngspice "
                                f"(failing: {sorted(failing)})")
        elif not failing & P.EXPECTED_FAILING[sab]:
            problems.append(f"{label}: failed only {sorted(failing)}, none of the expected measured "
                            f"checks {sorted(P.EXPECTED_FAILING[sab])}; the control cannot discriminate")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ngspice", default=os.environ.get("NGSPICE", "ngspice"))
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args(argv)
    pinned = R.pinned_major()
    thr = P.load_thresholds()
    exe = shutil.which(args.ngspice)
    info = R.ngspice_info(exe) if exe else None
    out = err = ""
    if info is not None and info.get("major") == pinned:
        print(f"pinned executable: {info['version']} ({info['path']})")
        with tempfile.TemporaryDirectory(prefix="pra-ci-assert-") as work:
            Path(work, "deck.spice").write_text(R.compose_deck(None, with_dut=False))
            proc = subprocess.run([exe, "-b", "deck.spice"], cwd=work, capture_output=True, text=True,
                                  timeout=args.timeout, check=False)
            out, err = proc.stdout, proc.stderr
    problems = assess(info, pinned, out, err, thr)
    for p in problems:
        print(f"ERROR: {p}", file=sys.stderr)
    print("controls + sabotages: " + ("ok" if not problems else "FAILED"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
