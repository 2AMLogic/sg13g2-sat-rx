"""Negative controls for the mixer-cm-interface-probe layout of check_evidence_formats.py (issue #89).

A complete, self-consistent synthetic run (record pair + probe-log package) is built
with the REAL ``run_probe`` renderers from a fabricated, closed-form ngspice log, in a
temporary tree. Each test breaks exactly one rule and asserts a file-specific failure;
the unbroken run must pass. No simulator, PDK or network. The real tree is not modified.

Run: python3 -m unittest discover -s .github/scripts/tests -p 'test_check_cm_adapter.py'
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
BENCH = REPO / "sim" / "mixer-cm-interface-probe"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "tests"))

import check_evidence_formats as chk  # noqa: E402
import cmprobe as C  # noqa: E402
import fakelog  # noqa: E402
import run_probe as R  # noqa: E402

NAME = "mixer-cm-interface-probe"
RID = "20261010-120000-abcdef1"
SHA = "a" * 64


def make_env(rid: str) -> dict:
    return {"host": "h", "platform": "p", "python": "3.12", "git": {"commit": rid.split("-")[2] + "0" * 33, "dirty": False},
            "placeholder_sha256": SHA, "pdk_artifact_sha256": SHA,
            "ngspice": {"path": "/x/ngspice", "version": "ngspice-46", "major": 46, "sha256": SHA},
            "pdk": {"path": "/pdk", "fetched_version": "0.3.0", "sha256": {"cornerHBT.lib": SHA, "sg13g2_hbt_mod.lib": SHA},
                    "device": "npn13G2"},
            "pdk_integrity": {"gate": "stub", "ok": True, "problems": [], "notes": ["models match"]}}


def write_probe_run(root: Path, rid: str = RID, gate: bool = True) -> str:
    """A complete fresh probe run: record pair + probe-log package. Returns the file stem.

    gate=False builds the env a pre-#107 record carries (no 'pdk_integrity' key)."""
    exp = root / "sim" / NAME
    stdout = fakelog.stdout(fakelog.marks())
    parsed = C.parse_log(stdout, "")
    matrix = C.build_matrix(parsed, R.REFERENCES)
    ctl = C.evaluate_control(parsed["marks"])
    status, reasons = C.decide_status(True, matrix)
    env = make_env(rid)
    if not gate:
        env.pop("pdk_integrity")
    rec = {"record_id": rid, "status": status, "reasons": reasons,
           "scope": "interface-feasibility evidence only; no row-10/row-12 claim; no active-mixer NF number",
           "nominal_point": {"corner": "hbt_typ"}, "interface_matrix": matrix, "controls": ctl,
           "references": R.REFERENCES, "probe_logs": f"sim/{NAME}/probe-logs/{rid}/", "environment": env}
    (exp / "records").mkdir(parents=True, exist_ok=True)
    stem = f"{rid}-{status}"
    (exp / "records" / f"{stem}.json").write_text(json.dumps(rec, indent=2) + "\n")
    (exp / "records" / f"{stem}.md").write_text(R.render_md(rid, status, reasons, matrix, ctl, env))
    logs = exp / "probe-logs" / rid
    logs.mkdir(parents=True)
    (logs / "deck.spice").write_text("* deck\n")
    (logs / "stdout.txt").write_text(stdout)
    (logs / "stderr.txt").write_text("")
    (logs / "inventory.json").write_text(json.dumps({"parsed": parsed, "interface_matrix": matrix}, indent=2) + "\n")
    return stem


