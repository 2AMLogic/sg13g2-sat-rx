"""Fences for the committed layout/lna_stage1 records (issue #198).

These run in CI (the evidence-formats job collects `.github/scripts/tests`) and
need no PDK, no klayout and no simulator: everything checked here is a property
of files already in the tree. They are the stale-evidence fence for this
directory, playing the part `.github/workflows/signoff.yml` plays for
`signoff/block-manifest.json`.

Four invariants, each of which has a specific way of going wrong silently:

1. **Every record is bound to the committed layout.** A record whose
   `provenance.input.content_hash` no longer matches `lna_stage1_devices.gds`
   describes a different stream than the one in the tree -- the layout was
   regenerated and the records were not. Nothing else in CI would notice.

2. **`exit-codes.txt` agrees with the records.** The exit code is the one part
   of a run that lives outside the JSON, so it is the one part that can drift
   without any hash moving.

3. **No committed record carries an absolute host path.** `klt env-provenance
   lint-envelope` checks this locally; this keeps it checked after a hand edit,
   with no klt install needed.

4. **This directory still cites nothing.** `layout/lna_stage1/README.md`'s
   central claim is that no T1 item is claimed from it. That claim is prose
   until something enforces it, so this asserts the manifest carries no
   evidence entry pointing into `layout/`. If a later change legitimately does
   cite this layout, it must update this test deliberately -- which is the
   point.
"""

from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STUDY = REPO / "layout" / "lna_stage1"
RUNS = STUDY / "runs"

#: Record name -> the `status` value its exit code must agree with, and that
#: exit code. Taken from the committed records, so a tool whose verdict or exit
#: contract moves shows up here rather than in a README nobody re-reads.
EXPECTED = {
    "drc": ("clean", 0),
    "extract": ("extracted", 0),
    # `--findings-only` reports `status: not_checked` (the antenna half was
    # skipped) and exit 4; the supply verdict is `erc_status`.
    "erc": ("not_checked", 4),
    "ringcheck_activ": ("continuous", 0),
    "ringcheck_psd": ("continuous", 0),
    "ringcheck_m1": ("continuous", 0),
    "economy": (None, 0),  # economy reports no `status` field
    "lvs-devices": ("mismatch", 3),
}

ABSOLUTE_PATH_RE = re.compile(r"(?:/home/|/Users/|/root/)[A-Za-z0-9._-]")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_dirs() -> list[Path]:
    return sorted(p for p in RUNS.iterdir() if p.is_dir()) if RUNS.is_dir() else []


