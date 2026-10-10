"""`cli run` refuses an evidence-writing run on an unverified PDK artifact
(issue #103): exit 3, before any record id is allocated or anything is
simulated. No PDK, no simulator."""

from types import SimpleNamespace

import pytest

from harness import cli, pdkartifact


def _boom(*a, **k):
    raise AssertionError("must not be reached on an unverified install")


@pytest.fixture
def staged(monkeypatch, tmp_path):
    tb = SimpleNamespace(corners=["hbt"], temperatures_c=[27], nominal_supply_v=2.5,
                         supply_tolerance=0.1, experiment_dir=tmp_path)
    monkeypatch.setattr(cli, "load", lambda exp: tb)
    monkeypatch.setattr(cli, "_resolve_pdk", lambda: SimpleNamespace(version="v"))
    monkeypatch.setattr(cli, "ngspice_version", lambda: "ngspice-46")
    monkeypatch.setattr(cli.toolchain_mod, "load_pins", lambda sim: {})
    monkeypatch.setattr(cli.toolchain_mod, "check", lambda *a: [])
    monkeypatch.setattr(cli.toolchain_mod, "summary", lambda *a, **k: {})
    monkeypatch.setattr(cli, "resolve_corners", lambda names: names)
    monkeypatch.setattr(cli, "run_grid", _boom)
    monkeypatch.setattr(cli, "allocate_record_id", _boom)
    monkeypatch.setattr(cli, "build_record", _boom)
    return tmp_path


def test_run_returns_3_and_does_not_simulate_on_unverified_install(staged, monkeypatch, capsys):
    def unverified(pdk, sim_dir):
        raise pdkartifact.ArtifactNotVerified("model closure differs from the pin")

    monkeypatch.setattr(cli.pdkartifact, "verified_identity", unverified)
    assert cli.main(["run", str(staged)]) == 3
    assert "differs from the pin" in capsys.readouterr().err
    assert not (staged / "corners").exists()
