#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""`post` stage: de-embed the p1 runs, report L/Q/Z/SRF at the three band
frequencies, and evaluate the mesh and margin convergence budgets.

Adapted (p1 only, three band frequencies, declared budgets) from the sibling
`postprocess.py`, pinned in ../INPUTS.json (original under ../upstream/).

Reads   <dir>/results/inductor_p1{.s2p,/port_information.json,/run_meta.json}
        <dir>/results/convergence/p1_mesh0p5{.s2p,/...}
        <dir>/results/convergence/p1_margin400{.s2p,/...}
Writes  <dir>/results/p1_metrics.json  p1_lq.csv  p1_deembedded.s2p

Exit codes: 0 metrics written; 2 malformed/inconsistent data (nothing is
written, any previous metrics file is removed so stale success cannot
survive); 3 required solver output missing.
"""

import argparse
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emlib  # noqa: E402
import p1chain as C  # noqa: E402

# settings that must be identical across the three runs except the one varied
FIXED_SETTINGS = ("fstart", "fstop", "numfreq", "energy_limit", "cells_per_wavelength",
                  "excite_portnumbers", "Boundaries", "merge_polygon_size", "unit")
VARIANTS = {
    # name: (subpath of results, expected refined_cellsize, expected margin)
    "baseline": ("inductor_p1", 1.0, 200.0),
    "mesh0p5": ("convergence/p1_mesh0p5", 0.5, 200.0),
    "margin400": ("convergence/p1_margin400", 1.0, 400.0),
}


def jnum(x):
    """JSON-safe number: inf/nan become strings."""
    if isinstance(x, (complex, np.complexfloating)):
        return {"re": jnum(x.real), "im": jnum(x.imag)}
    if x is None:
        return None
    x = float(x)
    if np.isposinf(x):
        return "inf"
    if np.isnan(x):
        return "nan"
    return x


def load_variant(res, name):
    sub, cs, mg = VARIANTS[name]
    d = os.path.join(res, sub)
    s2p = d + ".s2p"
    if not os.path.isfile(s2p):
        raise FileNotFoundError(s2p)
    with open(os.path.join(d, "port_information.json")) as fh:
        pinfo = json.load(fh)
    with open(os.path.join(d, "run_meta.json")) as fh:
        meta = json.load(fh)
    st = meta["settings"]
    if abs(st["refined_cellsize"] - cs) > 1e-12 or abs(st["margin"] - mg) > 1e-12:
        raise C.DataError("%s: run_meta cellsize/margin (%s/%s) != expected (%s/%s)"
                          % (name, st["refined_cellsize"], st["margin"], cs, mg))
    if st["numfreq"] != C.EXPECTED_NUMFREQ or abs(st["fstop"] - C.SRF_CEILING_HZ) > 1:
        raise C.DataError("%s: sweep is not the declared 0-30 GHz / 601 samples" % name)
    f, S, z0 = C.read_snp_strict(s2p)
    if len(f) != C.EXPECTED_NUMFREQ:
        raise C.DataError("%s: %d samples, expected %d" % (name, len(f), C.EXPECTED_NUMFREQ))
    Lport = emlib.port_inductances(pinfo)
    tab = C.band_table(f, S, z0, Lport)
    return {"f": f, "S": S, "z0": z0, "Lport": Lport, "meta": meta, "tab": tab,
            "s2p": s2p, "dir": d}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    args = ap.parse_args()
    res = os.path.join(args.dir, "results")
    out_json = os.path.join(res, "p1_metrics.json")
    if os.path.exists(out_json):
        os.remove(out_json)
    runs = {}
    try:
        for name in VARIANTS:
            runs[name] = load_variant(res, name)
        base = runs["baseline"]
        for name in ("mesh0p5", "margin400"):
            for k in FIXED_SETTINGS:
                if runs[name]["meta"]["settings"].get(k) != base["meta"]["settings"].get(k):
                    raise C.DataError("%s: setting %r differs from baseline (must be fixed)"
                                      % (name, k))
    except FileNotFoundError as exc:
        print("MISSING solver output: %s" % exc)
        return 3
    except (C.DataError, KeyError, json.JSONDecodeError) as exc:
        print("DATA ERROR: %s" % exc)
        return 2

    base = runs["baseline"]
    rows = base["tab"]["rows"]
    mesh_e, mesh_ok, mesh_inv = C.compare_variants(rows, runs["mesh0p5"]["tab"]["rows"])
    marg_e, marg_ok, marg_inv = C.compare_variants(rows, runs["margin400"]["tab"]["rows"])

    f = base["tab"]["f"]
    # de-embedded Touchstone (the data the fit and the ngspice comparison use)
    fd, Sd = C.deembedded_S(base["f"], base["S"], base["z0"], base["Lport"])
    C.write_snp(os.path.join(res, "p1_deembedded.s2p"), fd, Sd, base["z0"], comments=[
        "p1 (inductor2 w=8.22 s=3.29 d=47.65 nr_r=1) openEMS extraction, baseline run",
        "port parasitic L removed by Z-domain series subtraction; DC point dropped",
        "L_port = %.4g pH, %.4g pH" % tuple(base["Lport"] * 1e12)])
    with open(os.path.join(res, "p1_lq.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["f_hz", "re_zse_ohm", "im_zse_ohm", "l_se_h", "q_se",
                    "re_zdiff_ohm", "im_zdiff_ohm"])
        t = base["tab"]
        Ld, Qd = C.lq(f, t["zdiff"])
        for i in range(len(f)):
            w.writerow(["%.10g" % f[i], "%.6g" % t["zse"][i].real, "%.6g" % t["zse"][i].imag,
                        "%.6g" % t["L_se"][i], "%.6g" % t["Q_se"][i],
                        "%.6g" % t["zdiff"][i].real, "%.6g" % t["zdiff"][i].imag])

    def table(r):
        return [{k: jnum(v) for k, v in row.items()} for row in r]

    metrics = {
        "schema": "passive-p1/metrics/1",
        "geometry": {"cell": "inductor2", "w_um": 8.22, "s_um": 3.29, "d_um": 47.65, "nr_r": 1},
        "baseline_settings": base["meta"]["settings"],
        "solver": base["meta"]["solver"],
        "route": base["tab"]["route"],
        "z0_ohm": base["z0"],
        "port_inductance_ph": [float(x) * 1e12 for x in base["Lport"]],
        "band": table(rows),
        "srf_se": {k: jnum(v) if not isinstance(v, bool) else v
                   for k, v in base["tab"]["srf_se"].items()},
        "srf_diff": {k: jnum(v) if not isinstance(v, bool) else v
                     for k, v in base["tab"]["srf_diff"].items()},
        "variants": {n: table(r["tab"]["rows"]) for n, r in runs.items()},
        "variant_inputs": {n: {"s2p": os.path.relpath(r["s2p"], args.dir),
                               "s2p_sha256": emlib.sha256(r["s2p"]),
                               "run_meta_sha256": emlib.sha256(os.path.join(r["dir"], "run_meta.json")),
                               "port_information_sha256": emlib.sha256(os.path.join(r["dir"], "port_information.json")),
                               "gds_sha256": r["meta"].get("gds_sha256"),
                               "stackup_xml_sha256": r["meta"].get("stackup_xml_sha256"),
                               "wall_seconds": r["meta"].get("wall_seconds")}
                           for n, r in runs.items()},
        "convergence": {
            "mesh_1p0_vs_0p5": {"entries": [{k: jnum(v) if k != "status" else v for k, v in e.items()} for e in mesh_e],
                                "within_budget": mesh_ok, "invalid_denominator": mesh_inv},
            "margin_200_vs_400": {"entries": [{k: jnum(v) if k != "status" else v for k, v in e.items()} for e in marg_e],
                                  "within_budget": marg_ok, "invalid_denominator": marg_inv},
            "budget_L_pct": C.L_BUDGET_PCT, "budget_Q_pct": C.Q_BUDGET_PCT,
            "denominator": "finer mesh / larger domain result",
            "gated_quantity": "single-ended L and Q (differential reported alongside)",
        },
        "converged": bool(mesh_ok and marg_ok),
    }
    with open(out_json, "w") as fh:
        json.dump(metrics, fh, indent=2, sort_keys=True)
        fh.write("\n")
    for r in rows:
        print("%.2f GHz  Zse=%.4g%+.4gj ohm  L=%.4g pH  Q=%s"
              % (r["f_hz"] / 1e9, r["zse"].real, r["zse"].imag, r["l_se_h"] * 1e12, r["q_se"]))
    print("mesh budget:   %s" % ("WITHIN" if mesh_ok else "NOT MET (invalid=%s)" % mesh_inv))
    print("margin budget: %s" % ("WITHIN" if marg_ok else "NOT MET (invalid=%s)" % marg_inv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
