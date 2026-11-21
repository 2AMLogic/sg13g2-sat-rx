"""Negative controls for the lna-passive-study layout of check_evidence_formats.py (issue #340).

A complete, self-consistent synthetic run (plan, prematch, variant decks, record
pair, manifest with the Stored evidence table) is built in a temporary tree.
Each test breaks exactly one rule and asserts a failure naming the file; the
unbroken run must pass. No simulator, PDK, klt or network; the real tree is
not modified.

Run: python3 -m unittest discover -s .github/scripts/tests -p 'test_check_lnapassive_adapter.py'
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parents[1]
sys.path.insert(0, str(SCRIPTS))

import check_evidence_formats as chk  # noqa: E402

NAME = "lna-passive-study"
RID = "20261121-040000-abcdef0"
PROCESSES = ("typ", "hbt_wcs")
TEMPS = (-40.0, 27.0)
SUPPLIES = (2.25, 2.5)
VARIANTS = ("V01",)

PLAN = {
    "plan_version": 1,
    "scope": "NON-CLAIMING substituted-primitive study; inductors stay IDEAL; "
             "no spec row is claimed; selects nothing; comparative deltas only",
    "baseline_record": "sim/lna-sparam-nf/records/20261114-211735-8a92c6e.md",
    "corner_axis": [{"name": n, "sections": {}} for n in PROCESSES],
    "temperatures_c": list(TEMPS),
    "supplies_v": list(SUPPLIES),
    "variants": [{"id": "V01", "assignment": {}}],
    "record": {"spec_rows_claimed_met": []},
}
CLAIM = ("NON-CLAIMING substituted-primitive comparison: Inductors stay IDEAL. "
         "No spec row is claimed met or missed. COMPARATIVE DELTAS ONLY.")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _record(rid: str = RID) -> dict:
    return {
        "record_id": rid, "status": "COLLECTED", "experiment": NAME,
        "spec_rows_claimed_met": [], "claim": CLAIM,
        "variants": list(VARIANTS),
        "variant_deck_sha256": {v: "sha256:" + _sha(f"deck {v}") for v in VARIANTS},
        "deltas": {v: {} for v in VARIANTS},
        "bound_cells": {v: {} for v in VARIANTS},
        "worst": {v: {} for v in VARIANTS},
        "gates": {"pass": True, "problems": []},
    }


def _sections(rec: dict, rows: list[tuple[str, int, str]]) -> str:
    table = "\n".join(f"| `{n}` | {s} | `{h}` |" for n, s, h in rows)
    return (
        f"# {NAME} record {rec['record_id']}\n\n"
        f"- **Status: {rec['status']}**\n\n"
        f"**Claim**: {rec['claim']}\n\n"
        "## Declaration\n## Controls and method identity\n"
        "## Comparative deltas at the row bound cells (variant - control)\n"
        "## Worst-case deltas per variant (over the bound cells)\n"
        "## Provenance and stored evidence\n\n"
        "## Stored evidence\n\n| file | bytes | sha256 |\n|---|---|---|\n"
        f"{table}\n")


def write_run(root: Path) -> Path:
    """A complete synthetic study under ``root``; returns sim/<bench>."""
    exp = root / "sim" / NAME
    (exp / "testbench" / "variants").mkdir(parents=True)
    (exp / "records").mkdir()
    (root / "manifests" / "artifacts").mkdir(parents=True)
    (exp / "testbench" / "plan.json").write_text(json.dumps(PLAN, indent=1))
    (exp / "testbench" / "prematch.json").write_text(json.dumps({"selection": None}))
    for v in VARIANTS:
        (exp / "testbench" / "variants" / f"{v}.spice").write_text(f"deck {v}")
    rec = _record()
    (exp / "records" / f"{RID}.json").write_text(json.dumps(rec, indent=1))
    entries, rows = [], []
    def add(name: str, text: str) -> None:
        name = f"sim/{NAME}/{name}"  # manifest names are full logical paths
        sha, size = _sha(text), len(text.encode())
        entries.append({"sha256": sha, "size": size, "kind": "evidence",
                        "producer": {"tool": "t", "version": "1", "loom.repo": "r",
                                     "commit": "0" * 40},
                        "uri": f"artifact:evidence/r/{sha[:2]}/{sha}", "name": name})
        rows.append((name, size, sha))
    add(f"records/{RID}-cells.json.gz", "cells")
    add(f"netlist-snapshots/{RID}/plan.json", "plan")
    add(f"netlist-snapshots/{RID}/prematch.json", "pre")
    add(f"netlist-snapshots/{RID}/control_V00.spice", "ctl")
    for deck in ("V00",) + VARIANTS:
        for proc in PROCESSES:
            for temp in TEMPS:
                for vdd in SUPPLIES:
                    add(f"corners/{RID}/{deck}__{proc}__{temp:g}C__{vdd:.2f}V.log", "log")
        if deck != "V00":
            add(f"netlist-snapshots/{RID}/variant_{deck}.spice", f"deck {deck}")
        for vdd in SUPPLIES:
            key = f"{deck}_{vdd:.2f}v"
            for kind in ("body", "request", "report"):
                add(f"netlist-snapshots/{RID}/{kind}_{key}.spice" if kind == "body"
                    else f"netlist-snapshots/{RID}/{kind}_{key}.json", kind)
    (root / "manifests" / "artifacts" / f"{NAME}-{RID}.manifest.json").write_text(
        json.dumps({"schema_version": 1, "entries": entries}, indent=1))
    (exp / "records" / f"{RID}.md").write_text(_sections(rec, rows))
    return exp


class LnaPassiveBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="lnapassive-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.exp = write_run(self.tmp)

    def problems(self) -> list[str]:
        probs: list[str] = []
        chk.ADAPTERS[NAME](_fake_problems(probs), self.tmp, self.exp)
        return probs


class _fake_problems:
    def __init__(self, sink: list[str]) -> None:
        self.sink = sink

    def add(self, where, message: str) -> None:
        self.sink.append(f"{where}: {message}")


class HappyPath(LnaPassiveBase):
    def test_passes(self) -> None:
        self.assertEqual(self.problems(), [])


class NegativeControls(LnaPassiveBase):
    def test_tampered_variant_deck_fails(self) -> None:
        (self.exp / "testbench" / "variants" / "V01.spice").write_text("deck V01 edited")
        self.assertTrue(any("deck sha256 disagrees" in p for p in self.problems()))

    def test_status_outside_vocabulary_fails(self) -> None:
        path = self.exp / "records" / f"{RID}.json"
        rec = json.loads(path.read_text())
        rec["status"] = "GREAT"
        path.write_text(json.dumps(rec))
        self.assertTrue(any("status 'GREAT'" in p for p in self.problems()))

    def test_claimed_row_fails(self) -> None:
        path = self.exp / "records" / f"{RID}.json"
        rec = json.loads(path.read_text())
        rec["spec_rows_claimed_met"] = [2]
        path.write_text(json.dumps(rec))
        self.assertTrue(any("spec_rows_claimed_met" in p for p in self.problems()))

    def test_missing_cell_log_fails(self) -> None:
        mpath = self.tmp / "manifests" / "artifacts" / f"{NAME}-{RID}.manifest.json"
        man = json.loads(mpath.read_text())
        victim = next(e for e in man["entries"]
                      if e["name"].endswith("V01__typ__27C__2.25V.log"))
        man["entries"].remove(victim)
        mpath.write_text(json.dumps(man))
        self.assertTrue(any("no stored log for declared cell"
                            f" {RID}/V01__typ__27C__2.25V" in p for p in self.problems()))

    def test_collected_with_failed_gates_fails(self) -> None:
        path = self.exp / "records" / f"{RID}.json"
        rec = json.loads(path.read_text())
        rec["gates"]["pass"] = False
        path.write_text(json.dumps(rec))
        self.assertTrue(any("COLLECTED but" in p for p in self.problems()))

    def test_committed_corners_dir_fails(self) -> None:
        (self.exp / "corners").mkdir()
        self.assertTrue(any("is not part of the lna-passive-study evidence layout"
                            in p for p in self.problems()))

    def test_scope_must_state_the_posture(self) -> None:
        plan_path = self.exp / "testbench" / "plan.json"
        plan = json.loads(plan_path.read_text())
        plan["scope"] = "a fine study"
        plan_path.write_text(json.dumps(plan))
        self.assertTrue(any("scope does not state" in p for p in self.problems()))

    def test_variant_outside_plan_fails(self) -> None:
        path = self.exp / "records" / f"{RID}.json"
        rec = json.loads(path.read_text())
        rec["variants"].append("V99")
        path.write_text(json.dumps(rec))
        self.assertTrue(any("outside the frozen plan" in p for p in self.problems()))


if __name__ == "__main__":
    unittest.main()
