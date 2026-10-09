#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fit a lumped `.subckt inductor la lb sub` to the openEMS extraction.

TOPOLOGY.  Element-for-element the same 2-pi topology that
../sg13g2_inductor_analytic.spice uses -- deliberately, so that every fitted
number can be read directly against that model's analytic value for the *same*
element, and the extraction-vs-analytic delta comes out as a per-element ratio
rather than as an opaque black-box difference:

  la o--[ Rser ]--[ 10-section R||L ladder ]--[ Lmain ]--o lb
          |        `----------- Cs -----------'          |
       [Cox]                                          [Cox]
          |                                              |
    [Rsub||Csub]                                   [Rsub||Csub]
          |                                              |
          +--------------------o sub --------------------+

FIT.  The 2-port splits exactly into a series and a shunt admittance for a
symmetric pi, so the fit splits too and each half is small and well-conditioned:

  Y_ser(f) = 1/Z_branch(Rser, Rlad, L1, Ltot) + j w Cs      (5 parameters)
  Y_sh(f)  = shunt(Cox, Rsub, Csub)                          (3 parameters)

Residuals are relative-with-a-floor, |Y_model - Y_meas| / (|Y_meas| + 0.05
max|Y_meas|), so a null in either admittance cannot dominate the objective.

OUTPUT.  `sg13g2_inductor_em.spice`, a drop-in replacement for the analytic
model on the same SG13G2_IND_MODEL_LIB interface.  It is NOT a pure lookup
table: it recomputes the analytic model's geometry-driven element values and
scales each by the fitted correction factor for the nearest extracted turn
count.  That keeps the corner (`mc_rsh`, `mc_rsub`) and temperature (`tc1`)
behaviour of the analytic model -- which the EM run, done at one process point
and one temperature, cannot supply -- while making the *level* of every element
the EM-extracted one at the three geometries that were actually extracted.
"""

import argparse
import csv
import json
import os
import sys

import numpy as np
from scipy.optimize import least_squares

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emlib  # noqa: E402
from postprocess import load_run  # noqa: E402

GEOMS = ["p1", "p13", "p11"]

# Fit band.  Lower edge: below ~0.3 GHz the Gaussian excitation carries little
# energy and the extracted Z is noisy.  Upper edge: 30 GHz, but never above
# SRF_MARGIN x the device's own extracted self-resonance -- a single-pi lumped
# network is not entitled to describe a 2.5 mm conductor past its first
# resonance, and letting the fit chase points there wrecks the sub-resonance
# accuracy that a tank design actually uses.  The same limit the analytic model
# states for itself ("valid ... only below the device's own SRF") is therefore
# enforced here rather than asserted.
FIT_FLO = 0.3e9
FIT_FHI = 30e9
SRF_MARGIN = 0.85

# --- the analytic model's own element values, recomputed here ---------------
# Transcribed from ../sg13g2_inductor_analytic.spice; that file is the
# authority for every constant and cites the PDK source of each.  They are
# recomputed rather than parsed so this script does not silently drift if that
# file's .param names change -- the emitted SPICE below carries the same
# constants and any mismatch shows up immediately in compare_analytic.py.
MU0 = 1.25663706212e-6
EPS0 = 8.8541878128e-12
PISQ = 9.86960440108936
KOCT = 3.31370849898476
AOCT = 0.828427124746190
TTM2 = 3.000e-6
RSH2 = 11.0e-3
RSH1 = 18.0e-3
DW2 = -0.140e-6
RTV2 = 1.1
CASUB = 3.233e-6
CPSUB = 31.175e-12
CA21 = 13.0e-6
RHOSUB = 0.5
EPSSI = 11.9
GRID = 0.01e-6


def analytic_elements(w, s, d, n):
    pitch = s + w + GRID
    din = d
    dout = d + 2 * (n - 1) * pitch + 2 * w
    davg = (din + dout) / 2
    fill = (dout - din) / (dout + din)
    ln = KOCT * n * (d + w + (n - 1) * pitch)
    weff = w + DW2
    lmw = 2.25 * MU0 * n * n * davg / (1 + 3.55 * fill)
    rdc = RSH2 * ln / weff
    lu = MU0 * ln * TTM2 / (2 * weff)
    l1 = lu / PISQ
    nvia = np.floor((w / 1e-6 + 0.06) / 1.96)
    narr = 2 * n * min(n - 1, 1)
    ltm1 = 2 * (1.70711 * w + 0.9143 * s)
    rcros = narr * RTV2 / (nvia * nvia) + (n - 1) * RSH1 * ltm1 / weff + 1e-9
    novl = 2 * (n - 1)
    cs = novl * weff * weff * CA21 + 1e-21
    aband = AOCT * (dout * dout - din * din)
    edge = KOCT * (dout + din)
    coxh = (aband * CASUB + edge * CPSUB) / 2
    aout = AOCT * dout * dout
    aeq = np.sqrt(aout / np.pi)
    rsi = 1.41421356237 * RHOSUB / (4 * aeq)
    csi = EPS0 * EPSSI * RHOSUB / rsi
    return {
        "Rser": rdc + rcros, "Rdc_only": rdc, "Rcros": rcros,
        "Rlad": 2 * rdc, "L1": l1, "Ltot": lmw,
        "Cs": cs, "Cox": coxh, "Rsub": rsi, "Csub": csi,
        "len_m": ln, "dout_m": dout,
    }


# ------------------------------------------------------------------- fitting
def _resid(model, meas, floor_frac=0.02):
    floor = floor_frac * np.max(np.abs(meas))
    r = (model - meas) / (np.abs(meas) + floor)
    return np.concatenate([r.real, r.imag])


def fit_series(f, ys_meas, guess):
    # Fit on the series IMPEDANCE, not the admittance: below resonance |Zser|
    # is smooth and monotonic, so a relative residual on it weights the whole
    # band evenly.  On Y it does not -- |Y| collapses at the series resonance
    # and the few points near it then dominate the objective and pull the
    # low-frequency R and L away by tens of percent.
    zs_meas = 1.0 / ys_meas
    lo = np.array([1e-3, 1e-3, 1e-15, 1e-12, 1e-18])
    hi = np.array([1e4, 1e6, 1e-6, 1e-6, 1e-12])
    x0 = np.array([guess["Rser"], guess["Rlad"], guess["L1"], guess["Ltot"], guess["Cs"]])
    x0 = np.clip(x0, lo * 1.001, hi * 0.999)

    def fun(lx):
        Rser, Rlad, L1, Ltot, Cs = np.exp(lx)
        return _resid(1.0 / emlib.y_series(f, Rser, Rlad, L1, Ltot, Cs), zs_meas)

    sol = least_squares(
        fun, np.log(x0), bounds=(np.log(lo), np.log(hi)),
        xtol=1e-14, ftol=1e-14, gtol=1e-14, max_nfev=20000,
    )
    Rser, Rlad, L1, Ltot, Cs = np.exp(sol.x)
    return {"Rser": Rser, "Rlad": Rlad, "L1": L1, "Ltot": Ltot, "Cs": Cs}, sol


def fit_shunt(f, yh_meas, guess):
    lo = np.array([1e-18, 1e-2, 1e-18])
    hi = np.array([1e-9, 1e7, 1e-9])
    x0 = np.clip(
        np.array([guess["Cox"], guess["Rsub"], guess["Csub"]]), lo * 1.001, hi * 0.999
    )

    def fun(lx):
        Cox, Rsub, Csub = np.exp(lx)
        return _resid(emlib.y_shunt(f, Cox, Rsub, Csub), yh_meas)

    sol = least_squares(
        fun, np.log(x0), bounds=(np.log(lo), np.log(hi)),
        xtol=1e-14, ftol=1e-14, gtol=1e-14, max_nfev=20000,
    )
    Cox, Rsub, Csub = np.exp(sol.x)
    return {"Cox": Cox, "Rsub": Rsub, "Csub": Csub}, sol


def band_errors(f, Zem, Zfit, flo, fhi):
    m = (f >= flo) & (f <= fhi)
    zse_em, zse_fit = emlib.z_single_ended(Zem)[m], emlib.z_single_ended(Zfit)[m]
    Lem, Qem = emlib.lq(f[m], zse_em)
    Lfi, Qfi = emlib.lq(f[m], zse_fit)
    def rel(a, b):
        return 100.0 * np.abs(a - b) / np.abs(b)
    return {
        "band_ghz": "%g-%g" % (flo / 1e9, fhi / 1e9),
        "max_rel_err_zse_pct": float(np.max(rel(zse_fit, zse_em))),
        "rms_rel_err_zse_pct": float(np.sqrt(np.mean(rel(zse_fit, zse_em) ** 2))),
        "max_rel_err_L_pct": float(np.max(rel(Lfi, Lem))),
        "rms_rel_err_L_pct": float(np.sqrt(np.mean(rel(Lfi, Lem) ** 2))),
        "max_rel_err_Q_pct": float(np.max(rel(Qfi, Qem))),
        "rms_rel_err_Q_pct": float(np.sqrt(np.mean(rel(Qfi, Qem) ** 2))),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--model-out", required=True)
    args = ap.parse_args()
    root, res = args.dir, os.path.join(args.dir, "results")

    fits = {}
    for g in GEOMS:
        s2p = os.path.join(res, "inductor_%s.s2p" % g)
        datadir = os.path.join(res, "inductor_%s" % g)
        if not os.path.isfile(s2p):
            print("MISSING %s" % s2p)
            continue
        gj = json.load(open(os.path.join(root, "gds", "inductor_%s.json" % g)))
        f, S, Z, Zd, z0, Lport, _ = load_run(datadir, s2p)
        Y = emlib.z2y(Zd)
        ys_meas, yh_meas = emlib.measured_series_shunt(Y)

        srf_em = emlib.srf(f, emlib.z_single_ended(Zd))
        fhi = FIT_FHI if not np.isfinite(srf_em) else min(FIT_FHI, SRF_MARGIN * srf_em)
        m = (f >= FIT_FLO) & (f <= fhi)
        ana = analytic_elements(
            gj["w_um"] * 1e-6, gj["s_um"] * 1e-6, gj["d_um"] * 1e-6, gj["nr_r"]
        )
        ser, sol_s = fit_series(f[m], ys_meas[m], ana)
        sh, sol_h = fit_shunt(f[m], yh_meas[m], ana)

        p = dict(ser)
        p["Rdc"] = p.pop("Rser")
        p.update(sh)
        Yfit = emlib.model_Y(f, p)
        Zfit = np.linalg.inv(Yfit)

        entry = {
            "geometry": g,
            "w_um": gj["w_um"], "s_um": gj["s_um"], "d_um": gj["d_um"],
            "nr_r": gj["nr_r"],
            "fitted": {**ser, **sh},
            "analytic": {k: v for k, v in ana.items()},
            "ratio_fitted_over_analytic": {
                k: ser.get(k, sh.get(k)) / ana[k]
                for k in ("Rser", "Rlad", "L1", "Ltot", "Cs", "Cox", "Rsub", "Csub")
            },
            "fit_band_hz": [FIT_FLO, float(fhi)],
            "srf_em_hz": float(srf_em),
            "srf_fitted_hz": float(emlib.srf(f, emlib.z_single_ended(Zfit))),
            "series_cost": float(sol_s.cost),
            "shunt_cost": float(sol_h.cost),
            "residual": {
                "fit_band": band_errors(f, Zd, Zfit, FIT_FLO, fhi),
                "full_extraction_band": band_errors(f, Zd, Zfit, 0.1e9, 30e9),
            },
        }
        fits[g] = entry
        r = entry["residual"]["fit_band"]
        print(
            "%-4s fit band %s GHz: |Zse| rms %.2f%% max %.2f%% | "
            "L rms %.2f%% | Q rms %.2f%% | SRF EM %.3g vs fit %.3g GHz"
            % (g, r["band_ghz"], r["rms_rel_err_zse_pct"], r["max_rel_err_zse_pct"],
               r["rms_rel_err_L_pct"], r["rms_rel_err_Q_pct"],
               srf_em / 1e9, entry["srf_fitted_hz"] / 1e9)
        )

        # per-geometry fitted-vs-EM curve, as evidence a reader can plot
        zse_em = emlib.z_single_ended(Zd)
        zse_fi = emlib.z_single_ended(Zfit)
        Lem, Qem = emlib.lq(f, zse_em)
        Lfi, Qfi = emlib.lq(f, zse_fi)
        with open(os.path.join(root, "fit", "fit_residual_%s.csv" % g), "w", newline="") as fh:
            wcsv = csv.writer(fh)
            wcsv.writerow(["f_hz", "l_em_h", "l_fit_h", "q_em", "q_fit",
                           "re_zse_em", "re_zse_fit", "im_zse_em", "im_zse_fit"])
            for i in range(len(f)):
                wcsv.writerow(["%.10g" % f[i]] + ["%.6g" % v for v in
                              (Lem[i], Lfi[i], Qem[i], Qfi[i],
                               zse_em[i].real, zse_fi[i].real,
                               zse_em[i].imag, zse_fi[i].imag)])

    with open(os.path.join(root, "fit", "fit_parameters.json"), "w") as fh:
        json.dump(fits, fh, indent=2, sort_keys=True)
        fh.write("\n")

    with open(os.path.join(root, "fit", "fit_summary.csv"), "w", newline="") as fh:
        wcsv = csv.writer(fh)
        wcsv.writerow(
            ["geometry", "nr_r", "element", "analytic", "em_fitted", "ratio_em_over_analytic"]
        )
        for g, e in fits.items():
            for k in ("Rser", "Rlad", "L1", "Ltot", "Cs", "Cox", "Rsub", "Csub"):
                v = e["fitted"].get(k)
                wcsv.writerow([g, e["nr_r"], k, "%.6g" % e["analytic"][k],
                               "%.6g" % v, "%.5g" % (v / e["analytic"][k])])

    emit_spice(args.model_out, fits, root)
    print("wrote", args.model_out)


# --------------------------------------------------------------- SPICE output
def emit_spice(path, fits, root):
    def k(g, name):
        return fits[g]["ratio_fitted_over_analytic"][name]

    # nr_r selects the geometry: the three extracted devices have 1, 4 and 5
    # turns respectively, so a single ternary chain on nr_r is unambiguous.
    def sel(name):
        return (
            "{nr_r <= 1 ? %.6g : (nr_r <= 4 ? %.6g : %.6g)}"
            % (k("p1", name), k("p11", name), k("p13", name))
        )

    prov = {g: {"w_um": e["w_um"], "s_um": e["s_um"], "d_um": e["d_um"], "nr_r": e["nr_r"],
                "fit_band_hz": e["fit_band_hz"],
                "residual_fit_band_rms_Zse_pct":
                    e["residual"]["fit_band"]["rms_rel_err_zse_pct"]}
            for g, e in fits.items()}

    hdr = f"""*******************************************************************************
* sg13g2_inductor_em.spice -- SG13G2 spiral inductor, LUMPED MODEL FITTED TO AN
* openEMS ELECTROMAGNETIC EXTRACTION OF THE PDK'S OWN INDUCTOR PCELL.
*
*   .subckt inductor la lb sub  w=<m> s=<m> d=<m> nr_r=<turns>
*
* GENERATED FILE -- do not edit by hand.  Produced by
* em-extraction/scripts/fit_lumped.py from the S-parameters in
* em-extraction/results/, by
*
*   sim/inductor-model/em-extraction/run_extraction.sh
*
* Same three terminals, same instance parameters and same corner knobs
* (mc_rsh, mc_rsub) as sg13g2_inductor_analytic.spice, so it is a drop-in
* replacement on the SG13G2_IND_MODEL_LIB interface.
*
* WHAT WAS EXTRACTED, AND HOW
* ---------------------------
* Solver     openEMS (FDTD), IHP's own documented EM route for this PDK.
* Geometry   the PDK's own KLayout inductor PCell (library SG13_dev, cell
*            inductor2), instantiated headlessly -- not a redrawn octagon.
* Stack      IHP's own openEMS stackup libs.tech/openems/openems_ihp_sg13g2/
*            workflow/SG13G2.xml (sigma_TopMetal2 = 3.03e7 S/m, i.e. the same
*            11 mOhm/sq typ. sheet resistance the analytic model uses;
*            sigma_substrate = 2 S/m, i.e. the same 50 Ohm*cm typ. RSBLK).
* Ports      2 lumped z-ports, LA and LB, each referenced to a local substrate
*            ground patch = the subcircuit's `sub` node.  Port parasitic
*            inductance de-embedded (Terman flat-ribbon, per IHP's own
*            scripts/deembed_openEMS.py method).
* Band       0.1 .. 30 GHz; the lumped fit is over 0.3 .. 30 GHz.
* Extracted  {json.dumps(prov, sort_keys=True)}
*
* WHAT THIS FILE IS NOT
* ---------------------
* 1. It is not an EM lookup table for arbitrary geometry.  Three geometries
*    were extracted.  Every element here is the ANALYTIC model's own
*    geometry-driven expression multiplied by the correction factor the EM fit
*    demanded at the nearest extracted turn count (nr_r <= 1 -> the 1-turn
*    device, nr_r <= 4 -> the 4-turn device, else the 5-turn device).  At the
*    three extracted geometries this reproduces the extraction to the fit
*    residual quoted above.  AWAY from them it is an EM-corrected analytic
*    model, and the correction is an extrapolation that nothing here validates.
* 2. It is not a PVT extraction.  The EM solve was run at ONE process point
*    (typ. metal and substrate conductivity, as shipped in IHP's EM stackup)
*    and ONE temperature.  All corner and temperature dependence in this file
*    is inherited unchanged from the analytic model's physics (mc_rsh, mc_rsub
*    and the tc1 coefficients).  A corner number from this file is the EM level
*    with the analytic model's *scaling*, not an EM corner.
* 3. It is not silicon.  No measured device backs any of it.
*
* Full method, mesh/boundary convergence data and the extraction-vs-analytic
* delta: sim/inductor-model/em-extraction/README.md.
*
* SPDX-License-Identifier: Apache-2.0
*******************************************************************************

.subckt inductor la lb sub

* ---- instance parameters (names fixed by the PDK's xschem/LVS netlists) ----
.param w = {{2.0e-6}}
.param s = {{2.1e-6}}
.param d = {{15.48e-6}}
.param nr_r = {{1}}

* ---- corner knobs, same meaning as in sg13g2_inductor_analytic.spice -------
.param mc_rsh = {{1.0}}
.param mc_rsub = {{1.0}}

* ---- EM correction factors (fitted / analytic), selected by turn count -----
.param kem_r    = {sel('Rser')}
.param kem_rlad = {sel('Rlad')}
.param kem_l1   = {sel('L1')}
.param kem_l    = {sel('Ltot')}
.param kem_cs   = {sel('Cs')}
.param kem_cox  = {sel('Cox')}
.param kem_rsi  = {sel('Rsub')}
.param kem_csi  = {sel('Csub')}

* ---- physical constants ----------------------------------------------------
.param ind_mu0 = {{1.25663706212e-6}}
.param ind_eps0 = {{8.8541878128e-12}}
.param ind_pisq = {{9.86960440108936}}
.param ind_koct = {{3.31370849898476}}
.param ind_aoct = {{0.828427124746190}}

* ---- PDK process constants (transcribed from sg13g2_inductor_analytic.spice,
*      which cites the PDK source of each) -----------------------------------
.param ind_ttm2 = {{3.000e-6}}
.param ind_rsh2 = {{11.0e-3}}
.param ind_rsh1 = {{18.0e-3}}
.param ind_tc2 = {{3.8e-3}}
.param ind_dw2 = {{-0.140e-6}}
.param ind_rtv2 = {{1.1}}
.param ind_casub = {{3.233e-6}}
.param ind_cpsub = {{31.175e-12}}
.param ind_ca21 = {{13.0e-6}}
.param ind_rhosub = {{0.5}}
.param ind_epssi = {{11.9}}
.param ind_grid = {{0.01e-6}}

* ---- geometry, read off the PCell ------------------------------------------
.param ind_n = {{nr_r}}
.param ind_pitch = {{s + w + ind_grid}}
.param ind_din = {{d}}
.param ind_dout = {{d + 2*(ind_n-1)*ind_pitch + 2*w}}
.param ind_davg = {{(ind_din + ind_dout)/2}}
.param ind_fill = {{(ind_dout - ind_din)/(ind_dout + ind_din)}}
.param ind_len = {{ind_koct*ind_n*(d + w + (ind_n-1)*ind_pitch)}}
.param ind_weff = {{w + ind_dw2}}

* ---- analytic element values (the EM correction multiplies these) ----------
.param ind_lmw = {{2.25*ind_mu0*ind_n*ind_n*ind_davg/(1 + 3.55*ind_fill)}}
.param ind_rshT = {{ind_rsh2*mc_rsh}}
.param ind_rdc = {{ind_rshT*ind_len/ind_weff}}
.param ind_nvia = {{floor((w/1e-6 + 0.06)/1.96)}}
.param ind_narr = {{2*ind_n*min(ind_n-1,1)}}
.param ind_ltm1 = {{2*(1.70711*w + 0.9143*s)}}
.param ind_rcros = {{ind_narr*ind_rtv2/(ind_nvia*ind_nvia) + (ind_n-1)*ind_rsh1*mc_rsh*ind_ltm1/ind_weff + 1e-9}}
.param ind_lu = {{ind_mu0*ind_len*ind_ttm2/(2*ind_weff)}}
.param ind_novl = {{2*(ind_n-1)}}
.param ind_cs0 = {{ind_novl*ind_weff*ind_weff*ind_ca21 + 1e-21}}
.param ind_aband = {{ind_aoct*(ind_dout*ind_dout - ind_din*ind_din)}}
.param ind_edge = {{ind_koct*(ind_dout + ind_din)}}
.param ind_coxh0 = {{(ind_aband*ind_casub + ind_edge*ind_cpsub)/2}}
.param ind_rhos = {{ind_rhosub*mc_rsub}}
.param ind_aout = {{ind_aoct*ind_dout*ind_dout}}
.param ind_aeq = {{sqrt(ind_aout/3.14159265358979)}}
.param ind_rsi0 = {{1.41421356237*ind_rhos/(4*ind_aeq)}}
.param ind_csi0 = {{ind_eps0*ind_epssi*ind_rhos/ind_rsi0}}

* ---- EM-corrected element values -------------------------------------------
* Rser carries mc_rsh and tc1 so that the corner/temperature scaling of the
* metal loss survives; the EM correction sets its level at 27 C, typ.
.param em_rser = {{kem_r*(ind_rdc + ind_rcros)}}
.param em_rlad = {{kem_rlad*2*ind_rdc}}
.param em_l1 = {{kem_l1*ind_lu/ind_pisq}}
.param em_lm1 = {{em_l1}}
.param em_lm2 = {{em_l1/4}}
.param em_lm3 = {{em_l1/9}}
.param em_lm4 = {{em_l1/16}}
.param em_lm5 = {{em_l1/25}}
.param em_lm6 = {{em_l1/36}}
.param em_lm7 = {{em_l1/49}}
.param em_lm8 = {{em_l1/64}}
.param em_lm9 = {{em_l1/81}}
.param em_lm10 = {{em_l1/100}}
.param em_lint = {{em_lm1+em_lm2+em_lm3+em_lm4+em_lm5+em_lm6+em_lm7+em_lm8+em_lm9+em_lm10}}
.param em_ltot = {{kem_l*ind_lmw}}
.param em_lmain = {{em_ltot - em_lint}}
.param em_cs = {{kem_cs*ind_cs0}}
.param em_coxh = {{kem_cox*ind_coxh0}}
.param em_rsi = {{kem_rsi*ind_rsi0}}
.param em_csi = {{kem_csi*ind_csi0}}

* ---- netlist ---------------------------------------------------------------
Rser    la    n02  r={{em_rser}}  tc1={{ind_tc2}}
Rk1  n02 n03 r={{em_rlad}} tc1={{ind_tc2}}
Lk1  n02 n03 {{em_lm1}}
Rk2  n03 n04 r={{em_rlad}} tc1={{ind_tc2}}
Lk2  n03 n04 {{em_lm2}}
Rk3  n04 n05 r={{em_rlad}} tc1={{ind_tc2}}
Lk3  n04 n05 {{em_lm3}}
Rk4  n05 n06 r={{em_rlad}} tc1={{ind_tc2}}
Lk4  n05 n06 {{em_lm4}}
Rk5  n06 n07 r={{em_rlad}} tc1={{ind_tc2}}
Lk5  n06 n07 {{em_lm5}}
Rk6  n07 n08 r={{em_rlad}} tc1={{ind_tc2}}
Lk6  n07 n08 {{em_lm6}}
Rk7  n08 n09 r={{em_rlad}} tc1={{ind_tc2}}
Lk7  n08 n09 {{em_lm7}}
Rk8  n09 n10 r={{em_rlad}} tc1={{ind_tc2}}
Lk8  n09 n10 {{em_lm8}}
Rk9  n10 n11 r={{em_rlad}} tc1={{ind_tc2}}
Lk9  n10 n11 {{em_lm9}}
Rk10 n11 n12 r={{em_rlad}} tc1={{ind_tc2}}
Lk10 n11 n12 {{em_lm10}}

Lmain   n12   lb   {{em_lmain}}
Cser    la    lb   {{em_cs}}

Coxa    la    n20  {{em_coxh}}
Rsia    n20   sub  r={{em_rsi}}
Csia    n20   sub  {{em_csi}}
Coxb    lb    n21  {{em_coxh}}
Rsib    n21   sub  r={{em_rsi}}
Csib    n21   sub  {{em_csi}}

.ends inductor
"""
    with open(path, "w") as fh:
        fh.write(hdr)


if __name__ == "__main__":
    main()
