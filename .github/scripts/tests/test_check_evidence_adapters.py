"""Tests for the passive-p1 / mixer-nf-method adapters of check_evidence_formats.py.

Standard library only (unittest; pytest also collects it). No simulator, PDK
or network: every test works on a temporary copy of the committed evidence or
a temporary git history of it, breaks exactly one thing, and asserts the
checker fails with a file-specific message. The real tree is never modified.

Run: python3 -m unittest discover -s .github/scripts/tests -p 'test_check_evidence_adapters.py'
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO / "sim" / "passive-p1" / "scripts"))

import check_evidence_formats as chk  # noqa: E402
import freeze_package as fz  # noqa: E402

PASSIVE = "passive-p1"
MIXER = "mixer-nf-method"
LNAMATCH = "lna-match-tradeoff"  # its negative controls: test_check_lnamatch_adapter.py
CMPROBE = "mixer-cm-interface-probe"  # its negative controls: test_check_cm_adapter.py
PRA = "mixer-pumped-rf-admittance"  # its negative controls: test_check_pra_adapter.py
P_UNAVAIL = "20261009-141515-0e10117-CAPABILITY_UNAVAILABLE"
P_CONTROLS = "20261009-141527-0e10117-CONTROLS-PASS"
M_ID = "20261009-181241-c40c552"
M_REC = f"{M_ID}-MODEL_ABSENT"
IGNORE = shutil.ignore_patterns("_build", "_selftest", "__pycache__")
# Both adapter campaigns in full (their records name input files, so scripts
# must come along) plus one small PVT bench so "no benches found" cannot fire.
COPIED = (PASSIVE, MIXER, "lna-sparam-nf")


def copy_sim(dst: Path) -> Path:
    for name in COPIED:
        shutil.copytree(REPO / "sim" / name, dst / "sim" / name, symlinks=False, ignore=IGNORE)
    return dst


def run(cwd: Path, *args: str) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def commit(cwd: Path, msg: str = "c") -> None:
    run(cwd, "git", "add", "-A")
    run(cwd, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


def edit_json(path: Path, fn) -> None:
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data, indent=2) + "\n")


def upgrade_to_v2(root: Path, rid: str, status: str) -> None:
    """Give a cloned legacy-shaped passive record the record_schema 2 package it now needs
    (settings-only package: valid for CAPABILITY_UNAVAILABLE, no solver data invented)."""
    exp = root / "sim" / PASSIVE
    with tempfile.TemporaryDirectory() as work:
        r = fz.publish(work, str(exp / "solver-artifacts"), rid, status, "geometry em convergence post fit compare")
    stem = f"{rid}-{status}"
    edit_json(exp / "records" / f"{stem}.json", lambda d: d.update(
        record_schema=2, stages="geometry em convergence post fit compare",
        artifact_package={"schema": fz.SCHEMA, "path": f"sim/{PASSIVE}/solver-artifacts/{rid}/",
                          "manifest": "manifest.json", "manifest_sha256": r["manifest_sha256"], "files": r["files"]}))
    md = exp / "records" / f"{stem}.md"
    md.write_text(md.read_text() + f"\n## Frozen solver artifacts\n\n- Package: `sim/{PASSIVE}/solver-artifacts/{rid}/`\n"
                  f"- Manifest sha256 `{r['manifest_sha256']}`\n")


def clone_passive_unavailable(root: Path, new_ts: str = "20261010-000000") -> str:
    """Append a complete, self-consistent copy of the passive record pair under a new id."""
    rec = root / "sim" / PASSIVE / "records"
    new = P_UNAVAIL.replace("20261009-141515", new_ts)
    iso = f"{new_ts[:4]}-{new_ts[4:6]}-{new_ts[6:8]}T{new_ts[9:11]}:{new_ts[11:13]}:{new_ts[13:15]}"
    for ext in ("md", "json"):
        text = (rec / f"{P_UNAVAIL}.{ext}").read_text().replace("20261009-141515", new_ts)
        text = text.replace("2026-10-09T14:15:15", iso)
        (rec / f"{new}.{ext}").write_text(text)
    upgrade_to_v2(root, new.rsplit("-", 1)[0], "CAPABILITY_UNAVAILABLE")
    return new


def clone_mixer_run(root: Path, new_ts: str = "20261010-000000") -> str:
    """Append a complete fresh mixer run (record pair + probe-log package)."""
    exp = root / "sim" / MIXER
    new_id = M_ID.replace("20261009-181241", new_ts)
    for ext in ("md", "json"):
        text = (exp / "records" / f"{M_REC}.{ext}").read_text().replace(M_ID, new_id)
        (exp / "records" / f"{new_id}-MODEL_ABSENT.{ext}").write_text(text)
    shutil.copytree(exp / "probe-logs" / M_ID, exp / "probe-logs" / new_id)
    # the inventory travels unchanged; nothing in the package names the id
    return new_id


class FormatBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_sim(Path(self._tmp.name))
        self.passive = self.root / "sim" / PASSIVE
        self.mixer = self.root / "sim" / MIXER

    def problems(self) -> list[str]:
        return chk.check_format(self.root).items

    def assertFails(self, *needles: str):
        found = self.problems()
        self.assertTrue(found, "checker passed a deliberately broken tree")
        for needle in needles:
            self.assertTrue(any(needle in p for p in found),
                            f"no problem mentioning {needle!r} in:\n" + "\n".join(found))


class CommittedEvidence(FormatBase):
    def test_real_tree_passes_unmodified(self):
        self.assertEqual(chk.check_format(REPO).items, [])

    def test_copy_passes(self):
        self.assertEqual(self.problems(), [])

    def test_adapters_are_registered_explicitly(self):
        self.assertEqual(set(chk.ADAPTERS), {PASSIVE, MIXER, LNAMATCH, CMPROBE, PRA})

    def test_adapters_actually_run(self):
        # if discovery silently skipped these layouts this would stay green
        (self.passive / "records" / f"{P_UNAVAIL}.json").unlink()
        self.assertFails("no paired .json")


class Discovery(FormatBase):
    def test_unrecognised_layout_fails_visibly(self):
        (self.root / "sim" / "newcampaign" / "records").mkdir(parents=True)
        (self.root / "sim" / "newcampaign" / "records" / "x.md").write_text("# x\n")
        self.assertFails("sim/newcampaign", "unrecognised evidence layout")

    def test_unrecognised_probe_logs_only_dir_fails(self):
        (self.root / "sim" / "other" / "probe-logs").mkdir(parents=True)
        self.assertFails("sim/other", "unrecognised evidence layout")

    def test_dir_without_evidence_dirs_is_not_a_layout(self):
        (self.root / "sim" / "scratch-notes").mkdir()
        (self.root / "sim" / "scratch-notes" / "a.txt").write_text("x")
        self.assertEqual(self.problems(), [])


class Passive(FormatBase):
    rec = property(lambda self: self.passive / "records")

    def test_fresh_pair_passes(self):
        clone_passive_unavailable(self.root)
        self.assertEqual(self.problems(), [])

    def test_missing_markdown_half(self):
        new = clone_passive_unavailable(self.root)
        (self.rec / f"{new}.md").unlink()
        self.assertFails(f"{new}.json", "no paired .md")

    def test_malformed_json(self):
        new = clone_passive_unavailable(self.root)
        (self.rec / f"{new}.json").write_text("{not json")
        self.assertFails(f"{new}.json", "not valid JSON")

    def test_json_status_disagrees_with_filename(self):
        new = clone_passive_unavailable(self.root)
        edit_json(self.rec / f"{new}.json", lambda d: d.update(status="QUALIFIED"))
        self.assertFails("JSON status 'QUALIFIED'")

    def test_json_record_id_disagrees(self):
        new = clone_passive_unavailable(self.root)
        edit_json(self.rec / f"{new}.json", lambda d: d.update(record_id="20260101-000000-abcdef0-X"))
        self.assertFails("record_id")

    def test_markdown_status_line_disagrees(self):
        new = clone_passive_unavailable(self.root)
        md = self.rec / f"{new}.md"
        md.write_text(md.read_text().replace("**Status: CAPABILITY_UNAVAILABLE**", "**Status: QUALIFIED**"))
        self.assertFails("does not state '- **Status: CAPABILITY_UNAVAILABLE**'")

    def test_unknown_status_rejected(self):
        new = clone_passive_unavailable(self.root)
        for ext in ("md", "json"):
            (self.rec / f"{new}.{ext}").rename(self.rec / f"{new[:-len('CAPABILITY_UNAVAILABLE')]}WIBBLE.{ext}")
        self.assertFails("status 'WIBBLE'")

    def test_unavailable_with_numbers_rejected(self):
        new = clone_passive_unavailable(self.root)
        edit_json(self.rec / f"{new}.json", lambda d: d.update(metrics={"L_h": 1e-10}))
        self.assertFails("carries metrics/compare numbers")

    def test_missing_provenance(self):
        new = clone_passive_unavailable(self.root)
        edit_json(self.rec / f"{new}.json", lambda d: d.pop("environment"))
        self.assertFails("'environment' is missing")

    def test_digest_markdown_json_mismatch(self):
        new = clone_passive_unavailable(self.root)
        edit_json(self.rec / f"{new}.json", lambda d: d.update(numerical_digest="0" * 64))
        self.assertFails("does not carry the JSON numerical_digest")

    def test_timestamp_mismatch(self):
        new = clone_passive_unavailable(self.root)
        edit_json(self.rec / f"{new}.json", lambda d: d.update(utc="2020-01-01T00:00:00+00:00"))
        self.assertFails("does not match the record id timestamp")

    def test_missing_declared_input_companion(self):
        new = clone_passive_unavailable(self.root)
        def add(d):
            d["input_hashes"]["files"]["scripts/does_not_exist.py"] = {"sha256": "a" * 64}
        edit_json(self.rec / f"{new}.json", add)
        self.assertFails("declared input 'scripts/does_not_exist.py' does not exist")

    def test_missing_declared_run_log(self):
        # legacy (pre-#58) records keep the existence-only run_log rule
        md = self.rec / f"{P_UNAVAIL}.md"
        md.write_text(md.read_text() + "\nSee `run_log/vanished.txt`.\n")
        self.assertFails("declared companion run_log/vanished.txt does not exist")

    def test_synthetic_record_in_records_rejected(self):
        new = clone_passive_unavailable(self.root)
        edit_json(self.rec / f"{new}.json", lambda d: d.update(synthetic=True))
        self.assertFails("synthetic smoke record inside records/")

    def test_synthetic_status_prefix_rejected(self):
        new = clone_passive_unavailable(self.root)
        for ext in ("md", "json"):
            (self.rec / f"{new}.{ext}").rename(self.rec / f"{new.replace('-CAPABILITY', '-SYNTHETIC-CAPABILITY')}.{ext}")
        self.assertFails("synthetic smoke record inside records/")

    def test_stray_file_in_records(self):
        (self.rec / "notes.txt").write_text("x")
        self.assertFails("notes.txt", "not a <YYYYMMDD>")

    def test_controls_all_pass_contradicts_status(self):
        edit_json(self.rec / f"{P_CONTROLS}.json", lambda d: d.update(all_pass=False))
        self.assertFails("all_pass=False contradicts status suffix")

    def test_controls_group_result_disagrees_with_markdown(self):
        md = self.rec / f"{P_CONTROLS}.md"
        md.write_text(md.read_text().replace("## malformed -- PASS", "## malformed -- FAIL"))
        self.assertFails("control sections disagree")

    def test_controls_missing_fixture(self):
        edit_json(self.rec / f"{P_CONTROLS}.json", lambda d: d.update(fixture="fixtures/gone.s2p"))
        self.assertFails("declared fixture 'fixtures/gone.s2p' does not exist")

    def test_controls_pass_is_valid_evidence(self):
        self.assertEqual([p for p in self.problems() if P_CONTROLS in p], [])


class MixerMethod(FormatBase):
    rec = property(lambda self: self.mixer / "records")

    def test_fresh_complete_run_passes(self):
        clone_mixer_run(self.root)
        self.assertEqual(self.problems(), [])

    def test_missing_markdown_half(self):
        new = clone_mixer_run(self.root)
        (self.rec / f"{new}-MODEL_ABSENT.md").unlink()
        self.assertFails("no paired .md")

    def test_malformed_json(self):
        new = clone_mixer_run(self.root)
        (self.rec / f"{new}-MODEL_ABSENT.json").write_text("[1, 2]")
        self.assertFails("JSON top level is not an object")

    def test_json_status_disagrees(self):
        new = clone_mixer_run(self.root)
        edit_json(self.rec / f"{new}-MODEL_ABSENT.json", lambda d: d.update(status="UNCONVERGED"))
        self.assertFails("JSON status 'UNCONVERGED'")

    def test_markdown_status_disagrees(self):
        new = clone_mixer_run(self.root)
        md = self.rec / f"{new}-MODEL_ABSENT.md"
        md.write_text(md.read_text().replace("- **Status: MODEL_ABSENT**", "- **Status: METHOD_VALIDATION**"))
        self.assertFails("does not state '- **Status: MODEL_ABSENT**'")

    def test_unknown_status(self):
        new = clone_mixer_run(self.root)
        for ext in ("md", "json"):
            (self.rec / f"{new}-MODEL_ABSENT.{ext}").rename(self.rec / f"{new}-GREAT.{ext}")
        self.assertFails("status 'GREAT'")

    def test_json_record_id_disagrees(self):
        new = clone_mixer_run(self.root)
        edit_json(self.rec / f"{new}-MODEL_ABSENT.json", lambda d: d.update(record_id=M_ID))
        self.assertFails("JSON record_id")

    def test_missing_provenance_hash(self):
        new = clone_mixer_run(self.root)
        edit_json(self.rec / f"{new}-MODEL_ABSENT.json", lambda d: d["environment"]["ngspice"].pop("sha256"))
        self.assertFails("environment.ngspice.sha256")

    def test_commit_does_not_match_id(self):
        new = clone_mixer_run(self.root)
        edit_json(self.rec / f"{new}-MODEL_ABSENT.json",
                  lambda d: d["environment"]["git"].update(commit="deadbeef" * 5))
        self.assertFails("environment.git.commit")

    def test_scope_disclaimer_required(self):
        new = clone_mixer_run(self.root)
        edit_json(self.rec / f"{new}-MODEL_ABSENT.json", lambda d: d.update(scope="all good"))
        self.assertFails("does not disclaim an active-mixer NF number")

    def test_missing_probe_log_package(self):
        new = clone_mixer_run(self.root)
        shutil.rmtree(self.mixer / "probe-logs" / new)
        self.assertFails("declared probe-log package", "does not exist")

    def test_missing_probe_log_file(self):
        new = clone_mixer_run(self.root)
        (self.mixer / "probe-logs" / new / "stdout.txt").unlink()
        self.assertFails("probe-log package is missing stdout.txt")

    def test_unexpected_probe_log_file(self):
        new = clone_mixer_run(self.root)
        (self.mixer / "probe-logs" / new / "extra.txt").write_text("x")
        self.assertFails("unexpected file in a probe-log package")

    def test_inventory_disagrees_with_record(self):
        new = clone_mixer_run(self.root)
        edit_json(self.mixer / "probe-logs" / new / "inventory.json", lambda d: d["inventory"].update(extra=1))
        self.assertFails("record and frozen log disagree")

    def test_orphan_probe_log_package(self):
        shutil.copytree(self.mixer / "probe-logs" / M_ID, self.mixer / "probe-logs" / "20261010-000000-c40c552")
        self.assertFails("belongs to no record")

    def test_wrong_probe_logs_pointer(self):
        new = clone_mixer_run(self.root)
        edit_json(self.rec / f"{new}-MODEL_ABSENT.json", lambda d: d.update(probe_logs=f"sim/{MIXER}/probe-logs/{M_ID}/"))
        self.assertFails("JSON probe_logs")

    def test_capability_unavailable_is_valid_without_logs(self):
        rid = "20261010-000000-c40c552"
        rec = {"record_id": rid, "status": "CAPABILITY_UNAVAILABLE", "reasons": ["no simulator"],
               "failed_check": "shutil.which('ngspice') is None",
               "environment": {"host": "h", "platform": "p", "python": "3", "git": {"commit": "c40c552" + "0" * 33}},
               "claims": "none; CAPABILITY_UNAVAILABLE cannot establish model absence"}
        (self.rec / f"{rid}-CAPABILITY_UNAVAILABLE.json").write_text(json.dumps(rec))
        (self.rec / f"{rid}-CAPABILITY_UNAVAILABLE.md").write_text(
            f"# mixer-nf-method record {rid}-CAPABILITY_UNAVAILABLE\n\n- **Status: CAPABILITY_UNAVAILABLE**\n"
            "- Failed check: `shutil.which('ngspice') is None`\n")
        self.assertEqual(self.problems(), [])
        edit_json(self.rec / f"{rid}-CAPABILITY_UNAVAILABLE.json", lambda d: d.update(probe_logs="x"))
        self.assertFails("cannot establish model absence")


class History(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.upstream = Path(cls._tmp.name) / "upstream"
        copy_sim(cls.upstream)
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
        self.logs = self.pr / "sim" / MIXER / "probe-logs" / M_ID

    def history(self) -> list[str]:
        return chk.check_append_only(self.pr, "origin/trunk", True)[0].items

    def assertHistoryFails(self, *needles: str):
        found = self.history()
        self.assertTrue(found, "history check passed a tampering commit")
        for needle in needles:
            self.assertTrue(any(needle in p for p in found), f"no {needle!r} in:\n" + "\n".join(found))

    def test_clean_branch_passes(self):
        self.assertEqual(self.history(), [])

    def test_modifying_probe_log_fails(self):
        (self.logs / "stdout.txt").write_text("edited\n")
        commit(self.pr)
        self.assertHistoryFails("probe-logs", "stdout.txt", "modified")

    def test_modifying_inventory_fails(self):
        (self.logs / "inventory.json").write_text("{}\n")
        commit(self.pr)
        self.assertHistoryFails("inventory.json", "modified")

    def test_deleting_probe_log_fails(self):
        (self.logs / "deck.spice").unlink()
        commit(self.pr)
        self.assertHistoryFails("deck.spice", "deleted")

    def test_renaming_probe_log_fails(self):
        run(self.pr, "git", "mv", f"sim/{MIXER}/probe-logs/{M_ID}/stderr.txt", f"sim/{MIXER}/probe-logs/{M_ID}/err.txt")
        commit(self.pr)
        self.assertHistoryFails("stderr.txt", "deleted or renamed")

    def test_renaming_probe_log_directory_fails(self):
        run(self.pr, "git", "mv", f"sim/{MIXER}/probe-logs/{M_ID}", f"sim/{MIXER}/probe-logs/20261010-000000-c40c552")
        commit(self.pr)
        self.assertHistoryFails("deleted or renamed")

    def test_adding_companion_to_existing_run_fails(self):
        (self.logs / "late-addition.txt").write_text("x\n")
        commit(self.pr)
        self.assertHistoryFails("late-addition.txt", "adds a file to record")

    def test_modifying_mixer_and_passive_records_still_fails(self):
        (self.pr / "sim" / MIXER / "records" / f"{M_REC}.md").write_text("edited\n")
        (self.pr / "sim" / PASSIVE / "records" / f"{P_UNAVAIL}.json").write_text("{}\n")
        commit(self.pr)
        self.assertHistoryFails(f"{M_REC}.md", f"{P_UNAVAIL}.json")

    def test_multicommit_tamper_is_not_hidden_by_later_commit(self):
        (self.logs / "stdout.txt").write_text("edited\n")
        commit(self.pr, "tamper")
        (self.pr / "sim" / MIXER / "README-note.txt").write_text("innocent")
        commit(self.pr, "later")
        self.assertHistoryFails("stdout.txt")

    def test_complete_fresh_run_passes_history_and_format(self):
        clone_mixer_run(self.pr)
        clone_passive_unavailable(self.pr)
        commit(self.pr, "fresh run")
        self.assertEqual(self.history(), [])
        self.assertEqual(chk.check_format(self.pr).items, [])

    def test_fresh_run_is_protected_once_it_is_the_base(self):
        new = clone_mixer_run(self.pr)
        commit(self.pr, "fresh run")
        merged = run(self.pr, "git", "rev-parse", "HEAD").strip()  # as if merged: the new base
        (self.pr / "sim" / MIXER / "probe-logs" / new / "stdout.txt").write_text("rewritten\n")
        commit(self.pr, "tamper")
        found = chk.check_append_only(self.pr, merged, True)[0].items
        self.assertTrue(any(new in p and "stdout.txt" in p and "modified" in p for p in found), found)

    def test_working_outputs_are_not_protected(self):
        # passive solver working output (results/, run_log/) is mutable by design
        (self.pr / "sim" / PASSIVE / "run_log" / "geometry_p1.txt").write_text("rerun\n")
        (self.pr / "sim" / PASSIVE / "results" / "p1_metrics.json").write_text("{}\n")
        commit(self.pr)
        self.assertEqual(self.history(), [])


if __name__ == "__main__":
    unittest.main()
