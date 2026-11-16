"""Unit fence for the lna_stage1 guard-ring containment predicate (#278).

These run in CI (the evidence-formats job collects `.github/scripts/tests`)
with no PDK, no klayout and no simulator: `layout/lna_stage1/containment.py`
is deliberately importable without `klayout.db` so this file can reach it
(`generate.py` itself is not importable in CI -- it exits at import when the
`klayout` module is absent).

The predicate keeps a bus that escaped the guard ring from passing the
generator silently. The pre-#278 code scanned Metal1/Metal2 recursively and
asserted only that some *inside* subset existed, so an escaped bus was
filtered out by the scan's own geometric test rather than flagged -- the
sabotaged build (a device group shifted 400 um east) succeeded. These tests
pin the replacement's contract: any single named box past any single edge is
reported by name, sub-micron escapes are caught, a box touching the boundary
is inside, and an empty bus set raises rather than vacuously passing.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "layout" / "lna_stage1"))

from containment import boxes_outside  # noqa: E402  (path set above)

#: The generator's guard-ring inner clearance region (``RING_INNER``), um.
INNER = (-6.0, -7.0, 72.0, 52.0)


def all_inside_boxes():
    """A realistic all-inside bus set: the 13 boxes the generator draws."""
    return [
        ("Xq1.C (c1)", (-1.5, 1.05, 57.5, 3.5)),
        ("Xq1.B (b1)", (-1.5, -3.5, 57.5, -1.06)),
        ("Xq1.E (e1)", (-1.5, -0.8, 57.5, 0.79)),
        ("Xq2.C (oc)", (-1.5, 21.05, 57.5, 23.5)),
        ("Xq2.B (b2)", (-1.5, 16.5, 57.5, 18.94)),
        ("Xq2.E (c1)", (-1.5, 19.2, 57.5, 20.79)),
        ("Xqr.C (nr)", (-1.5, 41.05, 8.5, 43.5)),
        ("Xqr.B (br)", (-1.5, 36.5, 8.5, 38.94)),
        ("Xqr.E (er)", (-1.5, 39.2, 8.5, 40.79)),
        ("c1 cascode Metal1 collector extension", (56.0, 1.05, 68.0, 3.5)),
        ("c1 cascode Metal2 strap", (65.5, 1.05, 67.5, 20.79)),
        ("c1 emitter-bar bridge Metal2", (56.4, 19.2, 67.5, 20.79)),
        ("vdd supply rail", (-1.5, 47.0, 68.0, 49.0)),
    ]


class AllInsidePasses(unittest.TestCase):
    def test_every_bus_inside_reports_no_offenders(self):
        self.assertEqual(boxes_outside(all_inside_boxes(), INNER), [])

    def test_a_box_touching_the_boundary_is_inside(self):
        exact = (INNER[0], INNER[1], INNER[2], INNER[3])
        self.assertEqual(boxes_outside([("exact", exact)], INNER), [])


class SingleEscapePastEachEdgeFails(unittest.TestCase):
    def test_one_box_past_each_edge_is_reported_by_name(self):
        escapes = [
            ("bus.past-west", (INNER[0] - 1.0, 0.0, 0.0, 1.0)),
            ("bus.past-south", (0.0, INNER[1] - 0.5, 1.0, 0.0)),
            ("bus.past-east", (72.5, 0.0, 73.5, 1.0)),
            ("bus.past-north", (0.0, 52.5, 1.0, 53.5)),
        ]
        for name, box in escapes:
            with self.subTest(escape=name):
                named = [("Xq1.C (c1)", (-1.5, 1.05, 57.5, 3.5)), (name, box)]
                escaped = boxes_outside(named, INNER)
                self.assertEqual(
                    [offender for offender, _ in escaped],
                    [name],
                    "the escaped bus must be named, not aggregated",
                )
                self.assertEqual(escaped[0][1], box)

    def test_sub_micron_past_any_edge_is_still_caught(self):
        # The stream's database unit is 1 nm, so a 1 nm escape is real
        # geometry, and a sub-nm one must not slip through the comparison
        # either.
        for eps in (0.001, 1e-6):
            with self.subTest(eps=eps):
                for name, box in (
                    ("bus.past-west", (INNER[0] - eps, 0.0, 0.0, 1.0)),
                    ("bus.past-south", (0.0, INNER[1] - eps, 1.0, 0.0)),
                    ("bus.past-east", (INNER[2] + eps, 0.0,
                                      INNER[2] + eps + 1.0, 1.0)),
                    ("bus.past-north", (0.0, INNER[3] + eps, 1.0,
                                        INNER[3] + eps + 1.0)),
                ):
                    escaped = boxes_outside([(name, box)], INNER)
                    self.assertEqual(
                        [offender for offender, _ in escaped], [name]
                    )

    def test_every_offender_is_named_when_several_escape(self):
        escaped = boxes_outside(
            [
                ("bus.past-east", (80.0, 0.0, 81.0, 1.0)),
                ("bus.past-north", (0.0, 60.0, 1.0, 61.0)),
            ],
            INNER,
        )
        self.assertEqual(
            [offender for offender, _ in escaped],
            ["bus.past-east", "bus.past-north"],
        )


class EmptyBusSetIsNotVacuous(unittest.TestCase):
    def test_no_collected_boxes_raises_rather_than_passing(self):
        # "Nothing outside" is only meaningful if there was something to
        # check: an empty bus set must raise so a collection regression
        # upstream cannot silence the whole check.
        with self.assertRaises(ValueError):
            boxes_outside([], INNER)


if __name__ == "__main__":
    unittest.main()
