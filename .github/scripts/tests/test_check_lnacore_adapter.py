"""Negative controls for the lna-core-variants layout of check_evidence_formats.py.

A synthetic record is written by the REAL ``corecollect.write_record`` from a
closed-form fake collection (the #74 ``matchfakes.FakeKlt``) into a temporary
copy of the bench, so the checker sees exactly the bytes the collector
produces. Each test breaks one thing and asserts a specific failure; the
unbroken record passes. No simulator, PDK or network; the real tree is never
modified.

Run: python3 -m pytest .github/scripts/tests/test_check_lnacore_adapter.py -q
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parents[1]
BENCH = REPO / "sim" / "lna-core-variants"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "tests"))
sys.path.insert(0, str(REPO / "sim" / "lna-match-tradeoff" / "tests"))

import check_evidence_formats as chk  # noqa: E402
import corecollect as cc  # noqa: E402
import corestudy as cs  # noqa: E402
import matchcollect as mc  # noqa: E402
import matchfakes as fakes  # noqa: E402
import matchstudy as ms  # noqa: E402
from test_corecollect import CONTROLS, GIT, fake_baseline_record  # noqa: E402

EXP = "sim/lna-core-variants"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    base = tmp_path_factory.mktemp("lnacore")
    root = base / "repo"
    exp = root / EXP
    (exp / "testbench").mkdir(parents=True)
    shutil.copyfile(BENCH / "testbench" / "variants.json", exp / "testbench" / "variants.json")
    st = ms.load_study(cs.METHOD_STUDY)
    dec = cs.load_declaration()
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(mc, "submit", fakes.FakeKlt(st, base / "fleet"))
        fake_baseline_record(base / "base.json")
        mp.setattr(cc, "BASELINE_RECORD_JSON", base / "base.json")
        mp.setattr(cc, "RECORDS", exp / "records")
        mp.setattr(cc, "CORNER_LOGS", exp / "corners")
        mp.setattr(cc, "SNAPSHOTS", exp / "netlist-snapshots")
        work = base / "work"
        work.mkdir()
        col = cc.run_collection(st, dec, work, fakes.Args())
        a = cc.assemble(st, dec, col["points"], CONTROLS)
        assert a["gate"] == []
        rid = cc.write_record(st, dec, col, a, CONTROLS,
                              pdk_prov={"fetched_version_file": "v", "model_sha256": {"cornerHBT.lib": "0" * 64}},
                              ngspice="ngspice-test", klt_version="klt-test",
                              started=dt.datetime(2026, 10, 11, tzinfo=dt.timezone.utc), git=GIT)
    finally:
        mp.undo()
    (exp / "README.md").write_text("# x\n\n## Running it\n\n```\npython3 run.py collect\n```\n")
    return root, rid


@pytest.fixture
def repo(built, tmp_path):
    src, rid = built
    root = tmp_path / "repo"
    shutil.copytree(src, root)
    return root, root / EXP, rid


def problems(root: Path) -> str:
    p = chk.Problems()
    chk.ADAPTERS["lna-core-variants"](p, root, root / EXP)
    return "\n".join(p.items)


def edit_json(path: Path, fn) -> None:
    d = json.loads(path.read_text())
    fn(d)
    path.write_text(json.dumps(d))


def edit_points(exp: Path, rid: str, fn) -> None:
    path = exp / "records" / f"{rid}-points.json.gz"
    pts = json.loads(gzip.decompress(path.read_bytes()))
    fn(pts)
    path.write_bytes(gzip.compress(json.dumps(pts).encode()))


def test_adapter_is_registered_and_the_unbroken_record_passes(repo):
    root, _, _ = repo
    assert "lna-core-variants" in chk.ADAPTERS
    assert problems(root) == ""


def test_whole_tree_walk_dispatches_to_the_adapter(repo):
    root, exp, rid = repo
    (exp / "records" / f"{rid}.json").unlink()
    out = "\n".join(chk.check_format(root).items)
    assert "no JSON sidecar" in out and "unrecognised evidence layout" not in out


def test_missing_and_corrupt_points_file(repo):
    root, exp, rid = repo
    (exp / "records" / f"{rid}-points.json.gz").write_bytes(b"\x1f\x8b broken")
    assert "unreadable gzip" in problems(root)
    (exp / "records" / f"{rid}-points.json.gz").unlink()
    assert "no points file" in problems(root)


def test_missing_undeclared_and_duplicate_points(repo):
    root, exp, rid = repo

    def mutate(pts):
        pts.pop(3)
        pts.append(dict(pts[0]))
        pts.append(dict(pts[1], id="nonexistent__hbt_typ_27c_2.50v"))

    edit_points(exp, rid, mutate)
    out = problems(root)
    for frag in ("missing declared point", "duplicate point id", "undeclared point"):
        assert frag in out


def test_nonfinite_and_short_bound_arrays(repo):
    root, exp, rid = repo

    def mutate(pts):
        oks = [x for x in pts if x["status"] == "ok"]
        oks[0]["bound"]["nf_bound_db"][4] = None
        oks[0]["summary"]["k_min"] = None
        for k in oks[1]["bound"]:
            oks[1]["bound"][k] = oks[1]["bound"][k][:-1]
        oks[2]["status"] = "error"
        oks[3].update(status="rejected_invalid", reason="")
        oks[4]["model_section"] = "hbt_wcs" if oks[4]["process"] != "hbt_wcs" else "hbt_typ"

    edit_points(exp, rid, mutate)
    out = problems(root)
    for frag in ("bound.nf_bound_db missing", "non-finite summary", "bound grid has 70 points",
                 "not a scientific outcome", "rejected point without a reason", "model_section"):
        assert frag in out


def test_gate_scope_reproduction_and_counts(repo):
    root, exp, rid = repo

    def mutate(d):
        d["gate"] = {"validate_collection": "failed", "problems": ["x"]}
        d["spec_rows_claimed_met"] = ["3"]
        d["reproduction"]["ok"] = False
        d["accepted_points"] = 1

    edit_json(exp / "records" / f"{rid}.json", mutate)
    out = problems(root)
    for frag in ("gate result is not recorded as passed", "no spec row is claimed", "reproduction",
                 "declared_points"):
        assert frag in out


def test_hashes_must_match_the_frozen_snapshots(repo):
    root, exp, rid = repo
    snap = exp / "netlist-snapshots" / rid
    with (snap / "variants.json").open("a") as fh:
        fh.write(" ")
    (snap / "lna_stage1.spice").write_text("* changed\n")
    out = problems(root)
    assert "frozen_inputs.variants_json_sha256" in out and "declaration.sha256" in out
    assert "frozen_inputs.design_netlist_sha256" in out


def test_chosen_variant_must_be_selectable(repo):
    root, exp, rid = repo
    edit_json(exp / "records" / f"{rid}.json", lambda d: d["selection"].update(chosen="diag_rbias_noiseless"))
    assert "not a declared selectable variant" in problems(root)


def test_snapshot_and_log_completeness(repo):
    root, exp, rid = repo
    snap = exp / "netlist-snapshots" / rid
    (snap / "netlist_ac.spice").unlink()
    (snap / "report_ac__2.500v.json").unlink()
    next((exp / "corners" / rid).glob("*.log.gz")).unlink()
    out = problems(root)
    assert "netlist_ac.spice" in out and "report_ac__2.500v.json" in out and "raw logs, but the requests ran" in out


def test_orphans_and_foreign_files(repo):
    root, exp, rid = repo
    (exp / "records" / "notes.txt").write_text("x")
    (exp / "corners" / "20990101-000000-abcdef0").mkdir()
    (exp / "probe-logs").mkdir()
    out = problems(root)
    assert "unexpected file in lna-core-variants records/" in out
    assert "orphan evidence" in out and "probe-logs/ is not part" in out
