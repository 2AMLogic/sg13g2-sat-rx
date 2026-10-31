"""Negative controls for the hbt-mismatch-pair layout of check_evidence_formats.py (issue #186).

A complete, self-consistent synthetic run (record pair + probe-log package) is built
with the REAL ``run_probe`` renderer from a fabricated, closed-form Monte Carlo result,
in a temporary tree. Each test breaks exactly one rule and asserts a file-specific
failure; the unbroken run must pass. No simulator, PDK, klt or network. The real tree
is not modified.

Run: python3 -m unittest discover -s .github/scripts/tests -p 'test_check_mcpair_adapter.py'
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parents[1]
BENCH = REPO / "sim" / "hbt-mismatch-pair"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "tests"))

import check_evidence_formats as chk  # noqa: E402
import mcpair as M  # noqa: E402
from test_mcpair import healthy_legs  # noqa: E402

# The cm-probe adapter test already puts a `run_probe` module in sys.modules;
# load THIS bench's driver under a unique name instead.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("mcpair_run_probe", BENCH / "run_probe.py")
R = _ilu.module_from_spec(_spec)
sys.modules["mcpair_run_probe"] = R
_spec.loader.exec_module(R)

NAME = "hbt-mismatch-pair"
RID = "20261012-120000-abcdef2"
RID_STATUS = f"{RID}-MC_METHOD_WORKS"
PACKAGE_FILES = ("pair_body.spice", "request_mc.json", "request_local.json",
                 "stats.json", "samples_mc.json")


class A:
    """The argparse namespace render_record/collect_provenance read."""

    n = 4
    seed = 186
    backend = "batch"
    local_backend = "local"
    klt_cmd = "klt"
    timeout_s = 1800
    skip_rerun = False
    skip_local = False
    no_write = False


def write_run(root: Path, rid_status: str = RID_STATUS, ev=None) -> Path:
    """A complete fresh probe run (record pair + package) under ``root``."""
    rid = rid_status.rsplit("-", 1)[0]
    status = rid_status.rsplit("-", 1)[1]
    exp = root / "sim" / NAME
    pkg = exp / "probe-logs" / rid
    pkg.mkdir(parents=True)
    for name in PACKAGE_FILES:
        (pkg / name).write_text("synthetic\n")
    if ev is None:
        legs = {"mc": healthy_legs(4), "rerun": healthy_legs(4), "local": healthy_legs(1)}
        ev = M.evaluate(batch=legs["mc"], rerun=legs["rerun"], local=legs["local"])
    args = A()
    # collect_provenance runs the real model-integrity gate, which needs a PDK
    # install; this suite must not (see module docstring). Stub it the way the
    # sibling adapter tests inject `pdk_integrity` into the record environment.
    real_gate = R.pdk_integrity
    R.pdk_integrity = lambda: {"gate": "stub", "ok": True, "problems": [], "notes": ["models match"]}
    try:
        prov = R.collect_provenance(args, {}, pkg)
    finally:
        R.pdk_integrity = real_gate
    prov["cmd_args"] = ["--n", "4", "--seed", "186"]
    md, rj = R.render_record(rid_status, status, ev, args, prov)
    rj = dict(rj)
    rj["provenance"] = prov["structured"]
    (exp / "records").mkdir(parents=True, exist_ok=True)
    (exp / "records" / f"{rid_status}.md").write_text(md)
    (exp / "records" / f"{rid_status}.json").write_text(json.dumps(rj, indent=2, sort_keys=True) + "\n")
    return exp


class McpairAdapterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mcpair-adapter-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def check(self, root: Path):
        problems = chk.Problems()
        chk.check_hbt_mismatch_pair(problems, root, root / "sim" / NAME)
        return problems

    def test_healthy_run_passes(self):
        exp = write_run(self.tmp)
        problems = self.check(self.tmp)
        self.assertFalse(problems.items, f"healthy synthetic run rejected: {problems.items}")

    def test_missing_scope_line_is_caught(self):
        exp = write_run(self.tmp)
        rec = exp / "records" / f"{RID_STATUS}.md"
        rec.write_text(rec.read_text().replace("- **Scope: METHOD only.**", "- **Scope:** gone"))
        problems = self.check(self.tmp)
        self.assertTrue(any("Scope" in p for p in problems.items), problems.items)

    def test_verdict_in_a_method_record_is_caught(self):
        exp = write_run(self.tmp)
        js = exp / "records" / f"{RID_STATUS}.json"
        rj = json.loads(js.read_text())
        rj["verdict"] = "measured_pass"
        js.write_text(json.dumps(rj, sort_keys=True))
        problems = self.check(self.tmp)
        self.assertTrue(any("verdict" in p for p in problems.items), problems.items)

    def test_works_status_with_false_gate_is_caught(self):
        exp = write_run(self.tmp)
        js = exp / "records" / f"{RID_STATUS}.json"
        rj = json.loads(js.read_text())
        rj["gates"] = dict(rj["gates"])
        rj["gates"]["mismatch_sampled"] = False
        js.write_text(json.dumps(rj, sort_keys=True))
        problems = self.check(self.tmp)
        self.assertTrue(any("mismatch_sampled" in p for p in problems.items), problems.items)

    def test_works_status_with_skipped_rerun_is_caught(self):
        exp = write_run(self.tmp)
        js = exp / "records" / f"{RID_STATUS}.json"
        rj = json.loads(js.read_text())
        rj["gates"] = dict(rj["gates"])
        rj["gates"]["reproducibility_max_rel"] = None
        js.write_text(json.dumps(rj, sort_keys=True))
        problems = self.check(self.tmp)
        self.assertTrue(any("reproducibility_max_rel" in p for p in problems.items), problems.items)

    def test_control_fail_without_false_gate_is_caught(self):
        exp = write_run(self.tmp)
        stem = f"{RID}-MC_METHOD_CONTROL_FAIL"
        (exp / "records" / f"{RID_STATUS}.md").rename(exp / "records" / f"{stem}.md")
        (exp / "records" / f"{RID_STATUS}.json").rename(exp / "records" / f"{stem}.json")
        js = exp / "records" / f"{stem}.json"
        rj = json.loads(js.read_text())
        rj["status"] = "MC_METHOD_CONTROL_FAIL"
        rj["gates"] = dict(rj["gates"])
        rj["gates"]["nominal_exact"] = True   # no gate false: status unjustified
        js.write_text(json.dumps(rj, sort_keys=True))
        problems = self.check(self.tmp)
        self.assertTrue(any("no control gate is false" in p for p in problems.items), problems.items)

    def test_missing_samples_evidence_is_caught(self):
        exp = write_run(self.tmp)
        rid = RID_STATUS.rsplit("-", 1)[0]
        (exp / "probe-logs" / rid / "samples_mc.json").unlink()
        problems = self.check(self.tmp)
        self.assertTrue(any("samples_mc.json" in p for p in problems.items), problems.items)

    def test_orphan_probe_log_package_is_caught(self):
        write_run(self.tmp)
        (self.tmp / "sim" / NAME / "probe-logs" / "20261012-120000-abcdef3").mkdir()
        problems = self.check(self.tmp)
        self.assertTrue(any("belongs to no record" in p for p in problems.items), problems.items)

    def test_status_disagreeing_with_filename_is_caught(self):
        exp = write_run(self.tmp)
        js = exp / "records" / f"{RID_STATUS}.json"
        rj = json.loads(js.read_text())
        rj["status"] = "MC_METHOD_CONTROL_FAIL"
        js.write_text(json.dumps(rj, sort_keys=True))
        problems = self.check(self.tmp)
        self.assertTrue(any("disagrees with the filename" in p for p in problems.items), problems.items)


if __name__ == "__main__":
    unittest.main()
