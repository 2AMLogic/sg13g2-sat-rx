#!/usr/bin/env python3
"""Guard-ring containment predicate for the lna_stage1 generator (issue #278).

Deliberately kdb-free: ``generate.py`` exits at import when the ``klayout``
module is absent, so a check living beside its ``kdb`` calls would be
unreachable from the pytest-only CI jobs. This module judges plain
``(left, bottom, right, top)`` micron tuples; the generator converts its
``DBox``es at the call site.

The judgement runs over *named* boxes collected by identity as the generator
drew them -- never over a layer scan. A recursive Metal1/Metal2 scan also sees
every PDK primitive's own geometry (the guard ring's 360 ptap pins and the
HBTs' internal shapes among them), so a scan cannot tell an escaped bus from
a shape that is legitimately outside the ring. Identity collection can, and
it is what lets a failure name the escaped bus instead of reporting an
aggregate.
"""

from __future__ import annotations

from collections.abc import Iterable

#: One axis-aligned rectangle in micron coordinates.
Box = tuple[float, float, float, float]


def boxes_outside(
    named_boxes: Iterable[tuple[str, Box]], inner: Box
) -> list[tuple[str, Box]]:
    """Return ``[(name, box), ...]`` for every named box not fully inside ``inner``.

    ``named_boxes`` is an iterable of ``(name, box)`` pairs; ``inner`` is the
    region every bus must lie inside, as ``(left, bottom, right, top)`` um.
    Touching the boundary counts as inside; anything past it on any edge is
    out -- the same sense the generator's pre-#278 filter encoded, now
    applied to flag rather than to discard.

    An empty ``named_boxes`` raises rather than vacuously passing: "nothing
    outside" is only a pass if there was bus geometry to check, so a
    collection regression upstream must not silence the whole check.
    """
    named = list(named_boxes)
    if not named:
        raise ValueError(
            "no bus boxes were collected to check against the guard ring -- "
            "containment cannot pass on nothing"
        )
    il, ib, ir, it = inner
    return [
        (name, box)
        for name, box in named
        if box[0] < il or box[1] < ib or box[2] > ir or box[3] > it
    ]
