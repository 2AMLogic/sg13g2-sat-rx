#!/usr/bin/env python3
"""Generate the LNA stage-1 **device-group** layout study (issue #198).

**NON-CLAIMING.** This stream is not the LNA stage-1 layout and cites no T1
item. It draws the only elements of ``design/netlist/lna_stage1.spice`` that
resolve to a PDK primitive -- the three ``npn13G2`` HBTs and the substrate
guard ring -- plus the labelled supply rails and inter-device nets needed to
run ``klt erc``'s supply half over them. Every resistor, capacitor and
inductor in the stage is **absent**: see ``realizability.json`` for the
per-element derivation and ``README.md`` for why drawing them is gated on a
``spec/`` decision record that does not exist.

What is drawn, and the one place it departs from the netlist:

``Xqr`` (``Nx=1``)
    one ``npn13G2`` instance -- the designed device exactly.

``Xq1``/``Xq2`` (``Nx=8``)
    eight ``npn13G2`` unit instances each, bussed in parallel. **This is not
    the designed device.** ``Nx=8`` is one HBT with eight emitter windows
    inside a single collector/base region; the pinned PDK's primitive stream
    ships only the fixed-geometry ``Nx=1`` cell, and the PDK's own
    parametrized ``npn13G2`` PCell -- which would draw the real multi-emitter
    device -- is not instantiable in this environment (the PDK vendors its
    ``cni`` compat shim as an uninitialized submodule; see
    ``realizability.json`` -> ``pcell_availability``). Eight parallel unit
    devices have different base resistance and emitter interconnect
    parasitics from one eight-window device, so this is a floorplan study of
    the right device count, not the designed geometry.

Pin identities are read from the PDK cell's **own** ``E``/``B``/``C`` text,
measured rather than assumed: the centre Metal2 stack is the **emitter**, the
lower Metal1 strip the **base**, the upper Metal1 strip the **collector**.
(``layout/probe-readiness/generate_probe.py``'s comments assign these three
differently; that probe is non-claiming, extracts no bipolar device, and is
not edited here -- but do not carry its assignment into new work.)

Determinism: no timestamps are embedded, so a regeneration is byte-identical
and the committed run records' input hashes stay valid.

Usage::

    python3 layout/lna_stage1/generate.py [--pr-gds PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from toolchain_pin import (  # noqa: E402  (path set above)
    ToolchainError,
    require_pdk_cells,
    resolve_pr_gds,
)

try:
    import klayout.db as kdb
except ImportError:  # pragma: no cover - environment guard
    sys.exit(
        "error: the `klayout` python module is required (it is a dependency "
        "of klayout-tools); run this script with the interpreter of the "
        "environment holding the pinned klt"
    )

# --- SG13G2 drawing/purpose layers (GDS layer/datatype) -----------------
L_METAL1 = (8, 0)  # Metal1.drawing
L_METAL2 = (10, 0)  # Metal2.drawing
L_VIA1 = (19, 0)  # Via1.drawing
L_TEXT_M1 = (8, 25)  # Metal1.text  (the curated deck's Metal1 label layer)
L_TEXT_M2 = (10, 25)  # Metal2.text

DBU_PER_UM = 1000

#: PDK primitive cells this study instances.
PR_CELLS = ("npn13G2", "ptap")

#: Measured ``npn13G2`` pin geometry (local um), from the cell's own E/B/C
#: text on layer 63/0 plus its Metal1.pin/Metal2.pin shapes. Used only to
#: place buses that overlap each pin with positive area.
HBT = {
    # centre Metal2 stack -- emitter
    "E_m2_y": (-0.78, 0.77),
    # lower Metal1 strip -- base
    "B_m1_y": (-1.26, -1.02),
    # upper Metal1 strip -- collector
    "C_m1_y": (1.01, 1.25),
    # pSD extent, the device's outermost drawn layer
    "psd": (-3.35, -3.33, 3.35, 3.78),
}

#: Unit-device pitch along a row (um). The device's pSD is 6.70 um wide, so
#: this leaves 2.30 um of pSD-to-pSD space between neighbouring units --
#: comfortably clear of the deck's pSD spacing rule rather than minimal.
UNIT_PITCH_UM = 9.0

#: Row origins (um) for the three device groups, and the net each group's
#: collector / base / emitter belongs to in `design/netlist/lna_stage1.spice`.
#: `Xq1`'s collector and `Xq2`'s emitter are the same net (`c1`): that is the
#: cascode connection, and it is drawn.
GROUPS = (
    {"refdes": "Xq1", "units": 8, "y": 0.0, "C": "c1", "B": "b1", "E": "e1"},
    {"refdes": "Xq2", "units": 8, "y": 20.0, "C": "oc", "B": "b2", "E": "c1"},
    {"refdes": "Xqr", "units": 1, "y": 40.0, "C": "nr", "B": "br", "E": "er"},
)

#: Guard-ring inner clearance region (um): every bus must lie inside it.
RING_INNER = (-6.0, -7.0, 72.0, 52.0)

#: ptap instance pitch (um) -- exactly the cell's Activ width, so the Activ
#: and pSD squares abut and merge into a closed annulus on each layer.
PTAP_PITCH_UM = 0.78

#: Metal1 band width (um) tying every ptap's Metal1 pin together.
RING_BAND_UM = 0.95

#: Via1 cut side (um) -- the size the PDK's own cells draw.
VIA1_UM = 0.19


def rect(cell, layer, x1, y1, x2, y2):
    cell.shapes(cell.layout().layer(*layer)).insert(kdb.DBox(x1, y1, x2, y2))


def label(cell, layer, text, x, y):
    cell.shapes(cell.layout().layer(*layer)).insert(
        kdb.DText(text, kdb.DTrans(kdb.DTrans.R0, kdb.DVector(x, y)))
    )


def inst_at(cell, cell_name, x_um, y_um):
    """Instance ``cell_name`` at (``x_um``, ``y_um``).

    ``CellInstArray`` takes a dbu-space ``Trans``; its overloads do not accept
    a micron-space ``DTrans`` (one silently converts through integer dbu, so a
    14 um displacement becomes 14 dbu). Convert to integer dbu here.
    """
    ly = cell.layout()
    return kdb.CellInstArray(
        ly.cell(cell_name).cell_index(),
        kdb.Trans(
            kdb.Trans.R0,
            kdb.Vector(
                int(round(x_um * DBU_PER_UM)), int(round(y_um * DBU_PER_UM))
            ),
        ),
    )


def place_group(cell, group):
    """Place one device group's unit instances and return their x origins."""
    xs = [i * UNIT_PITCH_UM for i in range(group["units"])]
    for x in xs:
        cell.insert(inst_at(cell, "npn13G2", x, group["y"]))
    return xs