def write_unavailable(root: Path, rid: str = RID) -> str:
    exp = root / "sim" / NAME
    (exp / "records").mkdir(parents=True, exist_ok=True)
    status = "CAPABILITY_UNAVAILABLE"
    failed = "pinned ngspice-46 not found"
    env = {k: v for k, v in make_env(rid).items() if k not in ("ngspice", "pdk", "pdk_integrity")}
    rec = {"record_id": rid, "status": status, "reasons": ["pinned simulator not available"],
           "failed_check": failed, "scope": "no probe ran; no active-mixer NF number; no row-10/row-12 claim",
           "environment": env}
    stem = f"{rid}-{status}"
    (exp / "records" / f"{stem}.json").write_text(json.dumps(rec, indent=2) + "\n")
    (exp / "records" / f"{stem}.md").write_text(R.render_unavailable_md(rid, status, failed))
    return stem


def edit_json(path: Path, fn) -> None:
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data, indent=2) + "\n")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        exp = self.root / "sim" / NAME
        exp.mkdir(parents=True)
        shutil.copyfile(BENCH / "README.md", exp / "README.md")
        # one small PVT bench so "no benches found" cannot fire
        shutil.copytree(REPO / "sim" / "lna-sparam-nf", self.root / "sim" / "lna-sparam-nf",
                        ignore=shutil.ignore_patterns("_build", "_selftest", "__pycache__"))
        self.exp = exp
        self.rec = exp / "records"

    def problems(self) -> list[str]:
        return chk.check_format(self.root).items

    def assertFails(self, *needles: str):
        found = self.problems()
        self.assertTrue(found, "checker passed a deliberately broken tree")
        for needle in needles:
            self.assertTrue(any(needle in p for p in found), f"no problem mentioning {needle!r} in:\n" + "\n".join(found))


