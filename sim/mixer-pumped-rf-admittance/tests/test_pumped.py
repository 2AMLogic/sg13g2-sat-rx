"""Tests for the pumped RF-port admittance probe (issue #111). No simulator.

Phasor extraction against the passive RC and ideal modulated known answers, the
wrong-current-sign / omitted-image-coupling / no-baseline sabotages failing them
numerically, the DUT classification (scalar / matrix / inconclusive), the deck mark
schema and the CI assertion's failure modes. From the repo root:

    python3 -m pytest sim/mixer-pumped-rf-admittance/tests -q
    python3 -m unittest discover -s sim/mixer-pumped-rf-admittance/tests   # stdlib only
"""

from __future__ import annotations

import cmath
import json
import math
import re
import sys
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import ci_assert as A  # noqa: E402
import pumped as P  # noqa: E402
import run_probe as R  # noqa: E402

THR = P.load_thresholds()
DUT_SCALAR = {"uu": 0.010 + 0.020j, "ul": 0.0002 * cmath.exp(1j), "lu": 0.0002 * cmath.exp(-0.5j),
              "ll": 0.012 + 0.018j}
DUT_MATRIX = {"uu": 0.010 + 0.020j, "ul": 0.004 * cmath.exp(1j), "lu": 0.003 * cmath.exp(-0.5j),
              "ll": 0.012 + 0.018j}


def evaluate(mk: dict, sabotage=None) -> dict:
    return P.evaluate(P.parse_log(P.synth_stdout(mk), ""), THR, sabotage)


def failing(ev: dict) -> set:
    return {n for n, c in ev["controls"]["checks"].items() if not c["pass"]}


class Phasors(unittest.TestCase):
    def test_integral_roundtrip(self):
        x = 0.3 - 0.7j
        self.assertAlmostEqual(P.phasor_from_integrals(*P.integrals_from_phasor(x, 4e-8), 4e-8), x)

    def test_sin_tone_is_cosine_referenced(self):
        # a*sin(wt + phi) = Re(a e^{j(phi - 90)} e^{jwt})
        p = P.sin_tone_phasor(2.0, 30.0)
        for t in (0.0, 0.1, 0.37):
            self.assertAlmostEqual((p * cmath.exp(1j * t)).real, 2.0 * math.sin(t + math.radians(30)))

    def test_windows_hold_integer_periods(self):
        for win, (a, b) in P.WINDOWS.items():
            for f in (P.F_U, P.F_L, P.F_LO):
                n = (b - a) * f
                self.assertAlmostEqual(n, round(n), places=6, msg=f"{win} {f}")

    def test_cond2(self):
        self.assertAlmostEqual(P.cond2(1, 0, 0, 1), 1.0)
        self.assertAlmostEqual(P.cond2(1, 0, 0, 10), 10.0)
        self.assertAlmostEqual(P.cond2(1j, 0, 0, -10), 10.0)
        self.assertEqual(P.cond2(1, 2, 2, 4), float("inf"))

    def test_solve2(self):
        x, y = P.solve2(1, 1j, 2, -1, 1 + 1j, 3)
        self.assertAlmostEqual(1 * x + 1j * y, 1 + 1j)
        self.assertAlmostEqual(2 * x - y, 3)
        with self.assertRaises(P.ProbeError):
            P.solve2(1, 2, 2, 4, 0, 0)