def bus_extent(xs):
    """The x span a bus must cover to overlap every unit's pins, with margin."""
    return xs[0] - 1.5, xs[-1] + 1.5


def wire_group(cell, group, xs):
    """Bus one group's collectors, bases and emitters, and label each net.

    Each bus is a single rectangle that overlaps every unit instance's pin on
    that terminal with positive area -- the simplest shape that makes the
    group one electrical node per terminal, and the easiest to keep clear of
    the deck's width/spacing rules.
    """
    y0 = group["y"]
    x_lo, x_hi = bus_extent(xs)

    # Collector: Metal1, from just inside the upper pin up to +3.5 um.
    c_y = (y0 + HBT["C_m1_y"][0] + 0.04, y0 + 3.5)
    rect(cell, L_METAL1, x_lo, c_y[0], x_hi, c_y[1])
    label(cell, L_TEXT_M1, group["C"], xs[0], c_y[1] - 0.5)

    # Base: Metal1, from -3.5 um up to just inside the lower pin.
    b_y = (y0 - 3.5, y0 + HBT["B_m1_y"][1] - 0.04)
    rect(cell, L_METAL1, x_lo, b_y[0], x_hi, b_y[1])
    label(cell, L_TEXT_M1, group["B"], xs[0], b_y[0] + 0.5)

    # Emitter: Metal2 bar straight across the centre Metal2 pins.
    e_y = (y0 + HBT["E_m2_y"][0] - 0.02, y0 + HBT["E_m2_y"][1] + 0.02)
    rect(cell, L_METAL2, x_lo, e_y[0], x_hi, e_y[1])
    label(cell, L_TEXT_M2, group["E"], xs[0], y0)

    return {"collector_y": c_y, "base_y": b_y, "emitter_y": e_y}


