#!/usr/bin/env python3
"""Generate the layout-chain readiness probe cell (issue #185).

Non-claiming probe: a single throwaway-quality cell (`probe_readiness`)
that instances the PDK's own primitives -- one `npn13G2` HBT, one `cmim`
MIM capacitor, one `rsil` poly resistor -- wires each device pin out to a
labelled Metal1/Metal2/Metal5/TopMetal1 net, and surrounds everything with
a ptap guard ring. It is NOT the LNA layout and cites nothing.

The probe exists to exercise the klt layout chain (drc / extract / lvs /
ring-check / economy) against these device types for the first time in
this repo and record, per tool, what actually happens. See README.md.

Usage:
    python3 generate_probe.py [--pr-gds PATH] [--out PATH]

Only the `klayout` Python module (installed as klayout-tools' dependency)
is required; the script never opens a GUI.
"""

import argparse
import os
import sys

try:
    import klayout.db as kdb
except ImportError:
    sys.exit(
        "error: the `klayout` python module is required (it is a dependency "
        "of klayout-tools); run this script with the interpreter from that "
        "install, e.g. $(which klt)-adjacent venv python"
    )

# --- SG13G2 drawing/purpose layers (GDS layer/datatype) -----------------
L_ACTIV = (1, 0)  # Activ.drawing
L_METAL1 = (8, 0)  # Metal1.drawing
L_METAL2 = (10, 0)  # Metal2.drawing
L_METAL5 = (67, 0)  # Metal5.drawing
L_TOPMETAL1 = (126, 0)  # TopMetal1.drawing
L_TEXT_M1 = (8, 25)  # Metal1.text   (curated deck's Metal1 label layer)
L_TEXT_M2 = (10, 25)  # Metal2.text
L_TEXT_M5 = (67, 25)  # Metal5.text
L_TEXT_TM1 = (126, 25)  # TopMetal1.text

DBU_PER_UM = 1000

# PDK primitive cells this probe instances (from sg13g2_pr.gds)
PR_CELLS = ("npn13G2", "cmim", "rsil", "ptap")

DEFAULT_PR_GDS_CANDIDATES = (
    "/home/ubuntu/share/pdk/ihp-sg13g2/libs.ref/sg13g2_pr/gds/sg13g2_pr.gds",
    os.path.expanduser(
        "~/share/pdk/ihp-sg13g2/libs.ref/sg13g2_pr/gds/sg13g2_pr.gds"
    ),
)


def find_pr_gds(explicit):
    if explicit:
        if not os.path.isfile(explicit):
            sys.exit(f"error: --pr-gds not found: {explicit}")
        return explicit
    for cand in DEFAULT_PR_GDS_CANDIDATES:
        if os.path.isfile(cand):
            return cand
    sys.exit(
        "error: sg13g2_pr.gds not found at any default candidate; pass "
        "--pr-gds /path/to/ihp-sg13g2/libs.ref/sg13g2_pr/gds/sg13g2_pr.gds"
    )


def rect(cell, layer, x1, y1, x2, y2):
    cell.shapes(cell.layout().layer(*layer)).insert(
        kdb.DBox(x1, y1, x2, y2)
    )


def label(cell, layer, text, x, y):
    cell.shapes(cell.layout().layer(*layer)).insert(
        kdb.DText(text, kdb.DTrans(kdb.DTrans.R0, kdb.DVector(x, y)))
    )


def inst_at(cell, cell_name, x_um, y_um):
    """Instance `cell_name` at (x_um, y_um).

    CellInstArray takes a dbu-space `Trans` -- its overloads do not accept a
    micron-space `DTrans` (one silently converts through integer dbu, so a
    14 um displacement becomes 14 dbu). Convert to integer dbu here.
    """
    ly = cell.layout()
    return kdb.CellInstArray(
        ly.cell(cell_name).cell_index(),
        kdb.Trans(kdb.Trans.R0, kdb.Vector(int(round(x_um * DBU_PER_UM)),
                                           int(round(y_um * DBU_PER_UM)))),
    )


def place_ring(cell, ptap_cell_name):
    """Guard ring: `ptap` instances abutting along a rectangular path.

    ptap cell local layout (from sg13g2_pr.gds, um): Activ (0,0)-(0.78,0.78),
    Metal1 pin (0.09,0.09)-(0.69,0.69), pSD (-0.03,-0.03)-(0.81,0.81).
    Instance pitch is exactly the Activ width so Activ/pSD squares abut and
    merge into a closed annulus on each layer.
    """
    ly = cell.layout()
    pitch = 0.78
    # bottom-row ptap origins run x in [-6, -6+55*pitch]; N_X origins
    left = -6.0
    bottom = -12.0
    n_x = 56  # ptaps per horizontal row
    n_y = 41  # ptaps per vertical column
    top = bottom + (n_y - 1) * pitch  # 19.2
    right = left + (n_x - 1) * pitch  # 36.9

    pts = []
    for i in range(n_x):  # bottom row, west -> east
        pts.append((left + i * pitch, bottom))
    for j in range(1, n_y):  # right column, northwards (corner already set)
        pts.append((right, bottom + j * pitch))
    for i in range(1, n_x):  # top row, east -> west
        pts.append((right - i * pitch, top))
    for j in range(1, n_y - 1):  # left column, southwards (corners set)
        pts.append((left, top - j * pitch))

    for (x, y) in pts:
        cell.insert(inst_at(cell, ptap_cell_name, x, y))

    # Metal1 band tying every ptap's Metal1 pin together (4 overlapping
    # rectangles -> one merged ring). Slightly overhangs the ptap row so
    # every pin (0.09..0.69 relative to each origin) is fully covered.
    ov = 0.05
    w_lo = 0.95  # band width
    rect(cell, L_METAL1, left - ov, bottom - ov, right + pitch + ov, bottom + w_lo)
    rect(cell, L_METAL1, left - ov, top + pitch - w_lo, right + pitch + ov, top + pitch + ov)
    rect(cell, L_METAL1, left - ov, bottom - ov, left + w_lo, top + pitch + ov)
    rect(cell, L_METAL1, right + pitch - w_lo, bottom - ov, right + pitch + ov, top + pitch + ov)
    label(cell, L_TEXT_M1, "GND", 2.0, bottom + 0.4)
    return dict(left=left, bottom=bottom, top=top, right=right, n=len(pts))


