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


class IntegrityGate(unittest.TestCase):
    """Issue #107: the PDK model-integrity gate runs before the simulator. No real simulator or
    PDK is touched: shutil.which / ngspice_info / pdk_info / pdk_integrity / git_info are
    stubbed, RECORDS / PROBE_LOGS / HERE point into a temp dir, and subprocess.run is replaced
    by a recorder so the tests can assert whether the simulator was invoked."""

    SHA = "a" * 64

    def setUp(self):
        import contextlib
        from unittest import mock
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.sim_calls = []

        real_run = __import__("subprocess").run

        def fake_run(cmd, *a, **kw):
            if not cmd or cmd[0] != "/x/ngspice":  # e.g. platform.platform() -> `uname -p`
                return real_run(cmd, *a, **kw)
            self.sim_calls.append(cmd)
            return __import__("subprocess").CompletedProcess(cmd, 0, fakelog.stdout(fakelog.marks()), "")

        self.integ = {"gate": "stub", "ok": True, "problems": [], "notes": ["models match"]}
        major = R.pinned_major()
        patches = [
            mock.patch.object(R, "RECORDS", self.tmp / "records"),
            mock.patch.object(R, "PROBE_LOGS", self.tmp / "probe-logs"),
            mock.patch.object(R, "HERE", self.tmp),
            mock.patch.object(R.shutil, "which", lambda name: "/x/ngspice"),
            mock.patch.object(R, "ngspice_info", lambda exe: {"path": exe, "version": f"ngspice-{major}",
                                                              "major": major, "sha256": self.SHA}),
            mock.patch.object(R, "pdk_info", lambda: {
                "path": "/pdk", "fetched_version": "0.3.0", "model_lib": "/pdk/m/cornerHBT.lib",
                "section": "hbt_typ", "sha256": {"cornerHBT.lib": self.SHA, "sg13g2_hbt_mod.lib": self.SHA},
                "device": "npn13G2"}),
            mock.patch.object(R, "pdk_integrity", lambda banner: dict(self.integ)),
            mock.patch.object(R, "git_info", lambda: {"commit": "abcdef1" + "0" * 33, "dirty": False}),
            mock.patch.object(R.subprocess, "run", fake_run),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        (self.tmp / "records").mkdir()
        (self.tmp / "probe-logs").mkdir()
        self._redirect = contextlib.redirect_stdout

    def run_main(self, *argv):
        import io
        buf = io.StringIO()
        with self._redirect(buf):
            rc = R.main(list(argv))
        return rc, buf.getvalue()

    def fail_gate(self):
        self.integ = {"gate": "stub", "ok": False, "problems": ["cornerHBT.lib sha256 mismatch"],
                      "notes": []}

    @staticmethod
    def first_json(out: str) -> dict:
        return json.JSONDecoder().raw_decode(out[out.index("{"):])[0]

    def test_pass_path_runs_the_simulator_and_records_the_gate(self):
        rc, out = self.run_main("--no-write")
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.sim_calls), 1)
        self.assertEqual(self.sim_calls[0][1:], ["-b", "deck.spice"])
        self.assertIn("Model integrity gate (`sim/harness/pdkartifact.py`, run before the simulator): OK; "
                      "models match", out)
        self.assertNotIn("CAPABILITY_UNAVAILABLE", out)
        self.assertEqual(list((self.tmp / "records").iterdir()), [])

    def test_pass_path_write_carries_gate_outcome_in_environment(self):
        rc, _ = self.run_main()
        self.assertEqual(rc, 0)
        (js,) = sorted((self.tmp / "records").glob("*.json"))
        rec = json.loads(js.read_text())
        self.assertEqual(rec["environment"]["pdk_integrity"]["ok"], True)
        self.assertNotEqual(rec["status"], "CAPABILITY_UNAVAILABLE")

    def test_fail_path_no_write_is_capability_unavailable_and_runs_nothing(self):
        self.fail_gate()
        rc, out = self.run_main("--no-write")
        self.assertEqual(rc, 0)
        self.assertEqual(self.sim_calls, [], "the simulator must not run when the gate fails")
        rec = self.first_json(out)
        self.assertEqual(rec["status"], "CAPABILITY_UNAVAILABLE")
        self.assertIn("PDK model integrity gate failed", rec["failed_check"])
        self.assertIn("cornerHBT.lib sha256 mismatch", rec["failed_check"])
        self.assertEqual(rec["reasons"], [R.INTEGRITY_REASON])
        self.assertNotIn("simulator not available", " ".join(rec["reasons"]))
        for key in ("interface_matrix", "controls", "probe_logs"):
            self.assertNotIn(key, rec)
        self.assertEqual(list((self.tmp / "records").iterdir()), [])
        self.assertEqual(list((self.tmp / "probe-logs").iterdir()), [])
        self.assertFalse((self.tmp / "_build").exists())

    def test_fail_path_write_emits_only_the_unavailable_pair(self):
        self.fail_gate()
        rc, _ = self.run_main()
        self.assertEqual(rc, 0)
        self.assertEqual(self.sim_calls, [])
        names = sorted(p.name for p in (self.tmp / "records").iterdir())
        self.assertEqual(len(names), 2)
        self.assertTrue(all("-CAPABILITY_UNAVAILABLE." in n for n in names), names)
        self.assertEqual(list((self.tmp / "probe-logs").iterdir()), [])
        md = next((self.tmp / "records").glob("*.md")).read_text()
        self.assertIn("Failed check: PDK model integrity gate failed", md)
        self.assertIn("model-integrity outcome", md)
        self.assertNotIn("missing-tool", md)

    def test_allow_unpinned_bypasses_the_gate_but_never_writes(self):
        self.fail_gate()
        rc, _ = self.run_main("--allow-unpinned")
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.sim_calls), 1)
        self.assertEqual(list((self.tmp / "records").iterdir()), [])


