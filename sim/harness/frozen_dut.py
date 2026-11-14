"""Locate a study's frozen DUT netlist by its declared sha256.

A recorded study freezes one netlist: it pins the file's sha256 in its own
declaration and copies the bytes into every record's snapshot directory. Each
such study then read the *live* `design/netlist/lna_stage1.spice` back, which
was the same file -- true only for as long as the design never moved.

Issue #79 is where it moves: the study chose a core change, so the change
lands in `design/lna_stage1.sch` and the live netlist stops being the deck the
earlier records were taken on. From then on a study must read its OWN pinned
deck, or it would silently re-point a recorded campaign at a different
circuit.

:func:`resolve` does that, and only that: it returns the file whose bytes hash
to the declared value, preferring the live design netlist (so nothing changes
while the design still carries that deck) and falling back to the study's own
record snapshots. The pin is never relaxed, only located -- when nothing
matches, the declared design path comes back unchanged so the study's own
input check reports the mismatch, naming the declared path.

A campaign of the *new* core is a new declaration and a new record, never an
edit to the frozen one.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_bytes(path: Path) -> str | None:
    """The file's sha256, or ``None`` when it cannot be read."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


#: Snapshot files larger than this are not candidates (a frozen netlist,
#: fixture or manifest is text of a few kB; this only bounds the scan).
MAX_CANDIDATE_BYTES = 2 << 20


def _candidates(declared: Path, snapshots: Path):
    """The declared path first, then every plausible frozen copy of it.

    Same-basename snapshot copies come first (the common case, and cheap);
    then any other snapshot file, because a study may freeze a reference
    under a name of its own (`lna-headroom` freezes
    `sim/lna-sparam-nf/testbench/lna_stage1.spice` as `sparam_fixture.spice`).
    Record ids sort chronologically, so the oldest matching copy wins and the
    answer does not drift as later records are appended.
    """
    yield declared
    same_name = sorted(snapshots.glob(f"*/{declared.name}"))
    yield from same_name
    seen = set(same_name)
    for path in sorted(snapshots.glob("*/*")):
        if path in seen or not path.is_file():
            continue
        try:
            if path.stat().st_size > MAX_CANDIDATE_BYTES:
                continue
        except OSError:
            continue
        yield path


def resolve(declared: Path, declared_sha256: str | None, snapshots: Path) -> Path:
    """The declared file: *declared* if it still matches, else the matching
    frozen copy under *snapshots*, else *declared* unchanged.

    Returning *declared* when nothing matches is deliberate: the study's own
    input check then reports the mismatch, naming the path the declaration
    names, instead of this resolver failing somewhere less legible.
    """
    if not declared_sha256:
        return declared
    for path in _candidates(declared, snapshots):
        if sha256_bytes(path) == declared_sha256:
            return path
    return declared
