"""Tests for the conversion-matrix interface probe (issue #89). No simulator.

Covers the known-answer control math, each sabotage failing it, the status
logic and the deck/record plumbing. From the repo root:

    python3 -m pytest sim/mixer-cm-interface-probe/tests -q
    python3 -m unittest discover -s sim/mixer-cm-interface-probe/tests   # stdlib only
"""

from __future__ import annotations

import cmath
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cmprobe as C  # noqa: E402
import fakelog  # noqa: E402
import run_probe as R  # noqa: E402


def matrix(**kw):
    parsed = C.parse_log(fakelog.stdout(fakelog.marks(**kw.pop("mk", {})), **kw), "")
    return C.build_matrix(parsed, R.REFERENCES), parsed


class ClosedForm(unittest.TestCase):
    def test_ideal_mixer_transfers(self):
        gw, gi = C.ideal_transfers(1.0, 1.0, 30.0)
        self.assertAlmostEqual(abs(gw), 0.5)
        self.assertAlmostEqual(abs(gi), 0.5)
        self.assertAlmostEqual(math.degrees(cmath.phase(gw)), -30.0)
        self.assertAlmostEqual(math.degrees(cmath.phase(gi)), 30.0)

    def test_phasor_integral_roundtrip(self):
        x = 0.3 - 0.2j
        c, s = C.integrals_from_phasor(x, 40e-9)
        self.assertAlmostEqual(abs(C.phasor_from_integrals(c, s, 40e-9) - x), 0.0, places=15)

    def test_image_enters_conjugated(self):
        # sin(wt+ph)*sin(wLO t+th) at w = wLO - wIF has IF phasor (a/2) e^{+j(th-ph)}
        gw, gi = C.ideal_transfers()
        p = C.tone_phasor(1.0, C.PH_L_DEG)
        x = gi * p.conjugate()
        self.assertAlmostEqual(math.degrees(cmath.phase(x)), C.CTL_TH_DEG - C.PH_L_DEG)

    def test_direct_time_domain_check_of_the_closed_form(self):
        # Brute-force the same projection numerically for the wanted sideband.
        n, t0, t1 = 400000, C.WINDOW[0], C.WINDOW[1]
        dt = (t1 - t0) / n
        wlo, wif = 2 * math.pi * C.F_LO, 2 * math.pi * C.F_IF
        th, ph = math.radians(C.CTL_TH_DEG), math.radians(C.PH_U_DEG)
        ic = is_ = 0.0
        for i in range(n):
            t = t0 + (i + 0.5) * dt
            y = C.CTL_K * math.sin(wlo * t + th) * C.A_TONE * math.sin((wlo + wif) * t + ph)
            ic += y * math.cos(wif * t) * dt
            is_ += y * math.sin(wif * t) * dt
        x = C.phasor_from_integrals(ic, is_, t1 - t0)
        gw, _ = C.ideal_transfers()
        self.assertAlmostEqual(abs(x - gw * C.tone_phasor(C.A_TONE, C.PH_U_DEG)), 0.0, delta=1e-7)


class KnownAnswerControl(unittest.TestCase):
    def test_unsabotaged_control_passes(self):
        res = C.evaluate_control(C.synth_control_marks())
        self.assertTrue(res["pass"], res)

    def test_each_sabotage_fails(self):
        want = {"gain": ("wanted", "image"), "drop_image": ("image",), "image_sign": ("image",),
                "wrong_lo": ("wanted", "image", "frequency_null")}
        for name, bad in want.items():
            with self.subTest(sabotage=name):
                res = C.evaluate_control(C.synth_control_marks(name))
                self.assertFalse(res["pass"])
                failed = {k for k, v in res["checks"].items() if not v["pass"]}
                self.assertTrue(set(bad) <= failed, (name, failed))

    def test_sabotages_cover_every_declared_mode(self):
        self.assertEqual(set(C.SABOTAGES), {"gain", "drop_image", "image_sign", "wrong_lo"})

    def test_sabotage_override_reaches_the_deck(self):
        deck = R.compose_deck("/m/lib.lib", "image_sign")
        self.assertIn("SABOTAGE (--sabotage image_sign)", deck)
        self.assertIn(".param cimg=-1", deck)
        self.assertNotIn("SABOTAGE", R.compose_deck("/m/lib.lib"))

    def test_missing_mark_is_a_parse_defect_not_a_pass(self):
        mk = C.synth_control_marks()
        del mk["x_ctl_u_c"]
        with self.assertRaises(C.ProbeError):
            C.evaluate_control(mk)


