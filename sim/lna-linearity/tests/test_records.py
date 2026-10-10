"""Record round trip and reproduction of committed records (issue #57).

``run.finalize`` writes a record from closed-form fake logs into a temporary tree and
``run.verify_record`` must re-derive the published verdicts from the frozen logs alone;
tampering with a frozen log, the plan or a body must be noticed. Every committed record is
verified the same way. No simulator, PDK or network.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import types

import pytest

import analysis as A
import fakes
import linearity as L
import run as R
from conftest import BENCH


@pytest.fixture()
def built(tmp_path, monkeypatch):
    plan = L.load_plan(BENCH / "testbench" / "plan.json")
    monkeypatch.setattr(R, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(R, "LOGS", tmp_path / "corners")
    monkeypatch.setattr(R, "SNAPS", tmp_path / "snaps")
    monkeypatch.setattr(R, "plan_provenance", lambda: {"file": "x", "sha256": R.sha256_file(R.PLAN_PATH), "commit": "b" * 40, "dirty": False})
    monkeypatch.setattr(R, "dirty_code", lambda: [])
    # build and verify must not depend on a simulator binary on this host (the CI job has none)
    real_which = R.shutil.which
    monkeypatch.setattr(R.shutil, "which", lambda name, *a, **k: None if name == "ngspice" else real_which(name, *a, **k))
    work = tmp_path / "work"
    work.mkdir()
    args = types.SimpleNamespace(klt_cmd="echo klt-test", backend="batch", timeout_s=60, no_stage_models=True,
                                 runner_version_check="warn")
    reqs = R.write_requests(plan, work, "batch", args)
    reports = {}
    for key in reqs:
        rep = {"status": "pass", "corners": [{}], "environment": {"engine": "ngspice", "engine_version": "46",
               "models_lib_sha256": "a" * 64, "netlist_sha256": "a" * 64, "remote": {"job_id": key}}, "provenance": {}}
        (work / f"report_{key}.json").write_text(json.dumps(rep))
        reports[key] = rep
    amp40 = L.cubic_tone_amps(10.0, -2000.0, L.vs_peak_from_pav_dbm(-40.0), False)["f0"]
    texts = fakes.fake_logs(plan, excursion_per_v=0.14 / amp40, floor_v=1e-9)
    pdk = types.SimpleNamespace(path=tmp_path, model_lib=tmp_path / "cornerHBT.lib")
    assert R.finalize(plan, work, reqs, texts, reports, R.python_controls(plan), pdk,
                      dt.datetime.now(dt.timezone.utc), args) == 0
    rid = next((tmp_path / "records").glob("*.md")).stem
    return rid, tmp_path


def test_published_verdicts_reproduce_from_frozen_logs(built):
    rid, _ = built
    assert R.verify_record(rid) == []


def test_tampered_log_is_noticed(built):
    rid, tmp = built
    p = tmp / "corners" / rid / "mid_two.log.gz"
    text = gzip.open(p, "rt").read()
    # nudge one IM3 amplitude inside the fit: the stored verdicts no longer reproduce
    text = text.replace("m_b_two10_im3l_c = ", "m_b_two10_im3l_c = 9", 1)
    with gzip.open(p, "wt") as fh:
        fh.write(text)
    probs = R.verify_record(rid)
    assert probs and any("do not reproduce" in x for x in probs)


def test_edited_body_is_noticed(built):
    rid, tmp = built
    body = tmp / "snaps" / rid / "body_low_one.spice"
    body.write_text(body.read_text().replace("alterparam va1", "alterparam va1 ", 1) + "\n* edited\n")
    assert any("does not regenerate" in x for x in R.verify_record(rid))


def test_record_states_the_placeholder_scope_and_targets(built):
    rid, tmp = built
    rec = json.loads((tmp / "records" / f"{rid}.json").read_text())
    assert rec["spec_rows_claimed_met"] == [] and "placeholder" in rec["scope"]
    assert rec["plan_declaration"]["targets"]["iip3_dbm"] == -15.0 and rec["plan_declaration"]["targets"]["p1db_dbm"] == -25.0
    md = (tmp / "records" / f"{rid}.md").read_text()
    assert "**Claim**" in md and "IDEAL lossless L/C matching" in md and "unchanged" in md
    assert rec["status"] == "COLLECTED"
    # host ngspice is collect-time provenance only; its absence is recorded, never fatal
    assert rec["environment"]["host_ngspice"] == ["ngspice not found on the collecting host's PATH"]


def test_failing_control_gives_a_controls_failed_record_not_a_verdict(tmp_path, monkeypatch):
    plan = L.load_plan(BENCH / "testbench" / "plan.json")
    texts = fakes.fake_logs(plan, floor_v=1e-9)
    texts["control_two"] = fakes.fake_log(plan, "control_two", a1=10.0, a3=-900.0, floor_v=1e-9)
    res = A.analyze(plan, texts)
    assert not res["ngspice_control"]["pass"]


@pytest.mark.parametrize("rid", sorted(p.stem for p in (BENCH / "records").glob("*.json")) if (BENCH / "records").is_dir() else [])
def test_committed_records_reproduce(rid):
    assert R.verify_record(rid) == []
