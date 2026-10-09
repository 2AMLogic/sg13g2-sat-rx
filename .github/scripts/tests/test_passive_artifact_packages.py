"""Tests for the frozen passive-p1 solver-artifact packages (issue #58).

Fixture data only: tiny placeholder files stand in for solver output, so no
openEMS, numpy, PDK or network is needed and nothing here makes a numerical
claim. They exercise (a) the publisher (sim/passive-p1/scripts/freeze_package.py),
(b) the CI checker's package rules and append-only protection, and (c) the
documented reanalysis command against a frozen package.

Run: python3 -m pytest .github/scripts/tests/test_passive_artifact_packages.py -q
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_check_evidence_adapters import (  # noqa: E402
    PASSIVE, REPO, P_UNAVAIL, FormatBase, chk, clone_passive_unavailable, commit, copy_sim, edit_json, fz, run,
)

sys.path.insert(0, str(REPO / "sim" / "passive-p1" / "scripts"))
import reanalyze_frozen as rz  # noqa: E402

STAGES = "geometry em convergence post fit compare"


def write_workdir(wd: Path, tag: str = "A", compare: bool = True) -> None:
    """Placeholder working tree. Contents carry `tag` so reuse of filenames is observable."""
    def put(rel: str, text: str) -> None:
        p = wd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    for rel in fz.SOLVER_FILES:
        put(rel, f"{tag}: {rel}\n")
    put("results/p1_metrics.json", json.dumps({"tag": tag, "band": [1, 2, 3]}))
    put("results/p1_lq.csv", f"{tag},lq\n")
    put("results/p1_deembedded.s2p", f"{tag} s2p\n")
    put("fit/p1_fit_parameters.json", json.dumps({"tag": tag}))
    put("fit/p1_fit_candidate.spice", f"* {tag}\n")
    put("results/p1_compare.json", json.dumps({"tag": tag, "zse": {}}))
    for rel in fz.GEOMETRY_LOGS + ("run_log/em_p1.txt", "run_log/em_conv_p1_mesh0p5.txt",
                                   "run_log/em_conv_p1_margin400.txt", "run_log/postprocess.txt",
                                   "run_log/fit.txt", "run_log/compare.txt"):
        put(rel, f"{tag} log {rel}\n")
    if not compare:
        (wd / "results/p1_compare.json").unlink()


def tree_hash(d: Path) -> dict[str, str]:
    return {p.relative_to(d).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(d.rglob("*")) if p.is_file()}


class Publisher(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.wd = self.base / "work"
        self.pk = self.base / "solver-artifacts"
        write_workdir(self.wd, "A")

    def publish(self, rid="20261010-000001-abcdef1", status="QUALIFIED", **kw):
        return fz.publish(str(self.wd), str(self.pk), rid, status, kw.pop("stages", STAGES),
                          has_compare=kw.pop("has_compare", True), **kw)

    def test_successive_publications_with_reused_working_filenames(self):
        r1 = self.publish("20261010-000001-abcdef1")
        before = tree_hash(Path(r1["dir"]))
        shutil.rmtree(self.wd)  # clearing the scratch dir ...
        write_workdir(self.wd, "B")  # ... and re-running writes the SAME filenames with new bytes
        r2 = self.publish("20261010-000002-abcdef1")
        self.assertEqual(tree_hash(Path(r1["dir"])), before, "first package changed after scratch reuse")
        self.assertEqual(fz.verify(r1["dir"]), [])
        self.assertEqual(fz.verify(r2["dir"]), [])
        self.assertIn("A: results/inductor_p1.s2p", (Path(r1["dir"]) / "results/inductor_p1.s2p").read_text())
        self.assertIn("B: results/inductor_p1.s2p", (Path(r2["dir"]) / "results/inductor_p1.s2p").read_text())
        self.assertNotEqual(r1["manifest_sha256"], r2["manifest_sha256"])

    def test_existing_package_is_never_overwritten(self):
        r1 = self.publish()
        before = tree_hash(Path(r1["dir"]))
        write_workdir(self.wd, "B")
        with self.assertRaises(fz.PublishError) as cm:
            self.publish()
        self.assertIn("already exists", str(cm.exception))
        self.assertEqual(tree_hash(Path(r1["dir"])), before)

    def test_leftover_interrupted_directory_is_refused_not_adopted(self):
        d = self.pk / "20261010-000001-abcdef1"
        d.mkdir(parents=True)
        (d / fz.INCOMPLETE).write_text("x")
        with self.assertRaises(fz.PublishError):
            self.publish()
        self.assertEqual([p.name for p in d.iterdir()], [fz.INCOMPLETE])  # untouched

    def test_interrupted_publication_leaves_nothing_and_id_is_reusable(self):
        calls = []

        def boom(rel):
            calls.append(rel)
            if len(calls) == 3:
                raise KeyboardInterrupt("simulated kill mid-copy")
        with self.assertRaises(KeyboardInterrupt):
            self.publish(_after_copy=boom)
        self.assertFalse((self.pk / "20261010-000001-abcdef1").exists(), "partial package left behind")
        self.assertEqual(fz.verify(self.publish()["dir"]), [])  # clean retry of the same id

    def test_missing_stage_output_refuses_before_creating_anything(self):
        (self.wd / "results/convergence/p1_margin400.s2p").unlink()
        with self.assertRaises(fz.PublishError) as cm:
            self.publish()
        self.assertIn("p1_margin400.s2p", str(cm.exception))
        self.assertFalse(self.pk.exists() and any(self.pk.iterdir()))

    def test_required_files_follow_the_outcome(self):
        (self.wd / "results/p1_compare.json").unlink()
        with self.assertRaises(fz.PublishError):  # QUALIFIED needs the comparison
            self.publish("20261010-000001-abcdef1", "QUALIFIED")
        r = self.publish("20261010-000002-abcdef1", "UNCONVERGED", stages="em convergence post", has_compare=False)
        files = {e["path"] for e in json.loads((Path(r["dir"]) / "manifest.json").read_text())["files"]}
        self.assertIn("results/p1_metrics.json", files)
        self.assertIn("settings.json", files)
        self.assertFalse(files & {"fit/p1_fit_candidate.spice", "run_log/fit.txt"},
                         "stale fit output from an earlier run must not be frozen for an UNCONVERGED record")

    def test_capability_unavailable_keeps_diagnostics_without_inventing_solver_data(self):
        empty = self.base / "empty"
        empty.mkdir()
        (empty / "run_log").mkdir()
        (empty / "run_log/geometry_p1.txt").write_text("diag\n")
        (empty / "results").mkdir()
        (empty / "results/p1_metrics.json").write_text("{}")  # stale leftover: must not be frozen
        r = fz.publish(str(empty), str(self.pk), "20261010-000003-abcdef1", "CAPABILITY_UNAVAILABLE", "geometry em")
        files = {e["path"] for e in json.loads((Path(r["dir"]) / "manifest.json").read_text())["files"]}
        self.assertEqual(files, {"run_log/geometry_p1.txt", "settings.json"})

    def test_bad_run_id_refused(self):
        for bad in ("../x", "20261010-000001", "abc"):
            with self.assertRaises(fz.PublishError):
                self.publish(bad)

    def test_verify_detects_tampering(self):
        d = Path(self.publish()["dir"])
        (d / "results/p1_metrics.json").write_text("{}")
        (d / "stray.txt").write_text("x")
        probs = "\n".join(fz.verify(str(d)))
        self.assertIn("sha256 mismatch: results/p1_metrics.json", probs)
        self.assertIn("file not in manifest: stray.txt", probs)

    def test_publisher_and_checker_agree_on_required_files(self):
        for status in fz.STATUSES:
            for stages in (STAGES, "post fit compare", "em convergence post", "geometry", ""):
                for hc in (True, False):
                    req, _opt = fz.required_paths(status, stages, hc)
                    self.assertEqual(sorted(req), chk.passive_required_paths(status, stages.split(), hc),
                                     (status, stages, hc))


def make_v2_record(root: Path, status: str, wd: Path, ts: str = "20261010-000000", stages: str = STAGES) -> str:
    """Replace a cloned (settings-only) v2 record by one of `status` backed by a package from `wd`."""
    exp = root / "sim" / PASSIVE
    new = clone_passive_unavailable(root, ts)
    rid = new.rsplit("-", 1)[0]
    shutil.rmtree(exp / "solver-artifacts" / rid)
    r = fz.publish(str(wd), str(exp / "solver-artifacts"), rid, status, stages,
                   has_compare=(status in ("QUALIFIED",)))
    old_stem, new_stem = new, f"{rid}-{status}"
    for ext in ("md", "json"):
        p = exp / "records" / f"{old_stem}.{ext}"
        p.rename(exp / "records" / f"{new_stem}.{ext}")
    md = exp / "records" / f"{new_stem}.md"
    md.write_text(md.read_text().replace("CAPABILITY_UNAVAILABLE", status).replace(
        "- Reason", "- Reason"))
    rj = exp / "records" / f"{new_stem}.json"

    def fix(d):
        d.update(record_id=new_stem, status=status, stages=stages, failed_command="", reasons=["fixture"],
                 metrics=json.loads((wd / "results/p1_metrics.json").read_text()),
                 compare=json.loads((wd / "results/p1_compare.json").read_text()) if status == "QUALIFIED" else None)
        d["artifact_package"].update(manifest_sha256=r["manifest_sha256"], files=r["files"])
    edit_json(rj, fix)
    sha_old = [ln for ln in md.read_text().splitlines() if "Manifest sha256" in ln]
    text = md.read_text()
    for ln in sha_old:
        text = text.replace(ln, f"- Manifest sha256 `{r['manifest_sha256']}`")
    md.write_text(text)
    return new_stem


class CheckerPackages(FormatBase):
    def setUp(self):
        super().setUp()
        self.wd = Path(self._tmp.name) / "wd"
        write_workdir(self.wd, "A", compare=False)
        self.stem = make_v2_record(self.root, "UNCONVERGED", self.wd, stages="em convergence post")
        self.rid = self.stem.rsplit("-", 1)[0]
        self.pkg = self.passive / "solver-artifacts" / self.rid
        self.rec_js = self.passive / "records" / f"{self.stem}.json"

    def rewrite_manifest(self, fn):
        mp = self.pkg / "manifest.json"
        edit_json(mp, fn)
        sha = hashlib.sha256(mp.read_bytes()).hexdigest()
        text = (self.passive / "records" / f"{self.stem}.md").read_text()
        old = json.loads(self.rec_js.read_text())["artifact_package"]["manifest_sha256"]
        (self.passive / "records" / f"{self.stem}.md").write_text(text.replace(old, sha))
        edit_json(self.rec_js, lambda d: d["artifact_package"].update(manifest_sha256=sha))

    def test_complete_new_package_passes(self):
        self.assertEqual(self.problems(), [])

    def test_legacy_records_stay_valid_without_package(self):
        self.assertEqual(self.problems(), [])
        self.assertTrue((self.passive / "records" / f"{P_UNAVAIL}.json").is_file())
        self.assertFalse((self.passive / "solver-artifacts" / P_UNAVAIL.rsplit("-", 1)[0]).exists())

    def test_new_record_without_schema_is_rejected(self):
        edit_json(self.rec_js, lambda d: (d.pop("record_schema"), d.pop("artifact_package")))
        self.assertFails("no 'record_schema'")

    def test_unknown_schema_rejected(self):
        edit_json(self.rec_js, lambda d: d.update(record_schema=3))
        self.assertFails("unknown record_schema")

    def test_missing_listed_file(self):
        (self.pkg / "results/p1_lq.csv").unlink()
        self.assertFails("listed file results/p1_lq.csv is missing")

    def test_tampered_bytes(self):
        (self.pkg / "results/inductor_p1.s2p").write_text("edited\n")
        self.assertFails("sha256 does not match the manifest")

    def test_tampered_manifest(self):
        edit_json(self.pkg / "manifest.json", lambda d: d["files"][0].update(sha256="0" * 64))
        self.assertFails("manifest sha256 does not match the record")

    def test_extra_unlisted_file(self):
        (self.pkg / "results/extra.txt").write_text("x")
        self.assertFails("not listed in manifest.json")

    def test_absolute_path_reference(self):
        self.rewrite_manifest(lambda d: d["files"].append({"path": "/etc/passwd", "sha256": "0" * 64, "bytes": 1}))
        self.assertFails("unsafe or malformed package path '/etc/passwd'")

    def test_traversal_reference(self):
        self.rewrite_manifest(lambda d: d["files"].append({"path": "results/../../x", "sha256": "0" * 64, "bytes": 1}))
        self.assertFails("unsafe or malformed package path 'results/../../x'")

    def test_incomplete_manifest_missing_required_output(self):
        def drop(d):
            d["files"] = [e for e in d["files"] if e["path"] != "results/convergence/p1_mesh0p5.s2p"]
        self.rewrite_manifest(drop)
        self.assertFails("package is incomplete: required stage output results/convergence/p1_mesh0p5.s2p")

    def test_interrupted_publication_marker(self):
        (self.pkg / fz.INCOMPLETE).write_text("x")
        self.assertFails("interrupted/incomplete publication")

    def test_missing_manifest_is_incomplete(self):
        (self.pkg / "manifest.json").unlink()
        self.assertFails("no manifest.json")

    def test_orphan_package_directory(self):
        shutil.copytree(self.pkg, self.passive / "solver-artifacts" / "20261011-000000-abcdef1")
        self.assertFails("belongs to no record")

    def test_leftover_interrupted_package_without_record(self):
        d = self.passive / "solver-artifacts" / "20261011-000000-abcdef1"
        d.mkdir()
        (d / fz.INCOMPLETE).write_text("x")
        self.assertFails("belongs to no record")

    def test_record_numbers_differ_from_frozen_bytes(self):
        edit_json(self.rec_js, lambda d: d["metrics"].update(tag="other"))
        self.assertFails("record 'metrics' differs from the packaged results/p1_metrics.json")

    def test_wrong_package_pointer(self):
        edit_json(self.rec_js, lambda d: d["artifact_package"].update(path="sim/passive-p1/solver-artifacts/../records/"))
        self.assertFails("artifact_package.path")

    def test_markdown_must_name_package(self):
        md = self.passive / "records" / f"{self.stem}.md"
        md.write_text(md.read_text().replace(f"solver-artifacts/{self.rid}/", "elsewhere/"))
        self.assertFails("Markdown does not name its frozen package")

    def test_symlink_in_package(self):
        (self.pkg / "results/link.txt").symlink_to("/etc/hostname")
        self.assertFails("symlink inside a frozen package")

    def test_capability_unavailable_package_may_not_carry_solver_data(self):
        wd2 = Path(self._tmp.name) / "wd2"
        write_workdir(wd2, "A")
        # a settings-only unavailable package is valid; bolting solver data on is not
        stem = clone_passive_unavailable(self.root, "20261012-000000")
        rid = stem.rsplit("-", 1)[0]
        self.assertEqual(self.problems(), [])
        shutil.copy(wd2 / "results/p1_metrics.json", self.passive / "solver-artifacts" / rid / "p1_extra.json")
        self.assertFails("not listed in manifest.json")


class MakeRecordEndToEnd(FormatBase):
    """make_record.py (stdlib path, --unavailable) publishes a package the checker accepts."""

    def run_make_record(self, wd: Path, *extra: str) -> subprocess.CompletedProcess:
        script = REPO / "sim" / "passive-p1" / "scripts" / "make_record.py"
        return subprocess.run([sys.executable, "-I", str(script), "--dir", str(wd), "--records-dir",
                               str(self.passive / "records"), "--unavailable", "--failed-command", "command -v openEMS",
                               "--detail", "openEMS not found on PATH", "--stages", "geometry em",
                               "--commands", "fixture", *extra], capture_output=True, text=True)

    def test_unavailable_record_publishes_checkable_package(self):
        wd = Path(self._tmp.name) / "wd"
        (wd / "run_log").mkdir(parents=True)
        (wd / "run_log" / "geometry_p1.txt").write_text("diagnostic\n")
        r = self.run_make_record(wd, "--solver-settings", '{"EM_THREADS": "2"}')
        self.assertEqual(r.returncode, 0, r.stderr)
        pkgs = sorted((self.passive / "solver-artifacts").iterdir())
        self.assertEqual(len(pkgs), 1)
        man = json.loads((pkgs[0] / "manifest.json").read_text())
        self.assertEqual({e["path"] for e in man["files"]}, {"run_log/geometry_p1.txt", "settings.json"})
        self.assertEqual(json.loads((pkgs[0] / "settings.json").read_text())["solver_settings"], {"EM_THREADS": "2"})
        self.assertEqual(self.problems(), [])

    def test_refused_publication_writes_no_record(self):
        wd = Path(self._tmp.name) / "wd"
        wd.mkdir()
        before = sorted(p.name for p in (self.passive / "records").iterdir())
        (wd / "results").mkdir()
        (wd / "results" / "p1_metrics.json").write_text(json.dumps({"band": [], "convergence": {
            k: {"invalid_denominator": True, "within_budget": False} for k in ("mesh_1p0_vs_0p5", "margin_200_vs_400")},
            "budget_L_pct": 5, "budget_Q_pct": 10}))
        r = subprocess.run([sys.executable, "-I", str(REPO / "sim/passive-p1/scripts/make_record.py"), "--dir", str(wd),
                            "--records-dir", str(self.passive / "records"), "--stages", "post"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("REFUSED", r.stderr)
        self.assertEqual(sorted(p.name for p in (self.passive / "records").iterdir()), before)
        self.assertFalse((self.passive / "solver-artifacts").exists() and any((self.passive / "solver-artifacts").iterdir()))


class HistoryPackages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.upstream = tmp / "upstream"
        copy_sim(cls.upstream)
        cls.wd = tmp / "wd"
        write_workdir(cls.wd, "A", compare=False)
        cls.stem = make_v2_record(cls.upstream, "UNCONVERGED", cls.wd, stages="em convergence post")
        cls.rid = cls.stem.rsplit("-", 1)[0]
        run(cls.upstream, "git", "init", "-q", "-b", "trunk")
        commit(cls.upstream, "base")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self._work = tempfile.TemporaryDirectory()
        self.addCleanup(self._work.cleanup)
        self.pr = Path(self._work.name) / "pr"
        run(Path(self._work.name), "git", "clone", "-q", "--local", str(self.upstream), str(self.pr))
        run(self.pr, "git", "checkout", "-q", "-b", "feature")
        self.pkg = self.pr / "sim" / PASSIVE / "solver-artifacts" / self.rid
        self.relpkg = f"sim/{PASSIVE}/solver-artifacts/{self.rid}"

    def history(self) -> list[str]:
        return chk.check_append_only(self.pr, "origin/trunk", True)[0].items

    def assertHistoryFails(self, *needles: str):
        found = self.history()
        self.assertTrue(found, "history check passed a tampering commit")
        for n in needles:
            self.assertTrue(any(n in p for p in found), f"no {n!r} in:\n" + "\n".join(found))

    def test_base_tree_is_clean_and_valid(self):
        self.assertEqual(self.history(), [])
        self.assertEqual(chk.check_format(self.pr).items, [])

    def test_modify_package_file(self):
        (self.pkg / "results/p1_metrics.json").write_text("{}")
        commit(self.pr)
        self.assertHistoryFails("p1_metrics.json", "modified")

    def test_modify_manifest(self):
        (self.pkg / "manifest.json").write_text("{}")
        commit(self.pr)
        self.assertHistoryFails("manifest.json", "modified")

    def test_delete_package_file(self):
        (self.pkg / "run_log/em_p1.txt").unlink()
        commit(self.pr)
        self.assertHistoryFails("em_p1.txt", "deleted")

    def test_rename_package_file(self):
        run(self.pr, "git", "mv", f"{self.relpkg}/run_log/em_p1.txt", f"{self.relpkg}/run_log/em_p1_renamed.txt")
        commit(self.pr)
        self.assertHistoryFails("em_p1.txt", "deleted or renamed")

    def test_rename_package_directory(self):
        run(self.pr, "git", "mv", self.relpkg, f"sim/{PASSIVE}/solver-artifacts/20261011-000000-abcdef1")
        commit(self.pr)
        self.assertHistoryFails("deleted or renamed")

    def test_add_file_to_existing_run_id(self):
        (self.pkg / "results").mkdir(exist_ok=True)
        (self.pkg / "results/late.json").write_text("{}")
        commit(self.pr)
        self.assertHistoryFails("late.json", "adds a file to record")

    def test_fresh_complete_publication_passes_history_and_format(self):
        wd = Path(self._work.name) / "wd2"
        write_workdir(wd, "B", compare=False)
        make_v2_record(self.pr, "UNCONVERGED", wd, ts="20261013-000000", stages="em convergence post")
        commit(self.pr, "new run")
        self.assertEqual(self.history(), [])
        self.assertEqual(chk.check_format(self.pr).items, [])

    def test_scratch_directories_stay_unprotected(self):
        (self.pr / "sim" / PASSIVE / "results").mkdir(exist_ok=True)
        (self.pr / "sim" / PASSIVE / "results" / "p1_metrics.json").write_text("{}\n")
        commit(self.pr)
        self.assertEqual(self.history(), [])


class Reanalysis(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        wd = self.base / "wd"
        write_workdir(wd, "A")
        r = fz.publish(str(wd), str(self.base / "solver-artifacts"), "20261010-000001-abcdef1", "QUALIFIED", STAGES,
                       has_compare=True)
        self.pkg = Path(r["dir"])
        self.record = self.base / "records" / "rec.json"
        self.record.parent.mkdir()
        self.record.write_text("original record\n")
        # test doubles for the analysis scripts: deterministic, numpy-free
        self.stubs = self.base / "stubs"
        self.stubs.mkdir()
        body = ("import argparse,json,os\na=argparse.ArgumentParser();a.add_argument('--dir');d=a.parse_args().dir\n"
                "%s\n")
        (self.stubs / "postprocess_p1.py").write_text(body % (
            "os.makedirs(d+'/results',exist_ok=True);json.dump({'tag':'A','band':[1,2,3]},open(d+'/results/p1_metrics.json','w'))"))
        (self.stubs / "fit_p1.py").write_text(body % (
            "os.makedirs(d+'/fit',exist_ok=True);open(d+'/fit/p1_fit_candidate.spice','w').write('* fit')"))
        (self.stubs / "compare_p1.py").write_text(body % (
            "json.dump({'tag':'A','zse':{}},open(d+'/results/p1_compare.json','w'))"))

    def test_reanalysis_is_separate_and_leaves_package_and_record_untouched(self):
        before_pkg, before_rec = tree_hash(self.pkg), self.record.read_bytes()
        out = self.base / "reanalysis"
        s = rz.reanalyze(str(self.pkg), str(out), sys.executable, scripts_dir=str(self.stubs))
        self.assertEqual([r["exit"] for r in s["runs"]], [0, 0, 0])
        self.assertEqual(s["equals_frozen_json"], {"results/p1_metrics.json": True, "results/p1_compare.json": True})
        self.assertTrue((out / "reanalysis.json").is_file())
        self.assertTrue((out / "work/results/p1_metrics.json").is_file())
        self.assertEqual(tree_hash(self.pkg), before_pkg)
        self.assertEqual(self.record.read_bytes(), before_rec)
        self.assertEqual(fz.verify(str(self.pkg)), [])

    def test_staged_inputs_are_only_solver_numerics(self):
        out = self.base / "dry"
        s = rz.reanalyze(str(self.pkg), str(out), dry_run=True)
        self.assertEqual(sorted(s["staged_inputs"]), sorted(fz.SOLVER_FILES))
        self.assertFalse((out / "work/results/p1_metrics.json").exists(), "frozen derived results must not be pre-staged")
        self.assertEqual(s["runs"], [])

    def test_tampered_package_refused(self):
        (self.pkg / "results/inductor_p1.s2p").write_text("edited\n")
        with self.assertRaises(rz.ReanalysisError) as cm:
            rz.reanalyze(str(self.pkg), str(self.base / "o"), dry_run=True)
        self.assertIn("integrity", str(cm.exception))
        self.assertFalse((self.base / "o").exists())

    def test_output_inside_package_or_records_refused(self):
        for bad in (self.pkg / "reanalysis", self.base / "records" / "x", self.base / "solver-artifacts" / "y"):
            with self.assertRaises(rz.ReanalysisError, msg=str(bad)):
                rz.reanalyze(str(self.pkg), str(bad), dry_run=True)

    def test_existing_nonempty_output_refused(self):
        out = self.base / "o2"
        out.mkdir()
        (out / "keep").write_text("x")
        with self.assertRaises(rz.ReanalysisError):
            rz.reanalyze(str(self.pkg), str(out), dry_run=True)

    def test_cli_exit_codes(self):
        r = subprocess.run([sys.executable, str(REPO / "sim/passive-p1/scripts/reanalyze_frozen.py"), str(self.pkg),
                            "--out", str(self.base / "cli"), "--dry-run"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([sys.executable, str(REPO / "sim/passive-p1/scripts/reanalyze_frozen.py"), str(self.pkg),
                            "--out", str(self.pkg / "inside")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
