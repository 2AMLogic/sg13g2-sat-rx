#!/usr/bin/env python3
"""Shared klt toolchain-pin check for every ``layout/`` runner (issue #198).

``layout/toolchain.json``'s own comment block asks for exactly this: "Keep ONE
shared implementation (conventionally ``layout/toolchain_pin.py``) that every
DRC/LVS/extraction runner imports, rather than re-deriving this check per
runner -- otherwise the runners can drift apart on what they check." Until this
file existed there was no such implementation: ``layout/probe-readiness/
generate_probe.py`` does not consult ``klt_required_commands`` at all, so the
2026-10-12 paragraph's claim that it "is, for now, the one runner that checks
this list" described an intent rather than code. This module is the
implementation; the stale claim is corrected by a new append-only paragraph in
``layout/toolchain.json`` rather than by editing that one.

What it checks, and why each is a *loud* failure rather than a skipped check:

``require_commands()``
    every entry of ``klt_required_commands`` appears in ``klt --help``'s
    subcommand list. A missing command means the runner's evidence would be
    silently narrower than the pin promises.

``require_pdk_cells()``
    every PDK primitive cell a generator is about to instance exists in the
    stream it reads them from. A missing cell means the generator would emit a
    layout with a device quietly absent.

``resolve_pr_gds()``
    the pinned PDK's primitive GDS is present at all.

Standard library only, so a runner can import it before any third-party
package is known to be installed. Nothing here runs ``klt``'s *checks* -- it
only establishes that the pinned tool and PDK are the ones in front of us.

Usage from a runner::

    from toolchain_pin import load_pin, require_commands, resolve_pr_gds

    pin = load_pin()
    require_commands(pin, ("drc", "erc"), klt="/path/to/klt")

Usage as a CLI (the ``--check`` convention every runner also exposes)::

    python3 layout/toolchain_pin.py --check --klt /path/to/klt
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

#: Repository-relative location of the pin document this module reads.
TOOLCHAIN_JSON = "layout/toolchain.json"

#: PDK-install-relative location of the primitive GDS the generators instance
#: their devices from. Kept here rather than in each generator so a PDK
#: re-layout moves one string.
PR_GDS_RELPATH = "libs.ref/sg13g2_pr/gds/sg13g2_pr.gds"

#: Search order for the PDK install root, after $PDK_ROOT/$PDK_PATH. These are
#: the roots this repo's own simulation harness already resolves against.
PDK_ROOT_CANDIDATES = (
    "~/share/pdk",
    "/usr/share/pdk",
)

#: Install subtree inside a PDK root (``sim/pdk-artifact.json``'s
#: ``install_subtree``).
PDK_SUBTREE = "ihp-sg13g2"


class ToolchainError(Exception):
    """A pinned tool, command or PDK input is missing or wrong.

    Runners turn this into a clean stderr message plus a non-zero exit, never
    a traceback and never a silently-skipped check.
    """


def repo_root(start: str | None = None) -> str:
    """The repository root, found by walking up from ``start`` to the nearest
    directory holding ``layout/toolchain.json``.

    Deliberately not ``git rev-parse``: a runner must work in an exported
    source tree with no ``.git`` (the same reason ``klt signoff`` grew
    ``--repo-root``), and the pin document is the thing we actually need.
    """
    here = os.path.abspath(start or os.path.dirname(os.path.abspath(__file__)))
    while True:
        if os.path.isfile(os.path.join(here, TOOLCHAIN_JSON)):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            raise ToolchainError(
                f"could not find {TOOLCHAIN_JSON} in any ancestor of "
                f"{os.path.abspath(start or __file__)}"
            )
        here = parent


def load_pin(root: str | None = None) -> dict:
    """Parse ``layout/toolchain.json`` and return it.

    Raises :class:`ToolchainError` when a field every runner depends on is
    absent, rather than letting a ``KeyError`` surface later from inside a
    generator.
    """
    root = root or repo_root()
    path = os.path.join(root, TOOLCHAIN_JSON)
    try:
        with open(path, encoding="utf-8") as handle:
            pin = json.load(handle)
    except OSError as exc:
        raise ToolchainError(f"cannot read {TOOLCHAIN_JSON}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ToolchainError(f"{TOOLCHAIN_JSON} is not valid JSON: {exc}") from exc

    for field in ("klt_install", "klt_required_commands"):
        if field not in pin:
            raise ToolchainError(f"{TOOLCHAIN_JSON} is missing {field!r}")
    if not isinstance(pin["klt_required_commands"], list):
        raise ToolchainError(
            f"{TOOLCHAIN_JSON}: klt_required_commands must be a JSON array"
        )
    return pin


def klt_subcommands(klt: str) -> set[str]:
    """Every subcommand ``klt --help`` advertises for the install at ``klt``.

    Parsed out of the help text's subcommand block, which is the only
    machine-readable list a `klt` build exposes without running a verb.
    """
    try:
        proc = subprocess.run(
            [klt, "--help"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except OSError as exc:
        raise ToolchainError(f"cannot run {klt!r}: {exc}") from exc
    if proc.returncode != 0:
        raise ToolchainError(
            f"{klt} --help exited {proc.returncode}: {proc.stderr.strip()[:400]}"
        )

    found: set[str] = set()
    in_block = False
    for line in proc.stdout.splitlines():
        if line.startswith("positional arguments:"):
            in_block = True
            continue
        if in_block:
            if line.startswith("options:"):
                break
            stripped = line.strip()
            # Subcommand rows are indented further than the "<command>"
            # header and start with the verb; continuation lines of a long
            # description are indented further still and are skipped by
            # requiring the row to begin at the verb column.
            if not stripped or stripped.startswith("<"):
                continue
            indent = len(line) - len(line.lstrip())
            if indent == 4:
                found.add(stripped.split()[0])
    if not found:
        raise ToolchainError(
            f"could not parse any subcommand out of {klt} --help; refusing to "
            "report the pin as satisfied on an unparsed help text"
        )
    return found


def require_commands(
    pin: dict, extra: tuple[str, ...] = (), *, klt: str = "klt"
) -> list[str]:
    """Assert the install at ``klt`` has every pinned command, plus ``extra``.

    ``extra`` is for a runner that needs a verb the pin does not list yet --
    it is reported in the error message exactly like a pinned one, so the fix
    (add it to ``klt_required_commands``) is visible from the failure.

    Returns the sorted list of commands that were checked.
    """
    want = sorted(set(pin["klt_required_commands"]) | set(extra))
    have = klt_subcommands(klt)
    missing = [command for command in want if command not in have]
    if missing:
        raise ToolchainError(
            "the klt install at {klt!r} is missing required command(s): {missing}.\n"
            "  {relpath} pins klt_install = {install!r}.\n"
            "  Install that pin into a throwaway environment (never the host "
            "tool):\n"
            "    uv venv /tmp/klt-pin && uv pip install --python "
            "/tmp/klt-pin/bin/python {install!r}\n"
            "  then re-run with --klt /tmp/klt-pin/bin/klt.".format(
                klt=klt,
                missing=", ".join(missing),
                relpath=TOOLCHAIN_JSON,
                install=pin["klt_install"],
            )
        )
    return want


def pdk_root() -> str:
    """The resolved PDK install root (the directory *holding* ``ihp-sg13g2``).

    ``$PDK_ROOT`` wins, then ``$PDK_PATH``, then
    :data:`PDK_ROOT_CANDIDATES`. Raises :class:`ToolchainError` when none
    holds the pinned install subtree -- the "fail loudly if the pinned PDK is
    absent" half of the pin.
    """
    candidates = [
        value
        for value in (os.environ.get("PDK_ROOT"), os.environ.get("PDK_PATH"))
        if value
    ]
    candidates.extend(os.path.expanduser(path) for path in PDK_ROOT_CANDIDATES)
    for root in candidates:
        if os.path.isdir(os.path.join(root, PDK_SUBTREE)):
            return root
    raise ToolchainError(
        "the pinned PDK install was not found: no candidate root holds a "
        f"{PDK_SUBTREE!r} subtree (tried: {', '.join(candidates)}). Set "
        "$PDK_ROOT to the directory containing it."
    )


def pdk_install() -> str:
    """The resolved ``<pdk root>/ihp-sg13g2`` install directory."""
    return os.path.join(pdk_root(), PDK_SUBTREE)


def resolve_pr_gds(explicit: str | None = None) -> str:
    """Absolute path of the PDK primitive GDS, or raise.

    ``explicit`` (a runner's ``--pr-gds``) is honoured but still checked, so a
    typo fails here rather than as a missing-cell error later.
    """
    if explicit:
        if not os.path.isfile(explicit):
            raise ToolchainError(f"--pr-gds not found: {explicit}")
        return os.path.abspath(explicit)
    path = os.path.join(pdk_install(), PR_GDS_RELPATH)
    if not os.path.isfile(path):
        raise ToolchainError(
            f"the pinned PDK install has no {PR_GDS_RELPATH}; expected it at "
            f"{path}"
        )
    return path


def require_pdk_cells(layout, names) -> None:
    """Assert every cell in ``names`` exists in the already-read ``layout``.

    Takes a ``klayout.db.Layout`` rather than a path so a generator that has
    already read the stream does not read it twice. Named here, beside the
    command check, because "the pinned PDK is present but this primitive is
    not in it" is the same class of failure as a missing `klt` verb: the
    runner would otherwise emit a layout with a device silently absent.
    """
    missing = [name for name in names if layout.cell(name) is None]
    if missing:
        raise ToolchainError(
            "the pinned PDK's primitive stream does not contain required "
            f"cell(s): {', '.join(missing)}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="check this repo's klt toolchain pin against an install"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="run every check and report; exit 1 on the first failure",
    )
    parser.add_argument(
        "--klt", default="klt", help="klt executable to check (default: klt)"
    )
    parser.add_argument(
        "--extra",
        default="",
        help="comma-separated extra commands to require beyond the pin",
    )
    args = parser.parse_args(argv)

    try:
        pin = load_pin()
        extra = tuple(name for name in args.extra.split(",") if name)
        checked = require_commands(pin, extra, klt=args.klt)
        pr_gds = resolve_pr_gds()
    except ToolchainError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"klt_install:  {pin['klt_install']}")
    print(f"commands ok:  {', '.join(checked)}")
    # Printed relative to the PDK root so a pasted log carries no host path.
    print(f"pdk pr_gds:   <pdk>/{PDK_SUBTREE}/{PR_GDS_RELPATH}")
    print(f"pdk present:  {os.path.isfile(pr_gds)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
