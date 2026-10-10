#!/usr/bin/env python3
"""Write signoff/evidence/item1-design-sources.json, the artifact-anchored
generic attestation for T1 item 1 (Design sources), and print the manifest
entry that cites it.

    python3 signoff/make_item1_evidence.py

The attestation is "pass" only if design/export_netlist.sh --check says the
committed netlist is the one the committed xschem sources produce now. It
binds (provenance.input) the derived netlist and lists the schematic sources
with their hashes in metrics, so a changed schematic or netlist makes the
citation stale rather than silently still met. See signoff/README.md
("Adding a citation") and klt signoff's artifact-anchored generic evidence.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ["design/lna_stage1.sch", "design/lna_stage1.sym"]
NETLIST = "design/netlist/lna_stage1.spice"
OUT = ROOT / "signoff" / "evidence" / "item1-design-sources.json"


def sha(path: str) -> str:
    return "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def main() -> int:
    chk = subprocess.run([str(ROOT / "design" / "export_netlist.sh"), "--check"],
                         capture_output=True, text=True, cwd=ROOT)
    status = "pass" if chk.returncode == 0 else "fail"
    env = {
        "schema_version": 1,
        "kind": "generic",
        "status": status,
        "t1_item": 1,
        "summary": ("Committed xschem schematic sources and the SPICE netlist derived from them "
                    "(klt netlist --block via design/export_netlist.sh); the committed netlist matches "
                    "what the sources export now."),
        "source": "design/export_netlist.sh --check",
        "metrics": {"sources": {p: sha(p) for p in SOURCES}, "netlist": NETLIST,
                    "check_output": (chk.stdout + chk.stderr).strip()},
        "provenance": {"input": {"path": NETLIST, "content_hash": sha(NETLIST)}},
    }
    OUT.write_text(json.dumps(env, indent=2) + "\n")
    print(json.dumps({"1": {"file": "signoff/evidence/item1-design-sources.json",
                            "content_hash": sha(NETLIST)}}, indent=2))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
