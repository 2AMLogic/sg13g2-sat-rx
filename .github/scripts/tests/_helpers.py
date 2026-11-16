"""Helpers shared by the evidence-checker self-tests (not collected by pytest)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

# Self-sufficient: a test file imported alone must not depend on another test
# module having put the scripts dir on sys.path first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_evidence_formats as chk  # noqa: E402


def run(cwd, *args):
    try:
        return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as e:
        # CalledProcessError's message omits the captured output; surface it so a
        # CI-only failure (e.g. a fixture `git clone` exiting 128) names its cause.
        raise RuntimeError(
            f"{list(args)} failed in {cwd} (exit {e.returncode})\n"
            f"stdout:\n{e.stdout}\nstderr:\n{e.stderr}"
        ) from e


def mirror_manifests(root: Path, repo: Path) -> None:
    """Copy the committed ``manifests/`` tree into a fixture repo.

    A stored-evidence record under ``sim/`` (issue #226) names
    ``manifests/artifacts/<bench>-<id>.manifest.json``; the checker refuses the
    record when that manifest is missing, so any fixture that copies a bench
    with stored-form records must mirror the committed manifests too.
    """
    if (repo / "manifests" / "artifacts").is_dir():
        shutil.copytree(repo / "manifests", Path(root) / "manifests")


def mirror_signoff(root: Path, repo: Path) -> None:
    """Copy the committed item-1 block-coverage attestation into a fixture tree.

    The format half runs the block-coverage check (issue #170) on every tree
    it validates: without the committed ``signoff/block-coverage.json`` the
    check refuses with "missing block_coverage". ``design/`` is absent in
    fixtures, so the committed ``no_design_source`` mixer claim stays honest.
    """
    root = Path(root)
    (root / "signoff").mkdir(exist_ok=True)
    shutil.copyfile(repo / "signoff" / "block-coverage.json", root / "signoff" / "block-coverage.json")


def commit(cwd, msg="c"):
    run(cwd, "git", "add", "-A")
    run(cwd, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


def edit_json(path: Path, fn) -> None:
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data, indent=2) + "\n")


class CheckerCase(unittest.TestCase):
    """problems()/assertFails() over chk.check_format(self.root)."""

    def problems(self) -> list[str]:
        return chk.check_format(self.root).items

    def assertFails(self, *needles: str):
        found = self.problems()
        self.assertTrue(found, "checker passed a deliberately broken tree")
        for needle in needles:
            self.assertTrue(any(needle in p for p in found),
                            f"no problem mentioning {needle!r} in:\n" + "\n".join(found))
