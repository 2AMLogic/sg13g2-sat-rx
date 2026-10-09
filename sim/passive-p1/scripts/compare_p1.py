#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""`compare` stage: ngspice fitted subcircuit vs de-embedded Touchstone.

Adapted in purpose (EM vs ngspice on the same port convention) from the
sibling `compare_analytic.py`; the implementation is new (a two-excitation
two-port deck, see p1chain.ngspice_two_port) so that S-parameters as well as
Z_se are compared.

Test fixture: one local `ngspice -b` AC run, LA = port 1, LB = port 2, `sub`
= node 0 (the same substrate reference as the EM ports), z0 from the
Touchstone header (S normalisation).  Z_se = 1/Y11 of the model vs
Z11 - Z12*Z21/Z22 of the de-embedded EM.

Writes <dir>/results/p1_compare.json.  Exit 0 if computed (verdict is made by
make_record.py), 3 inputs missing, 2 malformed.
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emlib  # noqa: E402
import p1chain as C  # noqa: E402


def compare(model_file, model_name, s2p_deembedded, workdir, params=""):
    f_em, S_em, z0 = C.read_snp_strict(s2p_deembedded)
    f_em_p, zse_em, _, route = C.impedances(f_em, S_em, z0)
    keep = f_em > 0
    f_em, S_em = f_em[keep], S_em[keep]
    fg, Y, S_mod, deck = C.ngspice_two_port(model_file, model_name, f_em, workdir, params, z0)
    zse_mod = 1.0 / Y[:, 0, 0]
    zr = C.zse_residuals(fg, zse_mod, f_em, zse_em)
    sr = C.s_residuals(fg, S_mod, f_em, S_em)
    return {"z0_ohm": z0, "zse": zr, "s": sr, "em_route": route,
            "fixture": "ngspice -b AC, LA/LB driven in one deck, sub=0, z0=%g, grid %.6g..%.6g Hz (%d pts)"
                       % (z0, fg[0], fg[-1], len(fg)),
            "pass_budget_pct": C.FIT_BUDGET_PCT,
            "pass": all(e["rel_err_pct"] <= C.FIT_BUDGET_PCT for e in zr["at_band"])}, deck


def jsonable(o):
    if isinstance(o, dict):
        return {k: jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (complex, np.complexfloating)):
        return {"re": float(o.real), "im": float(o.imag)}
    if isinstance(o, (np.floating, np.integer, np.bool_)):
        return o.item()
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    args = ap.parse_args()
    res = os.path.join(args.dir, "results")
    out = os.path.join(res, "p1_compare.json")
    if os.path.exists(out):
        os.remove(out)
    cand = os.path.join(args.dir, "fit", "p1_fit_candidate.spice")
    s2p = os.path.join(res, "p1_deembedded.s2p")
    if not (os.path.isfile(cand) and os.path.isfile(s2p)):
        print("MISSING fit candidate or de-embedded Touchstone")
        return 3
    try:
        r, deck = compare(cand, "p1_inductor_em", s2p, os.path.join(res, "compare_work"))
    except C.DataError as exc:
        print("DATA ERROR: %s" % exc)
        return 2
    r["inputs"] = {"candidate_sha256": emlib.sha256(cand), "deembedded_s2p_sha256": emlib.sha256(s2p),
                   "deck": os.path.relpath(deck, args.dir)}
    with open(out, "w") as fh:
        json.dump(jsonable(r), fh, indent=2, sort_keys=True)
        fh.write("\n")
    for e in r["zse"]["at_band"]:
        print("%.2f GHz |Zfit-ZEM|/|ZEM| = %.3f %%" % (e["f_hz"] / 1e9, e["rel_err_pct"]))
    print("band RMS %.3f %% max %.3f %%  -> %s" % (r["zse"]["rms_pct"], r["zse"]["max_pct"],
                                                  "within 5%" if r["pass"] else "EXCEEDS 5%"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
