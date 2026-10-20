"""Helpers shared by the evidence-checker self-tests (not collected by pytest)."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

import check_evidence_formats as chk


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
