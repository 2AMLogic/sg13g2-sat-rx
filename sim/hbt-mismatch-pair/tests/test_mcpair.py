"""Closed-form tests for the hbt-mismatch-pair Monte Carlo method probe.

No simulator, no PDK, no klt: report ingestion, statistics, the known-answer
gates, the sabotage negative controls and the record-side helpers are all
exercised on synthetic reports shaped exactly like the klt ones (see the
fixture builder).
"""

from __future__ import annotations

import json
import math
import unittest

import mcpair as M


# ---------------------------------------------------------------------------
# synthetic klt report fixtures
# ---------------------------------------------------------------------------


def make_unit(process: str, sample_index: int, ratio: float, off: float,
              ic1: float | None = None, status: str = "pass") -> dict:
    if ic1 is None:
        ic1 = 5.2e-4 * ratio
    return {
        "corner_id": f"{process}/novdd/27C/mc{sample_index}",
        "process": process,
        "status": status,
        "runtime_s": 2.0,
        "measurements": [
            {"name": M.SENTINEL_NAME, "value": 2.5, "status": "pass"},
        ],
        "diagnostics": [],
        "artifacts": {"log": f"{process}_{sample_index}.log", "raw": None, "deck": None},
        "monte_carlo": {
            "sample_index": sample_index,
            "seed": 1000 + sample_index,
            "process_seed": 2000 + sample_index,
            "mismatch_seed": 3000 + sample_index,
        },
        "_log_text": (f"m_ic1 = {ic1:.10e}\n"
                      f"m_ic2 = {ic1 / ratio:.10e}\n"
                      f"m_ratio = {ratio:.10e}\n"
                      f"m_off = {off:.10e}\n"),
    }


def make_report(n: int = 6, *, mismatch_ratio=lambda i: 1.0 + 0.14 * ((i % 3) - 1),
                stat_ratio=lambda i: 1.0, nominal_ratio=lambda i: 1.0) -> dict:
    """A report with `n` samples per corner; per-corner ratio callouts above."""
    corners = []
    for i in range(n):
        corners.append(make_unit("hbt_typ_mismatch", i, mismatch_ratio(i), 0.02 * ((i % 3) - 1)))
    for i in range(n):
        corners.append(make_unit("hbt_typ_stat", i, stat_ratio(i), 0.0, ic1=5.2e-4 + 1e-6 * i))
    for i in range(n):
        corners.append(make_unit("hbt_typ", i, nominal_ratio(i), 0.0))
    return {"status": "pass", "corners": corners}


def ingest(report: dict, n: int, label: str = "fixture") -> dict[str, list[dict]]:
    logs = {(c["process"], c["monte_carlo"]["sample_index"]): c["_log_text"]
            for c in report["corners"]}
    legs = M.samples_from_report(report, expected_n=n, label=label)
    M.attach_log_measurements(
        legs, read_text=lambda u: logs.get((u["process"], u["sample_index"])))
    return legs


def healthy_legs(n: int = 6) -> dict[str, list[dict]]:
    return ingest(make_report(n), n)


# ---------------------------------------------------------------------------
# request shape
# ---------------------------------------------------------------------------


class TestRequestShape(unittest.TestCase):
    def test_request_carries_monte_carlo_and_corner_order(self):
        req = M.build_request("pair_body.spice", n=100, seed=186, backend="batch",
                              timeout_s=1800)
        self.assertEqual(req["monte_carlo"], {"n": 100, "seed": 186, "vary": "both"})
        self.assertEqual(req["corners"]["process"], list(M.CORNERS))
        self.assertEqual(req["corners"]["temperature_c"], [M.TEMPERATURE_C])
        self.assertEqual(req["netlist"], "pair_body.spice")
        self.assertTrue(req["options"]["keep_artifacts"])

    def test_corner_order_is_part_of_the_seed_contract(self):
        """The local agreement request must reuse the exact corner list: klt
        keys the per-sample seeds on corner_index."""
        self.assertEqual(M.CORNERS, ("hbt_typ_mismatch", "hbt_typ_stat", "hbt_typ"))

    def test_batch_request_declares_runner_version_check(self):
        req = M.build_request("b.spice", n=2, seed=1, backend="batch", timeout_s=10)
        self.assertEqual(req["batch"], {"runner_version_check": M.RUNNER_VERSION_CHECK_DEFAULT})

    def test_local_request_has_no_batch_block(self):
        req = M.build_request("b.spice", n=1, seed=1, backend="local", timeout_s=10)
        self.assertNotIn("batch", req)


# ---------------------------------------------------------------------------
# ingestion
# ---------------------------------------------------------------------------


