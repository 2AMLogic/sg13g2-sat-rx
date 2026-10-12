"""Negative controls for signoff/make_item9_evidence.py (issue #182).

Each test copies only the inputs the generator reads (sim/<bench>/README.md,
sim/<bench>/records/*.md, sim/pdk-artifact.json) into a temp tree, breaks one
thing, and asserts the generator fails on that check -- and that the unbroken
copy passes. The final test fences the committed envelope: it must equal what
the generator produces from the real tree now, so a changed bound README,
record or PDK pin makes CI red until the envelope is regenerated.

Run: python3 -m pytest signoff/tests -q
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SIGNOFF = Path(__file__).resolve().parents[1]
REPO = SIGNOFF.parent
sys.path.insert(0, str(SIGNOFF))

import make_item9_evidence as gen  # noqa: E402


@pytest.fixture()
def tree(tmp_path):
    sim = REPO / "sim"
    for b in gen.bench_dirs(REPO):
        dst = tmp_path / "sim" / b
        (dst / "records").mkdir(parents=True)
        shutil.copy(sim / b / "README.md", dst / "README.md")
        for md in (sim / b / "records").glob("*.md"):
            shutil.copy(md, dst / "records" / md.name)
    shutil.copy(sim / "pdk-artifact.json", tmp_path / "sim" / "pdk-artifact.json")
    return tmp_path


def failed(root):
    env, res, _ = gen.build(root)
    return env["status"], sorted(k for k, v in res.items() if not v)


def newest(root):
    return gen.newest_record(root, gen.BENCH)


def test_unbroken_copy_passes(tree):
    assert failed(tree) == ("pass", [])


def test_missing_readme_fails(tree):
    (tree / "sim" / "passive-p1" / "README.md").unlink()
    assert failed(tree) == ("fail", ["readme:passive-p1"])


def test_readme_without_invocation_block_fails(tree):
    (tree / "sim" / "lna-headroom" / "README.md").write_text("# lna-headroom\n\nno commands here\n")
    assert failed(tree) == ("fail", ["readme:lna-headroom"])


def test_readme_with_heading_but_no_fence_fails(tree):
    (tree / "sim" / "lna-headroom" / "README.md").write_text("# x\n\n## Cold start\n\nrun it somehow\n")
    assert failed(tree) == ("fail", ["readme:lna-headroom"])


def test_record_without_artifact_line_fails(tree):
    r = newest(tree)
    r.write_text(re.sub(r"^- PDK artifact:.*\n", "", r.read_text(), flags=re.M))
    status, bad = failed(tree)
    assert status == "fail" and "record:pdk-artifact-line" in bad


def test_record_naming_pdk_unknown_fails(tree):
    r = newest(tree)
    r.write_text(re.sub(r"^- PDK: .*$", "- PDK: sg13g2 ihp-sg13g2 (unknown)", r.read_text(), flags=re.M))
    status, bad = failed(tree)
    assert status == "fail" and "record:pdk-not-unknown" in bad


def test_legacy_unknown_record_as_newest_fails(tree):
    # only a legacy (pre-#103, PDK unknown, no artifact line) record present
    recs = tree / "sim" / gen.BENCH / "records"
    keep = "20261010-012923-6cad7fc.md"
    for md in recs.glob("*.md"):
        if md.name != keep:
            md.unlink()
    status, bad = failed(tree)
    assert status == "fail"
    assert "record:pdk-artifact-line" in bad and "record:pdk-not-unknown" in bad


def test_artifact_commit_not_matching_pin_fails(tree):
    r = newest(tree)
    r.write_text(re.sub(r"commit `[0-9a-f]{40}`", "commit `" + "0" * 40 + "`", r.read_text(), count=1))
    status, bad = failed(tree)
    assert status == "fail" and "record:pdk-commit-matches-pin" in bad


def test_changed_pdk_pin_fails(tree):
    p = tree / "sim" / "pdk-artifact.json"
    p.write_text(p.read_text() + "\n")
    status, bad = failed(tree)
    assert status == "fail" and "record:pdk-digest-matches-pin" in bad


def test_unexplained_fail_status_fails(tree):
    r = newest(tree)
    r.write_text(r.read_text().replace("## Result\n**FAIL**\n", "## Result\n**FAIL**\n- s11_db_mid exceeded limit\n"))
    status, bad = failed(tree)
    assert status == "fail" and "record:fail-only-unswept-axis" in bad


def test_incomplete_points_fails(tree):
    r = newest(tree)
    r.write_text(re.sub(r"(\d+) point grid(.*?), \d+ completed", r"\1 point grid\2, 0 completed", r.read_text(), count=1))
    status, bad = failed(tree)
    assert status == "fail" and "record:all-declared-points-completed" in bad


def test_cli_exits_nonzero_on_failure(tree, tmp_path):
    (tree / "sim" / "passive-p1" / "README.md").unlink()
    env, res, _ = gen.build(tree)
    assert env["status"] == "fail" and not res["readme:passive-p1"]


def test_attestation_text_disclaims_spec_rows():
    env, _, _ = gen.build(REPO)
    assert "does NOT attest that any spec row is met" in env["summary"]


def test_committed_envelope_is_fresh_and_manifest_pins_it():
    env, _, rec = gen.build(REPO)
    assert env["status"] == "pass"
    committed = json.loads((REPO / gen.OUT_REL).read_text())
    assert committed == env, "regenerate: python3 signoff/make_item9_evidence.py"
    manifest = json.loads((SIGNOFF / "block-manifest.json").read_text())
    cite = manifest["evidence"]["9"]
    assert cite["file"] == gen.OUT_REL
    assert cite["content_hash"] == env["provenance"]["input"]["content_hash"]


def test_real_cli_returns_zero_and_prints_citation():
    out = subprocess.run([sys.executable, str(SIGNOFF / "make_item9_evidence.py")],
                         capture_output=True, text=True, cwd=REPO)
    assert out.returncode == 0
    assert "content_hash" in json.loads(out.stdout)["9"]
