"""Issue #92: the single-corner smoke verdict must be trustworthy.

Simulator-independent negative controls: run_grid is stubbed with synthetic
point results, so neither ngspice nor a PDK is needed. The CLI skips only the
"process axis never swept" check (--smoke-subset, --no-write only); every other
failure must reach the exit status, and sim/characterize.sh must not reinterpret
that status.
"""

import os
import stat
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest

from harness import cli
from harness import corners as C
from harness import testbench as T
from harness.runner import PointResult

SIM = Path(__file__).resolve().parents[2]
EXPERIMENTS = ("lna-sparam-nf", "mixer-conversion-iip3")


def _varying(p, name, k):
    return 1.0 + k + p.temp_c / 100.0 + p.vdd


def _results(tb, mode="good"):
    corners = C.resolve_corners(["hbt_typ"])
    points = C.build_grid(corners, tb.temperatures_c, C.supply_points(tb.nominal_supply_v, tb.supply_tolerance))
    out = []
    for p in points:
        m = {}
        for k, name in enumerate(tb.measure):
            if mode == "stuck_temp":
                m[name] = 1.0 + k + p.vdd
            elif mode == "stuck_supply":
                m[name] = 1.0 + k + p.temp_c / 100.0
            else:
                m[name] = _varying(p, name, k)
        out.append(PointResult(point=p, status="ok", measurements=m))
    if mode == "missing":
        out[0] = PointResult(point=out[0].point, status="failed", missing=list(tb.measure))
    if mode == "error":
        out[0] = PointResult(point=out[0].point, status="error", message="ngspice crashed")
    return out


@pytest.fixture
def run_cli(monkeypatch, capsys):
    def go(exp, mode, *flags, tb_mutator=None):
        tb = T.load(SIM / exp)
        if tb_mutator:
            tb_mutator(tb)
        calls = []
        monkeypatch.setattr(cli, "load", lambda _e: tb)
        monkeypatch.setattr(cli, "_resolve_pdk", lambda: SimpleNamespace(version="stub"))
        monkeypatch.setattr(cli, "ngspice_version", lambda: "ngspice-46")
        monkeypatch.setattr(cli.toolchain_mod, "check", lambda *a, **k: [])

        def fake_run_grid(*a, **k):
            calls.append(1)
            return _results(tb, mode)

        monkeypatch.setattr(cli, "run_grid", fake_run_grid)
        wrote = []
        monkeypatch.setattr(cli, "write_record", lambda *a, **k: wrote.append(1))
        monkeypatch.setattr(cli, "write_netlist_snapshot", lambda *a, **k: wrote.append(1))
        rc = cli.main(["run", exp, "--corners", "hbt_typ", *flags])
        return rc, calls, wrote, capsys.readouterr()

    return go


@pytest.mark.parametrize("exp", EXPERIMENTS)
def test_valid_smoke_succeeds_without_evidence_writes(run_cli, exp):
    rc, calls, wrote, _ = run_cli(exp, "good", "--no-write", "--smoke-subset")
    assert rc == 0 and calls and not wrote


@pytest.mark.parametrize("exp", EXPERIMENTS)
def test_without_flag_unswept_process_still_fails(run_cli, exp):
    rc, _, _, io = run_cli(exp, "good", "--no-write")
    assert rc == 1 and "on the process axis" in io.err


@pytest.mark.parametrize("exp", EXPERIMENTS)
@pytest.mark.parametrize("mode,axis", [("stuck_temp", "temperature"), ("stuck_supply", "supply")])
def test_stuck_swept_axis_fails_smoke(run_cli, exp, mode, axis):
    rc, _, _, io = run_cli(exp, mode, "--no-write", "--smoke-subset")
    assert rc == 1 and f"on the {axis} axis" in io.err


@pytest.mark.parametrize("exp", EXPERIMENTS)
@pytest.mark.parametrize("mode", ["missing", "error"])
def test_missing_measurement_or_simulator_error_fails(run_cli, exp, mode):
    rc, _, _, _ = run_cli(exp, mode, "--no-write", "--smoke-subset")
    assert rc == 1


def test_violated_bound_fails_smoke(run_cli):
    def tighten(tb):
        name = next(iter(tb.measure))
        tb.checks[name] = {**tb.checks.get(name, {}), "max": -1e9}

    rc, _, _, io = run_cli("lna-sparam-nf", "good", "--no-write", "--smoke-subset", tb_mutator=tighten)
    assert rc == 1 and "FAIL" in io.err


@pytest.mark.parametrize("flags", [("--smoke-subset",), ("--smoke-subset", "--claim", "x")])
def test_evidence_writing_run_cannot_opt_in(run_cli, flags):
    rc, calls, wrote, io = run_cli("lna-sparam-nf", "good", *flags)
    assert rc == 2 and not calls and not wrote and "--no-write" in io.err


def _stub_python(tmp_path, harness_exit):
    """A python3 stand-in: verify-pdk and the Ka-band smoke succeed; the
    harness `run` prints a complete point count and exits `harness_exit`."""
    stub = tmp_path / "python3"
    stub.write_text(
        "#!/bin/bash\n"
        'case "$*" in\n'
        '  *"verify-pdk"*) exit 0 ;;\n'
        '  *"harness.cli run"*) echo "27/27 points ok"; echo "FAIL: stuck" >&2; '
        "exit " + str(harness_exit) + " ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return stub


@pytest.mark.parametrize("harness_exit,expected", [(0, 0), (1, 2)])
def test_wrapper_propagates_harness_exit_after_point_count(tmp_path, harness_exit, expected):
    _stub_python(tmp_path, harness_exit)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    r = subprocess.run(["bash", str(SIM / "characterize.sh"), "smoke"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == expected, r.stdout + r.stderr


def test_wrapper_passes_smoke_subset_with_no_write():
    text = (SIM / "characterize.sh").read_text()
    assert "--no-write --smoke-subset" in text
    assert "Not counted as a failure" not in text
