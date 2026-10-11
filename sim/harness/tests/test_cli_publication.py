"""cli run publication gate (issue #141): a grid is simulated from the input
state captured at load time, so publication must refuse -- writing nothing --
when the working manifest or netlist fragment has changed (or vanished)
since; and a clean run must publish the frozen manifest next to the frozen
netlist. Simulator-free: run_grid is stubbed, no PDK, no ngspice."""

import json
from pathlib import Path

import pytest

from harness import cli
from harness import corners as C
from harness import testbench as T
from harness.pdk import Pdk
from harness.runner import PointResult

SIM = Path(__file__).resolve().parents[2]

ART = {"status": "verified", "upstream_repo": "https://example.invalid/pdk", "upstream_tag": "v0",
       "upstream_commit": "a" * 40, "manifest": "sim/pdk-artifact.json", "manifest_sha256": "b" * 64,
       "files_verified": 4, "method": "test"}


def make_bench(tmp_path):
    tbdir = tmp_path / "exp" / "testbench"
    tbdir.mkdir(parents=True)
    (tbdir / "d.spice").write_text("R1 a b 1k\n")
    (tbdir / "tb.json").write_text(json.dumps(
        {"name": "t", "netlist": "d.spice", "measure": {"gain": "1"}, "corners": ["hbt"]}))
    return tmp_path / "exp"


@pytest.fixture
def staged(monkeypatch, tmp_path):
    exp = make_bench(tmp_path)
    tb = T.load(exp)
    monkeypatch.setattr(cli, "load", lambda _exp: tb)
    monkeypatch.setattr(cli, "_resolve_pdk",
                        lambda: Pdk(name="fake", path=tmp_path, variant="v",
                                    source="test", model_lib_rel="m.lib"))
    monkeypatch.setattr(cli, "ngspice_version", lambda: "ngspice-46")
    monkeypatch.setattr(cli.toolchain_mod, "load_pins", lambda sim: {})
    monkeypatch.setattr(cli.toolchain_mod, "check", lambda *a, **k: [])
    monkeypatch.setattr(cli.toolchain_mod, "summary", lambda *a, **k: {})
    monkeypatch.setattr(cli.pdkartifact, "verified_identity", lambda pdk, sim: ART)

    def fake_run_grid(tb, pdk, points, workdir, **k):
        # Like runner.run_grid: one per-point log in log_dir (for a write run,
        # corners/<record-id>/) while the grid runs, before the drift gate.
        log_dir = k.get("log_dir")
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            for p in points:
                (log_dir / f"{p.corner_id}.log").write_text("* fake corner log\n")
        return [PointResult(point=p, status="ok", measurements={"gain": 1.0})
                for p in points]

    monkeypatch.setattr(cli, "run_grid", fake_run_grid)
    return exp, tb


def test_drifted_working_manifest_refuses_publication(staged, capsys):
    exp, tb = staged
    (tb.directory / T.MANIFEST_NAME).write_text(
        json.dumps({"name": "t", "netlist": "d.spice", "measure": {"gain": "tampered"}}))
    rc = cli.main(["run", str(exp), "--backend", "local"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "refusing to record" in err and "working manifest" in err
    assert not (exp / "records").exists() and not (exp / "netlist-snapshots").exists()
    # The per-point logs the grid wrote into corners/<record-id>/ are not
    # evidence on a refusal: the run's own log directory is removed, so no
    # orphan package is left for the evidence checker to flag.
    corners = exp / "corners"
    assert corners.is_dir() and not any(corners.iterdir())


def test_drifted_netlist_fragment_refuses_publication(staged, capsys):
    exp, tb = staged
    (tb.directory / "d.spice").write_text("R1 a b 9k\n")
    rc = cli.main(["run", str(exp), "--backend", "local"])
    assert rc == 1
    assert "netlist fragment" in capsys.readouterr().err
    assert not (exp / "records").exists() and not (exp / "netlist-snapshots").exists()
    corners = exp / "corners"
    assert corners.is_dir() and not any(corners.iterdir())


def test_clean_run_publishes_record_with_both_frozen_artifacts(staged):
    exp, tb = staged
    rc = cli.main(["run", str(exp), "--backend", "local"])
    assert rc == 0
    snaps = exp / "netlist-snapshots"
    records = list((exp / "records").glob("*.md"))
    assert len(records) == 1
    md = records[0].read_text()
    rid = records[0].stem
    frozen = snaps / f"{rid}.tb.json"
    assert frozen.read_bytes() == (tb.directory / T.MANIFEST_NAME).read_bytes()
    assert (snaps / f"{rid}.spice").is_file()
    assert f"**Manifest**: `netlist-snapshots/{rid}.tb.json`" in md
    assert tb.manifest_sha256 in md


def test_select_axis_keeps_declared_levels_and_refuses_new_ones():
    assert cli.select_axis([-40.0, 27.0, 125.0], "", "temperatures") == [-40.0, 27.0, 125.0]
    assert cli.select_axis([-40.0, 27.0, 125.0], "27", "temperatures") == [27.0]
    assert cli.select_axis([2.25, 2.5, 2.75], "2.50,2.5", "supplies") == [2.5]
    with pytest.raises(ValueError, match="not one of"):
        cli.select_axis([2.25, 2.5, 2.75], "2.6", "supplies")
    with pytest.raises(ValueError, match="not a number"):
        cli.select_axis([27.0], "warm", "temperatures")


def test_subset_write_run_requires_reason(staged, capsys):
    exp, _tb = staged
    rc = cli.main(["run", str(exp), "--backend", "local", "--corners", "hbt_typ",
                   "--temperatures", "27", "--supplies", "1.2"])
    assert rc == 2
    assert "--subset-reason" in capsys.readouterr().err
    assert not (exp / "records").exists()


def test_single_point_subset_record_carries_justification(staged):
    exp, _tb = staged
    rc = cli.main(["run", str(exp), "--backend", "local", "--corners", "hbt_typ",
                   "--temperatures", "27", "--supplies", "1.2",
                   "--subset-reason", "one local debug point"])
    records = list((exp / "records").glob("*.md"))
    assert len(records) == 1
    md = records[0].read_text()
    assert "  - Temperature: 27 C" in md and "  - Supply: 1.20 V" in md
    assert "1 point grid (subset of" in md
    assert "Justification: one local debug point" in md
    logs = list((exp / "corners" / records[0].stem).glob("*.log"))
    assert [p.name for p in logs] == ["hbt_typ_27c_1.20v.log"]
    assert rc in (0, 1)  # status is the checks' verdict; the record is written either way