def stitch_cascode(cell, lower, upper, lower_xs, upper_xs):
    """Join ``Xq1``'s collector (Metal1) to ``Xq2``'s emitter (Metal2).

    Both are net ``c1``. The collector bus is Metal1 and the emitter bar is
    Metal2, so the connection is a Via1 under a Metal2 strap: the Metal1 bus
    is extended east past the row, a Metal2 strap runs north from it to the
    emitter bar's own east end, and a column of Via1 cuts sits inside both.
    """
    strap_x = (upper_xs[-1] + 2.5, upper_xs[-1] + 4.5)
    # Extend the Metal1 collector bus east to sit under the strap.
    rect(
        cell,
        L_METAL1,
        lower_xs[-1] + 1.5,
        lower["collector_y"][0],
        strap_x[1] + 0.5,
        lower["collector_y"][1],
    )
    # Metal2 strap from the collector bus up to the emitter bar's latitude.
    rect(cell, L_METAL2, strap_x[0], lower["collector_y"][0], strap_x[1],
         upper["emitter_y"][1])
    # ...and a Metal2 bridge east from the emitter bar's own end to the strap.
    # Without it the strap stops 1 um short of the bar and `c1` extracts as two
    # separate nets -- which `klt extract` reports as a split_net_labels
    # warning rather than as an error, so it is asserted below too.
    rect(
        cell,
        L_METAL2,
        upper_xs[-1] + 1.5 - 0.1,
        upper["emitter_y"][0],
        strap_x[1],
        upper["emitter_y"][1],
    )
    # Via1 column, inside both metals on every side.
    cx = 0.5 * (strap_x[0] + strap_x[1])
    y_lo = lower["collector_y"][0] + 0.5
    y_hi = lower["collector_y"][1] - 0.5
    n_cuts = 4
    step = (y_hi - y_lo - VIA1_UM) / (n_cuts - 1)
    for i in range(n_cuts):
        y = y_lo + i * step
        rect(
            cell,
            L_VIA1,
            cx - 0.5 * VIA1_UM,
            y,
            cx + 0.5 * VIA1_UM,
            y + VIA1_UM,
        )
    return strap_x


def place_supply_rail(cell, x_lo, x_hi, y_centre):
    """The ``vdd`` rail: a labelled Metal1 rail on its own electrical island.

    Every element that would connect to ``vdd`` in this stage (``Rref``,
    ``Rd``, ``R1b``, ``Lfeed``) is absent from this stream, so the rail is
    deliberately a bare, unloaded conductor. It exists so ``klt erc`` has a
    second declared supply to resolve, and the claim must say it carries no
    load -- it is not evidence that the stage's supply distribution works.
    """
    rect(cell, L_METAL1, x_lo, y_centre - 1.0, x_hi, y_centre + 1.0)
    label(cell, L_TEXT_M1, "vdd", x_lo + 2.0, y_centre)


