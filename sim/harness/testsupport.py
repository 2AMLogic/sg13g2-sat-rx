"""Shared synthetic-measurement helpers for bench unit tests.

This lives inside the importable ``harness`` package rather than in a
``tests/conftest.py`` on purpose: under pytest's default ``prepend`` import
mode every bench's ``conftest`` module shares the single top-level name
``conftest``, and each conftest rebinds it, so a bare ``from conftest import
...`` resolves against whichever bench's conftest was imported last (issue
#287). Importing from a real package module is collision-free.
"""


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