class KnownAnswers(unittest.TestCase):
    def test_rc_closed_form(self):
        y = P.rc_expected()
        z = 1 / y["uu"]
        self.assertAlmostEqual(z.real, 25.0)
        self.assertAlmostEqual(z.imag, -1 / (2 * math.pi * P.F_U * 1e-12))
        self.assertEqual(y["ul"], 0)

    def test_modulated_closed_form(self):
        y = P.md_expected()
        self.assertAlmostEqual(abs(y["ul"]), 0.006)
        self.assertAlmostEqual(math.degrees(cmath.phase(y["lu"])), 40.0)
        self.assertGreater(P.kappa(y), 0.2)  # strong coupling: the matrix fixture

    def test_controls_pass_on_closed_form(self):
        ev = evaluate(P.synth_marks())
        self.assertTrue(ev["controls"]["pass"], failing(ev))
        self.assertIsNone(ev["dut"])
        fx = ev["controls"]["fixtures"]
        self.assertEqual(fx["rc"]["classification"], P.S_SCALAR)
        self.assertEqual(fx["md"]["classification"], P.S_MATRIX)

    def test_extraction_uses_measured_not_applied_voltage(self):
        # The RC port voltage differs from the applied EMF (50 ohm source): the extraction must
        # still recover the closed form, so it cannot be using the EMF.
        mk = P.synth_marks()
        v = P.raw_phasor(mk, "rc", "v", "p1", "w", "u")
        self.assertGreater(abs(v - P.sin_tone_phasor(P.A_EMF, P.PH_U_DEG)), 1e-4)
        y = P.extract(mk, "rc", "primary")["y"]
        self.assertAlmostEqual(abs(y["uu"] / P.rc_expected()["uu"] - 1), 0, places=9)


class Sabotages(unittest.TestCase):
    def setUp(self):
        self.mk = P.synth_marks()

    def test_wrong_current_sign_fails_by_180_degrees(self):
        ev = evaluate(self.mk, "current_sign")
        c = ev["controls"]["checks"]
        self.assertFalse(c["rc.uu"]["pass"])
        self.assertAlmostEqual(c["rc.uu"]["phase_err_deg"], 180.0, places=6)
        self.assertAlmostEqual(c["rc.uu"]["mag_rel_err"], 0.0, places=9)  # a sign, not a gain error
        self.assertTrue(failing(ev) & P.EXPECTED_FAILING["current_sign"])

    def test_omitted_image_coupling_fails_numerically(self):
        ev = evaluate(self.mk, "omit_image")
        c = ev["controls"]["checks"]
        self.assertAlmostEqual(c["md.ul"]["mag_rel_err"], 1.0)  # coupling reported as zero
        # the scalar I/V at phase p1 is off by the coupling term (|Y_ul|/|Y_uu| ~ 0.26)
        err = abs(complex(*c["md.uu"]["measured"]) / complex(*c["md.uu"]["expected"]) - 1)
        self.assertGreater(err, 0.1)
        self.assertFalse(c["md.uu"]["pass"])
        # the LTI RC fixture is insensitive to the omission: the modulated fixture is what catches it
        self.assertTrue(c["rc.uu"]["pass"])

    def test_no_baseline_fails(self):
        ev = evaluate(self.mk, "no_baseline")
        self.assertFalse(ev["controls"]["checks"]["md.uu"]["pass"])
        self.assertTrue(failing(ev) & P.EXPECTED_FAILING["no_baseline"])

    def test_every_sabotage_fails_an_expected_check(self):
        for sab in P.SABOTAGES:
            with self.subTest(sab=sab):
                ev = evaluate(self.mk, sab)
                self.assertFalse(ev["controls"]["pass"])
                self.assertTrue(failing(ev) & P.EXPECTED_FAILING[sab])