class ProbeRun(Base):
    def setUp(self):
        super().setUp()
        self.stem = write_probe_run(self.root)
        self.js = self.rec / f"{self.stem}.json"
        self.md = self.rec / f"{self.stem}.md"
        self.logs = self.exp / "probe-logs" / RID

    def test_adapter_registered(self):
        self.assertIn(NAME, chk.ADAPTERS)

    def test_fresh_complete_run_passes(self):
        self.assertEqual(self.problems(), [])
        self.assertIn("Model integrity gate", self.md.read_text())

    def test_pre_gate_run_without_pdk_integrity_still_renders_and_passes(self):
        for p in (self.js, self.md):
            p.unlink()
        shutil.rmtree(self.logs)
        stem = write_probe_run(self.root, gate=False)
        self.assertNotIn("pdk_integrity", json.loads((self.rec / f"{stem}.json").read_text())["environment"])
        self.assertNotIn("Model integrity gate", (self.rec / f"{stem}.md").read_text())
        self.assertEqual(self.problems(), [])

    def test_statuses_are_not_the_27_vocabulary(self):
        self.assertNotIn("METHOD_VALIDATION", chk.CM_STATUSES)
        old = self.rec / f"{RID}-MODEL_ABSENT"
        self.md.rename(old.with_suffix(".md"))
        self.js.rename(old.with_suffix(".json"))
        self.assertFails("status 'MODEL_ABSENT' is not one of")

    def test_method_validation_status_rejected(self):
        for ext in ("md", "json"):
            (self.rec / f"{self.stem}.{ext}").rename(self.rec / f"{RID}-METHOD_VALIDATION.{ext}")
        self.assertFails("status 'METHOD_VALIDATION' is not one of")

    def test_missing_markdown_half(self):
        self.md.unlink()
        self.assertFails("no paired .md")

    def test_malformed_json(self):
        self.js.write_text("{nope")
        self.assertFails("not valid JSON")

    def test_json_status_disagrees(self):
        edit_json(self.js, lambda d: d.update(status="INTERFACES_PARTIAL"))
        self.assertFails("does not match file name status")

    def test_markdown_status_disagrees(self):
        self.md.write_text(self.md.read_text().replace("- **Status: INTERFACES_BLOCKED**", "- **Status: INTERFACES_PARTIAL**"))
        self.assertFails("does not state '- **Status: INTERFACES_BLOCKED**'")

    def test_first_line_must_name_the_bench(self):
        self.md.write_text(self.md.read_text().replace("# mixer-cm-interface-probe record", "# mixer-nf-method record", 1))
        self.assertFails("first line must be")

    def test_record_id_disagrees(self):
        edit_json(self.js, lambda d: d.update(record_id="20261010-120001-abcdef1"))
        self.assertFails("does not match the record id")

    def test_scope_disclaimer_required(self):
        edit_json(self.js, lambda d: d.update(scope="interface evidence"))
        self.assertFails("does not disclaim an active-mixer NF number")

    def test_commit_does_not_match_id(self):
        edit_json(self.js, lambda d: d["environment"]["git"].update(commit="1234567" + "0" * 33))
        self.assertFails("does not match the sha in the record id")

    def test_missing_environment_hash(self):
        edit_json(self.js, lambda d: d["environment"].pop("pdk_artifact_sha256"))
        self.assertFails("pdk_artifact_sha256")

    def test_missing_ngspice_hash(self):
        edit_json(self.js, lambda d: d["environment"]["ngspice"].update(sha256="short"))
        self.assertFails("environment.ngspice.sha256")

    def test_empty_reasons(self):
        edit_json(self.js, lambda d: d.update(reasons=[]))
        self.assertFails("'reasons' must be a non-empty list")

    # ---- interface matrix rules -------------------------------------------------
    def test_missing_interface(self):
        edit_json(self.js, lambda d: d["interface_matrix"].pop("noise_covariance_ib_ic"))
        self.assertFails("interface_matrix keys")

    def test_extra_interface(self):
        edit_json(self.js, lambda d: d["interface_matrix"].update(bonus={"state": "demonstrated"}))
        self.assertFails("interface_matrix keys")

    def test_invalid_state(self):
        edit_json(self.js, lambda d: d["interface_matrix"]["lo_period_trajectory"].update(state="maybe"))
        self.assertFails("state 'maybe' is not one of")

    def test_missing_reference(self):
        edit_json(self.js, lambda d: d["interface_matrix"]["noise_covariance_ib_ic"].update(reference=""))
        self.assertFails("no primary 'reference'")

    def test_probe_basis_needs_marks(self):
        edit_json(self.js, lambda d: d["interface_matrix"]["lo_period_trajectory"].pop("probe_marks"))
        self.assertFails("no 'probe_marks' object")

    def test_status_must_follow_from_states(self):
        def flip(d):
            for ent in d["interface_matrix"].values():
                ent["state"] = "demonstrated"
        edit_json(self.js, flip)
        self.assertFails("does not follow from the interface states")

    def test_transfer_demonstrated_requires_passing_control(self):
        edit_json(self.js, lambda d: d["controls"].update({"pass": False}))
        self.assertFails("known-answer control did not pass")

    def test_controls_verdict_required(self):
        edit_json(self.js, lambda d: d.pop("controls"))
        self.assertFails("controls.pass")

    # ---- probe-log package ----------------------------------------------------------
    def test_missing_probe_log_package(self):
        shutil.rmtree(self.logs)
        self.assertFails("does not exist")

    def test_missing_probe_log_file(self):
        (self.logs / "stdout.txt").unlink()
        self.assertFails("missing stdout.txt")

    def test_unexpected_probe_log_file(self):
        (self.logs / "extra.txt").write_text("x")
        self.assertFails("unexpected file in a probe-log package")

    def test_empty_deck(self):
        (self.logs / "deck.spice").write_text("")
        self.assertFails("probe-log file is empty")

    def test_inventory_disagrees_with_record(self):
        def tamper(d):
            d["interface_matrix"]["lo_period_trajectory"]["state"] = "unknown"
        edit_json(self.logs / "inventory.json", tamper)
        self.assertFails("differs from the record's")

    def test_inventory_shape(self):
        edit_json(self.logs / "inventory.json", lambda d: d.pop("parsed"))
        self.assertFails("needs 'parsed' and 'interface_matrix'")

    def test_wrong_probe_logs_pointer(self):
        edit_json(self.js, lambda d: d.update(probe_logs="sim/elsewhere/"))
        self.assertFails("probe_logs")

    def test_orphan_probe_log_package(self):
        shutil.copytree(self.logs, self.exp / "probe-logs" / "20261010-130000-abcdef1")
        self.assertFails("belongs to no record")

    def test_foreign_dirs_rejected(self):
        (self.exp / "corners").mkdir()
        self.assertFails("is not part of the mixer-cm-interface-probe evidence layout")

    def test_stray_file_in_records(self):
        (self.rec / "notes.md").write_text("x")
        self.assertFails("not a <YYYYMMDD>-<HHMMSS>-<git-sha>-<STATUS>")

    def test_bench_readme_required(self):
        (self.exp / "README.md").unlink()
        self.assertFails("bench has records/ but no cold-start README")


