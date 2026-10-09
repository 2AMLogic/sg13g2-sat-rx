#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""De-embed the lumped ports and extract L/Q/SRF from every openEMS run.

Writes, per geometry:
  results/inductor_<g>_deembedded.s2p   raw extraction minus the port parasitic
  results/inductor_<g>_lq.csv           L/Q vs frequency, single-ended + diff
and one summary:
  results/em_summary.csv                scalar L/Q/SRF per geometry
  results/convergence.csv               mesh/margin sensitivity of those scalars

Needs only numpy; no EM solver, no PDK.
"""

import argparse
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emlib  # noqa: E402

GEOMS = ["p1", "p13", "p11"]
SPOT_F = [1e9, 5e9, 10e9, 20e9]


def load_run(datadir, s2p):
    f, S, z0 = emlib.read_snp(s2p)
    with open(os.path.join(datadir, "port_information.json")) as fh:
        pinfo = json.load(fh)
    Lport = emlib.port_inductances(pinfo)
    Z = emlib.s2z(S, z0)
    Zd = emlib.deembed_series_L(f, Z, Lport)
    return f, S, Z, Zd, z0, Lport, pinfo


def scalars(f, Z):
    zse = emlib.z_single_ended(Z)
    zdi = emlib.z_differential(Z)
    Lse, Qse = emlib.lq(f, zse)
    Ldi, Qdi = emlib.lq(f, zdi)
    out = {
        "srf_se_hz": emlib.srf(f, zse),
        "srf_diff_hz": emlib.srf(f, zdi),
    }
    for f0 in SPOT_F:
        g = "%dg" % int(round(f0 / 1e9))
        out["l_se_%s" % g] = emlib.at(f, Lse, f0)
        out["q_se_%s" % g] = emlib.at(f, Qse, f0)
        out["l_diff_%s" % g] = emlib.at(f, Ldi, f0)
        out["q_diff_%s" % g] = emlib.at(f, Qdi, f0)
    out["rdc_ohm"] = float(np.real(zse[np.argmin(np.abs(f - 1e8))]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    args = ap.parse_args()
    root = args.dir
    res = os.path.join(root, "results")

    summary_rows = []
    for g in GEOMS:
        datadir = os.path.join(res, "inductor_%s" % g)
        s2p = os.path.join(res, "inductor_%s.s2p" % g)
        if not os.path.isfile(s2p):
            print("MISSING %s -- skipping" % s2p)
            continue
        f, S, Z, Zd, z0, Lport, pinfo = load_run(datadir, s2p)
        Sd = emlib.z2s(Zd, z0)
        emlib.write_snp(
            os.path.join(res, "inductor_%s_deembedded.s2p" % g),
            f,
            Sd,
            z0,
            comments=[
                "openEMS extraction of the IHP SG13G2 inductor PCell, geometry %s" % g,
                "port parasitic de-embedded by cascading a negative series L per port",
                "L_port = %s pH (Terman flat-ribbon, from port_information.json)"
                % np.array2string(Lport * 1e12, precision=3),
            ],
        )

        zse_r, zdi_r = emlib.z_single_ended(Z), emlib.z_differential(Z)
        zse_d, zdi_d = emlib.z_single_ended(Zd), emlib.z_differential(Zd)
        Lse_r, Qse_r = emlib.lq(f, zse_r)
        Lse_d, Qse_d = emlib.lq(f, zse_d)
        Ldi_d, Qdi_d = emlib.lq(f, zdi_d)
        with open(os.path.join(res, "inductor_%s_lq.csv" % g), "w", newline="") as fh:
            wcsv = csv.writer(fh)
            wcsv.writerow(
                [
                    "f_hz",
                    "l_se_raw_h", "q_se_raw",
                    "l_se_h", "q_se", "re_zse_ohm", "im_zse_ohm",
                    "l_diff_h", "q_diff", "re_zdiff_ohm", "im_zdiff_ohm",
                ]
            )
            for i in range(len(f)):
                wcsv.writerow(
                    [
                        "%.10g" % f[i],
                        "%.6g" % Lse_r[i], "%.6g" % Qse_r[i],
                        "%.6g" % Lse_d[i], "%.6g" % Qse_d[i],
                        "%.6g" % zse_d[i].real, "%.6g" % zse_d[i].imag,
                        "%.6g" % Ldi_d[i], "%.6g" % Qdi_d[i],
                        "%.6g" % zdi_d[i].real, "%.6g" % zdi_d[i].imag,
                    ]
                )

        row = {"geometry": g}
        row.update({k: "%.6g" % v for k, v in scalars(f, Zd).items()})
        gj = json.load(open(os.path.join(root, "gds", "inductor_%s.json" % g)))
        row.update(
            {
                "w_um": gj["w_um"], "s_um": gj["s_um"],
                "d_um": gj["d_um"], "nr_r": gj["nr_r"],
                "l_port1_ph": "%.4g" % (Lport[0] * 1e12),
                "l_port2_ph": "%.4g" % (Lport[1] * 1e12),
            }
        )
        summary_rows.append(row)
        print(
            "%-4s L_se(1G)=%8.4g nH  Q_se(1G)=%6.3g  Q_se(10G)=%6.3g  SRF_se=%7.4g GHz"
            % (
                g,
                float(row["l_se_1g"]) * 1e9,
                float(row["q_se_1g"]),
                float(row["q_se_10g"]),
                float(row["srf_se_hz"]) / 1e9,
            )
        )

    if summary_rows:
        keys = list(summary_rows[0].keys())
        with open(os.path.join(res, "em_summary.csv"), "w", newline="") as fh:
            wcsv = csv.DictWriter(fh, fieldnames=keys)
            wcsv.writeheader()
            for r in summary_rows:
                wcsv.writerow(r)

    # ------------------------------------------------------------ convergence
    conv = os.path.join(res, "convergence")
    variants = [("baseline", os.path.join(res, "inductor_p1"), os.path.join(res, "inductor_p1.s2p"))]
    for name in ("p1_mesh0p5", "p1_margin400"):
        d = os.path.join(conv, name)
        if os.path.isdir(d):
            variants.append((name, d, d + ".s2p"))
    rows = []
    for name, d, s2p in variants:
        if not os.path.isfile(s2p):
            continue
        f, S, Z, Zd, z0, Lport, pinfo = load_run(d, s2p)
        r = {"variant": name}
        meta = json.load(open(os.path.join(d, "run_meta.json")))
        r["refined_cellsize_um"] = meta["settings"]["refined_cellsize"]
        r["margin_um"] = meta["settings"]["margin"]
        r["wall_seconds"] = meta.get("wall_seconds", "")
        r.update({k: "%.6g" % v for k, v in scalars(f, Zd).items()})
        rows.append(r)
    if len(rows) > 1:
        base = rows[0]
        for r in rows:
            for k in ("l_se_1g", "q_se_10g", "srf_se_hz", "l_se_10g", "q_se_1g"):
                r["d_%s_pct" % k] = "%.3g" % (
                    100.0 * (float(r[k]) - float(base[k])) / float(base[k])
                )
        keys = list(rows[0].keys())
        with open(os.path.join(res, "convergence.csv"), "w", newline="") as fh:
            wcsv = csv.DictWriter(fh, fieldnames=keys)
            wcsv.writeheader()
            for r in rows:
                wcsv.writerow(r)
        print("\nconvergence (vs baseline mesh %s um / margin %s um):"
              % (base["refined_cellsize_um"], base["margin_um"]))
        for r in rows[1:]:
            print(
                "  %-14s dL(1G)=%+7s %%  dQ(10G)=%+7s %%  dSRF=%+7s %%"
                % (r["variant"], r["d_l_se_1g_pct"], r["d_q_se_10g_pct"], r["d_srf_se_hz_pct"])
            )


if __name__ == "__main__":
    main()

