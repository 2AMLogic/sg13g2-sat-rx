"""The CI job's pins must equal the committed manifest's (no drift between the two)."""

import json
import re

from harness.pdk import REPO_ROOT, SIM_DIR


def test_workflow_pins_match_manifest():
    wf = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    m = json.loads((SIM_DIR / "pdk-artifact.json").read_text())
    assert re.search(r"IHP_PDK_COMMIT: (\w+)", wf).group(1) == m["upstream"]["commit"]
    assert re.search(r"NGSPICE_VERSION: '(\d+)'", wf).group(1) == str(m["ngspice"]["version"])
    assert re.search(r"NGSPICE_SHA256: (\w+)", wf).group(1) == m["ngspice"]["source_sha256"]


def test_readme_build_recipe_matches_workflow():
    """sim/README.md states the same ngspice build deps and configure flags CI uses."""
    wf = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    readme = " ".join((SIM_DIR / "README.md").read_text().split())
    deps = re.search(r"NGSPICE_BUILD_DEPS: (.+)", wf).group(1).strip()
    flags = re.search(r"NGSPICE_CONFIGURE_FLAGS: (.+)", wf).group(1).strip()
    assert "libreadline-dev" in deps.split()
    assert f"`{deps}`" in readme
    assert f"`./configure {flags}`" in readme


def test_passive_controls_run_in_sim_smoke_without_recording():
    """Issue #83: sim-smoke runs the passive-p1 synthetic controls, never with
    --write-record, before the clean-tree gate, with SciPy declared in a
    requirements file that is separate from the simulator-free one."""
    wf = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    sim_job = wf.split("\n  sim-smoke:", 1)[1]
    cmd = "python3 sim/passive-p1/scripts/controls.py all"
    assert cmd in sim_job
    line = next(ln for ln in sim_job.splitlines() if cmd in ln)
    assert "--write-record" not in line
    assert sim_job.index(cmd) < sim_job.index("No evidence record or tracked file")
    assert "pip install -r requirements-sim.txt" in sim_job
    sim_req = (REPO_ROOT / "requirements-sim.txt").read_text()
    test_req = (REPO_ROOT / "requirements-test.txt").read_text()
    assert re.search(r"^scipy>=[\d.]+,<[\d.]+$", sim_req, re.M)
    assert re.search(r"^numpy>=[\d.]+,<[\d.]+$", sim_req, re.M)
    assert "scipy" not in test_req  # requirements-test.txt stays simulator-free


def _bench_test_files():
    """Every pytest-collectable file under a tests/ directory of sim/ or .github/scripts/,
    as repo-relative POSIX paths."""
    found = []
    for root in (SIM_DIR, REPO_ROOT / ".github" / "scripts"):
        for p in root.rglob("*.py"):
            rel = p.relative_to(REPO_ROOT)
            if "tests" in rel.parts[:-1] and (p.name.startswith("test_") or p.name.endswith("_test.py")):
                found.append(rel.as_posix())
    return sorted(found)


_PYTEST_CMD = re.compile(r"^(?:-\s+)?(?:run:\s*)?(?:python3?\s+-m\s+)?pytest(?:\s+(?P<args>.*))?$")


def _pytest_args(wf):
    """Argument tokens of executable pytest commands only (plain string tokens, no YAML
    parse): a line counts when, after an optional `- ` / `run:` prefix, the command itself
    is `pytest` or `python[3] -m pytest`. YAML comment lines, trailing ` #` comments,
    `name:` descriptions and `pip install pytest` never count as coverage."""
    args = set()
    for ln in wf.splitlines():
        cmd = re.split(r"\s#", ln.strip(), maxsplit=1)[0].strip()
        if cmd.startswith("#"):
            continue
        m = _PYTEST_CMD.match(cmd)
        if m and m.group("args"):
            args.update(tok.rstrip("/") for tok in m.group("args").split())
    return args


def _not_run_by(wf, files):
    """Files whose own path, or one of whose parent directories, is not an argument of
    any executable `pytest` command in the workflow text."""
    args = _pytest_args(wf)
    def covered(f):
        parts = f.split("/")
        return any("/".join(parts[:i]) in args for i in range(1, len(parts) + 1))
    return [f for f in files if not covered(f)]


def test_every_bench_tests_file_is_run_by_ci():
    """Issue #117: a bench test file that no ci.yml `pytest` step names never runs and
    CI stays green; fail, naming the file, instead. Negative controls on synthetic text."""
    wf = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    files = _bench_test_files()
    assert any(f.startswith("sim/") for f in files)  # the glob is not vacuous
    assert any(f.startswith(".github/scripts/tests/") for f in files)
    missing = _not_run_by(wf, files)
    assert not missing, "test files not run by any pytest step in ci.yml: " + ", ".join(missing)

    # Negative control 1: drop the step that names one directory -> its files are reported.
    gone = "sim/lna-sparam-nf/tests"
    assert gone in wf
    cut = "\n".join(ln for ln in wf.splitlines() if gone not in ln)
    assert _not_run_by(cut, files) == [f for f in files if f.startswith(gone + "/")] != []
    # Negative control 2: a step naming one file does not cover a new sibling file.
    named = "sim/mixer-nf-method/tests/test_nfmethod.py"
    assert named in wf and _not_run_by(wf, [named]) == []
    sibling = "sim/mixer-nf-method/tests/test_new_bench.py"
    assert _not_run_by(wf, [sibling]) == [sibling]
    # A prefix-sharing directory is not covered by a string-prefix accident.
    assert _not_run_by(wf, ["sim/harness/tests2/test_x.py"]) == ["sim/harness/tests2/test_x.py"]

    # Negative control 3: commenting out a real pytest step leaves its files uncovered.
    commented = "\n".join(
        re.sub(r"^(\s*)", r"\1# ", ln) if gone in ln else ln for ln in wf.splitlines()
    )
    assert commented != wf
    assert _not_run_by(commented, files) == [f for f in files if f.startswith(gone + "/")]
    # Negative control 4: comment-only, trailing-comment, description and install lines
    # are not executable pytest commands.
    new = ["sim/new-bench/tests/test_new.py"]
    for text in (
        "# run: python -m pytest sim/new-bench/tests -q",
        "        run: echo skip  # python -m pytest sim/new-bench/tests -q",
        "      - name: Run pytest on sim/new-bench/tests",
        "        run: pip install pytest sim/new-bench/tests",
    ):
        assert _not_run_by(text, new) == new, text
    # Positive control: the same command, uncommented, does cover it.
    assert _not_run_by("        run: python -m pytest sim/new-bench/tests -q", new) == []
    assert _not_run_by("          python3 -m pytest sim/new-bench/tests  # bench", new) == []