class TestIngest(unittest.TestCase):
    def test_healthy_report_ingests_all_corners_and_samples(self):
        legs = healthy_legs(5)
        self.assertEqual(set(legs), set(M.CORNERS))
        for name, units in legs.items():
            self.assertEqual(len(units), 5)
            self.assertEqual([u["sample_index"] for u in units], [0, 1, 2, 3, 4])
            for u in units:
                self.assertEqual(set(M.MEASURE_NAMES) - set(u["measurements"]), set())

    def test_collapsed_mc_is_detected_not_averaged(self):
        report = make_report(6)
        report["corners"] = [c for c in report["corners"]
                             if c["process"] != "hbt_typ_mismatch"] + \
                            [make_unit("hbt_typ_mismatch", 0, 1.02, 0.01)]
        with self.assertRaises(M.ReportError) as ctx:
            M.samples_from_report(report, expected_n=6, label="collapsed")
        self.assertIn("collapsed", str(ctx.exception))

    def test_unit_without_sample_identity_is_refused(self):
        report = make_report(2)
        report["corners"][0]["monte_carlo"] = None
        with self.assertRaises(M.ReportError):
            M.samples_from_report(report, expected_n=2, label="noid")

    def test_missing_log_observable_is_refused(self):
        report = make_report(2)
        legs = M.samples_from_report(report, expected_n=2, label="x")
        for u in legs["hbt_typ_mismatch"]:
            u["_log_text"] = "m_ic1 = 1.0e-3\n"  # drops the rest
        with self.assertRaises(M.ReportError) as ctx:
            M.attach_log_measurements(legs, read_text=lambda u: u.pop("_log_text", None))
        self.assertIn("missing", str(ctx.exception))

    def test_nonfinite_report_value_never_reaches_the_statistics(self):
        report = make_report(2)
        legs = M.samples_from_report(report, expected_n=2, label="x")
        # "nan" does not match the finite-value regex -> the observable is
        # missing -> refused, never averaged over.
        legs["hbt_typ_mismatch"][0]["_log_text"] = (
            "m_ic1 = 1.0e-3\nm_ic2 = 1.0e-3\nm_ratio = nan\nm_off = 0.0\n")
        with self.assertRaises(M.ReportError):
            M.attach_log_measurements(legs, read_text=lambda u: u.pop("_log_text", None))


# ---------------------------------------------------------------------------
# statistics + gates
# ---------------------------------------------------------------------------