class DutClassification(unittest.TestCase):
    def test_scalar_adequate(self):
        ev = evaluate(P.synth_marks(DUT_SCALAR))
        self.assertEqual(ev["status"], P.S_SCALAR, ev["reasons"])
        self.assertLess(ev["dut"]["kappa"], 0.05)

    def test_matrix_required(self):
        ev = evaluate(P.synth_marks(DUT_MATRIX))
        self.assertEqual(ev["status"], P.S_MATRIX, ev["reasons"])
        self.assertGreater(ev["dut"]["scalar_phase_spread"], 0.05)  # model-free discriminator agrees

    def test_matrix_recovered_exactly(self):
        ev = evaluate(P.synth_marks(DUT_MATRIX))
        for e in P.ELEMENTS:
            self.assertAlmostEqual(abs(P.from_cplx(ev["dut"]["y"][e]) - DUT_MATRIX[e]), 0, places=12)

    def test_straddling_kappa_is_inconclusive(self):
        y = dict(DUT_SCALAR, ul=0.05 * abs(DUT_SCALAR["uu"]) * cmath.exp(0.3j))
        ev = evaluate(P.synth_marks(y, perturb={"refined": 0.0001}))
        self.assertGreater(ev["dut"]["kappa_uncertainty"], 0)
        self.assertEqual(ev["status"], P.S_INCONCLUSIVE, ev["reasons"])
        self.assertIn("straddles", ev["reasons"][0])

    def test_each_convergence_failure_is_inconclusive(self):
        for s, name in (("halved", "halving"), ("extended", "window"), ("refined", "timestep")):
            with self.subTest(check=name):
                ev = evaluate(P.synth_marks(DUT_MATRIX, perturb={s: 0.002}))
                self.assertFalse(ev["dut"]["checks"][name]["pass"])
                self.assertEqual(ev["status"], P.S_INCONCLUSIVE)
                self.assertIn(name, ev["reasons"][0])

    def test_weak_response_against_baseline_is_inconclusive(self):
        big = {"u": (1e-3 + 0j, 1e-4 + 0j), "l": (1e-3 + 0j, 1e-4 + 0j)}
        ev = evaluate(P.synth_marks(DUT_SCALAR, baseline={"dut": big}))
        self.assertFalse(ev["dut"]["checks"]["response_to_baseline"]["pass"])
        self.assertEqual(ev["status"], P.S_INCONCLUSIVE)

    def test_failed_controls_make_dut_inconclusive(self):
        wrong_rc = {e: v * 1.1 for e, v in P.rc_expected().items()}
        ev = evaluate(P.synth_marks(DUT_SCALAR, rc_y=wrong_rc))
        self.assertFalse(ev["controls"]["pass"])
        self.assertEqual(ev["status"], P.S_INCONCLUSIVE)
        self.assertIn("not qualified", ev["reasons"][0])

    def test_ill_conditioned_phases_are_inconclusive(self):
        st, why = P.classify(0.0, 0.0, False, THR, failed=["conditioning"])
        self.assertEqual(st, P.S_INCONCLUSIVE)
        self.assertIn("conditioning", why[0])

    def test_classify_never_returns_a_compliance_word(self):
        for k in (0.0, 0.05, 0.5):
            st, why = P.classify(k, 0.001, True, THR)
            self.assertIn(st, P.STATUSES)
            self.assertNotRegex(" ".join(why).lower(), r"complian|row 5|pass(es)? row")


class Parsing(unittest.TestCase):
    def test_incomplete_log(self):
        with self.assertRaises(P.ProbeError):
            P.evaluate(P.parse_log(P.synth_stdout(P.synth_marks(), done=False), ""), THR)

    def test_missing_mark(self):
        mk = P.synth_marks()
        mk.pop(P.mark_key("rc", "v", "p2", "w", "l", "s"))
        with self.assertRaises(P.ProbeError):
            evaluate(mk)

    def test_non_finite_mark_is_missing(self):
        parsed = P.parse_log("MARK a=nan b=1.5 c=\nMARK done\n", "")
        self.assertIsNone(parsed["marks"]["a"])
        self.assertIsNone(parsed["marks"]["c"])
        self.assertEqual(parsed["marks"]["b"], 1.5)


class DeckSchema(unittest.TestCase):
    @staticmethod
    def deck_marks(deck: str) -> set:
        return set(re.findall(r"(\w+_[cs])=\$&", deck))

    def test_controls_only_deck_has_exactly_the_control_marks(self):
        deck = R.compose_deck(None, with_dut=False)
        code = "\n".join(ln for ln in deck.splitlines() if not ln.lstrip().startswith("*"))
        self.assertNotIn("Ipu", code)
        self.assertNotIn("alterparam vrf", code)
        self.assertNotIn(".include", code)  # controls inlined: deck.spice alone reproduces the run
        self.assertEqual(self.deck_marks(deck), set(P.synth_marks()))

    def test_full_deck_marks_match_the_extraction_schema(self):
        deck = R.compose_deck("/pdk/cornerHBT.lib", with_dut=True)
        self.assertIn(str(R.PLACEHOLDER), deck)
        self.assertIn("alterparam vrf=0", deck)
        self.assertIn("Vpsense pj prf DC 0", deck)
        self.assertEqual(self.deck_marks(deck), set(P.synth_marks(DUT_SCALAR)))

    def test_refined_runs_halve_the_step(self):
        deck = R.compose_deck(None, with_dut=False)
        self.assertIn("tran 5e-13 1.2e-07 0 5e-13", deck)
        self.assertIn("tran 1e-12 1.6e-07 0 1e-12", deck)


