# SPDX-License-Identifier: Apache-2.0
#
# gen_geometry.py -- emit an EM-ready GDSII for one IHP SG13G2 spiral-inductor
# PCell instance, plus the two lumped-port footprints and the local substrate
# ground patch the openEMS workflow needs.
#
# The coil geometry is NOT redrawn here.  It is instantiated from the PDK's own
# KLayout PCell (`inductor2` in library `SG13_dev`, implemented by
# libs.tech/klayout/python/sg13g2_pycell_lib/ihp/inductor2_code.py, which
# subclasses inductors_code.py).  This script only adds the EM-workflow-specific
# artificial layers:
#
#   201/0  port-1 footprint (terminal LA)   -- gds2openEMS simulation_port
#   202/0  port-2 footprint (terminal LB)   -- gds2openEMS simulation_port
#   210/0  SUBGND, the local low-loss substrate ground patch under both ports
#
# and nothing else.  Port footprints are taken verbatim from the PCell's own pin
# boxes, so the EM port sits exactly where the LVS/schematic terminal sits.
#
# This must run inside KLayout's interpreter (it needs `pya`):
#
#   KLAYOUT_PATH=<scratch> klayout -zz -r gen_geometry.py -rd out=... -rd geom=p1
#
# See ../README.md section "Running it" for the wrapper that sets up the PDK
# overlay this needs (the release tarball ships pycell4klayout-api and
# pypreprocessor as EMPTY git submodules; both must be populated first).

import json
import os
import sys

# --- PDK python path -------------------------------------------------------
# `pdk_klayout` is passed in with -rd; it must be a libs.tech/klayout tree whose
# python/pycell4klayout-api and python/pypreprocessor submodules are populated.
PDK_KLAYOUT = pdk_klayout  # noqa: F821  (injected by klayout -rd)
OUT_GDS = out             # noqa: F821
OUT_JSON = outjson        # noqa: F821
GEOM = geom               # noqa: F821

sys.path.append(os.path.join(PDK_KLAYOUT, "python"))
sys.path.append(os.path.join(PDK_KLAYOUT, "python/pycell4klayout-api/source/python"))

import sg13g2_pycell_lib  # noqa: E402,F401  (registers library SG13_dev)

# The PCell wrapper routes parameter coercion through a Tcl callback layer that
# only exists in the commercial flow: it needs a parameters.tcl/callbacks.json
# pair that IHP-Open-PDK does not ship, and it is entered only when `tkinter`
# happens to already be in sys.modules.  Dropping the module from sys.modules
# takes the no-callback path, which is the correct behaviour for this PDK.
sys.modules.pop("tkinter", None)

# --- the geometries under study -------------------------------------------
# All three are IHP's own LVS unit testcases for the `inductor` device, from
# libs.tech/klayout/tech/lvs/testing/testcases/unit/ind_devices/netlist/inductor.cdl
# (L_pattern_1, L_pattern_13, L_pattern_11).  They are the same three probed by
# ../../tank-characterization/ and by the analytic model check.
GEOMETRIES = {
    #  name: (w_um, s_um, d_um, nr_r)
    "p1": (8.22, 3.29, 47.65, 1),
    "p13": (6.10, 3.29, 110.11, 5),
    "p11": (8.22, 3.74, 141.975, 4),
}

# GDS layers of the SG13G2 stack that carry conductor for this device.
L_TM2 = (134, 0)
L_TM1 = (126, 0)
L_TV2 = (133, 0)
L_TM2_PIN = (134, 2)
L_TM1_PIN = (126, 2)

L_PORT1 = (201, 0)
L_PORT2 = (202, 0)
L_SUBGND = (210, 0)

# How far the SUBGND patch extends beyond the union of the two port footprints.
SUBGND_MARGIN_UM = 15.0

w_um, s_um, d_um, nr_r = GEOMETRIES[GEOM]

layout = pya.Layout()  # noqa: F821
layout.dbu = 0.001

cell = layout.create_cell(
    "inductor2",
    "SG13_dev",
    {"w": w_um * 1e-6, "s": s_um * 1e-6, "d": d_um * 1e-6, "nr_r": nr_r},
)


