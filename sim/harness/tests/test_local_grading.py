"""Issue #138: local point grading requires finite, complete measurements AND
a successful simulator execution.

The real ``run_point`` / ``run_grid`` are called; only ``subprocess.run`` and
deck composition are stubbed, so no PDK, ngspice or network is needed.
"""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness import cli
from harness import corners as C
from harness import runner
from harness import testbench as T

SIM = Path(__file__).resolve().parents[2]
EXP = "mixer-conversion-iip3"


@pytest.fixture
def tb():
    return T.load(SIM / EXP)


@pytest.fixture
def point(tb):
    corners = C.resolve_corners(["hbt_typ"])
    return C.build_grid(corners, tb.temperatures_c[:1], C.supply_points(tb.nominal_supply_v, 0))[0]


def _log(tb, value="1.0", extra=()):
    return "\n".join([*extra, *(f"m_{n} = {value}" for n in tb.measure)]) + "\n"


@pytest.fixture
def sim(monkeypatch):
    """Stub the subprocess; returns a setter for (stdout, stderr, rc)."""
    state = {}
    monkeypatch.setattr(runner, "compose_deck", lambda *a, **k: "* stub deck\n")

    def fake_run(cmd, **kw):
        if "raise" in state:
            raise state["raise"]
        return subprocess.CompletedProcess(cmd, state["rc"], state["out"], state.get("err", ""))

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    def setup(out="", rc=0, err="", raises=None):
        state.update(out=out, rc=rc, err=err)
        if raises:
            state["raise"] = raises

    return setup


def _run(tb, point, tmp_path):
    return runner.run_point(tb, None, point, tmp_path)


def test_clean_success_control(tb, point, sim, tmp_path):
    sim(_log(tb, extra=["Note: Using default settings", "Warning: no error here",
                        "No. of Data Rows : 100", "Doing analysis at TEMP = 27"]))
    r = _run(tb, point, tmp_path)
    assert r.status == "ok" and not r.missing and r.returncode == 0 and not r.diagnostic
    assert set(r.measurements) == set(tb.measure)


def test_nonzero_exit_with_complete_measurements_fails(tb, point, sim, tmp_path):
    sim(_log(tb), rc=1)
    r = _run(tb, point, tmp_path)
    assert r.status == "failed" and r.returncode == 1 and "exit 1" in r.message
    assert "m_" in (tmp_path / r.log).read_text()  # raw log retained


def test_fatal_diagnostic_with_zero_exit_fails(tb, point, sim, tmp_path):
    sim(_log(tb, extra=["Fatal: simulation aborted"]), rc=0)
    r = _run(tb, point, tmp_path)
    assert r.status == "failed" and r.diagnostic == "Fatal: simulation aborted"
    assert "Fatal: simulation aborted" in r.message
    assert "Fatal: simulation aborted" in (tmp_path / r.log).read_text()


def test_nonfinite_values_fail(tb, point, sim, tmp_path):
    sim(_log(tb, value="1e999"))
    r = _run(tb, point, tmp_path)
    assert r.status == "failed"
    assert "non-finite" in r.message
    assert all(v == v and abs(v) != float("inf") for v in r.measurements.values())


def test_parse_measurements_drops_nonfinite():
    assert runner.parse_measurements("m_a = 1e999\nm_b = -1e999\nm_c = 2.5e-3\n") == {"c": 2.5e-3}


def test_missing_measurement_keeps_diagnostic(tb, point, sim, tmp_path):
    sim("Error: no such vector\n", rc=1)
    r = _run(tb, point, tmp_path)
    assert r.status == "failed" and r.missing and "Error: no such vector" in r.message


def test_timeout_keeps_diagnostic(tb, point, sim, tmp_path):
    sim(raises=subprocess.TimeoutExpired("ngspice", 5))
    r = _run(tb, point, tmp_path)
    assert r.status == "error" and "timed out" in r.message


@pytest.mark.parametrize("line", [
    "Fatal: simulation aborted", "fatal error: out of memory", "Error: no such vector x",
    "ERROR: singular matrix", "doAnalyses: TRAN:  Timestep too small",
    "run simulation interrupted",
])
def test_fatal_matcher_accepts_fatal(line):
    assert runner.fatal_diagnostic("ok\n" + line + "\n") == line


@pytest.mark.parametrize("line", [
    "Warning: model has no error term", "Note: ignoring fatal flag", "Errors: 0",
    "No. of Data Rows : 100", "  m_error_rate = 1.0e-03", "Circuit: * mixer error budget",
    "Reference value :  0.00000e+00", "Total analysis time (seconds) = 1.2",
    "Using SPARSE 1.3 as Direct Linear Solver", "no error",
])
def test_fatal_matcher_ignores_legitimate_logs(line):
    assert runner.fatal_diagnostic(line + "\n") == ""


@pytest.mark.parametrize("out,rc", [
    (None, 1),
    ("Fatal: simulation aborted\n", 0),
    ("INF", 0),
])
def test_failure_reaches_cli_smoke_exit_status(monkeypatch, capsys, tb, sim, tmp_path, out, rc):
    body = {"INF": _log(tb, "1e999"), None: _log(tb)}.get(out) or _log(tb, extra=[out.strip()])
    sim(body, rc=rc)
    real_grid = runner.run_grid
    monkeypatch.setattr(cli, "load", lambda _e: tb)
    monkeypatch.setattr(cli, "_resolve_pdk", lambda: SimpleNamespace(version="stub"))
    monkeypatch.setattr(cli, "ngspice_version", lambda: "ngspice-46")
    monkeypatch.setattr(cli.toolchain_mod, "check", lambda *a, **k: [])
    monkeypatch.setattr(
        cli, "run_grid",
        lambda tb_, pdk, pts, workdir, **k: real_grid(
            tb_, pdk, pts, tmp_path, **{**k, "log_dir": tmp_path}),
    )
    monkeypatch.setattr(cli, "write_record", lambda *a, **k: pytest.fail("recorded"))
    monkeypatch.setattr(cli, "write_netlist_snapshot", lambda *a, **k: pytest.fail("recorded"))
    rc_cli = cli.main(["run", EXP, "--corners", "hbt_typ", "--backend", "local",
                       "--no-write", "--smoke-subset"])
    assert rc_cli == 1
    assert "POINT FAILED" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# artifact-identity gate (issue #150): the local grid path refuses ambiguity
# ---------------------------------------------------------------------------

def test_grid_with_aliasing_ids_is_refused_before_any_deck_or_subprocess(tb, sim, tmp_path):
    points = C.build_grid(C.resolve_corners(["hbt_typ"]), (27.0,), [2.501, 2.504])
    assert points[0].corner_id == points[1].corner_id == "hbt_typ_27c_2.50v"
    sim(raises=AssertionError("ngspice must not run for an ambiguous grid"))
    with pytest.raises(C.CornerIdCollision, match="hbt_typ_27c_2.50v"):
        runner.run_grid(tb, None, points, tmp_path)
    assert list(tmp_path.iterdir()) == []  # no deck or log written either


def test_fine_grid_with_distinct_ids_runs_normally(tb, sim, tmp_path):
    sim(_log(tb), rc=0)
    points = C.build_grid(C.resolve_corners(["hbt_typ"]), (27.0,), [2.504, 2.506])
    results = runner.run_grid(tb, None, points, tmp_path)
    assert [r.status for r in results] == ["ok", "ok"]
    assert sorted(p.name for p in tmp_path.glob("*.spice")) == \
        ["hbt_typ_27c_2.50v.spice", "hbt_typ_27c_2.51v.spice"]
