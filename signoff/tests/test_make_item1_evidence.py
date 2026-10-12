"""Negative controls for signoff/make_item1_evidence.py (issue #191).

The generator shells out to design/export_netlist.sh --check, which needs klt,
xschem and an IHP-Open-PDK checkout. These tests never spawn it: subprocess.run
is faked. ROOT/OUT are monkeypatched to a temp tree so the committed envelope
is never rewritten.

Run: python3 -m pytest signoff/tests -q
"""
import hashlib
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

import make_item1_evidence as gen  # noqa: E402

OUT_REL = "signoff/evidence/item1-design-sources.json"


@pytest.fixture()
def tree(tmp_path, monkeypatch):
    for rel in gen.SOURCES + [gen.NETLIST]:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, dst)
    out = tmp_path / OUT_REL
    out.parent.mkdir(parents=True)
    monkeypatch.setattr(gen, "ROOT", tmp_path)
    monkeypatch.setattr(gen, "OUT", out)
    return tmp_path


def fake_check(monkeypatch, rc, stdout="", stderr=""):
    calls = []

    def run(*a, **k):
        calls.append(a[0])
        return subprocess.CompletedProcess(a[0], rc, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(gen.subprocess, "run", run)
    return calls


def run_gen(capsys):
    rc = gen.main()
    capsys.readouterr()
    return rc, json.loads(gen.OUT.read_text())


def test_pass_when_check_succeeds(tree, monkeypatch, capsys):
    calls = fake_check(monkeypatch, 0, stdout="netlist up to date")
    rc, env = run_gen(capsys)
    assert rc == 0
    assert env["status"] == "pass"
    assert env["t1_item"] == 1
    assert calls and calls[0][1] == "--check"
    assert set(env["metrics"]["sources"]) == set(gen.SOURCES)
    assert env["provenance"]["input"]["path"] == gen.NETLIST


def test_fail_when_check_reports_drift(tree, monkeypatch, capsys):
    fake_check(monkeypatch, 1, stderr="DRIFT: netlist differs")
    rc, env = run_gen(capsys)
    assert rc == 1
    assert env["status"] == "fail"
    assert "DRIFT: netlist differs" in env["metrics"]["check_output"]


def test_edited_schematic_changes_source_hash(tree, monkeypatch, capsys):
    fake_check(monkeypatch, 0)
    _, base = run_gen(capsys)
    sch = tree / "design/lna_stage1.sch"
    sch.write_bytes(sch.read_bytes() + b"\n* edit\n")
    _, new = run_gen(capsys)
    key = "design/lna_stage1.sch"
    assert new["metrics"]["sources"][key] != base["metrics"]["sources"][key]
    assert new["metrics"]["sources"]["design/lna_stage1.sym"] == \
        base["metrics"]["sources"]["design/lna_stage1.sym"]


def test_edited_netlist_changes_bound_hash(tree, monkeypatch, capsys):
    fake_check(monkeypatch, 0)
    _, base = run_gen(capsys)
    nl = tree / gen.NETLIST
    nl.write_bytes(nl.read_bytes() + b"* edit\n")
    _, new = run_gen(capsys)
    assert new["provenance"]["input"]["content_hash"] != \
        base["provenance"]["input"]["content_hash"]


@pytest.mark.parametrize("rel", gen.SOURCES + [gen.NETLIST])
def test_missing_input_raises_and_writes_nothing(tree, monkeypatch, rel):
    fake_check(monkeypatch, 0)
    (tree / rel).unlink()
    with pytest.raises(FileNotFoundError):
        gen.main()
    assert not gen.OUT.exists()


def test_committed_envelope_is_fresh_and_manifest_pins_it():
    committed = json.loads((REPO / OUT_REL).read_text())
    assert committed["status"] == "pass"
    assert committed["t1_item"] == 1
    for rel in gen.SOURCES:
        want = "sha256:" + hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
        assert committed["metrics"]["sources"][rel] == want, \
            "stale: rerun design/export_netlist.sh and signoff/make_item1_evidence.py"
    nl_hash = "sha256:" + hashlib.sha256((REPO / gen.NETLIST).read_bytes()).hexdigest()
    assert committed["provenance"]["input"]["content_hash"] == nl_hash
    manifest = json.loads((SIGNOFF / "block-manifest.json").read_text())
    cite = manifest["evidence"]["1"]
    assert cite["file"] == OUT_REL
    assert cite["content_hash"] == nl_hash


def test_netlist_header_source_hash_matches_sources():
    header = (REPO / gen.NETLIST).read_text().splitlines()[:5]
    m = re.search(r"sources sha256 .*?:\s*([0-9a-f]{64})", "\n".join(header))
    assert m, "netlist header lacks sources sha256"
    cat = b"".join((REPO / rel).read_bytes() for rel in gen.SOURCES)
    assert m.group(1) == hashlib.sha256(cat).hexdigest()
