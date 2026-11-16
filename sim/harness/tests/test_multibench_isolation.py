"""Multi-bench namespace isolation guard (issue #302).

sim/conftest.py re-anchors sys.path/sys.modules per test module and per test,
so a bench combination imports its own run_probe / ci_assert / conftest
instead of whichever bench bound the name first. These tests run pytest itself
over the combinations that used to break -- the issue's acceptance-criteria
command, both orders of the pair whose breakage flipped between collection
time and run time, and a full collect-only sweep of every bench at once --
and fail when a bench resolves another bench's module again. No simulator, no
PDK; each subprocess is a fresh interpreter so the nested runs are
independent of this session.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# Full runs: the issue's acceptance-criteria command, then the cm-probe vs
# lna-linearity pair in both orders (glob order broke collection the other
# way around; see the measured addendum on #302).
FULL_RUNS = [
    ["sim/mixer-pumped-rf-admittance/tests",
     "sim/mixer-cm-interface-probe/tests",
     "sim/mixer-nf-method/tests"],
    ["sim/mixer-cm-interface-probe/tests", "sim/lna-linearity/tests"],
    ["sim/lna-linearity/tests", "sim/mixer-cm-interface-probe/tests"],
]


def _run_pytest(*args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args, "-q", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=300, env=env,
    )


def _assert_clean(proc, args):
    assert proc.returncode == 0, (
        f"multi-bench run failed for {args} "
        f"(rc={proc.returncode}):\n{proc.stdout[-4000:]}\n{proc.stderr[-2000:]}"
    )


def test_multi_bench_full_runs_pass_in_every_order():
    for args in FULL_RUNS:
        _assert_clean(_run_pytest(*args), args)


def test_full_multi_bench_collection_has_no_errors():
    benches = sorted(str(p) for p in (REPO / "sim").glob("*/tests"))
    assert len(benches) >= 10
    _assert_clean(_run_pytest(*benches, "--collect-only"), benches)
