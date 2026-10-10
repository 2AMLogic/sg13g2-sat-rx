"""run.py (klt-sim driver) and the verified PDK artifact identity (issue #103).

A record needs the hash-verified artifact identity; `build_record` refuses
without one. These tests pin that run.py refuses BEFORE anything is
submitted or written (no klt call, no record id, no corners/<id>/ directory)
and that the identity it verified is the one handed to ingest/build_record.
No PDK, no simulator, no klt.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
SIM = BENCH.parent
for p in (str(SIM), str(BENCH)):
    if p not in sys.path:
        sys.path.insert(0, p)

from harness import pdkartifact  # noqa: E402

_spec = importlib.util.spec_from_file_location("lna_sparam_nf_run", BENCH / "run.py")
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)

FAKE_PDK = object()
IDENTITY = {"status": "verified", "upstream_commit": "a" * 40, "manifest_sha256": "b" * 64}


def _unverified(pdk, sim_dir):
    raise pdkartifact.ArtifactNotVerified("model closure differs from the pin")


def _boom(*a, **k):
    raise AssertionError("must not be reached on an unverified install")


@pytest.fixture
def unverified(monkeypatch):
    monkeypatch.setattr(run, "_pdk", lambda: FAKE_PDK)
    monkeypatch.setattr(run.pdkartifact, "verified_identity", _unverified)
    # Anything that submits work or touches the evidence tree must not run.
    monkeypatch.setattr(run.subprocess, "run", _boom)
    monkeypatch.setattr(run, "allocate_record_id", _boom)
    monkeypatch.setattr(run, "build_record", _boom)
    monkeypatch.setattr(run, "write_record", _boom)
    monkeypatch.setattr(run, "write_netlist_snapshot", _boom)


def test_characterize_refuses_before_submitting_on_unverified_install(unverified, capsys):
    assert run.main(["characterize"]) == 3
    err = capsys.readouterr().err
    assert "differs from the pin" in err and "nothing submitted" in err


def test_ingest_refuses_before_any_log_dir_on_unverified_install(unverified, tmp_path, capsys):
    report = tmp_path / "report_2.50v.json"
    report.write_text("{}")
    (tmp_path / "body_2.50v.spice").write_text(".param vdd_val=2.5\n")
    corners_before = sorted((BENCH / "corners").iterdir()) if (BENCH / "corners").exists() else []
    assert run.main(["ingest", str(report)]) == 3
    assert "NO record written" in capsys.readouterr().err
    corners_after = sorted((BENCH / "corners").iterdir()) if (BENCH / "corners").exists() else []
    assert corners_after == corners_before


def test_characterize_hands_its_verified_identity_to_ingest(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "_pdk", lambda: FAKE_PDK)
    monkeypatch.setattr(run.pdkartifact, "verified_identity", lambda pdk, sim: IDENTITY)
    seen = {}

    class Done:
        returncode, stderr = 0, ""

    monkeypatch.setattr(run.subprocess, "run", lambda *a, **k: Done())
    monkeypatch.setattr(run, "SCRATCH", tmp_path)

    def fake_ingest(tb, reports, args, verified=None):
        seen["v"] = verified
        return 0

    monkeypatch.setattr(run, "ingest", fake_ingest)
    assert run.main(["characterize"]) == 0
    assert seen["v"] == (FAKE_PDK, IDENTITY)


def test_ingest_passes_identity_to_build_record():
    # Static guard: the only build_record call in run.py carries pdk_artifact.
    src = (BENCH / "run.py").read_text()
    call = src[src.index("record = build_record("):]
    call = call[:call.index("\n    write_netlist_snapshot")]
    assert "pdk_artifact=pdk_artifact" in call


def test_dry_run_needs_no_verified_install(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "_pdk", _boom)
    monkeypatch.setattr(run, "SCRATCH", tmp_path)
    monkeypatch.setattr(run.subprocess, "run", _boom)
    assert run.main(["characterize", "--dry-run"]) == 0