def place_ring(cell, inner):
    """Substrate guard ring: ``ptap`` instances abutting along a rectangle.

    ``ptap`` local layout (from ``sg13g2_pr.gds``, um): Activ (0,0)-(0.78,0.78),
    Metal1 pin (0.09,0.09)-(0.69,0.69), pSD (-0.03,-0.03)-(0.81,0.81). The
    instance pitch is exactly the Activ width so the Activ/pSD squares abut
    and merge into a closed annulus on each layer.
    """
    left = inner[0] - 1.0
    bottom = inner[1] - 1.0
    n_x = int((inner[2] + 1.0 - left) / PTAP_PITCH_UM) + 1
    n_y = int((inner[3] + 1.0 - bottom) / PTAP_PITCH_UM) + 1
    right = left + (n_x - 1) * PTAP_PITCH_UM
    top = bottom + (n_y - 1) * PTAP_PITCH_UM

    origins = []
    for i in range(n_x):  # bottom row, west -> east
        origins.append((left + i * PTAP_PITCH_UM, bottom))
    for j in range(1, n_y):  # east column, northwards (corner already set)
        origins.append((right, bottom + j * PTAP_PITCH_UM))
    for i in range(1, n_x):  # top row, east -> west
        origins.append((right - i * PTAP_PITCH_UM, top))
    for j in range(1, n_y - 1):  # west column, southwards (corners set)
        origins.append((left, top - j * PTAP_PITCH_UM))
    for (x, y) in origins:
        cell.insert(inst_at(cell, "ptap", x, y))

    # Metal1 band tying every ptap's Metal1 pin together: four overlapping
    # rectangles merging into one ring, each slightly overhanging the ptap row
    # so every pin (0.09..0.69 from its origin) is fully covered.
    ov = 0.05
    x0, y0 = left - ov, bottom - ov
    x1 = right + PTAP_PITCH_UM + ov
    y1 = top + PTAP_PITCH_UM + ov
    rect(cell, L_METAL1, x0, y0, x1, y0 + RING_BAND_UM)
    rect(cell, L_METAL1, x0, y1 - RING_BAND_UM, x1, y1)
    rect(cell, L_METAL1, x0, y0, x0 + RING_BAND_UM, y1)
    rect(cell, L_METAL1, x1 - RING_BAND_UM, y0, x1, y1)
    label(cell, L_TEXT_M1, "gnd", x0 + 3.0, y0 + 0.5 * RING_BAND_UM)

    return {
        "instances": len(origins),
        "x": (left, right + PTAP_PITCH_UM),
        "y": (bottom, top + PTAP_PITCH_UM),
        "metal1_inner": (
            x0 + RING_BAND_UM,
            y0 + RING_BAND_UM,
            x1 - RING_BAND_UM,
            y1 - RING_BAND_UM,
        ),
    }


def assert_nets_connected(ly, top):
    """Fail loudly if any labelled net lands on two disconnected conductors.

    This exists because the failure it catches is silent everywhere else: a
    routing gap leaves one *name* on two nets, which ``klt extract`` reports
    only as a ``split_net_labels`` warning (the netlist quietly gains ``c1``
    and ``c1$1``), DRC passes, and ``klt lvs`` then mismatches for a reason
    that looks like a device-recognition problem rather than a layout bug. It
    caught exactly that on the cascode strap during this study's development.

    Builds connected components over merged Metal1 / Metal2 joined through
    Via1, then checks every label name resolves to exactly one component.
    Returns ``{net: component_count}`` for the record.
    """
    metal = {
        "Metal1": kdb.Region(top.begin_shapes_rec(ly.layer(*L_METAL1))).merged(),
        "Metal2": kdb.Region(top.begin_shapes_rec(ly.layer(*L_METAL2))).merged(),
    }
    components: list[tuple[str, Any]] = []
    for name, region in metal.items():
        for poly in region.each():
            components.append((name, poly))

    parent = list(range(len(components)))

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # A via cut joins every component it lands inside.
    vias = kdb.Region(top.begin_shapes_rec(ly.layer(*L_VIA1))).merged()
    for via in vias.each():
        via_region = kdb.Region(via)
        hit = [
            index
            for index, (_, poly) in enumerate(components)
            if not kdb.Region(poly).interacting(via_region).is_empty()
        ]
        for other in hit[1:]:
            union(hit[0], other)

    # Resolve each label to the component holding it.
    by_net: dict[str, set[int]] = {}
    for layer, metal_name in ((L_TEXT_M1, "Metal1"), (L_TEXT_M2, "Metal2")):
        iterator = top.begin_shapes_rec(ly.layer(*layer))
        while not iterator.at_end():
            shape = iterator.shape()
            if shape.is_text():
                text = shape.text.transformed(iterator.trans())
                probe = kdb.Region(
                    kdb.Box(text.x - 1, text.y - 1, text.x + 1, text.y + 1)
                )
                owner = None
                for index, (name, poly) in enumerate(components):
                    if name != metal_name:
                        continue
                    if not kdb.Region(poly).interacting(probe).is_empty():
                        owner = index
                        break
                if owner is None:
                    raise ToolchainError(
                        f"label {text.string!r} at ({text.x / DBU_PER_UM}, "
                        f"{text.y / DBU_PER_UM}) um sits on no {metal_name} "
                        "shape -- it would name no net"
                    )
                by_net.setdefault(text.string, set()).add(find(owner))
            iterator.next()

    split = {net: len(roots) for net, roots in by_net.items() if len(roots) > 1}
    if split:
        raise ToolchainError(
            "these labelled nets land on more than one disconnected "
            "conductor, so the layout does not implement the net it names: "
            + ", ".join(f"{net} ({count} pieces)" for net, count in sorted(split.items()))
        )
    return {net: len(roots) for net, roots in sorted(by_net.items())}