class MatrixAndStatus(unittest.TestCase):
    def test_pinned_like_log_is_blocked_with_transfers_demonstrated(self):
        m, parsed = matrix()
        self.assertEqual(m["wanted_sideband_transfer"]["state"], "demonstrated")
        self.assertEqual(m["image_sideband_transfer"]["state"], "demonstrated")
        self.assertEqual(m["lo_period_trajectory"]["state"], "demonstrated")
        self.assertEqual(m["noise_intensity_per_mechanism"]["state"], "unsupported")
        self.assertEqual(m["noise_covariance_ib_ic"]["state"], "unsupported")
        self.assertEqual(C.decide_status(True, m)[0], C.S_BLOCKED)
        self.assertEqual(set(m), set(C.INTERFACES))

    def test_failed_control_blocks_the_transfer_claim(self):
        for name in C.SABOTAGES:
            with self.subTest(sabotage=name):
                m, _ = matrix(mk={"sabotage": name})
                self.assertEqual(m["wanted_sideband_transfer"]["state"], "unknown")
                self.assertEqual(m["image_sideband_transfer"]["state"], "unknown")

    def test_nonlinear_dut_is_not_demonstrated(self):
        m, _ = matrix(mk={"dut_nonlinear": 0.1})
        self.assertEqual(m["wanted_sideband_transfer"]["state"], "unknown")

    def test_unsettled_orbit_is_unknown(self):
        m, _ = matrix(mk={"settled": False})
        self.assertEqual(m["lo_period_trajectory"]["state"], "unknown")
        self.assertEqual(m["wanted_sideband_transfer"]["state"], "unknown")
        self.assertEqual(m["image_sideband_transfer"]["state"], "unknown")
        self.assertIn("not settled", m["wanted_sideband_transfer"]["note"])

    def test_periodic_noise_commands_present_leaves_noise_unresolved(self):
        m, _ = matrix(pss_missing=False, pnoise_missing=False)
        self.assertEqual(m["noise_intensity_per_mechanism"]["state"], "unknown")

    def test_dut_response_subtracts_the_baseline(self):
        m, parsed = matrix()
        g = m["wanted_sideband_transfer"]["probe_marks"]
        self.assertAlmostEqual(g["gain_magnitude"], abs(fakelog.DUT_GW), places=6)
        self.assertAlmostEqual(g["gain_phase_deg"], 177.0, places=3)
        gi = m["image_sideband_transfer"]["probe_marks"]
        self.assertAlmostEqual(gi["gain_magnitude"], abs(fakelog.DUT_GI), places=6)

    def test_status_vocabulary_has_no_method_validation(self):
        self.assertNotIn("METHOD_VALIDATION", C.STATUSES)
        for tool_ok in (True, False):
            st, _ = C.decide_status(tool_ok, matrix()[0] if tool_ok else None)
            self.assertNotEqual(st, "METHOD_VALIDATION")

    def test_all_states_map_to_statuses(self):
        m, _ = matrix()
        for k in m:
            m[k]["state"] = "demonstrated"
        self.assertEqual(C.decide_status(True, m)[0], C.S_DEMONSTRATED)
        m["noise_covariance_ib_ic"]["state"] = "unknown"
        self.assertEqual(C.decide_status(True, m)[0], C.S_PARTIAL)
        m["noise_covariance_ib_ic"]["state"] = "unsupported"
        self.assertEqual(C.decide_status(True, m)[0], C.S_BLOCKED)
        self.assertEqual(C.decide_status(False, None)[0], C.S_CAPABILITY_UNAVAILABLE)

    def test_incomplete_log_is_a_parse_defect(self):
        parsed = C.parse_log(fakelog.stdout(fakelog.marks(), done=False), "")
        with self.assertRaises(C.ProbeError):
            C.build_matrix(parsed, R.REFERENCES)


class Plumbing(unittest.TestCase):
    def test_deck_has_no_unsubstituted_tokens_and_inlines_control(self):
        deck = R.compose_deck("/m/lib.lib")
        for tok in ("{model_lib}", "{placeholder}", "{runs}", "{control}"):
            self.assertNotIn(tok, deck)
        self.assertIn("Bcm cout 0", deck)
        for run in C.RUNS:
            self.assertIn(f"run {run}:", deck)
        self.assertIn("tran 1p 1.2e-07 0 1p", deck)

    def test_reparse_roundtrip_from_a_frozen_log(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "stdout.txt").write_text(fakelog.stdout(fakelog.marks()))
            (d / "stderr.txt").write_text("")
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(R.main(["--reparse", str(d)]), 0)
            out = json.loads(buf.getvalue())
            self.assertEqual(out["status"], "INTERFACES_BLOCKED")
            self.assertTrue(out["control"]["pass"])

    def test_placeholder_is_read_only_input(self):
        self.assertTrue(R.PLACEHOLDER.is_file())
        self.assertIn(str(R.PLACEHOLDER), R.compose_deck("/m/lib.lib"))


if __name__ == "__main__":
    unittest.main()
