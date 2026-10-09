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
