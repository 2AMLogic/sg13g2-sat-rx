"""Negative controls for the lna-match-tradeoff layout of check_evidence_formats.py.

A synthetic record is written by the REAL ``collect.write_record`` from a
closed-form fake collection (sim/lna-match-tradeoff/tests/fakes.py) into a
temporary copy of the bench, so the checker sees exactly the bytes the
collector produces. Each test breaks one thing and asserts a specific
failure; the unbroken record passes. No simulator, PDK or network; the real
tree is never modified.

Run: python3 -m pytest .github/scripts/tests/test_check_lnamatch_adapter.py -q
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parents[1]
BENCH = REPO / "sim" / "lna-match-tradeoff"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "tests"))

import check_evidence_formats as chk  # noqa: E402
import matchcollect as collect  # noqa: E402
import matchfakes as fakes  # noqa: E402
import matchstudy as ms  # noqa: E402
from test_matchcollect import CONTROLS, GIT, write_fake_baseline_logs  # noqa: E402

EXP = "sim/lna-match-tradeoff"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """One synthetic record, built once; tests work on copies."""
    base = tmp_path_factory.mktemp("lnam")
    root = base / "repo"
    exp = root / EXP
    (exp / "testbench").mkdir(parents=True)
    shutil.copyfile(BENCH / "testbench" / "study.json", exp / "testbench" / "study.json")
    st = ms.load_study()
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(collect, "submit", fakes.FakeKlt(st, base / "fleet"))
        write_fake_baseline_logs(base / "baseline")
        mp.setattr(collect, "BASELINE_LOGS", base / "baseline")
        mp.setattr(collect, "RECORDS", exp / "records")
        mp.setattr(collect, "CORNER_LOGS", exp / "corners")
        mp.setattr(collect, "SNAPSHOTS", exp / "netlist-snapshots")
        work = base / "work"
        work.mkdir()
        col = collect.run_collection(st, work, fakes.Args())
        a = collect.assemble(st, col, CONTROLS)
        assert a["gate"] == []
        rid = collect.write_record(
            st, col, rep=a["rep"], xc=a["xc"], controls=CONTROLS, concl=a["concl"], gate=a["gate"],
            pdk_prov={"fetched_version_file": "v", "model_sha256": {"cornerHBT.lib": "0" * 64}},
            ngspice="ngspice-test", klt_version="klt-test",
            started=dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc), git=GIT)
    finally:
        mp.undo()
    return root, rid


@pytest.fixture
def repo(built, tmp_path):
    src, rid = built
    root = tmp_path / "repo"
    shutil.copytree(src, root)
    return root, root / EXP, rid


def problems(root: Path) -> str:
    p = chk.Problems()
    chk.ADAPTERS["lna-match-tradeoff"](p, root, root / EXP)
    return "\n".join(p.items)


def edit_json(path: Path, fn) -> None:
    d = json.loads(path.read_text())
    fn(d)
    path.write_text(json.dumps(d))


def edit_cells(exp: Path, rid: str, fn) -> None:
    path = exp / "records" / f"{rid}-cells.json.gz"
    cells = json.loads(gzip.decompress(path.read_bytes()))
    fn(cells)
    path.write_bytes(gzip.compress(json.dumps(cells).encode()))


def first_ok(cells, role="candidate"):
    return next(c for c in cells if c["status"] == "ok" and c["role"] == role)


def test_adapter_is_registered_and_the_unbroken_record_passes(repo):
    root, _, _ = repo
    assert "lna-match-tradeoff" in chk.ADAPTERS
    assert problems(root) == ""


def test_whole_tree_walk_dispatches_to_the_adapter(repo):
    root, exp, rid = repo
    (exp / "records" / f"{rid}.json").unlink()
    out = "\n".join(chk.check_format(root).items)
    assert "no JSON sidecar" in out and "unrecognised evidence layout" not in out


def test_missing_sidecar_json(repo):
    root, exp, rid = repo
    (exp / "records" / f"{rid}.json").unlink()
    assert "no JSON sidecar" in problems(root)


def test_corrupted_cells_file(repo):
    root, exp, rid = repo
    (exp / "records" / f"{rid}-cells.json.gz").write_bytes(b"\x1f\x8b broken")
    assert "unreadable gzip" in problems(root)


def test_missing_cells_file(repo):
    root, exp, rid = repo
    (exp / "records" / f"{rid}-cells.json.gz").unlink()
    assert "no cells file" in problems(root)


def test_missing_declared_cell(repo):
    root, exp, rid = repo
    edit_cells(exp, rid, lambda cs: cs.pop(5))
    out = problems(root)
    assert "missing declared cell" in out and "cells on disk" in out


def test_undeclared_and_duplicate_cell(repo):
    root, exp, rid = repo

    def mutate(cs):
        cs.append(dict(cs[0]))
        cs.append(dict(cs[1], id="corners__nonexistent__hbt_typ_27c_2.50v"))

    edit_cells(exp, rid, mutate)
    out = problems(root)
    assert "duplicate cell id" in out and "undeclared cell" in out


def test_nonfinite_value_in_an_ok_cell(repo):
    root, exp, rid = repo

    def mutate(cs):
        c = first_ok(cs)
        c["band"]["nf_db"][7] = None  # how the writer stores a NaN
        c["summary"]["nf_max_db"] = None

    edit_cells(exp, rid, mutate)
    out = problems(root)
    assert "band.nf_db missing, wrong length or non-finite" in out and "non-finite summary" in out


def test_wrong_frequency_grid(repo):
    root, exp, rid = repo

    def mutate(cs):
        b = first_ok(cs)["band"]
        for k in b:
            b[k] = b[k][:-1]

    edit_cells(exp, rid, mutate)
    assert "band grid has 70 points, the declaration says 71" in problems(root)


def test_refined_control_and_status_and_reason(repo):
    root, exp, rid = repo

    def mutate(cs):
        oks = [c for c in cs if c["status"] == "ok" and c["role"] == "candidate"]
        oks[0]["refined"]["ok"] = False
        oks[1]["status"] = "error"
        oks[2].update(status="rejected_invalid", reason="")
        oks[3]["model_section"] = "hbt_wcs" if oks[3]["process"] != "hbt_wcs" else "hbt_typ"

    edit_cells(exp, rid, mutate)
    out = problems(root)
    for frag in ("without a passing refined-grid control", "not a scientific outcome",
                 "rejected cell without a reason", "model_section"):
        assert frag in out


def test_gate_scope_and_counts(repo):
    root, exp, rid = repo

    def mutate(d):
        d["gate"] = {"validate_collection": "failed", "problems": ["x"]}
        d["declared_cells"] += 1
        d["scope"] = "feasible"
        d["spec_rows_claimed_met"] = [3]

    edit_json(exp / "records" / f"{rid}.json", mutate)
    out = problems(root)
    assert "gate result is not recorded as passed" in out and "declared_cells" in out
    assert "no spec row is claimed met" in out


def test_provenance_and_frozen_input_hashes(repo):
    root, exp, rid = repo

    def mutate(d):
        del d["provenance"]["klt"]
        d["provenance"]["pdk"]["model_sha256"] = {}
        d["declaration"]["sha256"] = "0" * 64

    edit_json(exp / "records" / f"{rid}.json", mutate)
    (exp / "netlist-snapshots" / rid / "lna_stage1.spice").write_text("* edited\n")
    out = problems(root)
    for frag in ("provenance.klt", "model_sha256", "declaration.sha256 does not match",
                 "design_netlist_sha256 does not match"):
        assert frag in out


def test_shortlist_must_be_declared_and_start_with_baseline(repo):
    root, exp, rid = repo
    edit_json(exp / "records" / f"{rid}.json",
              lambda d: d["shortlist"].update(names=["probe_thru"] + d["shortlist"]["names"]))
    out = problems(root)
    assert "start with the declared baseline" in out and "not a declared selectable network" in out


def test_raw_logs_and_snapshot_pieces(repo):
    root, exp, rid = repo
    logs = sorted((exp / "corners" / rid).glob("*.log.gz"))
    logs[0].write_bytes(b"not gzip")
    logs[1].unlink()
    snap = exp / "netlist-snapshots" / rid
    next(snap.glob("body_corners__*")).unlink()
    (snap / "study.json").unlink()
    out = problems(root)
    assert "unreadable gzip" in out and "raw logs, but the requests ran 28 units" in out
    assert "snapshot lacks body_corners__" in out and "snapshot lacks the frozen declaration" in out


def test_markdown_must_keep_its_disclaimers(repo):
    root, exp, rid = repo
    md = exp / "records" / f"{rid}.md"
    md.write_text(md.read_text().replace("Spec rows claimed met**: none", "Spec rows claimed met**: 3"))
    assert "Spec rows claimed met**: none" in problems(root)


def test_orphans_and_stray_files(repo):
    root, exp, rid = repo
    (exp / "records" / "20260101-000000-1234567.json").write_text("{}")
    (exp / "records" / "notes.txt").write_text("x")
    (exp / "corners" / "20260101-000000-1234567").mkdir()
    out = problems(root)
    assert "belongs to no record (no 20260101-000000-1234567.md)" in out
    assert "unexpected file in lna-match-tradeoff records/" in out and "orphan evidence" in out


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_editing_a_committed_record_fails_append_only(repo):
    root, exp, rid = repo
    _git(root, "init", "-q", "-b", "main")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "record")
    md = exp / "records" / f"{rid}.md"
    md.write_text(md.read_text().replace("Outcome", "Outcome (edited)"))
    hist, _ = chk.check_append_only(root, "main", True)
    assert any(f"records/{rid}.md" in i and "modified" in i for i in hist.items)
