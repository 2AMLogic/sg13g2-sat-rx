"""Simulator-free tests for ci_assert.assess (issue #104): fake logs only."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cmprobe as C  # noqa: E402
import fakelog  # noqa: E402
import ci_assert as A  # noqa: E402

PIN = 46
INFO = {"path": "/x/ngspice", "version": "ngspice-46", "major": 46}


def log(sab=None, **kw):
    return fakelog.stdout(fakelog.marks(sab), **kw)


class Assess(unittest.TestCase):
    def test_happy_path_positive_and_all_sabotages(self):
        self.assertEqual(A.assess("pos", None, INFO, PIN, log(), ""), [])
        for sab in C.SABOTAGES:
            self.assertEqual(A.assess(sab, sab, INFO, PIN, log(sab), ""), [], sab)

    def test_sabotage_set_matches_declared_modes(self):
        self.assertEqual(set(A.EXPECTED_FAILING), set(C.SABOTAGES))

    def test_missing_executable_fails(self):
        self.assertTrue(A.assess("pos", None, None, PIN, log(), ""))

    def test_wrong_version_fails(self):
        bad = dict(INFO, major=45)
        self.assertTrue(A.assess("pos", None, bad, PIN, log(), ""))
        self.assertTrue(A.assess("gain", "gain", bad, PIN, log("gain"), ""))

    def test_broken_positive_control_fails(self):
        self.assertTrue(A.assess("pos", None, INFO, PIN, log("gain"), ""))

    def test_missing_control_marks_fail(self):
        mk = fakelog.marks()
        del mk["x_ctl_u_c"]
        for sab in (None, "gain"):
            self.assertTrue(A.assess("x", sab, INFO, PIN, fakelog.stdout(mk), ""))

    def test_empty_or_incomplete_log_fails(self):
        self.assertTrue(A.assess("pos", None, INFO, PIN, "", ""))
        self.assertTrue(A.assess("pos", None, INFO, PIN, log(done=False), ""))

    def test_nonfinite_measurement_fails(self):
        mk = fakelog.marks()
        mk["x_ctl_u_c"] = float("nan")
        self.assertTrue(A.assess("pos", None, INFO, PIN, fakelog.stdout(mk), ""))

    def test_unexpectedly_passing_sabotage_fails(self):
        for sab in C.SABOTAGES:
            probs = A.assess(sab, sab, INFO, PIN, log(), "")  # unsabotaged marks
            self.assertTrue(probs and "PASSING" in probs[0], sab)

    def test_sabotage_failing_on_wrong_check_fails(self):
        # a log failing only the linearity/superposition bookkeeping is not a measured failure
        mk = fakelog.marks()
        mk["x_ctl_u2_c"] *= 1.5
        mk["x_ctl_u2_s"] *= 1.5
        probs = A.assess("image_sign", "image_sign", INFO, PIN, fakelog.stdout(mk), "")
        self.assertTrue(probs)


if __name__ == "__main__":
    unittest.main()
