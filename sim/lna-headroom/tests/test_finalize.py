"""The unified finalize() mints correct stage-1 and stage-2 records from synthetic logs (issue #351).

The REAL finalize -- real analysis, renderer, record and snapshot layout -- runs against the
closed-form fake klt logs of test_headroom.py / test_refinement.py into temporary trees, and the
real verify_record() then re-derives each synthetic record from its frozen logs. This guards the
stage-specific branches (analysis inputs, ``stage``, small-signal snapshot files, renderer and
summary line) now that finalize_refined is collapsed into finalize. No simulator, PDK or network;
the committed records are not modified.
"""

from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path

import pytest

import headroom as H
from test_headroom import HP as HP1, LP, all_texts, hist_from as hist1_from
from test_refinement import HP as HP2, hist_from as hist2_from, stage2_texts


def load_run():
    spec = importlib.util.spec_from_file_location("lna_headroom_run", H.BENCH_DIR / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def mint_record(R, tmp_path: Path, monkeypatch, hp: dict, texts: dict) -> str:
    """Run the real write_requests + finalize on fakes into tmp_path; return the record id."""
    work = tmp_path / "work"
    work.mkdir()
    args = types.SimpleNamespace(klt_cmd="echo", backend="batch", timeout_s=60, no_stage_models=True,
                                 runner_version_check="warn")
    reqs = R.write_requests(hp, LP, work, "batch", args)
    reports = {}
    for key in H.request_keys(hp):
        rep = {"status": "pass", "corners": [{}], "environment": {
            "engine": "ngspice", "engine_version": "46", "models_lib_sha256": "a" * 64,
            "netlist_sha256": "a" * 64, "remote": {"provider": "aws-batch-fleet", "job_id": f"klt-sim-{key}"}},
               "provenance": {"klt_version": "test"}}
        (work / f"report_{key}.json").write_text(json.dumps(rep))
        reports[key] = rep
    monkeypatch.setattr(R, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(R, "LOGS", tmp_path / "corners")
    monkeypatch.setattr(R, "SNAPS", tmp_path / "netlist-snapshots")
    pdk = types.SimpleNamespace(path=tmp_path, model_lib=tmp_path / "cornerHBT.lib")
    import datetime as dt
    rc = R.finalize(hp, LP, work, reqs, texts, reports, pdk, dt.datetime.now(dt.timezone.utc), args)
    assert rc == 0
    return next(p.stem for p in (tmp_path / "records").glob("*.md"))


def test_finalize_mints_a_stage1_record_that_verifies(tmp_path, monkeypatch, capsys):
    R = load_run()
    texts = all_texts()
    monkeypatch.setattr(H, "load_historical", lambda rid: hist1_from(texts["C00"]))
    rid = mint_record(R, tmp_path, monkeypatch, HP1, texts)
    rec_dir, snap = tmp_path / "records", tmp_path / "netlist-snapshots" / rid
    # The repo's committed plan.json is at plan_version 2; freeze the stage-1 view the record was
    # collected against into the snapshot, exactly as the real stage-1 collection did when the
    # committed plan still had no refinement block.
    (snap / "plan.json").write_text(json.dumps(HP1, indent=2) + "\n")
    rec = json.loads((rec_dir / f"{rid}.json").read_text())
    assert rec["stage"] == 1 and rec["status"] == "COLLECTED" and rec["spec_rows_claimed_met"] == []
    assert [r["key"] for r in rec["klt_requests"]] == H.request_keys(HP1)
    assert (rec_dir / f"{rid}-sweeps.json.gz").is_file()
    assert not (snap / "sparam_fixture.spice").exists() and not (snap / "sparam_tb.json").exists()
    for key in H.request_keys(HP1):
        for stem in ("body_{}.spice", "request_{}.json", "report_{}.json"):
            assert (snap / stem.format(key)).is_file()
        assert (tmp_path / "corners" / rid / f"{key}.log.gz").is_file()
    for c in H.candidates(HP1):
        assert (snap / f"variant_{c['id']}.spice").is_file()
    md = (rec_dir / f"{rid}.md").read_text()
    assert "stage 1 screening" in md and "stage 2 refinement" not in md
    assert "shortlist" in capsys.readouterr().out
    assert R.verify_record(rid) == []


@pytest.mark.skipif(not H.refinement(HP2), reason="plan has no refinement block")
def test_finalize_mints_a_stage2_record_that_verifies(tmp_path, monkeypatch, capsys):
    R = load_run()
    texts = stage2_texts()
    monkeypatch.setattr(H, "load_stage1_historical", lambda hp: hist2_from(texts["C00_one"]))
    rid = mint_record(R, tmp_path, monkeypatch, HP2, texts)
    rec_dir, snap = tmp_path / "records", tmp_path / "netlist-snapshots" / rid
    rec = json.loads((rec_dir / f"{rid}.json").read_text())
    assert rec["stage"] == 2 and rec["status"] == "COLLECTED" and rec["spec_rows_claimed_met"] == []
    assert [r["key"] for r in rec["klt_requests"]] == H.request_keys(HP2)
    assert (snap / "sparam_fixture.spice").is_file() and (snap / "sparam_tb.json").is_file()
    for key in H.request_keys(HP2):
        for stem in ("body_{}.spice", "request_{}.json", "report_{}.json"):
            assert (snap / stem.format(key)).is_file()
        assert (tmp_path / "corners" / rid / f"{key}.log.gz").is_file()
    md = (rec_dir / f"{rid}.md").read_text()
    assert "stage 2 refinement" in md and "stage 1 screening" not in md
    assert "ranked" in capsys.readouterr().out
    assert R.verify_record(rid) == []
