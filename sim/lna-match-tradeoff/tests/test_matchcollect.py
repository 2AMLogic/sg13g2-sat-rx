"""The whole lna-match-tradeoff collection against a closed-form fake klt.

No simulator, PDK or network: ``collect.submit`` is replaced by
``fakes.FakeKlt`` and the lna-sparam-nf baseline logs by fake logs computed
from the same closed-form core. Covers request planning and backends, the
shortlist hand-off, a failed batch submit (no record, no local fallback),
corrupt logs, the gate, and the record writer (append-only).
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import math
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "tests"))

import matchcollect as collect  # noqa: E402
import matchfakes as fakes  # noqa: E402
import matchstudy as ms  # noqa: E402

ST = ms.load_study()
GIT = {"commit": "abcdef0" * 5 + "abcde", "short": "abcdef0", "branch": "t", "dirty": False}
CONTROLS = {"pad_27c": {"ok": True, "nf_err_db": 1e-6}, "pad_-40c": {"ok": True, "nf_err_db": 1e-6}}


def write_fake_baseline_logs(d: Path) -> None:
    """m_* logs in the lna-sparam-nf format, from the fake core, for every PVT point."""
    d.mkdir(parents=True, exist_ok=True)
    for p, t, v in ST.pvt_points():
        pl = ms.parse_log(fakes.fake_log(ST, ["baseline"], p, t, v))
        b = ms.analyze_candidate(ST, ST.baseline, pl.tables["baseline"])["band"]
        lines = []
        for suf, i in (("lo", 0), ("mid", 35), ("hi", 70)):
            for q in ("s11", "s21", "s22", "s12"):
                lines.append(f"m_{q}_db_{suf} = {b[q + '_db'][i]:.10e}")
            lines.append(f"m_nf_db_{suf} = {b['nf_db'][i]:.10e}")
            lines.append(f"m_k_{suf} = {b['k'][i]:.10e}")
        (d / f"{ms.corner_id(p, t, v)}.log").write_text("\n".join(lines) + "\n")


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake = fakes.FakeKlt(ST, tmp_path / "fleet")
    monkeypatch.setattr(collect, "submit", fake)
    write_fake_baseline_logs(tmp_path / "baseline")
    monkeypatch.setattr(collect, "BASELINE_LOGS", tmp_path / "baseline")
    for name, sub in (("RECORDS", "records"), ("CORNER_LOGS", "corners"), ("SNAPSHOTS", "netlist-snapshots")):
        monkeypatch.setattr(collect, name, tmp_path / "bench" / sub)
    work = tmp_path / "work"
    work.mkdir()
    return fake, work, tmp_path


def run(env, **kw):
    fake, work, _ = env
    args = fakes.Args()
    for k, v in kw.items():
        setattr(args, k, v)
    return collect.run_collection(ST, work, args)


def test_request_plan_backends_and_shortlist_handoff(env):
    fake, work, _ = env
    col = run(env)
    keys = [c["key"] for c in fake.calls]
    assert keys == ["screen__2.500v", "corners__2.250v", "corners__2.500v", "corners__2.750v"]
    assert fake.calls[0]["backend"] == "local" and fake.calls[0]["units"] == 1
    assert all(c["backend"] == "batch" and c["units"] == 9 for c in fake.calls[1:])
    assert fake.calls[1]["request"]["corners"]["process"] == list(ST.processes)
    assert fake.calls[1]["request"]["backend"] == "batch"
    spec = json.loads((work / "spec_corners__2.250v.json").read_text())
    assert spec["networks"][0] == "baseline" and spec["networks"][: len(col.shortlist["names"])] == col.shortlist["names"]
    assert all(n.startswith("probe_") for n in spec["networks"][len(col.shortlist["names"]):])
    assert len(col.cells) == len(ms.expected_cells(ST, col.shortlist["names"]))
    assert len(col.bounds) == 1 + 27


def test_values_never_change_across_corners(env):
    _, work, _ = env
    col = run(env)
    bodies = [(work / f"body_corners__{v:.3f}v.spice").read_text() for v in ST.supplies_v]
    for name in col.shortlist["names"]:
        c = ST.candidate(name)
        lines = {f"alterparam {k} = {v!r}" for k, v in c.params().items()}
        for b in bodies:
            assert lines <= set(b.splitlines())


def test_failed_batch_submit_stops_without_record_or_local_fallback(env, tmp_path, monkeypatch):
    fake = fakes.FakeKlt(ST, tmp_path / "fleet2", fail_on="corners__2.500v")
    monkeypatch.setattr(collect, "submit", fake)
    with pytest.raises(collect.CollectionError, match="klt sim failed"):
        run(env)
    assert [c["backend"] for c in fake.calls] == ["local", "batch", "batch"]
    assert not (tmp_path / "bench" / "records").exists()


def test_corrupt_unit_log_stops_the_collection(env, tmp_path, monkeypatch):
    fake = fakes.FakeKlt(ST, tmp_path / "fleet3", corrupt=("corners__2.250v", "baseline"))
    monkeypatch.setattr(collect, "submit", fake)
    with pytest.raises(collect.CollectionError, match="corrupt"):
        run(env)


def test_full_record_is_written_once_and_is_append_only(env):
    _, work, tmp = env
    col = run(env)
    a = collect.assemble(ST, col, CONTROLS)
    assert a["gate"] == [], a["gate"]
    assert a["rep"]["compared_points"] == 28 and a["rep"]["worst"]["nf_db"] < 1e-9
    assert a["xc"]["ok"]
    kw = dict(rep=a["rep"], xc=a["xc"], controls=CONTROLS, concl=a["concl"], gate=a["gate"],
              pdk_prov={"model_sha256": {"cornerHBT.lib": "0" * 64}}, ngspice="ngspice-test", klt_version="klt-test",
              started=dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc), git=GIT)
    rid = collect.write_record(ST, col, **kw)
    bench = tmp / "bench"
    md = (bench / "records" / f"{rid}.md").read_text()
    assert md.startswith(f"# lna-match-tradeoff record {rid}\n")
    assert "**Spec rows claimed met**: none" in md and "## Conclusion" in md
    data = json.loads((bench / "records" / f"{rid}.json").read_text())
    assert data["gate"]["validate_collection"] == "passed" and data["declared_cells"] == data["accepted_cells"]
    with gzip.open(bench / "records" / data["cells_file"], "rt") as fh:
        cells = json.load(fh)
    assert len(cells) == data["accepted_cells"]
    logs = sorted((bench / "corners" / rid).iterdir())
    assert len(logs) == 28 and all(p.name.endswith(".log.gz") for p in logs)
    snap = {p.name for p in (bench / "netlist-snapshots" / rid).iterdir()}
    assert {"study.json", "lna_stage1.spice", "body_screen__2.500v.spice", "request_corners__2.750v.json",
            "report_corners__2.250v.json", "spec_screen__2.500v.json"} <= snap
    # a second record in the same second gets a fresh id; nothing is overwritten
    rid2 = collect.write_record(ST, col, **kw)
    assert rid2 != rid and (bench / "records" / f"{rid}.md").read_text() == md


def test_gate_failure_writes_nothing(env):
    _, _, tmp = env
    col = run(env)
    a = collect.assemble(ST, col, {"pad_27c": {"ok": False}})
    assert any("control pad_27c failed" in g for g in a["gate"])
    with pytest.raises(collect.CollectionError, match="gate"):
        collect.write_record(ST, col, rep=a["rep"], xc=a["xc"], controls={}, concl=a["concl"], gate=a["gate"],
                             pdk_prov={}, ngspice="", klt_version="", started=dt.datetime.now(dt.timezone.utc),
                             git=GIT)
    assert not (tmp / "bench" / "records").exists()


def test_baseline_mismatch_fails_the_gate(env, tmp_path, monkeypatch):
    col = run(env)
    d = tmp_path / "baseline"
    p = d / "hbt_wcs_125c_2.25v.log"
    p.write_text(p.read_text().replace("m_nf_db_mid = ", "m_nf_db_mid = 9"))
    a = collect.assemble(ST, col, CONTROLS)
    assert any("hbt_wcs_125c_2.25v" in g and "nf_db" in g for g in a["gate"])


def test_conclusion_and_bound_on_the_fake(env):
    col = run(env)
    a = collect.assemble(ST, col, CONTROLS)
    concl = a["concl"]
    assert set(concl["per_candidate"]) == set(col.shortlist["names"])
    assert concl["bound"]["valid_points"] == 18 and concl["bound"]["points"] == 18
    for b in col.bounds.values():
        assert b["valid"] and math.isfinite(b["summary"]["nf_bound_max_db"])


def test_dry_run_writes_only_the_screen_request(env):
    fake, work, _ = env
    col = run(env, dry_run=True)
    assert fake.calls == [] and col.cells == []
    assert sorted(p.name for p in work.iterdir()) == ["body_screen__2.500v.spice", "request_screen__2.500v.json",
                                                      "spec_screen__2.500v.json"]
