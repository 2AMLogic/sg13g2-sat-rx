"""Put sim/ on sys.path so ``import harness`` works from any cwd.

These tests need neither ngspice nor a PDK: they exercise corner expansion,
manifest validation and record rendering on synthetic results.
"""

import sys
from pathlib import Path

SIM = Path(__file__).resolve().parents[2]
if str(SIM) not in sys.path:
    sys.path.insert(0, str(SIM))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_klt_submission(monkeypatch):
    """No test may submit a real ``klt sim`` request (issue #134): the batch
    path is exercised with a stubbed submitter only."""
    from harness import klt_driver

    def refuse(*a, **k):
        raise AssertionError("a unit test tried to submit a real klt sim request")

    monkeypatch.setattr(klt_driver, "submit", refuse)


@pytest.fixture(autouse=True)
def _no_real_artifact_broker(monkeypatch):
    """Issue #226: an evidence-writing ``cli run`` stores bytes through the real
    artifact store when ``$KLT_ARTIFACT_BROKER`` is set (it is, on fleet
    workers). No test may do that: drop the variable so the real store path
    fails closed instead; tests of the write path patch ``preflight`` and
    ``put_files`` themselves."""
    monkeypatch.delenv("KLT_ARTIFACT_BROKER", raising=False)
