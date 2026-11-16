"""Negative controls for the reuse.lock.json declared-master check (issue #277).

Standard library only. Tests build tiny repo trees in a temp dir, break exactly
one thing and assert check_reuse_masters names it; one control copies the
committed lock and its real masters. The real tree is never modified.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parents[1]
sys.path.insert(0, str(SCRIPTS))

import check_evidence_formats as chk  # noqa: E402

LOCK = "reuse.lock.json"

MASTER_A = textwrap.dedent("""\
    Z0_REF = 50.0
    def helper(x):
        return x + 1
    class Widget:
        pass
    IN = 0.1  # inlined comment assignment
    """)
MASTER_B = textwrap.dedent("""\
    from a import helper as hlp  # re-export, not a definition
    K_B = 1.380649e-23
    """)


def tiny_lock(masters, upstream=None) -> dict:
    doc = {"_comment": "tiny", "masters": masters}
    if upstream is not None:
        doc["upstream"] = upstream
    return doc


class TinyTree(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write_lock(self, doc) -> None:
        (self.root / LOCK).write_text(json.dumps(doc, indent=2), encoding="utf-8")

    def messages(self) -> str:
        return "\n".join(chk.check_reuse_masters(self.root).items)

    def test_clean_tree_has_no_problems(self) -> None:
        (self.root / "a.py").write_text(MASTER_A, encoding="utf-8")
        self.write_lock(tiny_lock([
            {"mechanic": "m_a", "master": "a.py",
             "symbols": ["Z0_REF", "helper", "Widget", "IN"], "what": "assignment + def + class forms"},
        ]))
        self.assertEqual(self.messages(), "")

    def test_assignment_form_is_a_definition(self) -> None:
        (self.root / "a.py").write_text("K_BOLTZMANN = 1.380649e-23\n", encoding="utf-8")
        self.write_lock(tiny_lock([
            {"mechanic": "m_k", "master": "a.py", "symbols": ["K_BOLTZMANN"], "what": "module-level assignment"},
        ]))
        self.assertEqual(self.messages(), "")

    def test_missing_lock(self) -> None:
        self.assertIn("reuse.lock.json", self.messages())
        self.assertIn("missing", self.messages())

    def test_malformed_json_is_one_problem(self) -> None:
        (self.root / LOCK).write_text("{not json", encoding="utf-8")
        items = chk.check_reuse_masters(self.root).items
        self.assertEqual(len(items), 1)
        self.assertIn("unreadable JSON", items[0])

    def test_masters_not_a_list_is_one_problem(self) -> None:
        self.write_lock({"_comment": "tiny", "masters": {"mechanic": "m"}})
        items = chk.check_reuse_masters(self.root).items
        self.assertEqual(len(items), 1)
        self.assertIn("'masters' list", items[0])

    def test_missing_master_path(self) -> None:
        self.write_lock(tiny_lock([
            {"mechanic": "m_a", "master": "sim/gone.py", "symbols": ["f"], "what": "renamed away"},
        ]))
        self.assertIn("sim/gone.py", self.messages())
        self.assertIn("does not exist", self.messages())

    def test_renamed_master_path(self) -> None:
        (self.root / "renamed.py").write_text(MASTER_A, encoding="utf-8")
        self.write_lock(tiny_lock([
            {"mechanic": "m_a", "master": "a.py", "symbols": ["helper"], "what": "renamed to renamed.py"},
        ]))
        self.assertIn("a.py", self.messages())

    def test_symbol_absent_from_existing_master(self) -> None:
        (self.root / "a.py").write_text(MASTER_A, encoding="utf-8")
        self.write_lock(tiny_lock([
            {"mechanic": "m_a", "master": "a.py", "symbols": ["no_such_symbol"], "what": "removed"},
        ]))
        self.assertIn("no_such_symbol", self.messages())
        self.assertIn("a.py", self.messages())

    def test_reexport_is_not_a_definition(self) -> None:
        # b.py only re-exports helper via `from a import helper as hlp`; the
        # master must define the symbol, so hlp is a problem.
        (self.root / "b.py").write_text(MASTER_B, encoding="utf-8")
        self.write_lock(tiny_lock([
            {"mechanic": "m_b", "master": "b.py", "symbols": ["hlp"], "what": "re-export only"},
        ]))
        self.assertIn("hlp", self.messages())

    def one_master(self, text: str, symbols: list[str]) -> list[str]:
        (self.root / "a.py").write_text(text, encoding="utf-8")
        self.write_lock(tiny_lock([
            {"mechanic": "m_a", "master": "a.py", "symbols": symbols, "what": "case"},
        ]))
        return chk.check_reuse_masters(self.root).items

    def test_docstring_prose_is_not_a_definition(self) -> None:
        text = '"""Notes.\nF = inoise^2 / (4 k T0 Z0).\nF_old = F_true + x\n"""\nreal = 1\n'
        self.assertEqual(self.one_master(text, ["real"]), [])
        items = self.one_master(text, ["F"])
        self.assertEqual(len(items), 1)
        self.assertIn("'F'", items[0])

    def test_async_def_is_a_definition(self) -> None:
        self.assertEqual(self.one_master("async def run():\n    pass\n", ["run"]), [])

    def test_unparseable_master_is_one_problem(self) -> None:
        items = self.one_master("def broken(:\n", ["broken", "other"])
        self.assertEqual(len(items), 1)
        self.assertIn("a.py", items[0])
        self.assertIn("does not parse", items[0])

    def test_annotation_only_and_tuple_targets_are_not_definitions(self) -> None:
        text = "x: int\ny: int = 3\na, b = 1, 2\n"
        self.assertEqual(self.one_master(text, ["y"]), [])
        self.assertEqual(len(self.one_master(text, ["x"])), 1)
        self.assertEqual(len(self.one_master(text, ["a"])), 1)

    def test_upstream_not_an_object_is_one_problem(self) -> None:
        self.write_lock(tiny_lock([], upstream=["corners.py"]))
        items = chk.check_reuse_masters(self.root).items
        self.assertEqual(len(items), 1)
        self.assertIn("reuse.lock.json:upstream", items[0])

    def test_upstream_modules_not_a_list_is_one_problem(self) -> None:
        self.write_lock(tiny_lock([], upstream={"repo": "u", "modules": "corners.py"}))
        items = chk.check_reuse_masters(self.root).items
        self.assertEqual(len(items), 1)
        self.assertIn("reuse.lock.json:upstream", items[0])
        self.assertIn("'modules'", items[0])

    def test_undeclared_mechanic_is_not_an_error(self) -> None:
        (self.root / "a.py").write_text(MASTER_A, encoding="utf-8")
        (self.root / "extra.py").write_text("def undeclared(x):\n    return x\n", encoding="utf-8")
        self.write_lock(tiny_lock([
            {"mechanic": "m_a", "master": "a.py", "symbols": ["helper"], "what": "only a.py declared"},
        ]))
        self.assertEqual(self.messages(), "")

    def test_duplicate_mechanic_id(self) -> None:
        (self.root / "a.py").write_text(MASTER_A, encoding="utf-8")
        entry = {"mechanic": "m_a", "master": "a.py", "symbols": ["helper"], "what": "dup"}
        self.write_lock(tiny_lock([entry, dict(entry)]))
        self.assertIn("m_a", self.messages())
        self.assertIn("more than once", self.messages())

    def test_entry_field_validation(self) -> None:
        self.write_lock(tiny_lock([
            {"mechanic": "", "master": "a.py", "symbols": [], "what": None},
            "not an object",
        ]))
        msgs = self.messages()
        self.assertIn("'mechanic'", msgs)
        self.assertIn("'what'", msgs)
        self.assertIn("'symbols'", msgs)
        self.assertIn("not an object", msgs)

    def test_master_outside_sim(self) -> None:
        (self.root / "tools").mkdir()
        (self.root / "tools" / "post.py").write_text(MASTER_A, encoding="utf-8")
        self.write_lock(tiny_lock([
            {"mechanic": "m_t", "master": "tools/post.py", "symbols": ["Widget"], "what": "no sim/ prefix assumed"},
        ]))
        self.assertEqual(self.messages(), "")

    def test_upstream_master_overlap_is_the_mispin(self) -> None:
        # The real mis-pin shape: a master under sim/harness/ (the base the
        # upstream module list is relative to) whose bare filename also
        # appears in upstream.modules.
        (self.root / "sim" / "harness").mkdir(parents=True)
        (self.root / "sim" / "harness" / "corners.py").write_text("CORNERS = []\n", encoding="utf-8")
        self.write_lock(tiny_lock(
            [{"mechanic": "m_c", "master": "sim/harness/corners.py", "symbols": ["CORNERS"], "what": "upstream module"}],
            upstream={"repo": "2AMLogic/gf180-sar-adc", "package": "sim-harness-core",
                      "modules": ["corners.py"]}))
        self.assertIn("corners.py", self.messages())
        self.assertIn("upstream-owned", self.messages())

    def test_upstream_modules_not_checked_against_the_tree(self) -> None:
        # Upstream-owned modules have no master here; their absence is not an error.
        self.write_lock(tiny_lock([], upstream={"repo": "u", "package": "p", "modules": ["pdk.py"]}))
        self.assertEqual(self.messages(), "")


class CommittedTree(unittest.TestCase):
    """The committed lock, checked against copies of its real masters."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        shutil.copy(REPO / LOCK, self.root / LOCK)
        masters = json.loads((REPO / LOCK).read_text(encoding="utf-8"))["masters"]
        for e in masters:
            src = REPO / e["master"]
            dst = self.root / e["master"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)

    def messages(self) -> str:
        return "\n".join(chk.check_reuse_masters(self.root).items)

    def test_committed_lock_is_clean(self) -> None:
        self.assertEqual("\n".join(chk.check_reuse_masters(self.root).items), "")

    def test_committed_lock_declares_the_expected_set(self) -> None:
        doc = json.loads((self.root / LOCK).read_text(encoding="utf-8"))
        paths = [e["master"] for e in doc["masters"]]
        self.assertEqual(paths, [
            "sim/harness/evidence_store.py",
            "sim/harness/frozen_dut.py",
            "sim/harness/klt_driver.py",
            "sim/harness/pdkartifact.py",
            "sim/harness/provenance.py",
            "sim/harness/rf.py",
            "sim/hbt-kaband-characterization/kaband.py",
            "sim/lna-sparam-nf/lna_nf.py",
        ])
        rf = next(e for e in doc["masters"] if e["master"] == "sim/harness/rf.py")
        self.assertEqual(rf["symbols"], ["K_BOLTZMANN", "noise_factor_from_inoise", "noise_factor_from_inoise_sq", "Z0_OHM", "db10", "db20", "dbm_strict", "dbm_floored", "watts", "available_power_w", "v_open_peak_for", "delivered_power_w", "dft_bin", "dft_bin_amplitude"])
        up = doc["upstream"]
        self.assertEqual(up["modules"],
                         ["pdk.py", "corners.py", "toolchain.py", "testbench.py",
                          "runner.py", "evidence.py", "report.py", "cli.py"])
        # rf.py is authored here (#262) and must not be upstream-owned despite
        # its row in the README generic-core table.
        self.assertNotIn("rf.py", up["modules"])
        comment = doc["_comment"]
        self.assertIn("9dad16b", comment)
        self.assertIn("#266", comment)
        self.assertNotIn("#262", comment)

    def test_moving_a_master_away_goes_red(self) -> None:
        (self.root / "sim" / "harness" / "provenance.py").rename(self.root / "sim" / "harness" / "prov.py")
        msgs = self.messages()
        self.assertIn("sim/harness/provenance.py", msgs)

    def test_removing_a_declared_symbol_goes_red(self) -> None:
        p = self.root / "sim" / "harness" / "rf.py"
        p.write_text(p.read_text(encoding="utf-8").replace(
            "K_BOLTZMANN = 1.380649e-23", "K_BOLTZMANN_GONE = 1.380649e-23"), encoding="utf-8")
        msgs = self.messages()
        self.assertIn("K_BOLTZMANN", msgs)

    def test_appending_a_declared_master_basename_to_upstream_goes_red(self) -> None:
        # The committed-tree form of the mis-pin control: take the real lock,
        # pin one of its own declared sim/harness/ masters as upstream-owned,
        # and the overlap rule must go red.
        doc = json.loads((self.root / LOCK).read_text(encoding="utf-8"))
        doc["upstream"]["modules"].append("rf.py")
        (self.root / LOCK).write_text(json.dumps(doc, indent=2), encoding="utf-8")
        msgs = self.messages()
        self.assertIn("rf.py", msgs)
        self.assertIn("upstream-owned", msgs)


if __name__ == "__main__":
    unittest.main()