class TestGates(unittest.TestCase):
    def test_healthy_fixture_is_MC_METHOD_WORKS(self):
        ev = M.evaluate(batch=healthy_legs(8), rerun=healthy_legs(8), local=healthy_legs(1))
        self.assertEqual(ev["status"], "MC_METHOD_WORKS")
        g = ev["findings"]["gates"]
        self.assertTrue(g["nominal_exact"])
        self.assertTrue(g["stat_global_cancels"])
        self.assertTrue(g["mismatch_sampled"])
        self.assertEqual(g["reproducibility_max_rel"], 0.0)
        self.assertEqual(g["local_vs_batch_max_rel"], 0.0)

    def test_mismatch_sigma_is_in_the_card_order(self):
        legs = healthy_legs(9)
        ev = M.evaluate(batch=legs, rerun=None, local=None)
        vs = ev["findings"]["gates"]["mismatch_sigma_vs_card"]
        self.assertGreater(vs["sigma_ratio_measured"], 0.05)
        self.assertLess(vs["sigma_ratio_measured"], 0.30)
        self.assertAlmostEqual(vs["expected_ratio_sigma_order"], 0.10 * math.sqrt(2.0))

    def test_nominal_spread_is_a_control_failure(self):
        legs = healthy_legs(4)
        for u in legs["hbt_typ"]:
            u["measurements"]["m_ratio"] = 1.0 + 1e-3
        ev = M.evaluate(batch=legs, rerun=None, local=None)
        self.assertEqual(ev["status"], "MC_METHOD_CONTROL_FAIL")
        self.assertFalse(ev["findings"]["gates"]["nominal_exact"])

    def test_stat_corner_spread_is_a_control_failure(self):
        legs = healthy_legs(4)
        for i, u in enumerate(legs["hbt_typ_stat"]):
            u["measurements"]["m_ratio"] = 1.0 + (1e-3 if i % 2 else -1e-3)
        ev = M.evaluate(batch=legs, rerun=None, local=None)
        self.assertEqual(ev["status"], "MC_METHOD_CONTROL_FAIL")
        self.assertFalse(ev["findings"]["gates"]["stat_global_cancels"])

    def test_flat_mismatch_is_a_control_failure(self):
        legs = healthy_legs(4)
        for u in legs["hbt_typ_mismatch"]:
            u["measurements"]["m_ratio"] = 1.0
        ev = M.evaluate(batch=legs, rerun=None, local=None)
        self.assertEqual(ev["status"], "MC_METHOD_CONTROL_FAIL")
        self.assertFalse(ev["findings"]["gates"]["mismatch_sampled"])

    def test_rerun_difference_fails_reproducibility(self):
        good, bad = healthy_legs(4), healthy_legs(4)
        for u in bad["hbt_typ_mismatch"]:
            u["measurements"]["m_ratio"] *= 1.1
        ev = M.evaluate(batch=good, rerun=bad, local=None)
        self.assertEqual(ev["status"], "MC_METHOD_REPRODUCIBILITY_FAIL")
        self.assertGreater(ev["findings"]["gates"]["reproducibility_max_rel"], 0.1)

    def test_local_disagreement_fails_agreement_gate(self):
        batch, local = healthy_legs(4), healthy_legs(1)
        for u in local["hbt_typ_mismatch"]:
            u["measurements"]["m_ratio"] *= 1.001  # 1e-3 rel > 1e-4 tol
        ev = M.evaluate(batch=batch, rerun=None, local=local)
        self.assertEqual(ev["status"], "MC_LOCAL_AGREEMENT_FAIL")
        self.assertGreater(ev["findings"]["gates"]["local_vs_batch_max_rel"], 1e-4)

    def test_skipped_legs_are_reported_as_none_not_zero(self):
        ev = M.evaluate(batch=healthy_legs(4), rerun=None, local=None)
        self.assertEqual(ev["status"], "MC_METHOD_WORKS")
        self.assertIsNone(ev["findings"]["gates"]["reproducibility_max_rel"])
        self.assertIsNone(ev["findings"]["gates"]["local_vs_batch_max_rel"])

    def test_misaligned_sample_identity_is_a_defect_not_a_number(self):
        a, b = healthy_legs(4), healthy_legs(4)
        b["hbt_typ_mismatch"][1]["sample_index"] = 99
        with self.assertRaises(M.ReportError):
            M.evaluate(batch=a, rerun=b, local=None)


# ---------------------------------------------------------------------------
# sabotage negative controls
# ---------------------------------------------------------------------------


class TestSabotage(unittest.TestCase):
    def test_stat_noise_degrades(self):
        ev = M.sabotage(healthy_legs(4), "stat_noise")
        self.assertEqual(ev["status"], "MC_METHOD_CONTROL_FAIL")

    def test_mismatch_flat_degrades(self):
        ev = M.sabotage(healthy_legs(4), "mismatch_flat")
        self.assertEqual(ev["status"], "MC_METHOD_CONTROL_FAIL")

    def test_unknown_mode_is_valueerror(self):
        with self.assertRaises(ValueError):
            M.sabotage(healthy_legs(2), "nope")


# ---------------------------------------------------------------------------
# failure classification + helpers
# ---------------------------------------------------------------------------


class TestFailures(unittest.TestCase):
    def test_rejected_classification(self):
        ev = M.evaluate_failure("rejected", "klt refused: SimError boom")
        self.assertEqual(ev["status"], "KLT_MC_REJECTED")

    def test_unavailable_classification(self):
        ev = M.evaluate_failure("unavailable", "klt unavailable")
        self.assertEqual(ev["status"], "CAPABILITY_UNAVAILABLE")

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            M.evaluate_failure("wat", "")

    def test_dist_matches_reference_stats(self):
        d = M.dist([1.0, 2.0, 3.0, 4.0])
        self.assertEqual(d["n"], 4)
        self.assertAlmostEqual(d["mean"], 2.5)
        self.assertAlmostEqual(d["sigma"], 1.2909944487358056)  # ddof=1
        self.assertEqual(d["min"], 1.0)
        self.assertEqual(d["max"], 4.0)

    def test_parse_measurements_reads_ngspice_prints(self):
        text = ("Note: Simulation executed from .control section \n"
                "m_ic1 = 5.2610078894e-04\n"
                "m_ratio = 1.0264778922e+00\n"
                "m_off = -3.053411107e-02\n"
                "harness_rail_v = 2.5\n")
        got = M.parse_measurements(text)
        self.assertAlmostEqual(got["m_ic1"], 5.2610078894e-04)
        self.assertAlmostEqual(got["m_ratio"], 1.0264778922)
        self.assertNotIn("harness_rail_v", got)


if __name__ == "__main__":
    unittest.main()
