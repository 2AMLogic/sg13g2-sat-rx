"""Negative controls for the mixer-topology-feasibility layout of
check_evidence_formats.py.

A synthetic record is written by the REAL ``collect.write_record`` from a
fake (closed-form) collection into a temporary copy of the bench, so the
checker is exercised on the exact bytes the collector produces. Each test
breaks one thing and asserts a file-specific failure; the unbroken record
must pass. No simulator, PDK or network. The real tree is never modified.

Run: python3 -m pytest .github/scripts/tests/test_check_mixfeas_adapter.py -q
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
BENCH = REPO / "sim" / "mixer-topology-feasibility"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "tests"))

import check_evidence_formats as chk  # noqa: E402
import collect  # noqa: E402
import mixfeas as mf  # noqa: E402
import test_collect as tc  # noqa: E402


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """tmp repo with the bench's tb.json and one synthetic record."""
    root = tmp_path / "repo"
    exp = root / "sim" / "mixer-topology-feasibility"
    (exp / "testbench").mkdir(parents=True)
    for f in (BENCH / "testbench").iterdir():
        shutil.copyfile(f, exp / "testbench" / f.name)
    study = mf.study_from_manifest(json.loads((exp / "testbench" / "tb.json").read_text()))
    fake_dir = tmp_path / "fake"
    fake_dir.mkdir()
    monkeypatch.setattr(collect, "submit", tc.Fake(study, fake_dir))
    work = tmp_path / "work"
    work.mkdir()
    col = collect.run_collection(study, ["reltol=1e-5"], work, tc.args())
    assert mf.validate_collection(study, col.cells) == []
    summary = collect.build_summary(study, col, mf.conclude(study, collect.per_candidate(study, col)))
    monkeypatch.setattr(collect, "RECORDS", exp / "records")
    monkeypatch.setattr(collect, "CORNER_LOGS", exp / "corners")
    monkeypatch.setattr(collect, "SNAPSHOTS", exp / "netlist-snapshots")
    monkeypatch.setattr(collect, "TB_DIR", exp / "testbench")
    rid = collect.write_record(
        study, json.loads((exp / "testbench" / "tb.json").read_text()), col, summary,
        pdk_prov={"fetched_version_file": "v", "model_sha256": {"cornerHBT.lib": "0" * 64}},
        ngspice="ngspice-test", klt_version="klt-test",
        crosscheck={"summary": "synthetic", "compared": 3}, converge={"c": {"drive_dbm": -6.0, "drive_kind": "selected", "ok": True, "checks": [], "failures": []}},
        claim="synthetic", supersedes="", started=dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc),
        git={"commit": "abcdef0" * 5 + "abcde", "short": "abcdef0", "branch": "t", "dirty": False})
    return root, exp, rid


def problems(root):
    return "\n".join(chk.check_format(root).items)


def test_unbroken_synthetic_record_passes(repo):
    root, _, _ = repo
    assert problems(root) == ""


def test_missing_sidecar_json(repo):
    root, exp, rid = repo
    (exp / "records" / f"{rid}.json").unlink()
    assert "no JSON sidecar" in problems(root)


def test_missing_cells_file(repo):
    root, exp, rid = repo
    (exp / "records" / f"{rid}-cells.json.gz").unlink()
    assert "no cells file" in problems(root)


def edit_cells(exp, rid, fn):
    path = exp / "records" / f"{rid}-cells.json.gz"
    cells = json.loads(gzip.decompress(path.read_bytes()))
    fn(cells)
    path.write_bytes(gzip.compress(json.dumps(cells).encode()))


def test_duplicate_cell_and_count_mismatch(repo):
    root, exp, rid = repo
    edit_cells(exp, rid, lambda cs: cs.append(dict(cs[0])))
    out = problems(root)
    assert "duplicate cell id" in out and "cells on disk" in out


def test_corrupt_status_is_not_a_scientific_outcome(repo):
    root, exp, rid = repo
    edit_cells(exp, rid, lambda cs: cs[0].update(status="error"))
    assert "not a scientific outcome" in problems(root)


def test_wrong_model_section_and_seed(repo):
    root, exp, rid = repo

    def mutate(cs):
        cs[0]["model_section"] = "hbt_typ" if cs[0]["corner"] != "hbt_typ" else "hbt_wcs"
        next(c for c in cs if c["matrix"] == "leakage")["seed"] = 1

    edit_cells(exp, rid, mutate)
    out = problems(root)
    assert "model_section" in out and "leakage cell seed" in out


def test_status_contradicting_stress(repo):
    root, exp, rid = repo
    edit_cells(exp, rid, lambda cs: next(c for c in cs if c["status"] == "ok").update(status="rejected_stress"))
    assert "contradicts its stress violations" in problems(root)


def test_gate_not_passed_and_declared_mismatch(repo):
    root, exp, rid = repo
    path = exp / "records" / f"{rid}.json"
    d = json.loads(path.read_text())
    d["gate"] = {"validate_collection": "failed", "problems": ["x"]}
    d["declared_cells"] += 1
    path.write_text(json.dumps(d))
    out = problems(root)
    assert "gate result is not recorded as passed" in out and "declared_cells" in out


def test_missing_provenance_and_scope(repo):
    root, exp, rid = repo
    path = exp / "records" / f"{rid}.json"
    d = json.loads(path.read_text())
    del d["provenance"]["klt"]
    d["provenance"]["pdk"]["model_sha256"] = {}
    d["scope"] = "feasible"
    path.write_text(json.dumps(d))
    out = problems(root)
    assert "provenance.klt" in out and "model_sha256" in out and "no spec row is claimed" in out


def test_missing_and_broken_raw_logs(repo):
    root, exp, rid = repo
    logs = sorted((exp / "corners" / rid).glob("*.log.gz"))
    logs[0].write_bytes(b"not gzip")
    assert "unreadable gzip" in problems(root)
    shutil.rmtree(exp / "corners" / rid)
    assert "no corners/<id>/*.log.gz" in problems(root)


def test_snapshot_pieces_required(repo):
    root, exp, rid = repo
    snap = exp / "netlist-snapshots" / rid
    (snap / "tb.json").unlink()
    next(snap.glob("body_*")).unlink()
    for p in list(snap.glob("body_*")):
        p.unlink()
    out = problems(root)
    assert "snapshot lacks tb.json" in out and "no body_* file" in out


def test_markdown_must_keep_its_disclaimers(repo):
    root, exp, rid = repo
    md = exp / "records" / f"{rid}.md"
    md.write_text(md.read_text().replace("Spec rows claimed met**: none", "Spec rows claimed met**: all"))
    assert "Spec rows claimed met**: none" in problems(root)


def test_orphan_evidence_file(repo):
    root, exp, rid = repo
    (exp / "records" / "20260101-000000-1234567-extra.csv").write_text("x")
    assert "belongs to no record" in problems(root)
