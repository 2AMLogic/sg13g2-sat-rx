"""Per-bench namespace isolation for multi-bench pytest runs (issue #302).

The benches import their probe/assert modules with bare ``import`` statements
resolved through ``sys.path`` inserts. Several module names are provided by
more than one bench (``run``, ``run_probe``, ``ci_assert``, ``conftest`` and
same-stem ``test_*.py`` files), and pytest's ``prepend`` import mode lets the
first bench to bind such a name own ``sys.modules`` for the rest of the
session: later benches silently reuse the first binder's file and fail at
collection (``from conftest import ...``) or at run time (assertions against
the wrong module's API). Bench modules also mutate ``sys.path`` at import
time -- ``sim/lna-headroom/headroom.py`` removes the lna-linearity directory
it temporarily added, ``sim/lna-linearity/ci_assert.py`` prepends its own
bench over anything anchored before it -- so neither session-start nor
collection-start path state survives until an import actually happens.

This conftest therefore isolates per bench instead of per session:

- a ``sys.meta_path`` finder resolves a colliding stem to the file in the
  importing module's own bench (its ``tests/`` helper directory first, then
  the bench directory), independent of ``sys.path`` order and of when the
  import runs;
- colliding stems are dropped from ``sys.modules`` before each test module
  import and before each test, so the finder gets to run instead of a stale
  first-binder cache hit;
- the owning bench's import roots are re-anchored to the head of ``sys.path``
  at the same points, which keeps unique-name imports working even after
  another bench's module scrambled or removed path entries;
- no ``sys.path`` entry is ever removed: benches deliberately import other
  benches' modules (``sim/lna-core-variants`` reuses ``lna-match-tradeoff``,
  ``sim/harness/tests/test_rf.py`` drives every bench's collector), and those
  dependencies must keep resolving.

Single-bench invocations are unaffected: the finder only answers for a bench
that actually provides the name, and the purge/re-anchor is a no-op when the
bench is alone. The regression guard for this behaviour lives in
``sim/harness/tests/test_multibench_isolation.py``.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SIM_DIR = Path(__file__).resolve().parent
_IMPORTLIB_MODULES = ("importlib", "_frozen_importlib", "_frozen_importlib_external")


def _bench_dirs():
    return [p for p in SIM_DIR.iterdir() if p.is_dir() and p.name != "__pycache__"]


def _shared_stems(relpattern):
    homes = {}
    for bench in _bench_dirs():
        for path in bench.glob(relpattern):
            homes.setdefault(path.stem, set()).add(bench.name)
    return {stem for stem, benches in homes.items() if len(benches) >= 2}


SHARED_BENCH_STEMS = _shared_stems("*.py")
SHARED_TEST_STEMS = _shared_stems("tests/*.py")
SHARED_STEMS = SHARED_BENCH_STEMS | SHARED_TEST_STEMS


def _bench_of(file):
    """The bench dir owning ``file``, or None when it is not a bench file."""
    file = Path(file).resolve()
    parent = file.parent
    if parent.name == "tests" and parent.parent.parent == SIM_DIR:
        return parent.parent
    if parent.parent == SIM_DIR:
        return parent
    return None


class _BenchResolver:
    """Resolve colliding stems to the importing bench's own file.

    ``sys.modules`` caches and ``sys.path`` scrambling defeat path-order
    tricks, so a bare ``import <shared stem>`` is answered here directly from
    the importing frame's bench instead. Only names more than one bench
    provides are intercepted; every other import keeps the normal resolution.
    """

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in SHARED_STEMS:
            return None
        frame = sys._getframe(1)
        while frame is not None:
            modname = frame.f_globals.get("__name__", "")
            if modname.split(".")[0] not in _IMPORTLIB_MODULES:
                break
            frame = frame.f_back
        else:
            return None
        file = frame.f_globals.get("__file__")
        bench = _bench_of(file) if file else None
        if bench is None:
            return None
        dirs = [bench / "tests", bench] if (bench / "tests").is_dir() else [bench]
        for candidate in dirs:
            candidate_file = candidate / f"{fullname}.py"
            if candidate_file.is_file():
                return importlib.util.spec_from_file_location(fullname, candidate_file)
        return None


sys.meta_path.insert(0, _BenchResolver())


def _owning_dirs(test_path):
    """The (tests dir, bench dir) owning ``test_path``, or None outside a bench."""
    tests_dir = test_path.parent
    bench = tests_dir.parent
    if tests_dir.name != "tests" or bench.parent != SIM_DIR:
        return None
    return tests_dir, bench


def _reanchor(test_path):
    """Move the owning bench's import roots to the head of ``sys.path``."""
    owned = _owning_dirs(test_path)
    if owned is None:
        return
    for entry in (str(SIM_DIR), str(owned[1]), str(owned[0])):
        while entry in sys.path:
            sys.path.remove(entry)
        sys.path.insert(0, entry)


def _purge(stems):
    for stem in stems:
        sys.modules.pop(stem, None)


def _drop_foreign_stem(test_path):
    """Forget a cached stem whose file differs from ``test_path`` (same-stem
    test files across benches would otherwise raise ImportPathMismatchError)."""
    module = sys.modules.get(test_path.stem)
    file = getattr(module, "__file__", None)
    if module is None or file is None:
        return
    try:
        foreign = Path(file).resolve() != test_path.resolve()
    except OSError:
        foreign = True
    if foreign:
        del sys.modules[test_path.stem]


def pytest_collectstart(collector):
    path = getattr(collector, "path", None)
    if not isinstance(collector, pytest.Module) or path is None:
        return
    path = Path(path).resolve()
    if _owning_dirs(path) is None:
        return
    _reanchor(path)
    _drop_foreign_stem(path)
    _purge(SHARED_STEMS)


def pytest_runtest_setup(item):
    path = getattr(item, "path", None)
    if path is None:
        return
    path = Path(path).resolve()
    if _owning_dirs(path) is None:
        return
    _reanchor(path)
    _purge(SHARED_BENCH_STEMS)
