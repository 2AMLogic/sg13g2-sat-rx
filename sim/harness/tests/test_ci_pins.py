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