def region(lay, dt):
    li = layout.find_layer(lay, dt)
    if li is None:
        return pya.Region()  # noqa: F821
    return pya.Region(cell.shapes(li))  # noqa: F821


# --- locate the two device terminals --------------------------------------
# The PCell draws the LA/LB feeds in TopMetal2 for the single-turn device and in
# TopMetal1 once a crossunder is needed, and puts its pin boxes on the matching
# layer.  Take whichever pin layer is non-empty; that also tells us which metal
# the EM port must land on.
pin_tm2 = region(*L_TM2_PIN)
pin_tm1 = region(*L_TM1_PIN)
if not pin_tm2.is_empty():
    pins, pin_layername = pin_tm2, "TopMetal2"
elif not pin_tm1.is_empty():
    pins, pin_layername = pin_tm1, "TopMetal1"
else:
    raise RuntimeError("PCell emitted no pin boxes on TopMetal1 or TopMetal2")

pin_boxes = [p.bbox() for p in pins.each()]
if len(pin_boxes) != 2:
    raise RuntimeError("expected exactly 2 pin boxes, got %d" % len(pin_boxes))
# Port 1 = LA = the left-hand terminal; port 2 = LB.  (Which one the PCell calls
# LA does not matter electrically for a symmetric 2-port extraction, but fixing
# the convention keeps the S-parameter files comparable across geometries.)
pin_boxes.sort(key=lambda b: b.left)

out_layers = {}
for name, (lay, dt) in (("TopMetal2", L_TM2), ("TopMetal1", L_TM1), ("TopVia2", L_TV2)):
    r = region(lay, dt)
    out_layers[name] = (lay, dt, r)

# --- build the output layout ----------------------------------------------
em = pya.Layout()  # noqa: F821
em.dbu = layout.dbu
top = em.create_cell("inductor_%s" % GEOM)

for name, (lay, dt, r) in out_layers.items():
    if r.is_empty():
        continue
    top.shapes(em.layer(lay, dt)).insert(r)

port_layers = [L_PORT1, L_PORT2]
for box, (lay, dt) in zip(pin_boxes, port_layers):
    top.shapes(em.layer(lay, dt)).insert(box)

subgnd = pya.Box(pin_boxes[0])  # noqa: F821
subgnd += pin_boxes[1]
m = int(round(SUBGND_MARGIN_UM / em.dbu))
subgnd = subgnd.enlarged(m, m)
top.shapes(em.layer(*L_SUBGND)).insert(subgnd)

em.write(OUT_GDS)

meta = {
    "geometry": GEOM,
    "w_um": w_um,
    "s_um": s_um,
    "d_um": d_um,
    "nr_r": nr_r,
    "pcell": {"library": "SG13_dev", "cell": "inductor2"},
    "port_metal_layer": pin_layername,
    "ports": [
        {
            "portnumber": i + 1,
            "terminal": t,
            "gds_layer": list(port_layers[i]),
            "box_um": [
                pin_boxes[i].left * em.dbu,
                pin_boxes[i].bottom * em.dbu,
                pin_boxes[i].right * em.dbu,
                pin_boxes[i].top * em.dbu,
            ],
        }
        for i, t in enumerate(("LA", "LB"))
    ],
    "subgnd_box_um": [
        subgnd.left * em.dbu,
        subgnd.bottom * em.dbu,
        subgnd.right * em.dbu,
        subgnd.top * em.dbu,
    ],
    "coil_bbox_um": [
        cell.dbbox().left,
        cell.dbbox().bottom,
        cell.dbbox().right,
        cell.dbbox().top,
    ],
    "polygon_counts": {n: r.count() for n, (_, _, r) in out_layers.items()},
}
with open(OUT_JSON, "w") as fh:
    json.dump(meta, fh, indent=2, sort_keys=True)
    fh.write("\n")

print("wrote %s (%s)" % (OUT_GDS, GEOM))
print(json.dumps(meta, indent=2, sort_keys=True))

