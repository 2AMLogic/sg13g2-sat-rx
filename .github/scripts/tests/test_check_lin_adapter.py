"""Negative controls for the lna-linearity layout of check_evidence_formats.py (issue #57).

A complete, self-consistent synthetic record is written by the REAL ``run.finalize``
(real analysis, real renderer, real snapshot layout) from closed-form fake klt logs into
a temporary tree. Each test breaks exactly one rule and asserts a file-specific failure;
the unbroken record must pass. No simulator, PDK or network. The real tree is not modified.

Run: python3 -m unittest discover -s .github/scripts/tests -p 'test_check_lin_adapter.py'
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parents[1]
BENCH = REPO / "sim" / "lna-linearity"
sys.path.insert(0, str(SCRIPTS))

import check_evidence_formats as chk  # noqa: E402

NAME = "lna-linearity"
SHA = "a" * 64
SHA1 = "b" * 40


def _load(name: str, path: Path, *paths: Path):
    for p in paths:
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# the bench modules import each other by their plain names (linearity, analysis); load them once
L = _load("linearity", BENCH / "linearity.py", BENCH, BENCH.parent)
A = _load("analysis", BENCH / "analysis.py")
R = _load("lin_run", BENCH / "run.py")
FAKES = _load("lin_fakes", BENCH / "tests" / "fakes.py", BENCH / "tests")


def build_record(root: Path, *, limit_violation: bool = True) -> str:
    """Write one record into root/sim/lna-linearity with the real finalize()."""
    exp = root / "sim" / NAME
    for sub in ("records", "corners", "netlist-snapshots", "testbench"):
        (exp / sub).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BENCH / "README.md", exp / "README.md")
    shutil.copyfile(BENCH / "testbench" / "plan.json", exp / "testbench" / "plan.json")
    plan = L.load_plan(BENCH / "testbench" / "plan.json")
    amp40 = L.cubic_tone_amps(10.0, -2000.0, L.vs_peak_from_pav_dbm(-40.0), False)["f0"]
    kw = dict(excursion_per_v=0.14 / amp40, floor_v=1e-9) if limit_violation else dict(floor_v=1e-9)
    texts = FAKES.fake_logs(plan, **kw)
    work = root / "work"
    work.mkdir(exist_ok=True)
    args = types.SimpleNamespace(klt_cmd="echo klt-test", backend="batch", timeout_s=60, no_stage_models=True,
                                 runner_version_check="warn")
    reqs = R.write_requests(plan, work, "batch", args)
    reports = {}
    for key in reqs:
        rep = {"status": "pass", "corners": [{}], "environment": {
            "engine": "ngspice", "engine_version": "46", "models_lib_sha256": SHA, "netlist_sha256": SHA,
            "remote": {"provider": "aws-batch-fleet", "job_id": f"klt-sim-{key}"}},
            "provenance": {"klt_version": "test"}}
        (work / f"report_{key}.json").write_text(json.dumps(rep))
        reports[key] = rep
    saved = (R.RECORDS, R.LOGS, R.SNAPS, R.plan_provenance, R.dirty_code)
    R.RECORDS, R.LOGS, R.SNAPS = exp / "records", exp / "corners", exp / "netlist-snapshots"
    R.plan_provenance = lambda: {"file": "sim/lna-linearity/testbench/plan.json", "sha256": R.sha256_file(R.PLAN_PATH),
                                 "commit": SHA1, "dirty": False}
    R.dirty_code = lambda: []
    pdk = types.SimpleNamespace(path=root, model_lib=root / "cornerHBT.lib")
    try:
        import datetime as dt
        rc = R.finalize(plan, work, reqs, texts, reports, R.python_controls(plan), pdk, dt.datetime.now(dt.timezone.utc), args)
    finally:
        R.RECORDS, R.LOGS, R.SNAPS, R.plan_provenance, R.dirty_code = saved
    assert rc == 0
    return next(p.stem for p in (exp / "records").glob("*.md"))


def edit_json(path: Path, fn) -> None:
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data, indent=2) + "\n")


def edit_gz_json(path: Path, fn) -> None:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    fn(data)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(data, fh)


class Base(unittest.TestCase):
    limit_violation = True

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "spec").mkdir()
        shutil.copyfile(REPO / "spec" / "target-spec.md", self.root / "spec" / "target-spec.md")
        shutil.copytree(REPO / "sim" / "lna-sparam-nf", self.root / "sim" / "lna-sparam-nf",
                        ignore=shutil.ignore_patterns("_build", "_selftest", "__pycache__"))
        self.rid = build_record(self.root, limit_violation=self.limit_violation)
        self.exp = self.root / "sim" / NAME
        self.js = self.exp / "records" / f"{self.rid}.json"
        self.md = self.exp / "records" / f"{self.rid}.md"
        self.sweeps = self.exp / "records" / f"{self.rid}-sweeps.json.gz"
        self.snap = self.exp / "netlist-snapshots" / self.rid
        self.logs = self.exp / "corners" / self.rid

    def problems(self) -> list[str]:
        return chk.check_format(self.root).items

    def assertFails(self, *needles: str):
        found = self.problems()
        self.assertTrue(found, "checker passed a deliberately broken tree")
        for needle in needles:
            self.assertTrue(any(needle in p for p in found), f"no problem mentioning {needle!r} in:\n" + "\n".join(found))


class LimitedRecord(Base):
    """IIP3 ok, P1dB bounded by the operating-limit rule (the shape the DUT is expected to take)."""

    def test_adapter_registered_and_fresh_record_passes(self):
        self.assertIn(NAME, chk.ADAPTERS)
        self.assertEqual(self.problems(), [])
        rec = json.loads(self.js.read_text())
        self.assertEqual(rec["status"], "COLLECTED")
        pe = rec["placements"]["mid"]
        self.assertEqual(pe["results"]["iip3"]["status"], "ok")
        self.assertEqual(pe["results"]["p1db"]["status"], "bounded")

    def test_constants_match_the_bench(self):
        plan = L.load_plan(BENCH / "testbench" / "plan.json")
        self.assertEqual(chk.lin_request_keys(plan), A.request_keys(plan))
        self.assertEqual(chk.LIN_VARIANTS, L.VARIANTS)
        self.assertEqual(chk.LIN_TWO_KEYS, ("p_f1_dbm", "p_f2_dbm", "p_im3l_dbm", "p_im3h_dbm"))
        t = chk.lin_spec_targets(REPO)
        self.assertEqual(t, {"iip3_dbm": plan["targets"]["iip3_dbm"], "p1db_dbm": plan["targets"]["p1db_dbm"]})

    # ---- identity / claim ------------------------------------------------------------
    def test_first_line_and_status(self):
        self.md.write_text(self.md.read_text().replace(f"# {NAME} record", "# other record", 1))
        self.assertFails("first line must be")

    def test_status_must_be_known(self):
        edit_json(self.js, lambda d: d.update(status="COMPLIANT"))
        self.assertFails("is not one of COLLECTED")

    def test_claim_must_state_placeholder(self):
        self.md.write_text(self.md.read_text().replace("placeholder circuit", "design"))
        self.assertFails("Claim line must state the IDEAL-matching placeholder circuit")

    def test_no_row_may_be_claimed_met(self):
        edit_json(self.js, lambda d: d.update(spec_rows_claimed_met=[7]))
        self.assertFails("spec_rows_claimed_met must be []")

    def test_commit_does_not_match_id(self):
        edit_json(self.js, lambda d: d["environment"]["git"].update(commit="1234567" + "0" * 33))
        self.assertFails("does not match the sha in the record id")

    # ---- plan / DUT identity -----------------------------------------------------------
    def test_plan_hash_and_dirty(self):
        (self.snap / "plan.json").write_text((self.snap / "plan.json").read_text() + "\n ")
        self.assertFails("plan.sha256 does not match")

    def test_plan_dirty_rejected(self):
        edit_json(self.js, lambda d: d["plan"].update(dirty=True))
        self.assertFails("plan.dirty must be false")

    def test_plan_commit_required(self):
        edit_json(self.js, lambda d: d["plan"].update(commit=""))
        self.assertFails("plan.commit must name the commit")

    def test_dut_identity_required(self):
        (self.snap / "lna_stage1.spice").write_text("* tampered\n")
        self.assertFails("dut.sha256 does not match")

    def test_missing_dut_snapshot_and_commit(self):
        edit_json(self.js, lambda d: d["dut"].pop("last_commit"))
        self.assertFails("dut.last_commit must name")
        (self.snap / "lna_stage1.spice").unlink()
        self.assertFails("snapshot lacks the frozen DUT")

    def test_environment_provenance(self):
        edit_json(self.js, lambda d: d["environment"].update(pdk_artifact_sha256="x"))
        self.assertFails("pdk_artifact_sha256")

    def test_simulator_provenance_per_request(self):
        edit_json(self.js, lambda d: d["klt_requests"][0].update(engine_version=None))
        self.assertFails("simulator provenance")
        edit_json(self.js, lambda d: d["klt_requests"][0].update(engine_version="46", models_lib_sha256="x"))
        self.assertFails("models_lib_sha256")

    def test_batch_request_needs_job_id(self):
        edit_json(self.js, lambda d: d["klt_requests"][1].update(remote=None))
        self.assertFails("remote job id")

    def test_request_set_is_exact(self):
        edit_json(self.js, lambda d: d.update(klt_requests=d["klt_requests"][1:]))
        self.assertFails("klt_requests must carry exactly")

    # ---- frozen artifacts -----------------------------------------------------------------
    def test_missing_log_and_log_without_done(self):
        (self.logs / "mid_two.log.gz").unlink()
        self.assertFails("raw logs")
        with gzip.open(self.logs / "mid_two.log.gz", "wt") as fh:
            fh.write("m_b_two00_n = 20000\n")
        self.assertFails("lacks LNLIN_DONE")

    def test_orphan_evidence(self):
        (self.exp / "corners" / "20200101-000000-abcdef1").mkdir()
        self.assertFails("orphan evidence")

    def test_unexpected_files(self):
        (self.snap / "stray.txt").write_text("x")
        self.assertFails("unexpected file in an lna-linearity netlist-snapshots")
        (self.exp / "records" / "notes.txt").write_text("x")
        self.assertFails("unexpected file in lna-linearity records/")

    def test_missing_snapshot_pieces(self):
        (self.snap / "body_low_one.spice").unlink()
        self.assertFails("snapshot lacks body_low_one.spice")
        (self.snap / "plan.json").unlink()
        self.assertFails("snapshot lacks the frozen plan.json")

    def test_request_must_target_nominal_process(self):
        rp = self.snap / "request_mid_one.json"
        edit_json(rp, lambda d: d["corners"].update(process=["hbt_wcs"]))
        self.assertFails("nominal process corner")

    def test_probe_logs_not_part_of_layout(self):
        (self.exp / "probe-logs").mkdir()
        self.assertFails("probe-logs/ is not part of the lna-linearity evidence layout")

    # ---- controls ---------------------------------------------------------------------------
    def test_negative_control_accepted_is_rejected(self):
        edit_json(self.js, lambda d: d["python_controls"]["negative"][0].update(rejected=False))
        self.assertFails("every negative control must be recorded as rejected")

    def test_required_negative_controls(self):
        edit_json(self.js, lambda d: d["python_controls"].update(
            negative=[n for n in d["python_controls"]["negative"] if n["name"] != "unbracketed_p1db"]))
        self.assertFails("negative control 'unbracketed_p1db' missing")

    def test_python_controls_must_pass(self):
        edit_json(self.js, lambda d: d["python_controls"].update(**{"pass": False}))
        self.assertFails("python_controls.pass must be true")

    def test_ngspice_control_consistency(self):
        edit_json(self.js, lambda d: d["controls"]["evaluations"]["two"].update(error_db=1.0))
        self.assertFails("controls.evaluations[two].pass disagrees", "controls.pass disagrees")
        edit_json(self.js, lambda d: d["controls"]["evaluations"]["two"].update(error_db=0.0, **{"pass": True}))
        edit_json(self.js, lambda d: d["controls"].update(**{"pass": False}))
        self.assertFails("controls.pass disagrees")

    def test_controls_failed_status_needs_failed_controls(self):
        edit_json(self.js, lambda d: d.update(status="CONTROLS_FAILED"))
        self.md.write_text(self.md.read_text().replace("- **Status: COLLECTED**", "- **Status: CONTROLS_FAILED**"))
        self.assertFails("inconsistent with controls.pass")

    # ---- estimator evidence --------------------------------------------------------------------
    def iip3(self, d, side="low"):
        return d["placements"]["mid"]["results"]["iip3"]["sidebands"][side]

    def test_both_sidebands_required(self):
        edit_json(self.js, lambda d: d["placements"]["mid"]["results"]["iip3"]["sidebands"].pop("high"))
        self.assertFails("both IM3 sidebands")

    def test_fit_interval_required(self):
        edit_json(self.js, lambda d: self.iip3(d).pop("interval_dbm"))
        self.assertFails("missing fit interval_dbm")

    def test_fit_interval_inside_declared_sweep(self):
        edit_json(self.js, lambda d: self.iip3(d).update(interval_dbm=[-80.0, -50.0]))
        self.assertFails("outside the declared sweep")

    def test_slopes_inside_declared_tolerance(self):
        edit_json(self.js, lambda d: self.iip3(d).update(slope_im3=2.0))
        self.assertFails("outside the declared 1:3 tolerance")

    def test_residuals_required_and_bounded(self):
        edit_json(self.js, lambda d: self.iip3(d).pop("residual_im3_db"))
        self.assertFails("missing fit residuals")
        edit_json(self.js, lambda d: self.iip3(d).update(residual_im3_db=0.0, residual_fund_db=3.0))
        self.assertFails("fit residual exceeds")

    def test_baseline_and_rejected_point_reasons_required(self):
        edit_json(self.js, lambda d: self.iip3(d).pop("baseline"))
        self.assertFails("missing small-signal gain baseline")
        edit_json(self.js, lambda d: self.iip3(d).update(baseline={"gain_db": 20.0}))
        edit_json(self.js, lambda d: self.iip3(d).pop("excluded_points"))
        self.assertFails("missing excluded_points")

    def test_reported_iip3_is_the_lower_sideband(self):
        edit_json(self.js, lambda d: d["placements"]["mid"]["results"]["iip3"].update(iip3_dbm=99.0))
        self.assertFails("not the lower of the two sidebands")

    def test_unavailable_needs_reason(self):
        edit_json(self.js, lambda d: d["placements"]["mid"]["results"].update(iip3={"status": "unavailable"}))
        self.assertFails("IIP3 unavailable without a reason")

    def test_bounded_p1db_has_no_number_and_a_bound(self):
        edit_json(self.js, lambda d: d["placements"]["mid"]["results"]["p1db"].update(p1db_in_dbm=-20.0))
        self.assertFails("must not carry a p1db_in_dbm number")
        edit_json(self.js, lambda d: d["placements"]["mid"]["results"]["p1db"].pop("p1db_in_dbm"))
        edit_json(self.js, lambda d: d["placements"]["mid"]["results"]["p1db"].pop("p1db_in_dbm_gt"))
        self.assertFails("bounded P1dB needs p1db_in_dbm_gt")

    def test_p1db_needs_baseline(self):
        edit_json(self.js, lambda d: d["placements"]["mid"]["results"]["p1db"].pop("baseline"))
        self.assertFails("lacks an established small-signal baseline")

    # ---- targets and verdicts ----------------------------------------------------------------------
    def test_target_may_not_be_relaxed(self):
        edit_json(self.js, lambda d: d["placements"]["mid"]["final"]["iip3"]["assessment"].update(target_dbm=-30.0))
        self.assertFails("differs from the ratified spec target")

    def test_plan_target_must_match_spec(self):
        def relax(d):
            d["plan_declaration"]["targets"]["iip3_dbm"] = -30.0
        edit_json(self.js, relax)
        snap_plan = self.snap / "plan.json"
        edit_json(snap_plan, lambda d: d["targets"].update(iip3_dbm=-30.0))
        edit_json(self.js, lambda d: d["plan"].update(sha256=R.sha256_file(snap_plan)))
        self.assertFails("plan_declaration.targets differs from the ratified spec table")

    def test_verdict_must_follow_from_value(self):
        def flip(d):
            a = d["placements"]["mid"]["final"]["iip3"]["assessment"]
            a["verdict"] = "fails" if a["verdict"] != "fails" else "meets"
        edit_json(self.js, flip)
        self.assertFails("does not follow from the value")

    def test_convergence_entries(self):
        edit_json(self.js, lambda d: d["placements"]["mid"]["convergence"]["iip3"].pop())
        self.assertFails("exactly the half_step and double_window variants")

    def test_final_status_follows_convergence(self):
        def bad(d):
            d["placements"]["mid"]["convergence"]["p1db"][0]["ok"] = False
        edit_json(self.js, bad)
        self.assertFails("final.converged disagrees", "must be 'unconverged'")

    def test_unconverged_must_be_not_determined(self):
        def bad(d):
            pe = d["placements"]["mid"]
            pe["convergence"]["iip3"][0]["ok"] = False
            pe["final"]["iip3"].update(converged=False, status="unconverged")
        edit_json(self.js, bad)
        self.assertFails("an unconverged estimator must be 'not_determined'")

    def test_unrestricted_reference_is_labelled(self):
        edit_json(self.js, lambda d: d["placements"]["mid"]["unrestricted_reference"].update(label="result"))
        self.assertFails("must be labelled 'NOT A RESULT'")

    def test_row_summary_follows_placements(self):
        edit_json(self.js, lambda d: d["rows"]["7"].update(worst_verdict="meets" if d["rows"]["7"]["worst_verdict"] != "meets" else "fails"))
        self.assertFails("worst_verdict is not the worst placement verdict")
        edit_json(self.js, lambda d: d["rows"].pop("8"))
        self.assertFails("rows must carry exactly '7' and '8'")

    # ---- sweeps sidecar ------------------------------------------------------------------------------
    def test_sweeps_must_hold_every_declared_point(self):
        edit_gz_json(self.sweeps, lambda d: d["mid"]["half_step"]["two"].pop())
        self.assertFails("the plan declares")

    def test_sweeps_need_both_im3_sidebands(self):
        def cut(d):
            d["low"]["base"]["two"][3].pop("p_im3h_dbm")
        edit_gz_json(self.sweeps, cut)
        self.assertFails("both IM3 sidebands are required")

    def test_sweeps_need_excursions(self):
        def cut(d):
            d["low"]["base"]["one"][3]["excursion_v"] = None
        edit_gz_json(self.sweeps, cut)
        self.assertFails("no device excursions")

    def test_sweeps_file_must_exist(self):
        self.sweeps.unlink()
        self.assertFails("sweeps file")

    def test_markdown_must_reference_artifacts_and_rows(self):
        self.md.write_text(self.md.read_text().replace(f"corners/{self.rid}/", "corners/elsewhere/"))
        self.assertFails(f"does not reference corners/{self.rid}/")
        self.md.write_text(self.md.read_text().replace("- row 7 (", "- r7 ("))
        self.assertFails("lacks the row 7 summary")

    def test_markdown_sections(self):
        self.md.write_text(self.md.read_text().replace("## Controls", "## Notes"))
        self.assertFails("missing required section '## Controls'")


class UnlimitedRecord(Base):
    """P1dB ok with a bracket (no operating-limit violation in the sweep)."""
    limit_violation = False

    def test_fresh_record_passes_and_has_a_bracketed_p1db(self):
        self.assertEqual(self.problems(), [])
        p = json.loads(self.js.read_text())["placements"]["mid"]["results"]["p1db"]
        self.assertEqual(p["status"], "ok")

    def test_bracket_must_straddle_the_drop(self):
        edit_json(self.js, lambda d: d["placements"]["mid"]["results"]["p1db"]["bracket"].update(drop_db=[1.5, 2.0]))
        self.assertFails("does not straddle the declared gain drop")

    def test_p1db_must_lie_in_its_bracket(self):
        edit_json(self.js, lambda d: d["placements"]["mid"]["results"]["p1db"].update(p1db_in_dbm=0.0))
        self.assertFails("lies outside its bracket")

    def test_bracket_required(self):
        edit_json(self.js, lambda d: d["placements"]["mid"]["results"]["p1db"].pop("bracket"))
        self.assertFails("requires a bracket")

    def test_output_p1db_consistency(self):
        edit_json(self.js, lambda d: d["placements"]["mid"]["results"]["p1db"].update(p1db_out_dbm=0.0))
        self.assertFails("p1db_out_dbm is inconsistent")


class SpecTargets(unittest.TestCase):
    def test_targets_parse_from_the_ratified_table(self):
        self.assertEqual(chk.lin_spec_targets(REPO), {"iip3_dbm": -15.0, "p1db_dbm": -25.0})

    def test_verdict_function(self):
        self.assertEqual(chk.lin_expected_verdict(-14.9, -15.0, 0.05), "meets")
        self.assertEqual(chk.lin_expected_verdict(-14.9, -15.0, 0.3), "marginal")
        self.assertEqual(chk.lin_expected_verdict(-16.0, -15.0, 0.3), "fails")


if __name__ == "__main__":
    unittest.main()
