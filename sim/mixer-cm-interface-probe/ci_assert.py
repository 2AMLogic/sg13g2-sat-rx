#!/usr/bin/env python3
"""CI control assertion for the conversion-matrix interface probe (issue #104).

    python3 sim/mixer-cm-interface-probe/ci_assert.py

Runs the known-answer ideal-mixer control once unsabotaged and once per sabotage
(gain, drop_image, image_sign, wrong_lo) on the PINNED ngspice, at the single nominal
point, five ngspice processes in total, no grid, no loop over corners. It writes nothing
under the repository (work dirs live in a temp directory) and prints no record.

It asserts the CONTROLS only, from structured results rather than exit codes:
  * the pinned executable actually ran (present, major == sim/pdk-artifact.json, deck
    completed with `MARK done`); a missing or wrong executable is a failure here, even
    though `run_probe.py` exits 0 with a CAPABILITY_UNAVAILABLE record in that case;
  * the unsabotaged control passes against the closed form;
  * each sabotage makes the control FAIL on a measured check (not a parse defect, not a
    missing mark); an unexpectedly passing sabotage fails.
It deliberately does NOT assert an overall interface status: unsupported noise
interfaces (INTERFACES_BLOCKED / PARTIAL) are a legitimate investigation outcome. A pass
is evidence about the control's discrimination only; it is not a record, not a row 10/12
claim, and not METHOD_VALIDATION.

Exit status 0 only when every assertion holds; 1 otherwise (problems on stderr).
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cmprobe as C  # noqa: E402
import run_probe as R  # noqa: E402

# A sabotage must fail at least one of these measured checks (never only the
# linearity/superposition bookkeeping checks).
EXPECTED_FAILING = {
    "gain": {"wanted", "image"},
    "drop_image": {"image"},
    "image_sign": {"image"},
    "wrong_lo": {"wanted", "image", "frequency_null"},
}
CHECK_NAMES = ("wanted", "image", "frequency_null", "linearity", "superposition")


def assess(label: str, sabotage: str | None, info: dict | None, pinned: int,
           stdout: str, stderr: str) -> list[str]:
    """Return the list of problems for one control run (empty = the assertion holds).

    Pure function of the executable info and the captured log, so every failure mode is
    testable without a simulator.
    """
    if info is None:
        return [f"{label}: ngspice executable not found; the pinned executable did not run"]
    if info.get("major") != pinned:
        return [f"{label}: ngspice major {info.get('major')!r} ({info.get('version')!r}) is not the "
                f"pinned {pinned} (sim/pdk-artifact.json); the pinned executable did not run"]
    try:
        parsed = C.parse_log(stdout, stderr)
    except C.ProbeError as exc:
        return [f"{label}: parse defect: {exc}"]
    if not parsed["completed"]:
        return [f"{label}: deck did not reach 'MARK done'; the control block did not run to completion"]
    try:
        ctl = C.evaluate_control(parsed["marks"])
    except C.ProbeError as exc:
        return [f"{label}: control marks missing or broken: {exc}"]
    checks = ctl.get("checks", {})
    absent = [n for n in CHECK_NAMES if n not in checks]
    if absent:
        return [f"{label}: control result lacks checks {absent}"]
    for n in ("wanted", "image"):
        vals = [checks[n]["mag_rel_err"], checks[n]["phase_err_deg"], *checks[n]["measured"]]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals):
            return [f"{label}: non-finite measurement in check '{n}'; control result is broken"]
    failing = {n for n, c in checks.items() if not c["pass"]}
    if sabotage is None:
        if ctl["pass"]:
            return []
        return [f"{label}: the real ideal-mixer control did not pass on the pinned ngspice "
                f"(failing checks: {sorted(failing)})"]
    if ctl["pass"]:
        return [f"{label}: sabotage '{sabotage}' left the control PASSING; it cannot discriminate"]
    if not failing & EXPECTED_FAILING[sabotage]:
        return [f"{label}: sabotage '{sabotage}' failed only {sorted(failing)}, none of the expected "
                f"measured checks {sorted(EXPECTED_FAILING[sabotage])}"]
    return []


def run_one(exe: str, sabotage: str | None, model_lib: str, timeout: int) -> tuple[str, str]:
    deck = R.compose_deck(model_lib, sabotage)
    with tempfile.TemporaryDirectory(prefix="cm-ci-assert-") as work:
        Path(work, "deck.spice").write_text(deck)
        proc = subprocess.run([exe, "-b", "deck.spice"], cwd=work, capture_output=True, text=True,
                              timeout=timeout, check=False)
    return proc.stdout, proc.stderr


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ngspice", default=os.environ.get("NGSPICE", "ngspice"))
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args(argv)

    pinned = R.pinned_major()
    exe = shutil.which(args.ngspice)
    info = R.ngspice_info(exe) if exe else None
    problems: list[str] = []
    if info is None or info.get("major") != pinned:
        problems += assess("preflight", None, info, pinned, "", "")
    else:
        model_lib = R.pdk_info()["model_lib"]
        print(f"pinned executable: {info['version']} ({info['path']})")
        for sab in (None, *sorted(C.SABOTAGES)):
            label = f"sabotage {sab}" if sab else "positive control"
            out, err = run_one(exe, sab, model_lib, args.timeout)
            probs = assess(label, sab, info, pinned, out, err)
            print(f"{label}: {'ok' if not probs else 'FAILED'}")
            problems += probs
    for p in problems:
        print(f"ERROR: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
