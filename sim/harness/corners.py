"""Process / voltage / temperature corner definitions and PVT grid mechanics.

GENERIC CORE:

- The classic five-corner MOS process sweep (``tt``, ``ff``, ``ss``, ``fs``,
  ``sf``) most open PDKs ship a ``.lib`` section for, registered below as the
  default ``CORNER_SETS["mos"]``. ``CORNER_SETS["tt"]`` is the reduced,
  single-corner smoke-test set (not a valid evidence matrix on its own).
- :class:`Corner`, :class:`PvtPoint`, :func:`build_grid`, :func:`supply_points`,
  :func:`resolve_corners` -- the PVT-grid arithmetic itself (a corner ×
  temperature × supply full factorial, in a stable order).
- :func:`sabotage` -- the harness's negative control: forces every corner's
  sections to typical so a corner-runner self-test can prove that switching
  corners actually changes what gets simulated, rather than silently
  simulating typical everywhere no matter what was asked for.

EXTENSION POINT -- corner sections don't generalize across PDKs (a PDK's
``.lib`` section names for "fast", "slow", or a device family other than MOS
are PDK-specific), and *which* additional corners matter is block-specific
(a SAR ADC cares about CDAC capacitor corners; a bandgap cares about
resistor and BJT corners; plenty of blocks need only the five MOS corners
as-is). Two ways to extend:

1. Edit the ``sections`` tuple on the built-in :data:`CORNERS` entries if
   this PDK's model library uses different section names than the
   ``tt``/``ff``/``ss``/``fs``/``sf`` default (most open PDKs use exactly
   these names; if not, this is the one edit new to this PDK).
2. Call :func:`register_corner` (and optionally :func:`register_corner_set`)
   to add block-specific corners on top -- see
   ``gf180-sar-adc/sim/harness/corners.py`` for a worked example that adds
   MiM/MOS-cap-dominated corners for a CDAC-heavy block.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

# Default PVT axes. A block's own CLAUDE.md / spec should state its PVT
# requirement explicitly; these are reasonable open-PDK defaults to start
# from, not a substitute for that statement.
DEFAULT_TEMPERATURES_C: tuple[float, ...] = (-40.0, 27.0, 125.0)
DEFAULT_SUPPLY_TOLERANCE: float = 0.10  # +/-10 %
DEFAULT_NOMINAL_SUPPLY_V: float = 1.2   # SG13G2 LV rail; the HBT RF bias rail is a spec-ratification decision

#: Device families in the order their ``.lib`` sections are included in the
#: generated deck (see runner.compose_deck). The generic core sweeps only
#: "mos" by default; a block adds families (and per-corner sections for them)
#: as it needs them.
FAMILIES: tuple[str, ...] = ("mos",)


@dataclass(frozen=True)
class Corner:
    """A named process corner: an ordered list of model ``.lib`` sections,
    one per entry in :data:`FAMILIES`."""

    name: str
    sections: tuple[str, ...]
    description: str = ""


#: The classic five MOS corners. Section names match FAMILIES = ("mos",);
#: most open PDKs use exactly these strings as their `.lib` section names --
#: if this PDK's model library uses different ones, edit the tuples below
#: rather than the surrounding mechanics.
CORNERS: dict[str, Corner] = {
    "tt": Corner("tt", ("tt",), "typical NMOS / typical PMOS"),
    "ff": Corner("ff", ("ff",), "fast NMOS / fast PMOS"),
    "ss": Corner("ss", ("ss",), "slow NMOS / slow PMOS"),
    "fs": Corner("fs", ("fs",), "fast NMOS / slow PMOS"),
    "sf": Corner("sf", ("sf",), "slow NMOS / fast PMOS"),
}

CORNER_SETS: dict[str, tuple[str, ...]] = {
    # Minimum bar for a quick smoke run. Not a valid evidence matrix on its own.
    "tt": ("tt",),
    # The five classic MOS corners -- the default.
    "mos": ("tt", "ff", "ss", "fs", "sf"),
}
DEFAULT_CORNER_SET = "mos"


def register_corner(
    name: str, sections: tuple[str, ...], description: str = "", *, sets: tuple[str, ...] = ()
) -> None:
    """Extension point: add a block-specific corner (and optionally the
    corner set(s) it belongs to) on top of the generic core.

    ``sections`` must have one entry per :data:`FAMILIES` in order -- add to
    ``FAMILIES`` first if this corner needs a device family the core does not
    already sweep (e.g. a capacitor or resistor family).
    """
    if len(sections) != len(FAMILIES):
        raise ValueError(
            f"corner {name!r}: {len(sections)} section(s) given, "
            f"expected one per family {FAMILIES!r}"
        )
    CORNERS[name] = Corner(name=name, sections=sections, description=description)
    for set_name in sets:
        CORNER_SETS[set_name] = CORNER_SETS.get(set_name, ()) + (name,)


def register_corner_set(name: str, corner_names: tuple[str, ...]) -> None:
    """Extension point: name a group of (already-registered) corners."""
    unknown = [c for c in corner_names if c not in CORNERS]
    if unknown:
        raise KeyError(f"corner set {name!r} references unknown corner(s): {unknown}")
    CORNER_SETS[name] = tuple(corner_names)


def resolve_corners(names: list[str] | tuple[str, ...] | None) -> list[Corner]:
    """Turn a list of corner *or* corner-set names into Corner objects."""
    if not names:
        names = [DEFAULT_CORNER_SET]
    resolved: list[Corner] = []
    seen: set[str] = set()
    for name in names:
        expanded = CORNER_SETS.get(name, (name,))
        for corner_name in expanded:
            if corner_name in seen:
                continue
            if corner_name not in CORNERS:
                raise KeyError(
                    f"unknown corner {corner_name!r}; "
                    f"known corners: {', '.join(sorted(CORNERS))}; "
                    f"known sets: {', '.join(sorted(CORNER_SETS))}"
                )
            seen.add(corner_name)
            resolved.append(CORNERS[corner_name])
    return resolved


def sabotage(corner_list: list[Corner]) -> list[Corner]:
    """Return the same corner *names* with every section forced to typical.

    This is the harness's negative control, not a feature: it reproduces the
    exact silent failure mode a corner sweep is most exposed to -- a runner
    that appears to sweep process corners but actually simulates typical
    everywhere (wrong model include, ignored parameter, wrong section name).
    A self-test should run once normally and once sabotaged; the sabotaged
    run's per-axis sensitivity checks (see report.axis_sensitivity) MUST
    fail. If they pass, corner switching is not taking effect and every
    downstream evidence record is worthless. Force ``--no-write`` whenever
    this is used -- a sabotaged run must never enter the evidence tree.

    ``typical`` is taken from ``corner_list[0]`` rather than the hardcoded
    global ``CORNERS["tt"]`` -- the built-in five-MOS-corner set happens to
    list "tt" first, so this is behavior-preserving for every existing MOS
    caller, but it also makes ``sabotage()`` work for a block-registered
    corner set whose "typical" entry has a different name (this repo's own
    ``CORNER_SETS["hbt"]`` lists ``hbt_typ`` first, by the same "typical
    goes first" convention -- see the SG13G2 HBT extension below). An empty
    ``corner_list`` has nothing to sabotage to and is returned unchanged.
    """
    if not corner_list:
        return []
    typical = corner_list[0].sections
    return [
        Corner(name=corner.name, sections=typical, description=f"SABOTAGED ({corner.description})")
        for corner in corner_list
    ]


def supply_points(
    nominal_v: float = DEFAULT_NOMINAL_SUPPLY_V,
    tolerance: float = DEFAULT_SUPPLY_TOLERANCE,
) -> list[float]:
    """Nominal supply and its +/- tolerance rails, low to high."""
    if tolerance <= 0:
        return [round(nominal_v, 6)]
    return [
        round(nominal_v * (1.0 - tolerance), 6),
        round(nominal_v, 6),
        round(nominal_v * (1.0 + tolerance), 6),
    ]


@dataclass(frozen=True)
class PvtPoint:
    """One point in the PVT grid -- exactly one ngspice invocation."""

    corner: Corner
    temp_c: float
    vdd: float
    index: int = field(default=0, compare=False)

    @property
    def corner_id(self) -> str:
        """``<process>_<temp>c_<supply>v`` -- the per-corner log/evidence id."""
        return f"{self.corner.name}_{self.temp_c:g}c_{self.vdd:.2f}v"

    def as_dict(self) -> dict:
        return {
            "corner": self.corner.name,
            "corner_sections": list(self.corner.sections),
            "temp_c": self.temp_c,
            "vdd": self.vdd,
            "corner_id": self.corner_id,
        }


def build_grid(
    corners: list[Corner],
    temperatures: list[float] | tuple[float, ...],
    supplies: list[float],
) -> list[PvtPoint]:
    """Full factorial P x V x T grid, in a stable, reproducible order."""
    return [
        PvtPoint(corner=corner, temp_c=float(temp), vdd=float(vdd), index=i)
        for i, (corner, temp, vdd) in enumerate(
            itertools.product(corners, temperatures, supplies)
        )
    ]


# ---------------------------------------------------------------------------
# SG13G2 block extension: HBT (bipolar) process corners.
#
# This is an EXTENSION, not an edit to the generic core above -- per this
# module's own docstring, a block calls register_corner()/register_corner_set()
# to add corners the generic five-MOS-corner default does not cover, rather
# than editing CORNERS/CORNER_SETS in place. This repo's first two benches
# (sim/lna-sparam-nf, sim/mixer-conversion-iip3) instantiate npn13G2 only --
# no MOS device appears anywhere in either testbench fragment -- so the
# built-in "mos"/"tt"/"ff"/"ss"/"fs"/"sf" corner set (which references .lib
# sections that do not exist in this repo's model_lib, cornerHBT.lib) is
# simply unused, not removed; a future bench that does instantiate
# sg13_lv_mos/sg13_hv_mos can still reach for it unmodified.
#
# sim/pdk.json's model_lib is libs.tech/ngspice/models/cornerHBT.lib. Reading
# that file against the installed PDK (confirmed 2026-09-12, IHP-Open-PDK
# v0.3.0 per sim/pdk.json) shows exactly three non-mismatch .LIB sections:
#
#     hbt_typ   -- typical (all vbic_*/sgp_mpa_* corner multipliers = 1.0)
#     hbt_bcs   -- best-case-speed  (vbic_tf=0.89, i.e. faster/less-delay
#                  transit-time corner -- higher fT/beta)
#     hbt_wcs   -- worst-case-speed (vbic_tf=1.11 -- slower transit time,
#                  lower fT/beta)
#
# (cornerHBT.lib also ships hbt_typ_mismatch/hbt_bcs_mismatch/
# hbt_wcs_mismatch/hbt_typ_stat sections for per-instance local-mismatch and
# statistical-variation studies; neither bench here needs those yet -- see
# sim/README.md if a future Monte-Carlo bench needs them.)
#
# FAMILIES stays ("mos",) unchanged: it is only an arity label for
# register_corner()'s "one section per family" check, not a claim about which
# device this repo actually sweeps. Renaming it to "hbt" would only cause an
# unnecessary merge conflict with a future MOS-family addition; the label is
# never surfaced in an evidence record (report.py records section names and
# descriptions, not the FAMILIES tuple itself).
register_corner("hbt_typ", ("hbt_typ",), "typical HBT (VBIC Rev.1.15, cornerHBT.lib)")
register_corner(
    "hbt_bcs", ("hbt_bcs",),
    "best-case-speed HBT (vbic_tf=0.89 -- faster transit time, higher fT/beta)",
)
register_corner(
    "hbt_wcs", ("hbt_wcs",),
    "worst-case-speed HBT (vbic_tf=1.11 -- slower transit time, lower fT/beta)",
)
register_corner_set("hbt", ("hbt_typ", "hbt_bcs", "hbt_wcs"))