class RenderBackwardCompat(unittest.TestCase):
    """render_md must accept an env written before the gate existed (no 'pdk_integrity')."""

    def env(self, **extra):
        sha = "a" * 64
        env = {"host": "h", "git": {"commit": "c" * 40, "dirty": False}, "placeholder_sha256": sha,
               "pdk_artifact_sha256": sha,
               "ngspice": {"path": "/x", "version": "ngspice-46", "sha256": sha},
               "pdk": {"path": "/pdk", "fetched_version": "0.3.0",
                       "sha256": {"cornerHBT.lib": sha, "sg13g2_hbt_mod.lib": sha}, "device": "npn"}}
        env.update(extra)
        return env

    def render(self, env):
        m, parsed = matrix()
        ctl = C.evaluate_control(parsed["marks"])
        status, reasons = C.decide_status(True, m)
        return R.render_md("rid", status, reasons, m, ctl, env)

    def test_env_without_gate_renders_and_omits_the_line(self):
        md = self.render(self.env())
        self.assertNotIn("Model integrity gate", md)
        self.assertIn("## Provenance", md)

    def test_env_with_gate_ok_and_failed(self):
        ok = self.render(self.env(pdk_integrity={"ok": True, "problems": [], "notes": ["n1"]}))
        self.assertIn("run before the simulator): OK; n1\n", ok)
        bad = self.render(self.env(pdk_integrity={"ok": False, "problems": ["p1"], "notes": []}))
        self.assertIn("run before the simulator): FAILED; p1\n", bad)

    def test_default_unavailable_text_is_unchanged(self):
        md = R.render_unavailable_md("rid", "CAPABILITY_UNAVAILABLE", "x")
        self.assertIn("This status is a missing-tool\n  outcome only; it never establishes", md)
        self.assertIn("host that has the pinned executable supersedes", md)


if __name__ == "__main__":
    unittest.main()
