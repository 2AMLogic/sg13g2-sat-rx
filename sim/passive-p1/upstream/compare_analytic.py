#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Record the extraction-vs-analytic delta on L, Q and SRF, per geometry.

This is the single most valuable output of issue #9: it converts the analytic
screening model's *asserted* error bars into *measured* ones.

Method.  Both SPICE models are driven by the same testbench the analytic model's
own known-answer check uses -- a 1 A AC current injected at LA with LB and `sub`
grounded, so V(la) = Z(f) -- at typ (mc_rsh = mc_rsub = 1) and 27 C, on the same
frequency grid the EM extraction produced.  The EM curve is the de-embedded
2-port collapsed to the same single-ended driving-point impedance
(Z11 - Z12*Z21/Z22).  Nothing is rescaled or aligned; the three curves are
compared point for point.

Writes:
  records/<record-id>-em-vs-analytic.csv    per geometry x frequency
  records/<record-id>-delta-summary.csv     the scalar delta table
  records/<record-id>.md                    the narrative record
  records/<record-id>-env.json              tool versions / provenance
"""

import argparse
import csv
import datetime
import json
import os
import platform
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emlib  # noqa: E402
from postprocess import load_run  # noqa: E402

GEOMS = [
    ("p1", 8.22, 3.29, 47.65, 1),
    ("p13", 6.10, 3.29, 110.11, 5),
    ("p11", 8.22, 3.74, 141.975, 4),
]
SPOT_F = [1e9, 2e9, 5e9, 10e9, 20e9]
FMIN, FMAX, DF = 1e8, 3e10, 5e7


def run_ngspice(model_lib, workdir):
    """Return f, {geom: Z(f)} for a `.subckt inductor` SPICE library."""
    npts = int(round((FMAX - FMIN) / DF)) + 1
    curve = os.path.join(workdir, "curve.csv")
    lines = [
        "* tb_em_vs_analytic -- driving-point Z of .subckt inductor, LB and sub grounded",
        '.include "%s"' % model_lib,
        ".temp 27",
    ]
    for name, w, s, d, n in GEOMS:
        lines += [
            "I%s 0 l%s dc 0 ac 1" % (name, name),
            "Ld%s l%s 0 1" % (name, name),
            "XL_%s l%s 0 0 inductor w=%gu s=%gu d=%gu nr_r=%d mc_rsh=1.0 mc_rsub=1.0"
            % (name, name, w, s, d, n),
        ]
    lines += [
        ".control",
        "set wr_singlescale",
        "set wr_vecnames",
        "ac lin %d %g %g" % (npts, FMIN, FMAX),
    ]
    vecs = []
    for name, *_ in GEOMS:
        lines += [
            "let zr_%s = real(v(l%s))" % (name, name),
            "let zi_%s = imag(v(l%s))" % (name, name),
        ]
        vecs += ["zr_%s" % name, "zi_%s" % name]
    lines += ["wrdata %s %s" % (curve, " ".join(vecs)), ".endc", ".end"]

    deck = os.path.join(workdir, "tb.spice")
    with open(deck, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(workdir, ".spiceinit"), "w") as fh:
        fh.write("set ngbehavior=hsa\nset skywaterpdk\n")
    r = subprocess.run(
        ["ngspice", "-b", deck], cwd=workdir, capture_output=True, text=True
    )
    if not os.path.isfile(curve):
        raise RuntimeError("ngspice produced no curve file:\n%s\n%s" % (r.stdout, r.stderr))
    a = np.genfromtxt(curve, names=True)
    f = a[a.dtype.names[0]]
    out = {}
    for i, (name, *_) in enumerate(GEOMS):
        out[name] = a["zr_%s" % name] + 1j * a["zi_%s" % name]
    return f, out, deck, r.stdout + r.stderr


def spot(f, y, f0):
    return emlib.at(f, y, f0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--analytic", required=True)
    ap.add_argument("--fitted", required=True)
    args = ap.parse_args()
    root, res = args.dir, os.path.join(args.dir, "results")
    recdir = os.path.join(root, "records")
    os.makedirs(recdir, exist_ok=True)

    repo = subprocess.run(
        ["git", "-C", root, "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip() or "nogit"
    record_id = "%s-%s" % (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S"), repo)

    with tempfile.TemporaryDirectory() as wd:
        f_ana, Z_ana, deck_a, log_a = run_ngspice(args.analytic, os.path.join(wd, "a") if os.makedirs(os.path.join(wd, "a"), exist_ok=True) or os.path.join(wd, "a") else wd)
        f_fit, Z_fit, deck_f, log_f = run_ngspice(args.fitted, os.path.join(wd, "f") if os.makedirs(os.path.join(wd, "f"), exist_ok=True) or os.path.join(wd, "f") else wd)
        with open(os.path.join(recdir, "%s-ngspice.txt" % record_id), "w") as fh:
            fh.write("=== analytic model ===\n" + log_a + "\n=== EM-fitted model ===\n" + log_f)

    rows = []
    summary = []
    for name, w, s, d, n in GEOMS:
        s2p = os.path.join(res, "inductor_%s.s2p" % name)
        if not os.path.isfile(s2p):
            print("MISSING %s" % s2p)
            continue
        fe, S, Z, Zd, z0, Lport, _ = load_run(os.path.join(res, "inductor_%s" % name), s2p)
        zse = emlib.z_single_ended(Zd)
        # put everything on the ngspice grid
        f = f_ana
        zem = np.interp(f, fe, zse.real) + 1j * np.interp(f, fe, zse.imag)
        za, zf = Z_ana[name], Z_fit[name]

        Lem, Qem = emlib.lq(f, zem)
        La, Qa = emlib.lq(f, za)
        Lf, Qf = emlib.lq(f, zf)
        for i in range(len(f)):
            rows.append(
                [name, "%.10g" % f[i]]
                + ["%.6g" % v for v in (Lem[i], La[i], Lf[i], Qem[i], Qa[i], Qf[i],
                                        zem[i].real, za[i].real, zf[i].real,
                                        zem[i].imag, za[i].imag, zf[i].imag)]
            )

        srf_em, srf_a, srf_f = (emlib.srf(f, z) for z in (zem, za, zf))
        row = {
            "geometry": name, "w_um": w, "s_um": s, "d_um": d, "nr_r": n,
            "srf_em_hz": srf_em, "srf_analytic_hz": srf_a, "srf_fitted_hz": srf_f,
            "d_srf_analytic_vs_em_pct": 100 * (srf_a - srf_em) / srf_em if np.isfinite(srf_em) else float("nan"),
        }
        for f0 in SPOT_F:
            g = "%dg" % int(round(f0 / 1e9))
            le, la_, lf = (spot(f, x, f0) for x in (Lem, La, Lf))
            qe, qa, qf = (spot(f, x, f0) for x in (Qem, Qa, Qf))
            row["l_em_%s_h" % g] = le
            row["l_analytic_%s_h" % g] = la_
            row["l_fitted_%s_h" % g] = lf
            row["d_l_analytic_vs_em_%s_pct" % g] = 100 * (la_ - le) / le
            row["d_l_fitted_vs_em_%s_pct" % g] = 100 * (lf - le) / le
            row["q_em_%s" % g] = qe
            row["q_analytic_%s" % g] = qa
            row["q_fitted_%s" % g] = qf
            row["d_q_analytic_vs_em_%s_pct" % g] = 100 * (qa - qe) / qe
            row["d_q_fitted_vs_em_%s_pct" % g] = 100 * (qf - qe) / qe
        summary.append(row)
        print(
            "%-4s  L(1G) EM %8.4g nH vs analytic %8.4g nH (%+6.1f %%) | "
            "Q(10G) EM %6.2f vs analytic %6.2f (%+6.1f %%) | SRF EM %s"
            % (
                name, row["l_em_1g_h"] * 1e9, row["l_analytic_1g_h"] * 1e9,
                row["d_l_analytic_vs_em_1g_pct"],
                row["q_em_10g"], row["q_analytic_10g"], row["d_q_analytic_vs_em_10g_pct"],
                ("%.2f GHz" % (srf_em / 1e9)) if np.isfinite(srf_em) else "none <30 GHz",
            )
        )

    with open(os.path.join(recdir, "%s-em-vs-analytic.csv" % record_id), "w", newline="") as fh:
        wcsv = csv.writer(fh)
        wcsv.writerow(
            ["geometry", "f_hz", "l_em_h", "l_analytic_h", "l_fitted_h",
             "q_em", "q_analytic", "q_fitted",
             "re_z_em", "re_z_analytic", "re_z_fitted",
             "im_z_em", "im_z_analytic", "im_z_fitted"]
        )
        wcsv.writerows(rows)

    if summary:
        keys = list(summary[0].keys())
        with open(os.path.join(recdir, "%s-delta-summary.csv" % record_id), "w", newline="") as fh:
            wcsv = csv.DictWriter(fh, fieldnames=keys)
            wcsv.writeheader()
            for r in summary:
                wcsv.writerow({k: ("%.6g" % v if isinstance(v, float) else v) for k, v in r.items()})

    env = {
        "record_id": record_id,
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "host": {"hostname": platform.node(), "platform": platform.platform()},
        "ngspice_version": subprocess.run(["ngspice", "--version"], capture_output=True, text=True).stdout.splitlines()[1:2],
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "models": {
            "analytic": {"path": os.path.relpath(args.analytic, root), "sha256": emlib.sha256(args.analytic)},
            "em_fitted": {"path": os.path.relpath(args.fitted, root), "sha256": emlib.sha256(args.fitted)},
        },
        "em_runs": {},
    }
    for name, *_ in GEOMS:
        rm = os.path.join(res, "inductor_%s" % name, "run_meta.json")
        if os.path.isfile(rm):
            m = json.load(open(rm))
            env["em_runs"][name] = {
                "solver": m["solver"], "settings": m["settings"],
                "gds_sha256": m["gds_sha256"],
                "stackup_xml_sha256": m["stackup_xml_sha256"],
                "wall_seconds": m.get("wall_seconds"),
                "host": m.get("host"),
            }
    with open(os.path.join(recdir, "%s-env.json" % record_id), "w") as fh:
        json.dump(env, fh, indent=2, sort_keys=True)
        fh.write("\n")

    fitj = os.path.join(root, "fit", "fit_parameters.json")
    fits = json.load(open(fitj)) if os.path.isfile(fitj) else {}
    conv = os.path.join(res, "convergence.csv")
    convrows = list(csv.DictReader(open(conv))) if os.path.isfile(conv) else []
    write_markdown(
        os.path.join(recdir, "%s.md" % record_id), record_id, summary, fits, convrows, env
    )

    with open(os.path.join(root, "results", "latest_record_id.txt"), "w") as fh:
        fh.write(record_id + "\n")
    print("record", record_id)


def _pct(x):
    return "n/a" if not np.isfinite(x) else "%+.1f %%" % x


def _ghz(x):
    return "none < 30 GHz" if not np.isfinite(x) else "%.2f GHz" % (x / 1e9)


def write_markdown(path, record_id, summary, fits, convrows, env):
    L = []
    A = L.append
    A("# Record `%s` — openEMS extraction of the SG13G2 spiral-inductor PCell" % record_id)
    A("")
    A("Generated by `sim/inductor-model/em-extraction/run_extraction.sh`. "
      "Append-only, per [`../../../README.md`](../../../README.md).")
    A("")
    A("## Method")
    A("")
    A("| | |")
    A("|---|---|")
    A("| Solver | `%s` |" % env["em_runs"].get("p1", {}).get("solver", {}).get("version_banner", "?"))
    A("| Engine | FDTD, time domain, Gaussian pulse, one run per excited port |")
    A("| Geometry | the PDK's own KLayout PCell `inductor2` (library `SG13_dev`), instantiated headlessly |")
    A("| Stack | IHP's own `libs.tech/openems/openems_ihp_sg13g2/workflow/SG13G2.xml`, sha256 `%s` |"
      % env["em_runs"].get("p1", {}).get("stackup_xml_sha256", "?")[:16])
    A("| Ports | 2 lumped z-ports (LA, LB) to a local SUBGND patch = the subcircuit's `sub` node |")
    A("| De-embedding | negative series L per port, Terman flat-ribbon, per IHP's own `scripts/deembed_openEMS.py` method |")
    s = env["em_runs"].get("p1", {}).get("settings", {})
    A("| Band | 0 .. %g GHz, %s points |" % (s.get("fstop", 0) / 1e9, s.get("numfreq", "?")))
    A("| Mesh | `refined_cellsize` %s um, `cells_per_wavelength` %s |"
      % (s.get("refined_cellsize"), s.get("cells_per_wavelength")))
    A("| Domain | GDS bbox + %s um margin, %s boundaries |"
      % (s.get("margin"), "/".join(sorted(set(s.get("Boundaries", []))))))
    A("| End criterion | residual energy %s dB |" % s.get("energy_limit"))
    A("| Host | `%s`, %s threads |"
      % (env["host"]["hostname"], s.get("numThreads", "auto")))
    A("")
    A("Process point: **one** — the typ. conductivities shipped in IHP's EM stackup "
      "(sigma_TopMetal2 = 3.03e7 S/m = 11 mOhm/sq; sigma_substrate = 2 S/m = 50 Ohm*cm), "
      "at one temperature. This is not a PVT extraction and nothing here should be read as one.")
    A("")
    A("## Extraction vs. the analytic screening model")
    A("")
    A("Both curves are the same driving-point impedance: 1 A AC into LA with LB "
      "and `sub` grounded, typ, 27 C. `d` = (analytic - EM) / EM.")
    A("")
    A("| Geometry | L(1 GHz) EM | L(1 GHz) analytic | dL | Q(1 GHz) EM | Q(1 GHz) analytic | dQ | Q(10 GHz) EM | Q(10 GHz) analytic | dQ | SRF EM | SRF analytic | dSRF |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in summary:
        A("| `%s` (%d turn%s) | %.4g nH | %.4g nH | %s | %.3g | %.3g | %s | %.3g | %.3g | %s | %s | %s | %s |"
          % (r["geometry"], r["nr_r"], "" if r["nr_r"] == 1 else "s",
             r["l_em_1g_h"] * 1e9, r["l_analytic_1g_h"] * 1e9, _pct(r["d_l_analytic_vs_em_1g_pct"]),
             r["q_em_1g"], r["q_analytic_1g"], _pct(r["d_q_analytic_vs_em_1g_pct"]),
             r["q_em_10g"], r["q_analytic_10g"], _pct(r["d_q_analytic_vs_em_10g_pct"]),
             _ghz(r["srf_em_hz"]), _ghz(r["srf_analytic_hz"]),
             _pct(r["d_srf_analytic_vs_em_pct"])))
    A("")
    A("## Fitted lumped model")
    A("")
    A("`../../sg13g2_inductor_em.spice`, same 2-pi topology as the analytic model "
      "so every element is directly comparable. Ratios below are fitted / analytic.")
    A("")
    if fits:
        el = ("Rser", "Rlad", "L1", "Ltot", "Cs", "Cox", "Rsub", "Csub")
        A("| Geometry | " + " | ".join(el) + " |")
        A("|---" * (len(el) + 1) + "|")
        for g in ("p1", "p13", "p11"):
            if g not in fits:
                continue
            rr = fits[g]["ratio_fitted_over_analytic"]
            A("| `%s` | " % g + " | ".join("%.3g" % rr[k] for k in el) + " |")
        A("")
        A("### Fit residual")
        A("")
        A("| Geometry | fit band | rms \\|dZ\\|/\\|Z\\| | max \\|dZ\\|/\\|Z\\| | rms dL | rms dQ | SRF fitted vs EM |")
        A("|---|---|---|---|---|---|---|")
        for g in ("p1", "p13", "p11"):
            if g not in fits:
                continue
            e = fits[g]
            r = e["residual"]["fit_band"]
            sf, se = e["srf_fitted_hz"], e["srf_em_hz"]
            A("| `%s` | %s GHz | %.2f %% | %.2f %% | %.2f %% | %.2f %% | %s |"
              % (g, r["band_ghz"], r["rms_rel_err_zse_pct"], r["max_rel_err_zse_pct"],
                 r["rms_rel_err_L_pct"], r["rms_rel_err_Q_pct"],
                 ("%s vs %s (%s)" % (_ghz(sf), _ghz(se), _pct(100 * (sf - se) / se)))
                 if np.isfinite(se) else "no SRF in band"))
        A("")
    if convrows:
        A("## Mesh and boundary convergence")
        A("")
        A("One-variable-at-a-time on `p1`, against the baseline settings above.")
        A("")
        A("| Variant | cellsize | margin | dL(1 GHz) | dQ(1 GHz) | dQ(10 GHz) | wall s |")
        A("|---|---|---|---|---|---|---|")
        for r in convrows:
            A("| `%s` | %s um | %s um | %s %% | %s %% | %s %% | %s |"
              % (r["variant"], r["refined_cellsize_um"], r["margin_um"],
                 r.get("d_l_se_1g_pct", "0"), r.get("d_q_se_1g_pct", "0"),
                 r.get("d_q_se_10g_pct", "0"), r.get("wall_seconds", "")))
        A("")
    A("## Provenance")
    A("")
    A("```json")
    A(json.dumps(env, indent=2, sort_keys=True))
    A("```")
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