class Unavailable(Base):
    def setUp(self):
        super().setUp()
        self.stem = write_unavailable(self.root)
        self.js = self.rec / f"{self.stem}.json"
        self.md = self.rec / f"{self.stem}.md"

    def test_valid_without_logs(self):
        self.assertEqual(self.problems(), [])

    def test_carries_no_probe_results(self):
        for key, val in (("interface_matrix", {}), ("probe_logs", "x"), ("controls", {})):
            with self.subTest(key=key):
                edit_json(self.js, lambda d, k=key, v=val: d.update({k: v}))
                self.assertFails(f"carries '{key}'")
                edit_json(self.js, lambda d, k=key: d.pop(k))

    def test_failed_check_required(self):
        edit_json(self.js, lambda d: d.pop("failed_check"))
        self.assertFails("failed_check")

    def test_markdown_failed_check_statement(self):
        self.md.write_text(self.md.read_text().replace("Failed check:", "Failure:"))
        self.assertFails("missing the 'Failed check:' statement")

    def test_scope_disclaimer_required(self):
        edit_json(self.js, lambda d: d.update(scope="no probe ran"))
        self.assertFails("does not disclaim an active-mixer NF number")

    def test_unavailable_with_logs_is_orphan(self):
        logs = self.exp / "probe-logs" / RID
        logs.mkdir(parents=True)
        (logs / "deck.spice").write_text("x")
        self.assertFails("belongs to no record")


def run(cwd: Path, *args: str) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def commit(cwd: Path, msg: str = "c") -> None:
    run(cwd, "git", "add", "-A")
    run(cwd, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


class History(unittest.TestCase):
    """The append-only check must cover the new bench's records/ and probe-logs/."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name) / "upstream"
        (base / "sim" / NAME).mkdir(parents=True)
        write_probe_run(base)
        run(base, "git", "init", "-q", "-b", "trunk")
        commit(base, "base")
        self.pr = Path(self._tmp.name) / "pr"
        run(Path(self._tmp.name), "git", "clone", "-q", "--local", str(base), str(self.pr))
        run(self.pr, "git", "checkout", "-q", "-b", "feature")

    def history(self) -> list[str]:
        return chk.check_append_only(self.pr, "origin/trunk", True)[0].items

    def test_clean_branch_passes(self):
        self.assertEqual(self.history(), [])

    def test_modifying_record_fails(self):
        p = next((self.pr / "sim" / NAME / "records").glob("*.md"))
        p.write_text(p.read_text() + "\nedited\n")
        commit(self.pr)
        self.assertTrue(any("modified" in x for x in self.history()))

    def test_modifying_probe_log_fails(self):
        (self.pr / "sim" / NAME / "probe-logs" / RID / "stdout.txt").write_text("edited\n")
        commit(self.pr)
        self.assertTrue(any("probe-logs" in x for x in self.history()))

    def test_appending_a_new_record_passes(self):
        write_unavailable(self.pr, "20261011-120000-abcdef1")
        commit(self.pr)
        self.assertEqual(self.history(), [])


if __name__ == "__main__":
    unittest.main()
