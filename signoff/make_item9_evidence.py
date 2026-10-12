#!/usr/bin/env python3
"""Write signoff/evidence/item9-testbenches-shipped.json, the artifact-anchored
generic attestation for T1 item 9 (Testbenches shipped), and print the manifest
entry that cites it.

    python3 signoff/make_item9_evidence.py

WHAT THIS ATTESTS: that the testbenches are shipped and reproducible -- every
sim/<bench>/ holding records/ has a cold-start README with a fenced invocation
block, and the primary bench (sim/lna-sparam-nf) has a newest record that was
written by the harness under a hash-verified, pinned PDK artifact. It does NOT
attest that any spec row is met, that any measured figure is good, or that the
bench's full PVT grid was re-run: the bound record is a declared single-point
subset, and its own Result may be FAIL for that reason alone (see the check
"record:fail-only-unswept-axis"). See signoff/README.md ("Adding a citation").

The attestation is "pass" only if every mechanically checkable part holds:

  * every sim/<dir> with a records/ directory has a README.md whose invocation
    section contains a fenced command block (same rule as
    .github/scripts/check_evidence_formats.py, imported, not re-implemented);
  * the newest record of sim/lna-sparam-nf carries a "- PDK artifact:
    **verified**" line (upstream commit + manifest sha256), that commit and
    digest match sim/pdk-artifact.json / its file hash, and the record does not
    name the PDK "unknown";
  * the record completed every point it declares, and if its Result is FAIL
    the only failures are "axis was never swept" sensitivity checks, which a
    declared single-point subset cannot satisfy.

It binds (provenance.input) the bound record by content hash and lists the
README set, pdk-artifact.json, and the newest record's pinned status of every
other bench in metrics. A changed record or README makes the citation stale
rather than silently still met. Exits non-zero (and writes status "fail") if
any check fails. "met" means bound to an audited artifact, not that the
design is any good.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".github" / "scripts"))
from evidence_checks.readmes import (  # noqa: E402
    PDK_ARTIFACT_RE, PDK_UNKNOWN_RE, readme_invocation_problem)

BENCH = "lna-sparam-nf"
PDK_PIN = "sim/pdk-artifact.json"
OUT_REL = "signoff/evidence/item9-testbenches-shipped.json"


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha(root: Path, rel: str) -> str:
    return "sha256:" + sha_bytes((root / rel).read_bytes())


def bench_dirs(root: Path) -> list:
    sim = root / "sim"
    return sorted(p.name for p in sim.iterdir() if p.is_dir() and (p / "records").is_dir())


def newest_record(root: Path, bench: str):
    recs = sorted((root / "sim" / bench / "records").glob("*.md"))
    return recs[-1] if recs else None


def record_pinned(text: str) -> bool:
    return bool(PDK_ARTIFACT_RE.search(text)) and not PDK_UNKNOWN_RE.search(text)


def checks(root: Path):
    """Return (checks dict, bound record rel path or None, pinned-by-bench dict)."""
    res, pinned = {}, {}
    benches = bench_dirs(root)
    res["benches:found"] = bool(benches) and BENCH in benches
    for b in benches:
        why = readme_invocation_problem(root / "sim" / b / "README.md")
        res[f"readme:{b}"] = why is None
        rec = newest_record(root, b)
        pinned[b] = bool(rec and record_pinned(rec.read_text(errors="replace")))

    rec = newest_record(root, BENCH)
    rec_rel = rec.relative_to(root).as_posix() if rec else None
    text = rec.read_text(errors="replace") if rec else ""
    m = PDK_ARTIFACT_RE.search(text)
    res["record:exists"] = rec is not None
    res["record:pdk-artifact-line"] = m is not None
    res["record:pdk-not-unknown"] = rec is not None and not PDK_UNKNOWN_RE.search(text)
    pin_file = root / PDK_PIN
    commit_ok = digest_ok = False
    if m and pin_file.is_file():
        try:
            commit = json.loads(pin_file.read_text())["upstream"]["commit"]
        except (KeyError, ValueError):
            commit = None
        line = m.group(0)
        commit_ok = commit is not None and f"commit `{commit}`" in line
        digest_ok = f"sha256 `{sha_bytes(pin_file.read_bytes())}`" in line
    res["record:pdk-commit-matches-pin"] = commit_ok
    res["record:pdk-digest-matches-pin"] = digest_ok
    pts = re.search(r"(\d+) point grid.*?, (\d+) completed", text)
    res["record:all-declared-points-completed"] = bool(pts) and pts.group(1) == pts.group(2)
    status = re.search(r"^\*\*Status\*\*: (\w+)", text, re.M)
    ok_status = False
    if status and status.group(1) == "pass":
        ok_status = True
    elif status and status.group(1) == "fail":
        sec = re.search(r"^## Result\n(.*?)(?=^## )", text, re.M | re.S)
        bullets = [l for l in (sec.group(1) if sec else "").splitlines() if l.startswith("- ")]
        ok_status = bool(bullets) and all("axis was never swept" in l for l in bullets)
    res["record:fail-only-unswept-axis"] = ok_status
    return res, rec_rel, pinned


def build(root: Path):
    res, rec_rel, pinned = checks(root)
    ok = all(res.values())
    benches = bench_dirs(root)
    env = {
        "schema_version": 1,
        "kind": "generic",
        "status": "pass" if ok else "fail",
        "t1_item": 9,
        "summary": (
            "Testbenches shipped: every sim/<bench>/ holding records/ has a cold-start README with a "
            "fenced invocation block, and the newest sim/lna-sparam-nf record was written by the harness "
            "under a hash-verified pinned PDK artifact (sim/pdk-artifact.json). This attests the "
            "testbenches are shipped and reproducible. It does NOT attest that any spec row is met, and "
            "the bound record is a declared single-point (hbt_typ, 27 C, 2.50 V) local subset, not the "
            "27-point grid; its Result may be FAIL only because a one-point run cannot satisfy "
            "axis-sensitivity checks. Presence/provenance checks only."),
        "source": "signoff/make_item9_evidence.py",
        "metrics": {
            "checks": res,
            "readmes": {b: sha(root, f"sim/{b}/README.md")
                        for b in benches if (root / "sim" / b / "README.md").is_file()},
            "pdk_pin": {PDK_PIN: sha(root, PDK_PIN) if (root / PDK_PIN).is_file() else None},
            "newest_record_pinned_pdk_by_bench": pinned,
        },
        "provenance": {"input": {"path": rec_rel,
                                 "content_hash": sha(root, rec_rel) if rec_rel else None}},
    }
    return env, res, rec_rel


def main() -> int:
    env, res, rec_rel = build(ROOT)
    out = ROOT / OUT_REL
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(env, indent=2) + "\n")
    if env["status"] != "pass":
        print("FAIL: " + ", ".join(k for k, v in res.items() if not v), file=sys.stderr)
        return 1
    print(json.dumps({"9": {"file": OUT_REL, "content_hash": env["provenance"]["input"]["content_hash"]}},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
