#!/usr/bin/env python3
"""Write signoff/evidence/item10-repo-hygiene.json, the artifact-anchored
generic attestation for T1 item 10 (Repo hygiene), and print the manifest
entry that cites it.

    python3 signoff/make_item10_evidence.py

The attestation is "pass" only if every mechanically checkable part holds:

  * README.md, LICENSE and spec/target-spec.md exist and are non-empty;
  * README.md has a "Reproduce" section linking sim/README.md and naming the
    sim/characterize.sh entry point;
  * .github/workflows/ci.yml invokes the evidence-format check
    (.github/scripts/check_evidence_formats.py) and the harness smoke test
    (sim/characterize.sh smoke), each as a `run:` step, not just a comment.

It binds (provenance.input) the CI workflow by content hash and lists the other
files with their hashes in metrics, so a changed workflow makes the citation
stale rather than silently still met. Exits non-zero (and writes status "fail")
if any check fails. "met" means bound to an audited artifact, not that the
repository is good. See signoff/README.md ("Adding a citation").
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CI = ".github/workflows/ci.yml"
FILES = ["README.md", "LICENSE", "spec/target-spec.md"]
OUT = ROOT / "signoff" / "evidence" / "item10-repo-hygiene.json"
OUT_REL = "signoff/evidence/item10-repo-hygiene.json"


def sha(path: str) -> str:
    return "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def run_lines(text: str) -> str:
    """Non-comment workflow text (so a commented-out step does not count)."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def checks() -> dict:
    res = {}
    for f in FILES:
        p = ROOT / f
        res[f"exists:{f}"] = p.is_file() and p.stat().st_size > 0
    ci = ROOT / CI
    ci_text = run_lines(ci.read_text()) if ci.is_file() else ""
    res[f"exists:{CI}"] = ci.is_file()
    res["ci:evidence-format-check"] = bool(
        re.search(r"^\s+python3? \.github/scripts/check_evidence_formats\.py\b", ci_text, re.M))
    res["ci:harness-smoke"] = bool(re.search(r"run:\s*sim/characterize\.sh smoke\s*$", ci_text, re.M))
    readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").is_file() else ""
    m = re.search(r"^##\s+Reproduce\b(.*?)(?=^##\s|\Z)", readme, re.M | re.S)
    sec = m.group(1) if m else ""
    res["readme:reproduce-links-sim-README"] = "](sim/README.md)" in sec
    res["readme:reproduce-names-characterize.sh"] = "sim/characterize.sh" in sec
    return res


def main() -> int:
    res = checks()
    ok = all(res.values())
    status = "pass" if ok else "fail"
    env = {
        "schema_version": 1,
        "kind": "generic",
        "status": status,
        "t1_item": 10,
        "summary": ("Repo hygiene: README (with a Reproduce section linking sim/README.md), LICENSE and "
                    "spec/target-spec.md are present; CI (.github/workflows/ci.yml) runs the evidence-format "
                    "check and the harness smoke test. Presence/invocation checks only; they do not judge "
                    "the content's quality."),
        "source": "signoff/make_item10_evidence.py",
        "metrics": {"checks": res,
                    "files": {f: sha(f) for f in FILES if (ROOT / f).is_file()}},
        "provenance": {"input": {"path": CI, "content_hash": sha(CI) if (ROOT / CI).is_file() else None}},
    }
    OUT.write_text(json.dumps(env, indent=2) + "\n")
    if not ok:
        print("FAIL: " + ", ".join(k for k, v in res.items() if not v), file=sys.stderr)
        return 1
    print(json.dumps({"10": {"file": OUT_REL, "content_hash": sha(CI)}}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
