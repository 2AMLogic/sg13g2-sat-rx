"""Negative controls for .github/scripts/check_evidence_formats.py.

Each test builds a temporary copy of the committed evidence (or a temporary
git history of it), breaks exactly one thing, and asserts the checker fails
with a file-specific message -- and that the unbroken copy passes. Nothing in
the real tree is touched: format fixtures are symlink farms whose mutated
entries are replaced by private real files; history fixtures are clones.

Run: python3 -m pytest .github/scripts/tests -q
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parents[1]
sys.path.insert(0, str(SCRIPTS))

import check_evidence_formats as chk  # noqa: E402

NATIVE = "lna-sparam-nf"
NATIVE2 = "mixer-conversion-iip3"
KABAND = "hbt-kaband-characterization"
NATIVE_ID = "20260912-034726-9204518"
KABAND_ID = "20261009-095220-7f35db5"


# ---------------------------------------------------------------- fixtures


def _link(src, dst):
    os.symlink(os.path.abspath(src), dst)


@pytest.fixture
def tree(tmp_path):
    """A symlink-farm copy of sim/ (read-only unless a test calls own())."""
    dst = tmp_path / "repo"
    shutil.copytree(REPO / "sim", dst / "sim", copy_function=_link, symlinks=True,
                    ignore=shutil.ignore_patterns("harness", "_build", "_selftest", "__pycache__"))
    # The spec-row coverage check (issue #50) reads the spec table + manifest.
    (dst / "spec").mkdir()
    for name in ("target-spec.md", "row-coverage.json"):
        shutil.copyfile(REPO / "spec" / name, dst / "spec" / name)
    return dst


def own(path: Path) -> Path:
    """Replace a symlinked file by a private writable copy."""
    if path.is_symlink():
        target = path.resolve()
        path.unlink()
        shutil.copyfile(target, path)
    return path


def problems_of(root: Path) -> list[str]:
    return chk.check_format(root).items


def assert_fails(root: Path, *needles: str):
    found = problems_of(root)
    assert found, "checker passed a deliberately broken tree"
    for needle in needles:
        assert any(needle in p for p in found), f"no problem mentioning {needle!r} in:\n" + "\n".join(found)


# ---------------------------------------------------------------- format


def test_current_tree_passes():
    assert problems_of(REPO) == []


def test_fixture_copy_passes(tree):
    assert problems_of(tree) == []


def test_layouts_are_both_recognised(tree):
    sim = tree / "sim"
    assert chk.is_kaband(sim / KABAND, chk.Problems(), tree)
    assert not chk.is_kaband(sim / NATIVE, chk.Problems(), tree)
    assert (sim / NATIVE / "netlist-snapshots" / f"{NATIVE_ID}.spice").is_file()
    assert (sim / KABAND / "netlist-snapshots" / KABAND_ID).is_dir()


def test_native_missing_header_field(tree):
    md = own(tree / "sim" / NATIVE / "records" / f"{NATIVE_ID}.md")
    md.write_text("\n".join(l for l in md.read_text().splitlines() if not l.startswith("**Wall time**")) + "\n")
    assert_fails(tree, f"{NATIVE_ID}.md", "missing required header field '**Wall time**:'")


def test_native_missing_snapshot(tree):
    (tree / "sim" / NATIVE / "netlist-snapshots" / f"{NATIVE_ID}.spice").unlink()
    assert_fails(tree, "missing netlist snapshot")


def test_native_missing_corner_log(tree):
    (tree / "sim" / NATIVE / "corners" / NATIVE_ID / "hbt_bcs_-40c_2.25v.log").unlink()
    assert_fails(tree, "missing declared corner identity 'hbt_bcs_-40c_2.25v'")


def test_native_extra_corner_log(tree):
    d = tree / "sim" / NATIVE / "corners" / NATIVE_ID
    (d / "hbt_typ_85c_2.50v.log").write_text("stray\n")
    assert_fails(tree, "unexpected corner identity 'hbt_typ_85c_2.50v'")


def test_native_declared_matrix_disagrees_with_artifacts(tree):
    md = own(tree / "sim" / NATIVE / "records" / f"{NATIVE_ID}.md")
    md.write_text(md.read_text().replace("2.25 V, 2.50 V, 2.75 V", "2.25 V, 2.50 V"))
    assert_fails(tree, "declares 27 grid points", "unexpected corner identity 'hbt_typ_27c_2.75v'")


def test_native_snapshot_names_other_record(tree):
    snap = own(tree / "sim" / NATIVE / "netlist-snapshots" / f"{NATIVE_ID}.spice")
    snap.write_text(snap.read_text().replace(NATIVE_ID, "20200101-000000-0000000"))
    assert_fails(tree, "snapshot header does not name record")


def test_orphan_corner_directory(tree):
    (tree / "sim" / NATIVE / "corners" / "20300101-000000-aaaaaaa").mkdir()
    assert_fails(tree, "orphan evidence")


def test_kaband_missing_header_field(tree):
    md = own(tree / "sim" / KABAND / "records" / f"{KABAND_ID}.md")
    md.write_text("\n".join(l for l in md.read_text().splitlines() if not l.startswith("**Experiment**")) + "\n")
    assert_fails(tree, "missing required header field '**Experiment**:'")


def test_kaband_broken_gzip(tree):
    log = tree / "sim" / KABAND / "corners" / KABAND_ID / "hbt_wcs_125c_2.75v.log.gz"
    log.unlink()
    log.write_bytes(b"this is not gzip data")
    assert_fails(tree, "hbt_wcs_125c_2.75v.log.gz", "unreadable gzip")


def test_kaband_truncated_gzip(tree):
    log = tree / "sim" / KABAND / "corners" / KABAND_ID / "hbt_typ_27c_2.50v.log.gz"
    data = gzip.compress(b"x" * 100000)
    log.unlink()
    log.write_bytes(data[: len(data) // 2])
    assert_fails(tree, "hbt_typ_27c_2.50v.log.gz", "unreadable gzip")


def test_kaband_missing_and_extra_corner(tree):
    d = tree / "sim" / KABAND / "corners" / KABAND_ID
    (d / "hbt_bcs_27c_2.50v.log.gz").unlink()
    (d / "hbt_typ_300c_2.50v.log.gz").write_bytes(gzip.compress(b"x"))
    assert_fails(tree, "missing declared corner identity 'hbt_bcs_27c_2.50v'",
                 "unexpected corner identity 'hbt_typ_300c_2.50v'")


def test_kaband_missing_snapshot_dir(tree):
    shutil.rmtree(tree / "sim" / KABAND / "netlist-snapshots" / KABAND_ID)
    assert_fails(tree, "missing netlist snapshot directory")


def test_kaband_missing_snapshot_file(tree):
    (tree / "sim" / KABAND / "netlist-snapshots" / KABAND_ID / "request_2.50v.json").unlink()
    assert_fails(tree, "missing snapshot file request_2.50v.json")


def test_kaband_snapshot_not_json(tree):
    p = tree / "sim" / KABAND / "netlist-snapshots" / KABAND_ID / "klt-report_2.25v.json"
    p.unlink()
    p.write_text("{not json")
    assert_fails(tree, "klt-report_2.25v.json", "not valid JSON")


def test_kaband_missing_companion(tree):
    (tree / "sim" / KABAND / "records" / f"{KABAND_ID}-cells.csv").unlink()
    assert_fails(tree, "missing companion file", f"{KABAND_ID}-cells.csv")


def test_kaband_companion_missing_identity(tree):
    p = tree / "sim" / KABAND / "records" / f"{KABAND_ID}-best.csv"
    lines = p.read_text().splitlines()
    p.unlink()
    p.write_text("\n".join(l for l in lines if not l.startswith("hbt_wcs_125c_2.75v,")) + "\n")
    assert_fails(tree, f"{KABAND_ID}-best.csv", "missing declared corner identity 'hbt_wcs_125c_2.75v'")


def test_kaband_unlisted_companion(tree):
    (tree / "sim" / KABAND / "records" / f"{KABAND_ID}-extra.csv").write_text("a\n1\n")
    assert_fails(tree, "not listed in its record's '## Sidecars'")


def test_kaband_supersedes_must_exist(tree):
    md = own(tree / "sim" / KABAND / "records" / "20261009-095725-dbf8179.md")
    md.write_text(md.read_text().replace("**Supersedes**: 20261009-095220-7f35db5", "**Supersedes**: 20200101-000000-0000000"))
    assert_fails(tree, "Supersedes names record '20200101-000000-0000000'")


def test_cli_exit_codes(tree, capsys):
    assert chk.main(["--root", str(tree), "--skip-history"]) == 0
    (tree / "sim" / NATIVE / "netlist-snapshots" / f"{NATIVE_ID}.spice").unlink()
    assert chk.main(["--root", str(tree), "--skip-history"]) == 1
    assert "ERROR" in capsys.readouterr().err


# ---------------------------------------------------------------- history


def run(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def commit(cwd, msg="c"):
    run(cwd, "git", "add", "-A")
    run(cwd, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


@pytest.fixture(scope="module")
def upstream(tmp_path_factory):
    """A real-content repo with branch 'trunk' holding all committed evidence."""
    root = tmp_path_factory.mktemp("upstream")
    shutil.copytree(REPO / "sim", root / "sim", symlinks=False,
                    ignore=shutil.ignore_patterns("harness", "_build", "_selftest", "__pycache__"))
    run(root, "git", "init", "-q", "-b", "trunk")
    commit(root, "base")
    return root


@pytest.fixture
def pr(upstream, tmp_path):
    """A clone on a feature branch; 'origin/trunk' is the PR base."""
    dst = tmp_path / "pr"
    run(tmp_path, "git", "clone", "-q", "--local", str(upstream), str(dst))
    run(dst, "git", "checkout", "-q", "-b", "feature")
    return dst


def history(root, base="origin/trunk", require=True):
    return chk.check_append_only(root, base, require)[0].items


def clone_record(exp: Path, old: str, new: str):
    """Append a complete, self-consistent copy of a record under a new id."""
    for p in sorted(exp.rglob("*")):
        if p.is_file() and old in str(p.relative_to(exp)) and not p.name.endswith(".pyc"):
            dest = exp / str(p.relative_to(exp)).replace(old, new)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if p.suffix == ".md" or (p.suffix == ".spice" and p.parent.name == "netlist-snapshots"):
                dest.write_text(p.read_text().replace(old, new))
            else:
                shutil.copyfile(p, dest)


def test_history_clean_branch_passes(pr):
    assert history(pr) == []


def test_history_multicommit_pr_modifying_old_record_fails(pr):
    rec = pr / "sim" / NATIVE / "records" / f"{NATIVE_ID}.md"
    rec.write_text(rec.read_text() + "\nedited after the fact\n")
    commit(pr, "tamper")
    (pr / "sim" / NATIVE / "NOTES.txt").write_text("unrelated")
    commit(pr, "later innocent commit")  # the last commit alone looks clean
    assert any(f"{NATIVE_ID}.md" in p and "modified" in p for p in history(pr))
    # Comparing only the last commit (the wrong base) would have missed it:
    assert history(pr, base="HEAD~1") == []


def test_history_deleting_corner_log_fails(pr):
    (pr / "sim" / NATIVE / "corners" / NATIVE_ID / "hbt_typ_27c_2.50v.log").unlink()
    commit(pr)
    assert any("hbt_typ_27c_2.50v.log" in p and "deleted" in p for p in history(pr))


def test_history_renaming_record_fails(pr):
    run(pr, "git", "mv", f"sim/{NATIVE}/records/{NATIVE_ID}.md", f"sim/{NATIVE}/records/{NATIVE_ID}-renamed.md")
    commit(pr)
    assert any(f"{NATIVE_ID}.md" in p and "deleted or renamed" in p for p in history(pr))


def test_history_modifying_kaband_sidecar_fails(pr):
    side = pr / "sim" / KABAND / "records" / f"{KABAND_ID}-points.csv.gz"
    side.write_bytes(gzip.compress(b"corner_id\nx\n"))
    commit(pr)
    assert any(f"{KABAND_ID}-points.csv.gz" in p and "modified" in p for p in history(pr))


def test_history_modifying_snapshot_fails(pr):
    snap = pr / "sim" / KABAND / "netlist-snapshots" / KABAND_ID / "body_2.50v.spice"
    snap.write_text(snap.read_text() + "* edit\n")
    commit(pr)
    assert any("body_2.50v.spice" in p for p in history(pr))


def test_history_adding_file_to_committed_record_fails(pr):
    (pr / "sim" / NATIVE / "corners" / NATIVE_ID / "hbt_typ_85c_2.50v.log").write_text("late addition\n")
    commit(pr)
    assert any("adds a file to record" in p for p in history(pr))


def test_history_appending_complete_new_records_passes(pr):
    clone_record(pr / "sim" / NATIVE, NATIVE_ID, "20261010-000000-abcdef0")
    clone_record(pr / "sim" / KABAND, KABAND_ID, "20261010-000001-abcdef1")
    # independent testbench / harness-side change in a second commit
    commit(pr, "new records")
    (pr / "sim" / NATIVE / "testbench" / "extra-note.txt").write_text("independent change")
    commit(pr, "testbench change")
    assert history(pr) == []
    assert chk.check_format(pr).items == []


def test_history_new_record_then_tamper_fails(pr):
    clone_record(pr / "sim" / NATIVE, NATIVE_ID, "20261010-000000-abcdef0")
    commit(pr, "good new record")
    (pr / "sim" / NATIVE / "corners" / NATIVE_ID / "hbt_typ_27c_2.50v.log").write_text("rewritten\n")
    commit(pr, "tamper")
    assert any("hbt_typ_27c_2.50v.log" in p for p in history(pr))


def test_new_record_missing_a_piece_fails_format(pr):
    clone_record(pr / "sim" / KABAND, KABAND_ID, "20261010-000001-abcdef1")
    (pr / "sim" / KABAND / "corners" / "20261010-000001-abcdef1" / "hbt_typ_27c_2.50v.log.gz").unlink()
    assert any("missing declared corner identity" in p for p in chk.check_format(pr).items)


def test_no_base_is_skipped_loudly_or_fails_when_required(tmp_path):
    root = tmp_path / "lone"
    shutil.copytree(REPO / "sim" / NATIVE, root / "sim" / NATIVE)
    run(root, "git", "init", "-q", "-b", "scratch")
    commit(root, "only commit")
    problems, note = chk.check_append_only(root, "0" * 40, False)
    assert problems.items == [] and "SKIPPED" in note
    problems, _ = chk.check_append_only(root, "0" * 40, True)
    assert any("--require-base" in p for p in problems.items)
    assert chk.check_format(root).items == []  # the format half does not depend on history


# ---------------------------------------------------------------- row-coverage staleness


def coverage_problems(root: Path) -> list[str]:
    return chk.check_row_coverage(root).items


def test_rows_mentioned_patterns():
    assert chk.rows_mentioned("see Rows 2-5 and row 17; rows 8, 9 and 10") == {2, 3, 4, 5, 17, 8, 9, 10}
    assert chk.rows_mentioned("no mention, 17 alone") == set()


def test_coverage_current_tree_passes():
    assert coverage_problems(REPO) == []


def test_coverage_stale_latest_record_fails_and_fixed_passes(tree):
    man = tree / "spec" / "row-coverage.json"
    doc = json.loads(man.read_text())
    entry = next(e for e in doc["rows"] if e["row"] == 5)
    recs = sorted((REPO / "sim" / "lna-sparam-nf" / "records").glob("*.md"))
    entry["latest_record"] = f"sim/lna-sparam-nf/records/{recs[0].name}"
    man.write_text(json.dumps(doc))
    found = coverage_problems(tree)
    assert any("row 5" in p and "stale" in p and recs[-1].name in p for p in found), found
    entry["latest_record"] = f"sim/lna-sparam-nf/records/{recs[-1].name}"
    man.write_text(json.dumps(doc))
    assert coverage_problems(tree) == []
