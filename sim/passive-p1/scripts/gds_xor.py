# SPDX-License-Identifier: Apache-2.0
# gds_xor.py -- geometric (not byte) comparison of two GDS files, per layer.
#   klayout -zz -r gds_xor.py -rd a=<pinned.gds> -rd b=<regenerated.gds>
# Prints one line per layer with the XOR area in um^2 and a final GEOMETRY_IDENTICAL /
# GEOMETRY_DIFFERS verdict.  Byte hashes of GDS files differ for reasons that are not
# geometry (header timestamps), so the geometry stage reports both.
import pya  # noqa: F821

la, lb = pya.Layout(), pya.Layout()  # noqa: F821
la.read(a)  # noqa: F821
lb.read(b)  # noqa: F821
ca, cb = la.top_cell(), lb.top_cell()
layers = sorted({(i.layer, i.datatype) for i in la.layer_infos()} | {(i.layer, i.datatype) for i in lb.layer_infos()})
bad = 0
for (l, d) in layers:
    def reg(lay, cell):
        li = lay.find_layer(l, d)
        return pya.Region(cell.begin_shapes_rec(li)) if li is not None else pya.Region()  # noqa: F821
    x = reg(la, ca) ^ reg(lb, cb)
    area = x.area() * (la.dbu ** 2)
    bad += area > 0
    print("layer %d/%d xor_area_um2 %.6g" % (l, d, area))
print("GEOMETRY_IDENTICAL" if bad == 0 else "GEOMETRY_DIFFERS")
