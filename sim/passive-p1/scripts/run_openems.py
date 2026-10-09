#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
#
# run_openems.py -- full 2-port openEMS/FDTD S-parameter extraction of one
# SG13G2 spiral-inductor PCell instance.
#
# Must run under the openEMS python venv (it needs openEMS/CSXCAD + gds2openEMS):
#
#   ~/opt/openEMS/venv/bin/python run_openems.py --geom p1 [...]
#
# Method, stated once here so every number downstream inherits it:
#
#   * Solver: openEMS (FDTD, time domain), IHP's own documented EM route for
#     this PDK (libs.doc/doc/EM_Simulation_Overview.pdf).
#   * Stack: IHP's own openEMS stackup SG13G2.xml, from
#     libs.tech/openems/openems_ihp_sg13g2/workflow/, copied verbatim into
#     ../stackup/.  That file is IHP's EM-facing transcription of the same
#     cross-section that libs.tech/klayout/tech/xsect/sg13g2_for_EM.xs defines
#     for KLayout; it carries per-layer z extents and per-metal conductivity.
#   * Ports: two lumped z-ports, each from the local SUBGND patch up to the
#     PCell's own LA/LB pin box, referenced to the substrate.  This is the
#     port topology of IHP's own run_inductor_2port.py example.
#   * Excitation: Gaussian pulse centred on (fstart+fstop)/2; one FDTD run per
#     excited port; S-parameters by FFT at `numfreq` points.
#   * Boundaries: PEC box.  The domain is the GDS bounding box grown by
#     `margin` on every side.  A PEC box is a *closed* domain: it images the
#     coil's currents in the walls and so pulls L down slightly.  `margin` is
#     the knob that controls how much; see ../README.md for the margin
#     convergence check.
#
# Everything the run depends on is written to <out>/run_meta.json so the record
# is self-describing.

import argparse
import json
import os
import platform
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emlib  # noqa: E402

from gds2openEMS import gds_reader, simulation_setup, stackup_reader, utilities  # noqa: E402
from openEMS import openEMS  # noqa: E402


def openems_version():
    try:
        out = subprocess.run(
            ["openEMS", "--version"], capture_output=True, text=True, timeout=60
        )
        lines = (out.stdout + out.stderr).strip().splitlines()
        for line in lines:
            if "version" in line.lower():
                return line.strip(" |")
        return lines[0] if lines else "unknown (no output)"
    except Exception as exc:  # pragma: no cover
        return "unknown (%s)" % exc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--geom", required=True)
    ap.add_argument("--gds", required=True)
    ap.add_argument("--geom-json", required=True)
    ap.add_argument("--xml", required=True)
    ap.add_argument("--out", required=True, help="simulation data directory")
    ap.add_argument("--s2p", required=True, help="Touchstone output path")
    ap.add_argument("--fstop", type=float, default=30e9)
    ap.add_argument("--numfreq", type=int, default=601)
    ap.add_argument("--cellsize", type=float, default=1.0)
    ap.add_argument("--margin", type=float, default=200.0)
    ap.add_argument("--energy-limit", type=float, default=-40.0)
    ap.add_argument("--cells-per-wavelength", type=int, default=20)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--preview-only", action="store_true")
    args = ap.parse_args()

    with open(args.geom_json) as fh:
        geom_meta = json.load(fh)

    os.makedirs(args.out, exist_ok=True)

    settings = {}
    settings["preview_only"] = args.preview_only
    settings["no_gui"] = True
    settings["unit"] = 1e-6
    settings["margin"] = args.margin
    settings["fstart"] = 0.0
    settings["fstop"] = args.fstop
    settings["numfreq"] = args.numfreq
    settings["refined_cellsize"] = args.cellsize
    settings["Boundaries"] = ["PEC"] * 6
    settings["cells_per_wavelength"] = args.cells_per_wavelength
    settings["energy_limit"] = args.energy_limit
    settings["merge_polygon_size"] = 1.0
    if args.threads:
        settings["numThreads"] = args.threads

    port_metal = geom_meta["port_metal_layer"]

    ports = simulation_setup.all_simulation_ports()
    for p in geom_meta["ports"]:
        ports.add_port(
            simulation_setup.simulation_port(
                portnumber=p["portnumber"],
                voltage=1,
                port_Z0=50,
                source_layernum=p["gds_layer"][0],
                from_layername="SUBGND",
                to_layername=port_metal,
                direction="z",
            )
        )

    materials_list, dielectrics_list, metals_list = stackup_reader.read_substrate(args.xml)
    layernumbers = metals_list.getlayernumbers()
    layernumbers.extend(ports.portlayers)

    allpolygons = gds_reader.read_gds(
        args.gds,
        layernumbers,
        purposelist=[0],
        metals_list=metals_list,
        preprocess=False,
        merge_polygon_size=settings["merge_polygon_size"],
    )

    FDTD = openEMS(EndCriteria=10 ** (settings["energy_limit"] / 10.0))
    FDTD.SetGaussExcite(
        (settings["fstart"] + settings["fstop"]) / 2,
        (settings["fstop"] - settings["fstart"]) / 2,
    )
    FDTD.SetBoundaryCond(settings["Boundaries"])

    settings["simulation_ports"] = ports
    settings["materials_list"] = materials_list
    settings["dielectrics_list"] = dielectrics_list
    settings["metals_list"] = metals_list
    settings["layernumbers"] = layernumbers
    settings["allpolygons"] = allpolygons
    settings["sim_path"] = args.out
    settings["model_basename"] = "inductor_%s" % args.geom

    t0 = time.time()
    for excite in ([1], [2]):
        settings["excite_portnumbers"] = excite
        simulation_setup.setupSimulation(FDTD=FDTD, settings=settings)
        simulation_setup.runSimulation(FDTD=FDTD, settings=settings)
    wall_s = time.time() - t0

    meta = {
        "geometry": geom_meta,
        "solver": {
            "tool": "openEMS",
            "version_banner": openems_version(),
            "engine": "FDTD (time domain), Gaussian pulse excitation",
        },
        "settings": {
            k: v
            for k, v in settings.items()
            if isinstance(v, (int, float, str, bool, list))
        },
        "stackup_xml_sha256": emlib.sha256(args.xml),
        "gds_sha256": emlib.sha256(args.gds),
        "host": {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "cpu_count": os.cpu_count(),
        },
        "wall_seconds": round(wall_s, 1),
    }
    with open(os.path.join(args.out, "run_meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
        fh.write("\n")

    if args.preview_only:
        print("preview only, no S-parameters")
        return

    f = np.linspace(settings["fstart"], settings["fstop"], settings["numfreq"])
    s11 = utilities.calculate_Sij(1, 1, f, args.out, ports)
    s21 = utilities.calculate_Sij(2, 1, f, args.out, ports)
    s12 = utilities.calculate_Sij(1, 2, f, args.out, ports)
    s22 = utilities.calculate_Sij(2, 2, f, args.out, ports)

    utilities.write_snp(
        np.array([[s11, s21], [s12, s22]]),
        f,
        args.s2p,
        z0=ports.get_reference_impedance(),
    )
    print("wrote", args.s2p, "in %.0f s" % wall_s)


if __name__ == "__main__":
    main()
