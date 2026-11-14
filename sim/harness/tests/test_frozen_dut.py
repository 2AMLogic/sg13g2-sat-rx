"""Locating a study's frozen DUT by its declared sha256 (issue #79)."""

from __future__ import annotations

import hashlib

from harness import frozen_dut as fd

FROZEN = b"* the deck the records were taken on\nRbias nr b1 2k m=1\n"
MOVED = b"* the design moved on\nRbias nr b1 10k m=1\n"
SHA = hashlib.sha256(FROZEN).hexdigest()


def _tree(tmp_path, design: bytes, snapshots: dict):
    live = tmp_path / "design" / "netlist" / "lna_stage1.spice"
    live.parent.mkdir(parents=True)
    live.write_bytes(design)
    snaps = tmp_path / "netlist-snapshots"
    for rid, files in snapshots.items():
        (snaps / rid).mkdir(parents=True)
        for name, data in files.items():
            (snaps / rid / name).write_bytes(data)
    return live, snaps


def test_the_live_file_wins_while_it_still_matches(tmp_path):
    live, snaps = _tree(tmp_path, FROZEN, {"r1": {"lna_stage1.spice": FROZEN}})
    assert fd.resolve(live, SHA, snaps) == live


def test_a_same_named_snapshot_copy_is_used_once_the_design_moves(tmp_path):
    live, snaps = _tree(tmp_path, MOVED, {"r1": {"lna_stage1.spice": FROZEN}})
    assert fd.resolve(live, SHA, snaps) == snaps / "r1" / "lna_stage1.spice"


def test_a_snapshot_copy_under_another_name_is_found_too(tmp_path):
    """lna-headroom freezes the lna-sparam-nf fixture as sparam_fixture.spice."""
    live, snaps = _tree(tmp_path, MOVED, {"r1": {"sparam_fixture.spice": FROZEN}})
    assert fd.resolve(live, SHA, snaps) == snaps / "r1" / "sparam_fixture.spice"


def test_the_oldest_matching_record_wins_so_the_answer_does_not_drift(tmp_path):
    live, snaps = _tree(tmp_path, MOVED, {"20261031-b": {"lna_stage1.spice": FROZEN},
                                          "20261011-a": {"lna_stage1.spice": FROZEN}})
    assert fd.resolve(live, SHA, snaps) == snaps / "20261011-a" / "lna_stage1.spice"


def test_no_match_returns_the_declared_path_so_the_study_reports_it(tmp_path):
    live, snaps = _tree(tmp_path, MOVED, {"r1": {"lna_stage1.spice": b"something else\n"}})
    assert fd.resolve(live, SHA, snaps) == live
    assert fd.resolve(live, SHA, tmp_path / "no-snapshots-here") == live


def test_no_declared_hash_is_a_no_op(tmp_path):
    live, snaps = _tree(tmp_path, MOVED, {"r1": {"lna_stage1.spice": FROZEN}})
    assert fd.resolve(live, None, snaps) == live
    assert fd.resolve(live, "", snaps) == live


def test_an_oversized_snapshot_file_is_not_scanned(tmp_path, monkeypatch):
    live, snaps = _tree(tmp_path, MOVED, {"r1": {"big_fixture.spice": FROZEN}})
    monkeypatch.setattr(fd, "MAX_CANDIDATE_BYTES", len(FROZEN) - 1)
    assert fd.resolve(live, SHA, snaps) == live


def test_sha256_bytes_reports_an_unreadable_file_as_none(tmp_path):
    assert fd.sha256_bytes(tmp_path / "missing") is None
    assert fd.sha256_bytes(tmp_path) is None
