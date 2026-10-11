"""The lna-core-variants collection against the #74 closed-form fake klt.

No simulator, PDK or network: ``matchcollect.submit`` is replaced by the #74
``matchfakes.FakeKlt`` (every variant's deck sees the same closed-form core,
which is enough to exercise planning, ingest, the gate and the record
writer), and the #74 baseline record by one computed from the fake.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH.parent / "lna-match-tradeoff" / "tests"))

import corecollect as cc  # noqa: E402
import corestudy as cs  # noqa: E402
import matchcollect as mc  # noqa: E402
import matchfakes as fakes  # noqa: E402
import matchstudy as ms  # noqa: E402

ST = ms.load_study(cs.METHOD_STUDY)
DEC = cs.load_declaration()
GIT = {"commit": "abcdef0" * 5 + "abcde", "short": "abcdef0", "branch": "t", "dirty": False}
CONTROLS = {"pad_27c": {"ok": True, "nf_err_db": 1e-6},
            "local_vs_fleet_core0_nominal": {"ok": True, "worst_db": 0.0, "tol_db": 1e-3}}


def fake_baseline_record(path: Path, *, shift: float = 0.0) -> None:
    bounds = {}
    for p, t, v in ST.pvt_points():
        pl = ms.parse_log(fakes.fake_log(ST, [c.name for c in cs.networks(ST)], p, t, v))
        b = ms.point_bound(ST, pl.tables, cs.networks(ST))
        s = dict(b["summary"])
        s["nf_bound_max_db"] += shift
        bounds[f"corners__{ms.corner_id(p, t, v)}"] = {"summary": s}
    path.write_text(json.dumps({"bounds": bounds}))


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake = fakes.FakeKlt(ST, tmp_path / "fleet")
    monkeypatch.setattr(mc, "submit", fake)
    for name, sub in (("RECORDS", "records"), ("CORNER_LOGS", "corners"), ("SNAPSHOTS", "netlist-snapshots")):
        monkeypatch.setattr(cc, name, tmp_path / "bench" / sub)
    fake_baseline_record(tmp_path / "base.json")
    monkeypatch.setattr(cc, "BASELINE_RECORD_JSON", tmp_path / "base.json")
    work = tmp_path / "work"
    work.mkdir()
    return fake, work, tmp_path


def args(**kw):
    a = fakes.Args()
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def test_one_batch_request_per_variant_and_supply(env):
    fake, work, _ = env
    col = cc.run_collection(ST, DEC, work, args())
    assert len(fake.calls) == len(DEC.variants) * len(ST.supplies_v)
    assert {c["backend"] for c in fake.calls} == {"batch"}
    assert all(c["units"] == 9 for c in fake.calls)
    assert len(col["points"]) == len(cs.expected_points(ST, DEC))
    body = (work / "body_ac__2.500v.spice").read_text()
    assert "Le1 e1 e1d" in body and "* CORE VARIANT ac" in body
    assert (work / "netlist_abc.spice").is_file()


def test_failed_batch_submit_stops_without_record_or_local_fallback(env, tmp_path, monkeypatch):
    fake = fakes.FakeKlt(ST, tmp_path / "fleet2", fail_on="c_rbias")
    monkeypatch.setattr(mc, "submit", fake)
    with pytest.raises(mc.CollectionError, match="klt sim failed"):
        cc.run_collection(ST, DEC, env[1], args())
    assert not (tmp_path / "bench").exists()


def test_corrupt_unit_log_stops_the_collection(env, tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "submit", fakes.FakeKlt(ST, tmp_path / "fleet3", corrupt=("a_le__2.250v", "probe_thru")))
    with pytest.raises(mc.CollectionError, match="corrupt"):
        cc.run_collection(ST, DEC, env[1], args())


def test_record_is_written_once_with_gate_reproduction_and_selection(env):
    _, work, tmp = env
    col = cc.run_collection(ST, DEC, work, args())
    a = cc.assemble(ST, DEC, col["points"], CONTROLS)
    assert a["gate"] == [], a["gate"]
    assert a["rep"]["ok"] and a["rep"]["compared_points"] == 27
    started = dt.datetime(2026, 10, 11, 3, 0, 0, tzinfo=dt.timezone.utc)
    rid = cc.write_record(ST, DEC, col, a, CONTROLS, pdk_prov={"model_sha256": {"x": "0"}}, ngspice="fake",
                          klt_version="fake", started=started, git=GIT)
    rec = tmp / "bench" / "records"
    md = (rec / f"{rid}.md").read_text()
    assert md.splitlines()[0] == f"# lna-core-variants record {rid}"
    for marker in ("**Spec rows claimed met**: none", "## Per-variant comparison", "## Selection",
                   "## Per-point bound", "## Conclusion", "hbt_wcs_125c_2.25v"):
        assert marker in md
    data = json.loads((rec / f"{rid}.json").read_text())
    assert data["gate"]["validate_collection"] == "passed" and data["spec_rows_claimed_met"] == []
    assert data["declared_points"] == data["accepted_points"] == 216
    with gzip.open(rec / f"{rid}-points.json.gz", "rt") as fh:
        assert len(json.load(fh)) == 216
    logs = list((tmp / "bench" / "corners" / rid).glob("*.log.gz"))
    assert len(logs) == 24 * 9
    snap = tmp / "bench" / "netlist-snapshots" / rid
    for f in ("variants.json", "study.json", "lna_stage1.spice", "netlist_ac.spice", "body_ac__2.500v.spice",
              "request_ac__2.500v.json", "report_ac__2.500v.json", "spec_ac__2.500v.json"):
        assert (snap / f).is_file(), f
    # append-only: a second record never overwrites the first
    rid2 = cc.write_record(ST, DEC, col, a, CONTROLS, pdk_prov={}, ngspice="fake", klt_version="fake",
                           started=started, git=GIT)
    assert rid2 != rid and (rec / f"{rid}.md").read_text() == md


def test_reproduction_mismatch_or_failed_control_blocks_the_record(env, tmp_path, monkeypatch):
    _, work, _ = env
    col = cc.run_collection(ST, DEC, work, args())
    fake_baseline_record(tmp_path / "shifted.json", shift=0.01)
    monkeypatch.setattr(cc, "BASELINE_RECORD_JSON", tmp_path / "shifted.json")
    a = cc.assemble(ST, DEC, col["points"], CONTROLS)
    assert any("reproduction" in g for g in a["gate"])
    with pytest.raises(mc.CollectionError, match="gate failed"):
        cc.write_record(ST, DEC, col, a, CONTROLS, pdk_prov={}, ngspice="f", klt_version="f",
                        started=dt.datetime.now(dt.timezone.utc), git=GIT)
    monkeypatch.setattr(cc, "BASELINE_RECORD_JSON", tmp_path / "base.json")
    bad = dict(CONTROLS, pad_27c={"ok": False})
    assert any("pad_27c" in g for g in cc.assemble(ST, DEC, col["points"], bad)["gate"])


def test_dry_run_writes_every_request_and_submits_nothing(env):
    fake, work, _ = env
    cc.run_collection(ST, DEC, work, args(dry_run=True))
    assert not fake.calls
    assert len(list(work.glob("request_*.json"))) == 24