class LayoutStudyRecords(unittest.TestCase):
    def setUp(self):
        self.assertTrue(STUDY.is_dir(), f"missing {STUDY}")
        self.dirs = run_dirs()
        self.assertTrue(self.dirs, f"no run directories under {RUNS}")

    def test_records_are_bound_to_the_committed_layout(self):
        gds = STUDY / "lna_stage1_devices.gds"
        self.assertTrue(gds.is_file(), f"missing {gds}")
        expected = f"sha256:{sha256(gds)}"

        checked = 0
        for run in self.dirs:
            for record in sorted(run.glob("*.json")):
                if record.name.endswith(".request.json"):
                    continue
                data = json.loads(record.read_text())
                provenance = data.get("provenance")
                if not isinstance(provenance, dict):
                    # `klt ring-check` carries no provenance block at all
                    # (klayout-tools#5650) -- a recorded tool gap, not drift.
                    continue
                input_block = provenance.get("input")
                if not isinstance(input_block, dict):
                    continue
                got = input_block.get("content_hash")
                if got is None:
                    continue
                self.assertEqual(
                    got,
                    expected,
                    f"{record.relative_to(REPO)} is bound to a different "
                    "layout than the committed lna_stage1_devices.gds -- "
                    "regenerate the records with run_checks.sh",
                )
                checked += 1
        self.assertGreater(checked, 0, "no record bound the layout at all")

    def test_erc_record_is_bound_to_the_committed_supply_spec(self):
        spec = STUDY / "erc-supply-spec.json"
        self.assertTrue(spec.is_file(), f"missing {spec}")
        expected = f"sha256:{sha256(spec)}"
        for run in self.dirs:
            record = run / "erc.json"
            if not record.is_file():
                continue
            data = json.loads(record.read_text())
            self.assertEqual(
                data["provenance"]["spec"]["content_hash"],
                expected,
                f"{record.relative_to(REPO)} pins a different supply spec "
                "than the committed erc-supply-spec.json; T1 item 11 reads "
                "that hash before trusting any declaration in the spec",
            )

    def test_realizability_report_is_bound_to_the_committed_netlist(self):
        report = STUDY / "realizability.json"
        netlist = REPO / "design" / "netlist" / "lna_stage1.spice"
        self.assertTrue(report.is_file(), f"missing {report}")
        data = json.loads(report.read_text())
        self.assertEqual(
            data["inputs"]["netlist"]["path"], "design/netlist/lna_stage1.spice"
        )
        self.assertEqual(
            data["inputs"]["netlist"]["content_hash"],
            f"sha256:{sha256(netlist)}",
            "realizability.json was derived from a different netlist than the "
            "committed one -- re-run realizability.py; the per-element "
            "verdicts and the layout/lna_stage1/README.md tables rest on it",
        )
        # The verdict counts the README's headline rests on.
        self.assertEqual(data["element_count"], 18)
        self.assertEqual(
            data["verdict_counts"],
            {"pdk_primitive_modeled": 3, "no_primitive_selected": 12,
             "no_pdk_model": 3},
        )

    def test_exit_codes_agree_with_the_records(self):
        for run in self.dirs:
            codes_path = run / "exit-codes.txt"
            self.assertTrue(codes_path.is_file(), f"missing {codes_path}")
            codes = {}
            for line in codes_path.read_text().split("\n"):
                if not line.strip():
                    continue
                name, code = line.rsplit(" ", 1)
                codes[name] = int(code)

            records = {
                p.stem
                for p in run.glob("*.json")
                if not p.name.endswith(".request.json")
            }
            self.assertEqual(
                set(codes),
                records,
                f"{codes_path.relative_to(REPO)} and the records in "
                f"{run.relative_to(REPO)} name different runs",
            )

            for name, code in sorted(codes.items()):
                self.assertIn(name, EXPECTED, f"unexpected record {name!r}")
                want_status, want_code = EXPECTED[name]
                self.assertEqual(
                    code,
                    want_code,
                    f"{name} exited {code}, expected {want_code}",
                )
                data = json.loads((run / f"{name}.json").read_text())
                if want_status is None:
                    self.assertNotIn("status", data)
                else:
                    self.assertEqual(
                        data["status"],
                        want_status,
                        f"{name}.json status disagrees with its exit code",
                    )

    def test_erc_supply_half_is_clean_and_was_real_work(self):
        """The four things T1 item 11's ERC half is graded on.

        Asserted here, not just narrated in the README, because each one can
        regress to a *silent clean*: a degenerate tie grades as skipped rather
        than failed, and a supply that resolves to zero islands is reported in
        `erc_findings` rather than in `status`.
        """
        for run in self.dirs:
            record = run / "erc.json"
            if not record.is_file():
                continue
            data = json.loads(record.read_text())
            where = record.relative_to(REPO)
            self.assertEqual(data["erc_status"], "clean", f"{where}: erc_status")
            self.assertEqual(data["erc_findings"], [], f"{where}: erc_findings")
            coverage = data["erc_coverage"]
            self.assertEqual(
                coverage["skipped"],
                [],
                f"{where}: a skipped check is not a clean one -- a degenerate "
                "tie would land here",
            )
            self.assertEqual(
                sorted(coverage["checked"]),
                [
                    'erc.missing_tie:["psub_ring_tap"]',
                    'erc.net_connectivity:["gnd"]',
                    'erc.net_connectivity:["vdd"]',
                ],
                f"{where}: the set of checks that were real work changed",
            )
            for net in data["nets"]:
                self.assertEqual(
                    net["matched_islands"],
                    net["expected_islands"],
                    f"{where}: supply {net['name']!r} does not resolve to its "
                    "declared island count",
                )

    def test_no_record_carries_an_absolute_host_path(self):
        for run in self.dirs:
            for path in sorted(run.iterdir()):
                if not path.is_file():
                    continue
                text = path.read_text(errors="replace")
                hit = ABSOLUTE_PATH_RE.search(text)
                self.assertIsNone(
                    hit,
                    f"{path.relative_to(REPO)} carries an absolute host path "
                    f"({text[max(0, hit.start() - 20):hit.end() + 40]!r})"
                    if hit
                    else "",
                )

    def test_the_study_still_cites_no_t1_item(self):
        """layout/lna_stage1/README.md's central claim, enforced.

        A citation pointing into `layout/` would make this directory a T1 claim
        for a stream holding 3 of the stage's 18 elements. If that ever becomes
        right, this assertion has to be changed on purpose.
        """
        manifest = json.loads(
            (REPO / "signoff" / "block-manifest.json").read_text()
        )

        def cited_files(entry):
            entries = entry if isinstance(entry, list) else [entry]
            for item in entries:
                if isinstance(item, dict) and isinstance(item.get("file"), str):
                    yield item["file"]

        for item_id, entry in (manifest.get("evidence") or {}).items():
            for cited in cited_files(entry):
                self.assertFalse(
                    cited.startswith("layout/"),
                    f"T1 item {item_id} cites {cited!r}: nothing under "
                    "layout/ is a claiming artifact today (see "
                    "layout/lna_stage1/README.md and "
                    "layout/probe-readiness/README.md)",
                )


if __name__ == "__main__":
    unittest.main()