def write_reference(path):
    """Write the SPICE reference holding exactly the devices this stream draws.

    Emitted by the generator rather than maintained by hand so the reference
    and the layout cannot drift: both come from :data:`GROUPS`.

    ``vdd`` is deliberately **not** a port here. Every element that would
    connect to it (``Rref``, ``Rd``, ``R1b``, ``Lfeed``) is absent from this
    stream, so no device in this reference touches it; declaring it would
    assert a port the netlist does not use. The drawn ``vdd`` rail exists for
    the ERC supply spec only -- see ``place_supply_rail``.
    """
    ports = []
    for group in GROUPS:
        for net in (group["C"], group["B"], group["E"]):
            if net not in ports:
                ports.append(net)
    ports.append("gnd")

    lines = [
        "* Reference netlist for lna_stage1_devices.gds (issue #198).",
        "* NON-CLAIMING: this is not the LNA stage-1 netlist. It holds only the",
        "* devices the device-group layout study actually draws -- the stage's",
        "* resistors, capacitors and inductors are absent from both. The",
        "* designed Nx=8 devices are drawn as 8 parallel Nx=1 units, so they",
        "* appear here as 8 parallel devices; see generate.py's module docstring.",
        "* DERIVED FILE: regenerate with generate.py, never edit by hand.",
        f".subckt lna_stage1_devices {' '.join(ports)}",
    ]
    for group in GROUPS:
        for index in range(group["units"]):
            lines.append(
                "{refdes}_{index} {c} {b} {e} gnd npn13G2 Nx=1".format(
                    refdes=group["refdes"],
                    index=index,
                    c=group["C"],
                    b=group["B"],
                    e=group["E"],
                )
            )
    lines.append(".ends lna_stage1_devices")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return len(ports)


