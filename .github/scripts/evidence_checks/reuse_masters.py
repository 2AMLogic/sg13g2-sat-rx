"""evidence_checks.reuse_masters: declared-master pointer check for reuse.lock.json (issue #277).

New check, not a split of the former single-file checker. ``reuse.lock.json``
names, per shared mechanic, the file that is its declared master and the
top-level symbols defined there, so a sibling repo's stamped-copy pin can be
validated against a statement of ownership instead of a moving sha.

This is a pointer check, not a type checker: it fails when a declared master
path is missing or renamed away, or a declared symbol is not defined at top
level (``def``/``class``/assignment) in its master. It never requires
completeness — an undeclared mechanic is never an error — so a re-homing
consolidation goes red in the consolidating PR while the wave can land in any
order. It also refuses a module that is declared both as this repo's master
and as upstream-owned, the exact mis-pin the convention prevents.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .common import Problems

LOCK_PATH = "reuse.lock.json"

# Top-level definition: ``def name``, ``class name`` or an assignment
# ``name = ...`` / ``name: T = ...``. A ``from ... import X as Y`` line is a
# re-export, not a definition, and deliberately does not match.
DEF_RE = re.compile(
    r"^(?:def|class)\s+([A-Za-z_]\w*)\b"
    r"|^([A-Za-z_]\w*)\s*(?::[^=]+?)?=(?!=)"
)


def defined_symbols(path: Path) -> set[str]:
    """Top-level names defined in a Python file (def/class/assignment)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    names: set[str] = set()
    for line in text.splitlines():
        m = DEF_RE.match(line)
        if m:
            names.add(m.group(1) or m.group(2))
    return names


def check_reuse_masters(root: Path) -> Problems:
    problems = Problems()
    lock = root / LOCK_PATH
    if not lock.is_file():
        problems.add(LOCK_PATH, "missing; a consumer cannot validate its pins against a declaration")
        return problems
    try:
        doc = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.add(LOCK_PATH, f"unreadable JSON: {exc}")
        return problems
    if not isinstance(doc, dict):
        problems.add(LOCK_PATH, "top level must be a JSON object")
        return problems
    entries = doc.get("masters")
    if not isinstance(entries, list):
        problems.add(LOCK_PATH, "top level must be an object with a 'masters' list")
        return problems

    seen_ids: set[str] = set()
    declared: set[str] = set()
    for i, e in enumerate(entries):
        where = f"{LOCK_PATH}:masters[{i}]"
        if not isinstance(e, dict):
            problems.add(where, "is not an object")
            continue
        mech = e.get("mechanic")
        master = e.get("master")
        symbols = e.get("symbols")
        what = e.get("what")
        if not isinstance(mech, str) or not mech.strip():
            problems.add(where, "'mechanic' is missing or not a non-empty string")
        elif mech in seen_ids:
            problems.add(where, f"mechanic {mech!r} listed more than once")
        else:
            seen_ids.add(mech)
        if not isinstance(what, str) or not what.strip():
            problems.add(where, "'what' is missing or not a non-empty string")
        if not isinstance(master, str) or not master.strip():
            problems.add(where, "'master' is missing or not a path string")
            continue
        if not isinstance(symbols, list) or not symbols \
                or not all(isinstance(s, str) and s.strip() for s in symbols):
            problems.add(where, f"master {master!r}: 'symbols' must be a non-empty list of strings")
            symbols = None
        master_path = root / master
        if not master_path.is_file():
            problems.add(where, f"declared master {master!r} does not exist "
                         "(renamed or deleted? update this declaration in the same PR)")
            continue
        declared.add(master)
        if symbols is None:
            continue
        defined = defined_symbols(master_path)
        for s in symbols:
            if s not in defined:
                problems.add(where, f"declared symbol {s!r} is not defined at top level in master {master!r}")

    upstream = doc.get("upstream")
    if isinstance(upstream, dict):
        modules = upstream.get("modules")
        if isinstance(modules, list):
            for mod in modules:
                if not isinstance(mod, str):
                    problems.add(f"{LOCK_PATH}:upstream", "'modules' must be a list of path strings")
                    break
                if mod in declared:
                    problems.add(f"{LOCK_PATH}:upstream", f"module {mod!r} is both upstream-owned and "
                                 "declared as this repo's master — exactly the mis-pin this convention prevents")
    return problems
