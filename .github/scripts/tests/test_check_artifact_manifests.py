"""Negative controls for the stored-evidence manifest checks (issue #226).

The fixture converts a committed harness-native record to the stored form (its
corner logs and frozen snapshots become artifact-store objects named by
``manifests/artifacts/<bench>-<id>.manifest.json``), proves the checker accepts
it, then breaks exactly one thing per test. Nothing in the real tree is touched.

Run: python3 -m pytest .github/scripts/tests -q
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_check_evidence_formats import NATIVE, NATIVE_ID, assert_fails, own, problems_of, tree  # noqa: E402,F401
import check_evidence_formats as chk  # noqa: E402
from _helpers import commit, run  # noqa: E402

LEGACY_SCHEME = "s3" + "://"  # built, so a grep for the literal stays clean


def _entry(path: Path, name: str) -> dict:
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    return {"sha256": sha, "size": len(data), "kind": "evidence",
            "producer": {"tool": "klt", "version": "t", "loom.repo": "owner/repo", "commit": None},
            "uri": f"artifact:evidence/owner__repo/{sha[:2]}/{sha}", "name": name}


def _table(entries) -> str:
    lines = ["", "## Stored evidence", "", "| name | size (B) | sha256 |", "|---|---:|---|"]
    lines += [f"| `{e['name']}` | {e['size']} | `{e['sha256']}` |" for e in entries]
    return "\n".join(lines) + "\n"


@pytest.fixture
def stored(tree):
    """``tree`` with the NATIVE record converted to the stored form."""
    bench = tree / "sim" / NATIVE
    prefix = f"sim/{NATIVE}"
    snaps = bench / "netlist-snapshots"
    entries = [_entry(snaps / f"{NATIVE_ID}.spice", f"{prefix}/netlist-snapshots/{NATIVE_ID}.spice")]
    frozen = snaps / f"{NATIVE_ID}.tb.json"
    if frozen.is_file():
        entries.append(_entry(frozen, f"{prefix}/netlist-snapshots/{NATIVE_ID}.tb.json"))
    for log in sorted((bench / "corners" / NATIVE_ID).iterdir()):
        entries.append(_entry(log, f"{prefix}/corners/{NATIVE_ID}/{log.name}"))
    shutil.rmtree(bench / "corners" / NATIVE_ID)
    for p in snaps.glob(f"{NATIVE_ID}*"):
        p.unlink() if p.is_file() or p.is_symlink() else shutil.rmtree(p)
    md = own(bench / "records" / f"{NATIVE_ID}.md")
    md.write_text(md.read_text().rstrip("\n") + "\n" + _table(entries))
    mdir = tree / "manifests" / "artifacts"
    mdir.mkdir(parents=True)
    mpath = mdir / f"{NATIVE}-{NATIVE_ID}.manifest.json"
    mpath.write_text(json.dumps({"schema_version": 1, "entries": entries}, indent=2) + "\n")
    return tree, mpath, md, entries


def _edit_manifest(mpath, fn):
    m = json.loads(mpath.read_text())
    fn(m)
    mpath.write_text(json.dumps(m, indent=2) + "\n")


def test_stored_form_record_passes(stored):
    tree, *_ = stored
    assert problems_of(tree) == []


def test_non_artifact_uri_fails(stored):
    tree, mpath, *_ = stored
    _edit_manifest(mpath, lambda m: m["entries"][0].update(uri=f"{LEGACY_SCHEME}bucket/{m['entries'][0]['sha256']}"))
    assert_fails(tree, "uri must be artifact:<key>", "names a storage location")


def test_https_uri_fails(stored):
    tree, mpath, *_ = stored
    _edit_manifest(mpath, lambda m: m["entries"][0].update(uri="https://host/x"))
    assert_fails(tree, "uri must be artifact:<key>")


def test_storage_location_text_anywhere_under_manifests_fails(stored):
    tree, *_ = stored
    (tree / "manifests" / "README.md").write_text("see arn:aws:s3:::bucket\n")
    assert_fails(tree, "manifests/README.md:1", "names a storage location")


def test_schema_violation_fails(stored):
    tree, mpath, *_ = stored
    _edit_manifest(mpath, lambda m: m["entries"][0].update(kind="other", size=0))
    assert_fails(tree, "kind must be 'evidence'", "size must be a positive integer")


def test_unknown_field_and_duplicate_name_fail(stored):
    tree, mpath, *_ = stored

    def mutate(m):
        m["entries"][0]["bucket"] = "x"
        m["entries"][1]["name"] = m["entries"][0]["name"]

    _edit_manifest(mpath, mutate)
    assert_fails(tree, "unknown field(s) bucket", "duplicate name")


def test_stray_file_in_manifest_dir_fails(stored):
    tree, mpath, *_ = stored
    (mpath.parent / "notes.txt").write_text("x\n")
    assert_fails(tree, "only <bench>-<run-id>.manifest.json files")


def test_stored_object_bytes_also_committed_fails(stored):
    tree, mpath, md, entries = stored
    log = next(e for e in entries if e["name"].endswith(".log"))
    # Re-commit one stored log's bytes under sim/ (the blob fallback).
    sim_log = tree / log["name"]
    sim_log.parent.mkdir(parents=True, exist_ok=True)
    original = next((Path(__file__).resolve().parents[3] / "sim" / NATIVE / "corners" / NATIVE_ID).glob(
        Path(log["name"]).name))
    shutil.copyfile(original, sim_log)
    assert_fails(tree, "committed beside its manifest", "its bytes are a stored object")


def test_stored_record_without_manifest_fails(stored):
    tree, mpath, *_ = stored
    mpath.unlink()
    assert_fails(tree, "is missing")


def test_missing_corner_log_entry_fails(stored):
    tree, mpath, md, _ = stored
    victim = next(e["name"] for e in json.loads(mpath.read_text())["entries"] if e["name"].endswith(".log"))
    _edit_manifest(mpath, lambda m: m.update(entries=[e for e in m["entries"] if e["name"] != victim]))
    assert_fails(tree, "missing declared corner identity", "has no manifest entry")


def test_table_disagreeing_with_manifest_fails(stored):
    tree, mpath, md, entries = stored
    md.write_text(md.read_text().replace(entries[0]["sha256"], "0" * 64))
    assert_fails(tree, "disagrees with the manifest")


def test_stored_record_must_name_a_netlist_snapshot(stored):
    tree, mpath, md, entries = stored
    gone = entries[0]["name"]
    _edit_manifest(mpath, lambda m: m.update(entries=[e for e in m["entries"] if e["name"] != gone]))
    assert_fails(tree, "no entry for the frozen netlist snapshot")


def test_committed_logs_beside_stored_record_fail(stored):
    tree, *_ = stored
    d = tree / "sim" / NATIVE / "corners" / NATIVE_ID
    d.mkdir(parents=True)
    (d / "typ.log").write_text("x\n")
    assert_fails(tree, "also commits this path")


def test_legacy_records_still_validate(tree):
    assert problems_of(tree) == []


# ------------------------------------------------------------ append-only


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "r"
    (root / "manifests" / "artifacts").mkdir(parents=True)
    (root / "sim").mkdir()
    run(root, "git", "init", "-q", "-b", "main")
    (root / "sim" / "keep").write_text("x\n")
    mp = root / "manifests" / "artifacts" / "b-20260101-000000-abcdef0.manifest.json"
    mp.write_text('{"schema_version": 1, "entries": []}\n')
    commit(root, "base")
    return root, mp


def test_manifest_edit_since_merge_base_fails(repo):
    root, mp = repo
    mp.write_text('{"schema_version": 1, "entries": [1]}\n')
    commit(root, "edit")
    problems, _ = chk.check_append_only(root, "HEAD~1", False)
    assert any("stored-evidence manifest was modified" in p for p in problems.items), problems.items


def test_manifest_delete_since_merge_base_fails(repo):
    root, mp = repo
    mp.unlink()
    commit(root, "rm")
    problems, _ = chk.check_append_only(root, "HEAD~1", False)
    assert any("deleted or renamed away" in p for p in problems.items), problems.items


def test_new_manifest_is_allowed(repo):
    root, mp = repo
    (mp.parent / "b-20260102-000000-abcdef0.manifest.json").write_text("{}\n")
    commit(root, "add")
    problems, _ = chk.check_append_only(root, "HEAD~1", False)
    assert problems.items == []
