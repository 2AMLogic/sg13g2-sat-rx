"""Negative controls for the spec-row coverage check of check_evidence_formats.py.

Standard library only. Each test copies the committed spec table, manifest and
the cited sim paths into a temp dir, breaks exactly one thing and asserts the
checker names it. The real tree is never modified.
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
sys.path.insert(0, str(SCRIPTS))

import check_evidence_formats as chk  # noqa: E402

IGNORE = shutil.ignore_patterns("_build", "_selftest", "__pycache__")


class RowCoverage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "spec").mkdir()
        for f in ("target-spec.md", "row-coverage.json"):
            shutil.copy(REPO / "spec" / f, self.root / "spec" / f)
        for name in ("lna-sparam-nf", "mixer-conversion-iip3", "mixer-nf-method"):
            shutil.copytree(REPO / "sim" / name, self.root / "sim" / name, ignore=IGNORE)
        self.man = self.root / "spec" / "row-coverage.json"

    def edit(self, fn) -> None:
        d = json.loads(self.man.read_text())
        fn(d)
        self.man.write_text(json.dumps(d, indent=2))

    def row(self, d: dict, n: int) -> dict:
        return next(r for r in d["rows"] if r["row"] == n)

    def messages(self) -> str:
        return "\n".join(str(i) for i in chk.check_row_coverage(self.root).items)

    def test_committed_manifest_is_clean(self) -> None:
        self.assertEqual(self.messages(), "")
        d = json.loads(self.man.read_text())
        self.assertEqual([r["row"] for r in d["rows"]], list(range(1, 21)))
        self.assertEqual(sum(r["status"] == "ratified-target" for r in d["rows"]), 11)

    def test_missing_row(self) -> None:
        self.edit(lambda d: d["rows"].remove(self.row(d, 12)))
        self.assertIn("row 12", self.messages())

    def test_ratified_row_absent(self) -> None:
        self.edit(lambda d: d["rows"].remove(self.row(d, 7)))
        self.assertIn("RATIFIED row silently absent", self.messages())

    def test_extra_row(self) -> None:
        self.edit(lambda d: d["rows"].append({"row": 21, "status": "open", "bound_corner": "-", "verdict": "no_bench", "blocked_by": "x"}))
        self.assertIn("row 21", self.messages())

    def test_status_mismatch(self) -> None:
        self.edit(lambda d: self.row(d, 5).update(status="ratified-target"))
        self.assertIn("disagrees with the spec table", self.messages())

    def test_dangling_bench(self) -> None:
        self.edit(lambda d: self.row(d, 2).update(bench="sim/does-not-exist"))
        self.assertIn("sim/does-not-exist", self.messages())

    def test_dangling_record(self) -> None:
        self.edit(lambda d: self.row(d, 2).update(latest_record="sim/lna-sparam-nf/records/nope.md"))
        self.assertIn("does not exist", self.messages())

    def test_overclaimed_verdict(self) -> None:
        self.edit(lambda d: self.row(d, 2).update(verdict="measured_pass"))
        self.assertIn("overclaimed", self.messages())

    def test_no_bench_needs_blocker(self) -> None:
        self.edit(lambda d: self.row(d, 7).pop("blocked_by"))
        self.assertIn("blocked_by", self.messages())

    def test_unknown_verdict(self) -> None:
        self.edit(lambda d: self.row(d, 2).update(verdict="looks_fine"))
        self.assertIn("not one of", self.messages())


if __name__ == "__main__":
    unittest.main()