def build(pr_gds, out_path):
    ly = kdb.Layout()
    ly.dbu = 1.0 / DBU_PER_UM

    # Read the PDK primitives into this layout so the pr cells can be
    # instanced directly; unused cells are pruned before writing.
    ly.read(pr_gds)
    for name in PR_CELLS:
        if ly.cell(name) is None:
            sys.exit(f"error: cell '{name}' not found in {pr_gds}")

    top = ly.create_cell("probe_readiness")

    # --- devices ---------------------------------------------------------
    # npn13G2 at origin: pins E=Metal1(-0.965,-1.26..-1.02),
    # B=Metal1(-0.915,1.01..1.25), C=Metal2(-0.745,-0.78..0.77) (local um)
    top.insert(inst_at(top, "npn13G2", 0.0, 0.0))
    # cmim at (14,0): top plate = TopMetal1 (local 0.345..6.645),
    # bottom plate = Metal5 (local -0.6..7.59)
    top.insert(inst_at(top, "cmim", 14.0, 0.0))
    # rsil at (30,0): pins A=Metal1(0.57..0.83), B=Metal1(-0.33..-0.07)
    top.insert(inst_at(top, "rsil", 30.0, 0.0))

    # --- wiring (overlap every device pin with positive area) ------------
    # npn emitter: Metal1 south, labelled net "E"
    rect(top, L_METAL1, -0.965, -6.0, 0.975, -1.0)
    label(top, L_TEXT_M1, "E", 0.0, -5.0)
    # npn base: Metal1 north, net "B"
    rect(top, L_METAL1, -0.915, 1.1, 0.925, 5.0)
    label(top, L_TEXT_M1, "B", 0.0, 4.5)
    # npn collector: Metal2 east, net "C"
    rect(top, L_METAL2, 0.745, -0.3, 6.0, 0.3)
    label(top, L_TEXT_M2, "C", 5.5, 0.15)

    # cmim top plate: extend its TopMetal1 plate east (min TM1 width 2 um)
    rect(top, L_TOPMETAL1, 20.0, 3.0, 26.0, 5.0)
    label(top, L_TEXT_TM1, "CT", 25.0, 4.0)
    # cmim bottom plate: Metal5 route from the plate rim east
    rect(top, L_METAL5, 21.0, 5.5, 26.0, 7.5)
    label(top, L_TEXT_M5, "CB", 25.0, 6.5)

    # rsil terminals: Metal1 north/south
    rect(top, L_METAL1, 29.9, 0.57, 30.6, 3.5)
    label(top, L_TEXT_M1, "RA", 30.3, 3.0)
    rect(top, L_METAL1, 29.9, -3.5, 30.6, -0.07)
    label(top, L_TEXT_M1, "RB", 30.3, -3.0)

    # --- guard ring -------------------------------------------------------
    ring = place_ring(top, "ptap")

    # prune every cell not in the probe's subtree so the written stream
    # carries only the probe (cells pruned bottom-up by index)
    keep = set(top.called_cells())
    keep.add(top.cell_index())
    doomed = [c.cell_index() for c in ly.each_cell() if c.cell_index() not in keep]
    for idx in sorted(doomed, reverse=True):
        ly.delete_cell(idx)

    # Deterministic stream: no embedment timestamps, so a regeneration is
    # byte-identical and the committed run records' input hashes stay valid.
    opts = kdb.SaveLayoutOptions()
    opts.gds2_write_timestamps = False
    top.write(out_path, opts)

    bb = top.bbox()
    print(f"pr_gds: {pr_gds}")
    print(f"wrote:  {out_path}")
    print(f"top:    {top.name}  bbox_um: ({bb.left / 1000.0}, {bb.bottom / 1000.0})"
          f" .. ({bb.right / 1000.0}, {bb.top / 1000.0})")
    print(f"ring:   {ring['n']} ptap instances, x {ring['left']}..{ring['right'] + 0.78},"
          f" y {ring['bottom']}..{ring['top'] + 0.78}")
    print("nets:   E B C CT CB RA RB GND (labels on Metal1/Metal2/Metal5/TopMetal1 text layers)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pr-gds", default=None,
                    help="path to sg13g2_pr.gds (default: search standard PDK roots)")
    ap.add_argument("--out", default=None,
                    help="output GDS path (default: probe.gds next to this script)")
    args = ap.parse_args()
    pr_gds = find_pr_gds(args.pr_gds)
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe.gds")
    build(pr_gds, out)


if __name__ == "__main__":
    main()
