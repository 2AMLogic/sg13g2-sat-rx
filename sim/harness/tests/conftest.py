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


def in_check_window(check, value):
    """Clamp a synthetic measurement into a bench's numeric [min, max] check
    window, so a stubbed 'good' run satisfies checks like the mixer bench's
    slope windows, fit_n and floor margin (issue #165 added those). Callers
    guarding against adversarial tb mutation (the tighten-a-bound control)
    pass a PRE-mutation check snapshot; axis-spread checks carry no min/max
    and pass through unchanged."""
    check = check or {}
    lo, hi = check.get("min"), check.get("max")
    if lo is None and hi is None:
        return value
    if lo is None:
        return min(value, hi - 1)
    if hi is None:
        return max(value, lo + 1)
    return (lo + hi) / 2


@pytest.fixture(autouse=True)
def _no_klt_submission(monkeypatch):
    """No test may submit a real ``klt sim`` request (issue #134): the batch
    path is exercised with a stubbed submitter only."""
    from harness import klt_driver

    def refuse(*a, **k):
        raise AssertionError("a unit test tried to submit a real klt sim request")

    monkeypatch.setattr(klt_driver, "submit", refuse)
