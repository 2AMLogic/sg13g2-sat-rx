"""Negative controls for signoff/make_item10_evidence.py (issue #191).

Each test copies the generator's inputs into a temp tree (ROOT/OUT
monkeypatched, so the committed envelope is never rewritten), breaks one
thing, and asserts exactly the expected check goes false. The freshness test
fences the committed envelope against the real tree.

Run: python3 -m pytest signoff/tests -q
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

SIGNOFF = Path(__file__).resolve().parents[1]
REPO = SIGNOFF.parent
sys.path.insert(0, str(SIGNOFF))

import make_item10_evidence as gen  # noqa: E402


@pytest.fixture()
def tree(tmp_path, monkeypatch):
    for rel in gen.FILES + [gen.CI]:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, dst)
    out = tmp_path / gen.OUT_REL
    out.parent.mkdir(parents=True)
    monkeypatch.setattr(gen, "ROOT", tmp_path)
    monkeypatch.setattr(gen, "OUT", out)
    return tmp_path


def run_gen(capsys):
    rc = gen.main()
    capsys.readouterr()
    return rc, json.loads(gen.OUT.read_text())


def edit(tree, rel, fn):
    p = tree / rel
    p.write_text(fn(p.read_text()))


def test_unbroken_copy_passes(tree, capsys):
    rc, env = run_gen(capsys)
    assert rc == 0
    assert env["status"] == "pass"
    assert env["t1_item"] == 10
    assert all(env["metrics"]["checks"].values())


def drop_section(t):
    return t.replace("## Reproduce", "## Other")


def drop_link(t):
    return t.replace("](sim/README.md)", "](sim/OTHER.md)")


def drop_script(t):
    return t.replace("sim/characterize.sh", "sim/other.sh")


def comment_evidence(t):
    return "\n".join("# " + l if "check_evidence_formats.py" in l else l
                     for l in t.splitlines()) + "\n"


def drop_smoke(t):
    return t.replace("run: sim/characterize.sh smoke", "run: echo skipped")


BREAKS = [
    ("LICENSE", lambda t: "", {"exists:LICENSE"}),
    ("README.md", drop_section, {"readme:reproduce-links-sim-README",
                                 "readme:reproduce-names-characterize.sh"}),
    ("README.md", drop_link, {"readme:reproduce-links-sim-README"}),
    ("README.md", drop_script, {"readme:reproduce-names-characterize.sh"}),
    (gen.CI, comment_evidence, {"ci:evidence-format-check"}),
    (gen.CI, drop_smoke, {"ci:harness-smoke"}),
]


@pytest.mark.parametrize("rel,fn,expected", BREAKS)
def test_single_break_fails_only_expected_checks(tree, capsys, rel, fn, expected):
    edit(tree, rel, fn)
    rc, env = run_gen(capsys)
    assert rc == 1
    assert env["status"] == "fail"
    bad = {k for k, v in env["metrics"]["checks"].items() if not v}
    assert bad == expected


def test_missing_ci_fails_with_null_hash(tree, capsys):
    (tree / gen.CI).unlink()
    rc, env = run_gen(capsys)
    assert rc == 1
    assert env["status"] == "fail"
    assert env["provenance"]["input"]["content_hash"] is None
    assert env["metrics"]["checks"][f"exists:{gen.CI}"] is False


def test_missing_license_not_listed_in_files(tree, capsys):
    (tree / "LICENSE").unlink()
    rc, env = run_gen(capsys)
    assert rc == 1
    assert "LICENSE" not in env["metrics"]["files"]


def test_editing_ci_changes_bound_hash(tree, capsys):
    _, base = run_gen(capsys)
    edit(tree, gen.CI, lambda t: t + "\n# edit\n")
    _, new = run_gen(capsys)
    assert new["provenance"]["input"]["content_hash"] != \
        base["provenance"]["input"]["content_hash"]


def test_committed_envelope_is_fresh_and_manifest_pins_it(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out.json"
    monkeypatch.setattr(gen, "OUT", out)
    assert gen.main() == 0
    capsys.readouterr()
    env = json.loads(out.read_text())
    committed = json.loads((REPO / gen.OUT_REL).read_text())
    assert committed == env, "regenerate: python3 signoff/make_item10_evidence.py"
    cite = json.loads((SIGNOFF / "block-manifest.json").read_text())["evidence"]["10"]
    assert cite["file"] == gen.OUT_REL
    assert cite["content_hash"] == env["provenance"]["input"]["content_hash"]
