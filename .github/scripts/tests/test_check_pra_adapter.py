"""Negative controls for the mixer-pumped-rf-admittance layout of check_evidence_formats.py (issue #111).

A complete, self-consistent synthetic run (record pair + probe-log package) is built
with the REAL ``run_probe`` renderer and ``pumped.evaluate`` on closed-form marks, in a
temporary tree. Each test breaks exactly one rule and asserts a file-specific failure;
the unbroken run must pass. No simulator, PDK or network. The real tree is not modified.

Run: python3 -m unittest discover -s .github/scripts/tests -p 'test_check_pra_adapter.py'
"""

from __future__ import annotations

import cmath
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parents[1]
BENCH = REPO / "sim" / "mixer-pumped-rf-admittance"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(BENCH))

import check_evidence_formats as chk  # noqa: E402
import pumped as P  # noqa: E402


def _load(name: str, path: Path):
    """Import a bench module under a unique name: several benches ship a ``run_probe.py``
    and the checker tests share one interpreter, so a plain ``import run_probe`` would hand
    the sibling test whichever bench was imported first."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _load("pra_run_probe", BENCH / "run_probe.py")

NAME = "mixer-pumped-rf-admittance"
RID = "20261010-120000-abcdef1"
SHA = "a" * 64
DUT = {"uu": 0.010 + 0.020j, "ul": 0.004 * cmath.exp(1j), "lu": 0.003 * cmath.exp(-0.5j), "ll": 0.012 + 0.018j}


def make_env(rid: str) -> dict:
    return {"host": "h", "platform": "p", "python": "3.12",
            "git": {"commit": rid.split("-")[2] + "0" * 33, "dirty": False},
            "placeholder_sha256": SHA, "pdk_artifact_sha256": SHA,
            "ngspice": {"path": "/x/ngspice", "version": "ngspice-46", "major": 46, "sha256": SHA},
            "pdk": {"path": "/pdk", "fetched_version": "0.3.0",
                    "sha256": {"cornerHBT.lib": SHA, "sg13g2_hbt_mod.lib": SHA}, "device": "npn13G2"},
            "pdk_integrity": {"gate": "stub", "ok": True, "problems": [], "notes": ["models match"]}}


def write_probe_run(root: Path, rid: str = RID, dut: dict | None = None) -> str:
    exp = root / "sim" / NAME
    thr = P.load_thresholds()
    stdout = P.synth_stdout(P.synth_marks(dut or DUT))
    parsed = P.parse_log(stdout, "")
    ev = json.loads(json.dumps(P.evaluate(parsed, thr)))
    status = ev["status"]
    env = make_env(rid)
    prov = {"file": f"sim/{NAME}/thresholds.json", "sha256": SHA, "commit": "c" * 40, "dirty": False}
    rec = {"record_id": rid, "status": status, "reasons": ev["reasons"], "scope": P.SCOPE,
           "nominal_point": {"corner": "hbt_typ"}, "thresholds": thr, "thresholds_provenance": prov,
           "classification": status, "evaluation": ev, "references": R.REFERENCES,
           "probe_logs": f"sim/{NAME}/probe-logs/{rid}/", "environment": env}
    (exp / "records").mkdir(parents=True, exist_ok=True)
    stem = f"{rid}-{status}"
    (exp / "records" / f"{stem}.json").write_text(json.dumps(rec, indent=2) + "\n")
    (exp / "records" / f"{stem}.md").write_text(R.render_md(rid, status, ev["reasons"], ev, thr, prov, env))
    logs = exp / "probe-logs" / rid
    logs.mkdir(parents=True)
    (logs / "deck.spice").write_text("* deck\n")
    (logs / "stdout.txt").write_text(stdout)
    (logs / "stderr.txt").write_text("")
    (logs / "inventory.json").write_text(json.dumps({"parsed": parsed, "evaluation": ev}, indent=2) + "\n")
    return stem


def write_unavailable(root: Path, rid: str = RID) -> str:
    exp = root / "sim" / NAME
    (exp / "records").mkdir(parents=True, exist_ok=True)
    status = "CAPABILITY_UNAVAILABLE"
    failed = "pinned ngspice-46 not found"
    env = {k: v for k, v in make_env(rid).items() if k not in ("ngspice", "pdk", "pdk_integrity")}
    rec = {"record_id": rid, "status": status, "reasons": ["pinned simulator not available"],
           "failed_check": failed, "scope": P.SCOPE, "environment": env}
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
        self.status = self.stem.split("-", 3)[3]
        self.js = self.rec / f"{self.stem}.json"
        self.md = self.rec / f"{self.stem}.md"
        self.logs = self.exp / "probe-logs" / RID

    def test_adapter_registered(self):
        self.assertIn(NAME, chk.ADAPTERS)

    def test_fresh_complete_run_passes(self):
        self.assertEqual(self.status, "MATRIX_REQUIRED")
        self.assertEqual(self.problems(), [])

    def test_scalar_and_inconclusive_runs_pass(self):
        for p in (self.js, self.md):
            p.unlink()
        shutil.rmtree(self.logs)
        write_probe_run(self.root, dut={"uu": 0.01 + 0.02j, "ul": 1e-5, "lu": 1e-5, "ll": 0.012 + 0.018j})
        self.assertEqual(self.problems(), [])
        self.assertTrue(list(self.rec.glob("*-SCALAR_ADEQUATE.json")))

    def test_scope_constants_match_the_bench(self):
        for phrase in chk.PRA_SCOPE_PHRASES:
            self.assertIn(phrase, P.SCOPE)
        self.assertEqual(chk.PRA_MD_MARKERS, R.SCOPE_MD_MARKERS)
        self.assertEqual(set(chk.PRA_THRESHOLDS), set(P.load_thresholds()))
        self.assertEqual(set(chk.PRA_STATUSES), set(P.STATUSES))

    # ---- identity / status -------------------------------------------------------
    def test_compliance_status_rejected(self):
        for ext in ("md", "json"):
            (self.rec / f"{self.stem}.{ext}").rename(self.rec / f"{RID}-COMPLIANT.{ext}")
        self.assertFails("status 'COMPLIANT' is not one of")

    def test_missing_markdown_half(self):
        self.md.unlink()
        self.assertFails("no paired .md")

    def test_json_status_disagrees(self):
        edit_json(self.js, lambda d: d.update(status="SCALAR_ADEQUATE"))
        self.assertFails("does not match file name status")

    def test_first_line_must_name_the_bench(self):
        self.md.write_text(self.md.read_text().replace(f"# {NAME} record", "# mixer-cm-interface-probe record", 1))
        self.assertFails("first line must be")

    def test_commit_does_not_match_id(self):
        edit_json(self.js, lambda d: d["environment"]["git"].update(commit="1234567" + "0" * 33))
        self.assertFails("does not match the sha in the record id")

    # ---- scope disclaimer ------------------------------------------------------------
    def test_json_scope_disclaimer_required(self):
        for phrase in chk.PRA_SCOPE_PHRASES:
            with self.subTest(phrase=phrase):
                orig = json.loads(self.js.read_text())["scope"]
                edit_json(self.js, lambda d, p=phrase: d.update(scope=d["scope"].replace(p, "")))
                self.assertFails(f"does not carry the disclaimer {phrase!r}")
                edit_json(self.js, lambda d, o=orig: d.update(scope=o))

    def test_markdown_scope_disclaimer_required(self):
        text = self.md.read_text()
        for marker in chk.PRA_MD_MARKERS:
            with self.subTest(marker=marker):
                self.md.write_text(text.replace(marker, "Scope: row 5 looks fine"))
                self.assertFails("missing the scope disclaimer")
        self.md.write_text(text)

    # ---- thresholds / numbers ----------------------------------------------------------
    def test_uncommitted_thresholds_rejected(self):
        edit_json(self.js, lambda d: d["thresholds_provenance"].update(dirty=True))
        self.assertFails("thresholds_provenance.dirty must be false")

    def test_thresholds_commit_required(self):
        edit_json(self.js, lambda d: d["thresholds_provenance"].update(commit=None))
        self.assertFails("thresholds_provenance.commit")

    def test_missing_threshold(self):
        edit_json(self.js, lambda d: d["thresholds"].pop("kappa_scalar_max"))
        self.assertFails("JSON 'thresholds' must carry exactly")

    def test_status_must_follow_from_kappa(self):
        # loosen the scalar bound in the record: the same numbers now say SCALAR_ADEQUATE
        edit_json(self.js, lambda d: d["thresholds"].update(kappa_scalar_max=0.9))
        self.assertFails("does not follow from the recorded controls")

    def test_check_flag_must_agree_with_threshold(self):
        edit_json(self.js, lambda d: d["evaluation"]["dut"]["checks"]["halving"].update(rel_change=0.5))
        self.assertFails("checks['halving'].pass=True contradicts")

    def test_kappa_must_follow_from_y(self):
        edit_json(self.js, lambda d: d["evaluation"]["dut"].update(kappa=0.01))
        self.assertFails("does not follow from evaluation.dut.y")

    def test_decisive_status_requires_passing_controls(self):
        def fail_controls(d):
            d["evaluation"]["controls"]["pass"] = False
            next(iter(d["evaluation"]["controls"]["checks"].values()))["pass"] = False
        edit_json(self.js, fail_controls)
        self.assertFails("expected INCONCLUSIVE")

    def test_controls_verdict_must_agree_with_checks(self):
        edit_json(self.js, lambda d: d["evaluation"]["controls"]["checks"]["rc.uu"].update({"pass": False}))
        self.assertFails("controls.pass disagrees")

    def test_classification_field_must_match(self):
        edit_json(self.js, lambda d: d.update(classification="SCALAR_ADEQUATE"))
        self.assertFails("JSON 'classification'")

    # ---- probe-log package / layout ---------------------------------------------------
    def test_missing_probe_log_package(self):
        shutil.rmtree(self.logs)
        self.assertFails("does not exist")

    def test_missing_probe_log_file(self):
        (self.logs / "stdout.txt").unlink()
        self.assertFails("missing stdout.txt")

    def test_unknown_file_in_probe_log_package(self):
        (self.logs / "extra.txt").write_text("x")
        self.assertFails("unexpected file in a probe-log package")

    def test_unknown_file_in_records(self):
        (self.rec / "notes.md").write_text("x")
        self.assertFails("not a <YYYYMMDD>-<HHMMSS>-<git-sha>-<STATUS>")

    def test_foreign_evidence_dir_rejected(self):
        (self.exp / "corners").mkdir()
        self.assertFails(f"is not part of the {NAME} evidence layout")

    def test_inventory_disagrees_with_record(self):
        edit_json(self.logs / "inventory.json", lambda d: d["evaluation"]["dut"].update(kappa=0.0))
        self.assertFails("differs from the record's")

    def test_orphan_probe_log_package(self):
        shutil.copytree(self.logs, self.exp / "probe-logs" / "20261010-130000-abcdef1")
        self.assertFails("belongs to no record")

    def test_bench_readme_required(self):
        (self.exp / "README.md").unlink()
        self.assertFails("bench has records/ but no cold-start README")


class Unavailable(Base):
    def setUp(self):
        super().setUp()
        self.stem = write_unavailable(self.root)
        self.js = self.rec / f"{self.stem}.json"

    def test_valid_without_logs(self):
        self.assertEqual(self.problems(), [])

    def test_carries_no_result(self):
        for key, val in (("evaluation", {}), ("probe_logs", "x"), ("classification", "SCALAR_ADEQUATE")):
            with self.subTest(key=key):
                edit_json(self.js, lambda d, k=key, v=val: d.update({k: v}))
                self.assertFails(f"carries '{key}'")
                edit_json(self.js, lambda d, k=key: d.pop(k))


def run(cwd: Path, *args: str) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def commit(cwd: Path, msg: str = "c") -> None:
    run(cwd, "git", "add", "-A")
    run(cwd, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


class History(unittest.TestCase):
    """The append-only check covers the new bench's records/ and probe-logs/."""

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
        self.exp = self.pr / "sim" / NAME

    def history(self) -> list[str]:
        return chk.check_append_only(self.pr, "origin/trunk", True)[0].items

    def test_clean_branch_passes(self):
        self.assertEqual(self.history(), [])

    def test_editing_a_frozen_record_fails(self):
        p = next((self.exp / "records").glob("*.json"))
        p.write_text(p.read_text().replace("MATRIX_REQUIRED", "SCALAR_ADEQUATE"))
        commit(self.pr)
        self.assertTrue(any("modified" in x for x in self.history()))

    def test_deleting_a_frozen_record_fails(self):
        next((self.exp / "records").glob("*.md")).unlink()
        commit(self.pr)
        self.assertTrue(any("deleted" in x for x in self.history()))

    def test_editing_a_frozen_log_fails(self):
        (self.exp / "probe-logs" / RID / "stdout.txt").write_text("edited\n")
        commit(self.pr)
        self.assertTrue(any("probe-logs" in x for x in self.history()))

    def test_adding_to_a_frozen_record_id_fails(self):
        (self.exp / "probe-logs" / RID / "extra.txt").write_text("x")
        commit(self.pr)
        self.assertTrue(any("already committed" in x for x in self.history()))

    def test_appending_a_new_record_passes(self):
        write_unavailable(self.pr, "20261011-120000-abcdef1")
        commit(self.pr)
        self.assertEqual(self.history(), [])


if __name__ == "__main__":
    unittest.main()