class Thresholds(unittest.TestCase):
    def test_every_value_is_justified(self):
        data = json.loads(P.THRESHOLDS_PATH.read_text())
        self.assertEqual(set(data["values"]), set(data["justification"]))
        for k, v in data["values"].items():
            self.assertGreater(v, 0, k)
            self.assertGreater(len(data["justification"][k]), 40, k)

    def test_tolerances_separate_sabotage_signatures(self):
        # omitted coupling on the modulated fixture is ~0.26; tolerances are far below it
        self.assertLess(THR["control_mag_rel_tol"] * 10, P.kappa(P.md_expected()))
        self.assertLess(THR["control_null_rel_tol"], THR["kappa_scalar_max"])


class Rendering(unittest.TestCase):
    def test_record_markdown_carries_scope_markers(self):
        ev = evaluate(P.synth_marks(DUT_MATRIX))
        env = {"ngspice": {"path": "/x", "version": "ngspice-46", "sha256": "a" * 64},
               "pdk": {"path": "/p", "fetched_version": "0.3.0", "device": "npn13G2",
                       "sha256": {"cornerHBT.lib": "a" * 64, "sg13g2_hbt_mod.lib": "a" * 64}},
               "placeholder_sha256": "a" * 64, "pdk_artifact_sha256": "a" * 64,
               "git": {"commit": "abc", "dirty": False}, "host": "h"}
        md = R.render_md("20261010-000000-abcdef1", ev["status"], ev["reasons"], ev, THR,
                         {"file": "thresholds.json", "sha256": "b" * 64, "commit": "c" * 40}, env)
        for marker in R.SCOPE_MD_MARKERS:
            self.assertIn(marker, md)
        self.assertIn(f"- **Status: {P.S_MATRIX}**", md)
        self.assertIn("probe-logs/20261010-000000-abcdef1/", md)
        un = R.render_unavailable_md("20261010-000000-abcdef1", P.S_UNAVAILABLE, "no ngspice")
        for marker in R.SCOPE_MD_MARKERS:
            self.assertIn(marker, un)


class CiAssert(unittest.TestCase):
    INFO = {"major": 46, "version": "ngspice-46"}

    def test_good_log_passes(self):
        self.assertEqual(A.assess(self.INFO, 46, P.synth_stdout(P.synth_marks()), "", THR), [])

    def test_missing_or_wrong_executable(self):
        self.assertIn("not found", A.assess(None, 46, "", "", THR)[0])
        self.assertIn("not the pinned", A.assess({"major": 45}, 46, "", "", THR)[0])

    def test_incomplete_deck(self):
        self.assertIn("MARK done", A.assess(self.INFO, 46, P.synth_stdout(P.synth_marks(), done=False), "", THR)[0])

    def test_broken_control_fails(self):
        wrong = {e: v * 1.1 for e, v in P.rc_expected().items()}
        probs = A.assess(self.INFO, 46, P.synth_stdout(P.synth_marks(rc_y=wrong)), "", THR)
        self.assertTrue(any("positive control" in p for p in probs))

    def test_non_discriminating_sabotage_fails(self):
        # if a sabotage left every one of its expected checks passing, CI must say so
        with mock.patch.dict(P.EXPECTED_FAILING, {"no_baseline": {"rc.uu"}}):
            probs = A.assess(self.INFO, 46, P.synth_stdout(P.synth_marks()), "", THR)
        self.assertTrue(any("no_baseline" in p and "cannot discriminate" in p for p in probs), probs)

if __name__ == "__main__":
    unittest.main()
