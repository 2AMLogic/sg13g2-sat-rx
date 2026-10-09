#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Synthetic (generated, NOT EM) fixtures for the analysis-chain controls.

Everything here is known by construction:
  * `lossless_L(L)`      ideal series inductor between LA and LB, no loss, no
                         shunt: Z_se = j*w*L exactly.  L_TRUE_H is an arbitrary
                         round number; it is NOT an estimate for p1.
  * `lossy_pi_run(...)`  a 2-pi network from the SAME element topology the fit
                         uses (emlib.model_Y), plus embedded port inductance,
                         written in the layout run_openems.py produces.  Used
                         only to smoke-test post/fit/compare/record plumbing.
                         Its element values are arbitrary test values.

  make_synthetic.py --write-fixture   regenerate fixtures/lossless_L_100pH.s2p
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emlib  # noqa: E402
import p1chain as C  # noqa: E402

CAMPAIGN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L_TRUE_H = 100e-12
Z0 = 50.0
GRID = np.linspace(0.0, 30e9, C.EXPECTED_NUMFREQ)  # same sweep as the campaign


def lossless_L_S(L=L_TRUE_H, f=GRID, z0=Z0):
    Z = 1j * 2 * np.pi * f * L
    S = np.zeros((len(f), 2, 2), dtype=complex)
    S[:, 0, 0] = S[:, 1, 1] = Z / (Z + 2 * z0)
    S[:, 0, 1] = S[:, 1, 0] = 2 * z0 / (Z + 2 * z0)
    return S


def write_lossless(path, L=L_TRUE_H):
    emlib.write_snp(path, GRID, lossless_L_S(L), Z0, comments=[
        "SYNTHETIC lossless series inductor, L = %.6g H (known by construction)" % L,
        "S11=S22=Z/(Z+2z0), S21=S12=2z0/(Z+2z0), Z=j*w*L, z0=50. NOT an EM result."])


def write_spice_L(path, L, name="synth_l"):
    with open(path, "w") as fh:
        fh.write("* synthetic ideal series inductor, L=%.9g H (known-answer control)\n" % L)
        fh.write(".subckt %s la lb sub\nL1 la lb %.12g\n.ends %s\n" % (name, L, name))


PORT_INFO = {"ports": [{"portnumber": 1, "Z0": 50, "direction": "Z", "length": 11.2303, "width": 8.22},
                       {"portnumber": 2, "Z0": 50, "direction": "Z", "length": 11.2303, "width": 8.22}],
             "unit": 1e-6, "name": "inductor_p1"}

# arbitrary but plausible-scale test elements (NOT sibling numbers, NOT results)
PI_TRUE = {"Rdc": 0.9, "Rlad": 1.8, "L1": 20e-12, "Ltot": 150e-12, "Cs": 2e-15,
           "Cox": 12e-15, "Rsub": 400.0, "Csub": 8e-15}


def pi_S(params, f=GRID, Lport=None):
    """S of the symmetric pi plus embedded port inductance; DC row via Y."""
    S = np.zeros((len(f), 2, 2), dtype=complex)
    pos = f > 0
    Y = emlib.model_Y(f[pos], params)
    Z = np.linalg.inv(Y)
    if Lport is not None:
        w = 2 * np.pi * f[pos]
        Z = Z.copy()
        for n, L in enumerate(Lport):
            Z[:, n, n] += 1j * w * L
    S[pos] = emlib.z2s(Z, Z0)
    ys = 1.0 / params["Rdc"]
    Ydc = np.array([[ys, -ys], [-ys, ys]])[None]
    S[~pos] = C.y2s(Ydc, Z0)
    return S


def lossy_pi_run(outdir, name, params, cellsize, margin, wall=1.0):
    """Write results-style files for one run under `outdir` (…/<name>[.s2p])."""
    d = os.path.join(outdir, name)
    os.makedirs(d, exist_ok=True)
    Lport = emlib.port_inductances(PORT_INFO)
    S = pi_S(params, GRID, Lport)
    emlib.write_snp(d + ".s2p", GRID, S, Z0, comments=["SYNTHETIC pi-network run (pipeline smoke only)"])
    json.dump(PORT_INFO, open(os.path.join(d, "port_information.json"), "w"), indent=2)
    meta = {"settings": {"Boundaries": ["PEC"] * 6, "cells_per_wavelength": 20, "energy_limit": -50.0,
                         "excite_portnumbers": [2], "fstart": 0.0, "fstop": 30e9, "margin": margin,
                         "merge_polygon_size": 1.0, "numfreq": 601, "refined_cellsize": cellsize, "unit": 1e-6},
            "solver": {"tool": "SYNTHETIC (no solver ran)", "version_banner": "n/a"},
            "gds_sha256": None, "stackup_xml_sha256": None, "wall_seconds": wall}
    json.dump(meta, open(os.path.join(d, "run_meta.json"), "w"), indent=2)


def lossy_campaign(workdir, mesh_scale_L=0.995, margin_scale_L=0.998):
    res = os.path.join(workdir, "results")
    os.makedirs(os.path.join(res, "convergence"), exist_ok=True)
    lossy_pi_run(res, "inductor_p1", PI_TRUE, 1.0, 200.0)
    pm = dict(PI_TRUE, Ltot=PI_TRUE["Ltot"] * mesh_scale_L, Rdc=PI_TRUE["Rdc"] * 1.02)
    lossy_pi_run(os.path.join(res, "convergence"), "p1_mesh0p5", pm, 0.5, 200.0)
    pg = dict(PI_TRUE, Ltot=PI_TRUE["Ltot"] * margin_scale_L)
    lossy_pi_run(os.path.join(res, "convergence"), "p1_margin400", pg, 1.0, 400.0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-fixture", action="store_true")
    a = ap.parse_args()
    if a.write_fixture:
        os.makedirs(os.path.join(CAMPAIGN, "fixtures"), exist_ok=True)
        write_lossless(os.path.join(CAMPAIGN, "fixtures", "lossless_L_100pH.s2p"))
        print("fixture written")
