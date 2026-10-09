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