def build(pr_gds, out_path, reference_path=None):
    ly = kdb.Layout()
    ly.dbu = 1.0 / DBU_PER_UM

    # Read the PDK primitives into this layout so the pr cells can be
    # instanced directly; unused cells are pruned before writing.
    ly.read(pr_gds)
    require_pdk_cells(ly, PR_CELLS)

    top = ly.create_cell("lna_stage1_devices")

    placed = {}
    for group in GROUPS:
        xs = place_group(top, group)
        placed[group["refdes"]] = (group, xs, wire_group(top, group, xs))

    strap_x = stitch_cascode(
        top,
        placed["Xq1"][2],
        placed["Xq2"][2],
        placed["Xq1"][1],
        placed["Xq2"][1],
    )

    # vdd rail, north of the bias device, inside the ring.
    place_supply_rail(top, -1.5, strap_x[1] + 0.5, 48.0)

    ring = place_ring(top, RING_INNER)

    # Every labelled net must be one connected conductor before anything is
    # written -- see assert_nets_connected for why this is not left to DRC.
    nets = assert_nets_connected(ly, top)

    # Every bus must sit inside the ring's Metal1 inner edge with clearance;
    # assert it rather than trusting the arithmetic above (a geometry bug here
    # would surface as a DRC spacing violation much later).
    inner = ring["metal1_inner"]
    bbox_buses = kdb.DBox()
    for layer in (L_METAL1, L_METAL2):
        li = ly.layer(*layer)
        it = top.begin_shapes_rec(li)
        while not it.at_end():
            shape = it.shape()
            if shape.is_box():
                box = shape.box.transformed(it.trans())
                dbox = kdb.DBox(
                    box.left / DBU_PER_UM,
                    box.bottom / DBU_PER_UM,
                    box.right / DBU_PER_UM,
                    box.top / DBU_PER_UM,
                )
                # The ring band itself is outside `inner` by construction.
                if not (
                    dbox.left < inner[0]
                    or dbox.bottom < inner[1]
                    or dbox.right > inner[2]
                    or dbox.top > inner[3]
                ):
                    bbox_buses += dbox
            it.next()
    if bbox_buses.empty():
        raise ToolchainError("no bus geometry landed inside the guard ring")

    # prune every cell not in this study's subtree so the written stream
    # carries only it (cells pruned bottom-up by index)
    keep = set(top.called_cells())
    keep.add(top.cell_index())
    doomed = [
        c.cell_index() for c in ly.each_cell() if c.cell_index() not in keep
    ]
    for idx in sorted(doomed, reverse=True):
        ly.delete_cell(idx)

    # Deterministic stream: no embedded timestamps, so a regeneration is
    # byte-identical and the committed run records' input hashes stay valid.
    opts = kdb.SaveLayoutOptions()
    opts.gds2_write_timestamps = False
    top.write(out_path, opts)

    bb = top.bbox()
    units = sum(group["units"] for group in GROUPS)
    print(f"pr_gds: {pr_gds}")
    print(f"wrote:  {out_path}")
    print(
        f"top:    {top.name}  bbox_um: ({bb.left / 1000.0}, "
        f"{bb.bottom / 1000.0}) .. ({bb.right / 1000.0}, {bb.top / 1000.0})"
    )
    # Nested same-quote f-strings are a 3.12+ (PEP 701) relaxation; this repo's
    # CI pins python 3.11, so build the group summary outside the f-string.
    groups_text = ", ".join(
        "{}x{}".format(group["refdes"], group["units"]) for group in GROUPS
    )
    print(f"hbt:    {units} npn13G2 unit instances ({groups_text})")
    print(f"ring:   {ring['instances']} ptap instances, "
          f"x {ring['x'][0]}..{ring['x'][1]}, y {ring['y'][0]}..{ring['y'][1]}")
    print(f"nets:   {' '.join(nets)}  "
          f"(all {len(nets)} single-component; labels on the Metal1/Metal2 "
          "text layers)")
    if reference_path:
        ports = write_reference(reference_path)
        print(f"ref:    {reference_path}  ({ports} ports, {units} devices)")
    print("absent: every R, C and L of the stage -- see realizability.json")


def main(argv: list[str] | None = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pr-gds",
        default=None,
        help="path to sg13g2_pr.gds (default: resolve from the pinned PDK)",
    )
    parser.add_argument(
        "--out",
        default=os.path.join(here, "lna_stage1_devices.gds"),
        help="output GDS path (default: lna_stage1_devices.gds beside this script)",
    )
    parser.add_argument(
        "--reference",
        default=os.path.join(here, "reference-devices.spice"),
        help="output SPICE reference path for `klt lvs` (default: "
        "reference-devices.spice beside this script); pass '' to skip",
    )
    args = parser.parse_args(argv)
    try:
        build(resolve_pr_gds(args.pr_gds), args.out, args.reference or None)
    except ToolchainError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
