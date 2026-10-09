#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Write one append-only campaign record and decide its status.

Statuses (exactly one per record):
  QUALIFIED               every declared limit met (converged mesh AND margin,
                          fit within 5% at all three band frequencies).
                          Valid only for the exact p1 geometry, the tested
                          band, and the nominal stackup point.
  UNCONVERGED             a mesh or margin delta exceeded its budget (or had an
                          invalid denominator).  No model is advertised.
  FIT_FAILED              the lumped fit failed or missed the 5% limit.
  CAPABILITY_UNAVAILABLE  the EM solver / a required tool or saved output is
                          absent.  The failed command/check is recorded; no
                          number from any other source is substituted.
A record is NEVER overwritten: files are opened exclusively; a re-run writes a
new record (the earlier one stays).  With --synthetic the status is prefixed
`SYNTHETIC-` and the record says so in its first line: it exercises the
pipeline on generated data and is not campaign evidence.

Usage:
  make_record.py --dir D [--records-dir R] [--synthetic]
  make_record.py --dir D --unavailable --failed-command CMD --detail TEXT

New (record_schema 2) campaign records first publish a frozen, exclusively
created solver-artifact package <records-dir>/../solver-artifacts/<id>/ with a
SHA-256 manifest (freeze_package.py), derive the record's numbers from the
FROZEN bytes, and name the package + manifest hash in the record.  Publication
is refused (nothing is written) when a stage output the outcome needs is
missing or the package already exists; a record-write failure removes the
package this run created.  --synthetic output is not campaign evidence and is
not packaged.  Hash integrity of the package is not numerical qualification.
"""

import argparse
import datetime
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import limits as C  # noqa: E402  (numpy-free: records must be writable without numpy)
import freeze_package as FZ  # noqa: E402  (stdlib only)

HERE = os.path.dirname(os.path.abspath(__file__))
CAMPAIGN = os.path.dirname(HERE)

DEFINITIONS = """\
* Geometry: PDK `inductor2` (SG13_dev), w=8.22 um, s=3.29 um, d=47.65 um, nr_r=1
  (single turn).  Exact geometry only; nothing here extends to other turns/widths.
* Ports: 2 lumped z-ports, port 1 = LA, port 2 = LB, each referenced to a local
  substrate ground patch (the model's `sub` node).  Touchstone z0 = 50 ohm.
* De-embedding: the lumped-port series inductance (Terman flat-ribbon, from the
  run's port_information.json) is subtracted from the diagonal of Z.
* Z_se = Z11 - Z12*Z21/Z22 (LA driven, LB and sub grounded); Z_diff =
  Z11 - Z12 - Z21 + Z22.  L = Im(Z)/omega; Q = Im(Z)/Re(Z) (infinite where
  Re Z is numerically zero).  SRF = first downward zero crossing of Im(Z_se);
  no crossing below the search ceiling is a LOWER BOUND, not an SRF.
* Gated quantity for convergence and fit limits: single-ended (Z_se, L_se,
  Q_se); differential is reported alongside, not gated.
* Process/temperature: the EM run uses the published stackup at its stated
  nominal point.  The temperature of that point is not stated by the stackup
  file and is NOT a calibrated corner.  Process spread, temperature
  coefficients and Monte Carlo are UNSUPPORTED here; no invented +/-% sweep.
"""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sh(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return (r.stdout + r.stderr).strip()
    except Exception as exc:  # pragma: no cover
        return "error: %s" % exc


def environment():
    env = {"host": platform.node(), "platform": platform.platform(), "python": sys.version.split()[0]}
    try:
        import numpy
        env["numpy"] = numpy.__version__
    except ImportError:
        env["numpy"] = None
    try:
        import scipy
        env["scipy"] = scipy.__version__
    except ImportError:
        env["scipy"] = None
    env["ngspice"] = (sh("ngspice -v 2>&1 | grep -m1 'ngspice-'") or "absent")
    env["klayout"] = sh("klayout -v 2>&1 | head -1") if sh("command -v klayout") else "absent"
    env["openEMS_binary"] = sh("command -v openEMS") or "absent"
    env["csxcad_import"] = sh("python3 -I -c 'import CSXCAD' 2>&1 | tail -1") or "ok"
    pdk = os.environ.get("IHP_PDK_ROOT") or os.path.expanduser("~/share/pdk/ihp-sg13g2")
    env["pdk_root"] = pdk
    vf = os.path.join(pdk, ".fetched-version")
    env["pdk_version_file"] = open(vf).read().strip() if os.path.isfile(vf) else "absent"
    env["git_commit"] = sh("git -C %s rev-parse HEAD" % CAMPAIGN)
    return env


def input_hashes():
    """sha256 of every pinned/adapted input as present now, plus the check
    that verbatim copies still match their recorded source hash."""
    man_path = os.path.join(CAMPAIGN, "INPUTS.json")
    if not os.path.isfile(man_path):
        return {"error": "INPUTS.json missing"}
    man = json.load(open(man_path))
    out = {"source_repo": man["source_repo"], "source_commit": man["source_commit"], "files": {}}
    for e in man["files"]:
        p = os.path.join(CAMPAIGN, e["path"])
        h = sha256(p) if os.path.isfile(p) else None
        out["files"][e["path"]] = {"role": e["role"], "sha256": h,
                                   "matches_manifest": h == e["sha256"],
                                   "verbatim_matches_source": (h == e["source_sha256"]) if e["role"] == "verbatim" else None}
    return out


def fmt(x, nd=4):
    if isinstance(x, dict) and "re" in x:
        return "%.*g%+.*gj" % (nd, x["re"], nd, x["im"])
    if isinstance(x, str):
        return x
    if x is None:
        return "n/a"
    return "%.*g" % (nd, x)


def decide(metrics, compare, fitprob):
    reasons = []
    if metrics is None:
        return "CAPABILITY_UNAVAILABLE", ["no saved solver output / metrics"]
    conv = metrics["convergence"]
    for k in ("mesh_1p0_vs_0p5", "margin_200_vs_400"):
        c = conv[k]
        if c["invalid_denominator"]:
            reasons.append("%s: invalid (near-zero/nonpositive) denominator" % k)
        elif not c["within_budget"]:
            reasons.append("%s: delta exceeds budget (L %g%%, Q %g%%)" % (k, conv["budget_L_pct"], conv["budget_Q_pct"]))
    if reasons:
        return "UNCONVERGED", reasons
    if fitprob:
        return "FIT_FAILED", [fitprob]
    if compare is None:
        return "FIT_FAILED", ["no fit/ngspice comparison available"]
    for e in compare["zse"]["at_band"]:
        if e["rel_err_pct"] > C.FIT_BUDGET_PCT:
            reasons.append("|Zfit-ZEM|/|ZEM| = %.3g%% at %.2f GHz > %g%%"
                           % (e["rel_err_pct"], e["f_hz"] / 1e9, C.FIT_BUDGET_PCT))
    if reasons:
        return "FIT_FAILED", reasons
    return "QUALIFIED", ["all declared limits met"]


def load(p):
    return json.load(open(p)) if os.path.isfile(p) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--records-dir")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--unavailable", action="store_true")
    ap.add_argument("--failed-command", default="")
    ap.add_argument("--detail", default="")
    ap.add_argument("--stages", default="")
    ap.add_argument("--commands", default="")
    ap.add_argument("--fit-problem", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--solver-settings", default="", help="JSON object of EM_* settings for settings.json")
    args = ap.parse_args()
    recdir = args.records_dir or os.path.join(args.dir, "records")
    os.makedirs(recdir, exist_ok=True)

    metrics = load(os.path.join(args.dir, "results", "p1_metrics.json"))
    compare = load(os.path.join(args.dir, "results", "p1_compare.json"))
    if args.unavailable:
        status, reasons = "CAPABILITY_UNAVAILABLE", [args.detail or "tool unavailable"]
        metrics = compare = None
    else:
        status, reasons = decide(metrics, compare, args.fit_problem)
        if status in ("UNCONVERGED",) or args.fit_problem:
            compare = None  # a comparison file left by an earlier run is not this outcome's evidence
    if args.synthetic:
        status = "SYNTHETIC-" + status

    now = datetime.datetime.now(datetime.timezone.utc)
    env = environment()
    gitshort = (env["git_commit"] or "nogit")[:7]
    rid = "%s-%s-%s" % (now.strftime("%Y%m%d-%H%M%S"), gitshort, status)

    digest_src = {"status": status, "metrics_band": metrics and metrics["band"],
                  "conv": metrics and metrics["convergence"],
                  "zse": compare and compare["zse"], "s": compare and compare["s"]}
    digest = hashlib.sha256(json.dumps(digest_src, sort_keys=True, default=str).encode()).hexdigest()

    pkg_info = None
    if not args.synthetic:
        try:
            settings = json.loads(args.solver_settings) if args.solver_settings else {}
        except ValueError:
            settings = {"unparsed": args.solver_settings}
        pkg_id = rid.rsplit("-", 1)[0]
        pkg_root = os.path.join(os.path.dirname(os.path.abspath(recdir)), FZ.PACKAGES_DIRNAME)
        try:
            pkg_info = FZ.publish(args.dir, pkg_root, pkg_id, status, args.stages, settings=settings,
                                  has_compare=compare is not None, commands=args.commands,
                                  failed_command=args.failed_command)
        except FZ.PublishError as exc:
            print("REFUSED to publish record %s: %s" % (rid, exc), file=sys.stderr)
            return 2
        if not args.unavailable:  # the record is derived from the frozen bytes, not the mutable copy
            fm = load(os.path.join(pkg_info["dir"], "results", "p1_metrics.json"))
            fc = load(os.path.join(pkg_info["dir"], "results", "p1_compare.json"))
            if fm != metrics or fc != compare:
                shutil.rmtree(pkg_info["dir"], ignore_errors=True)
                print("REFUSED: working results changed during publication", file=sys.stderr)
                return 2

    rec = {"record_id": rid, "status": status, "reasons": reasons, "utc": now.isoformat(),
           "numerical_digest": digest, "environment": env, "input_hashes": input_hashes(),
           "stages": args.stages, "commands": args.commands, "failed_command": args.failed_command,
           "metrics": metrics, "compare": compare, "synthetic": args.synthetic,
           "limits": {"L_mesh_margin_pct": C.L_BUDGET_PCT, "Q_mesh_margin_pct": C.Q_BUDGET_PCT,
                      "fit_Zse_pct": C.FIT_BUDGET_PCT, "srf_search_ceiling_hz": C.SRF_CEILING_HZ,
                      "band_hz": list(C.BAND_HZ)}}
    if pkg_info:
        rec["record_schema"] = 2
        rec["artifact_package"] = {
            "schema": FZ.SCHEMA, "path": "sim/passive-p1/%s/%s/" % (FZ.PACKAGES_DIRNAME, pkg_id),
            "manifest": "manifest.json", "manifest_sha256": pkg_info["manifest_sha256"], "files": pkg_info["files"]}

    L = []
    if args.synthetic:
        L += ["> **SYNTHETIC PIPELINE SMOKE RECORD -- generated data, NOT campaign evidence.**", ""]
    L += ["# passive-p1 record %s" % rid, "",
          "- **Status: %s**" % status,
          "- Reason(s): " + "; ".join(reasons),
          "- Claim scope: feasibility evidence for ONE geometry (p1). Not a passive-family choice, "
          "not matching-network sizing, not spec compliance. No qualified-model claim unless the "
          "status above is QUALIFIED, and then only for the exact geometry, the 17.7-21.2 GHz tested "
          "range and the nominal stackup point.",
          "- Numerical digest (re-run comparison key): `%s`" % digest, ""]
    if args.note:
        L += [args.note, ""]
    L += ["## Provenance", "",
          "- Source method: `2AMLogic/sg13g2-vco` @ `%s`, `sim/inductor-model/em-extraction` "
          "(pinned; inputs hashed in `../INPUTS.json`, reproduced below)."
          % rec["input_hashes"].get("source_commit", "?"),
          "- This repo commit: `%s`" % env["git_commit"],
          "- Host: %s (%s); python %s, numpy %s, scipy %s" % (env["host"], env["platform"], env["python"], env["numpy"], env["scipy"]),
          "- ngspice: %s" % env["ngspice"],
          "- klayout: %s" % env["klayout"],
          "- openEMS binary: %s; `import CSXCAD`: %s" % (env["openEMS_binary"], env["csxcad_import"]),
          "- PDK: `%s` (.fetched-version: %s)" % (env["pdk_root"], env["pdk_version_file"]),
          "- Stages requested: `%s`" % args.stages,
          "- Commands: `%s`" % args.commands, ""]
    if args.unavailable:
        L += ["## Failed capability check", "",
              "- Failed command/check: `%s`" % args.failed_command,
              "- Detail: %s" % args.detail, "",
              "No L, Q, SRF, convergence or fit number is reported in this record, and no number from "
              "any other source (including the sibling VCO's historical extraction) is substituted. "
              "Mesh convergence at 21.2 GHz, the fit, and the model qualification are therefore NOT "
              "established by this record.", ""]
    if metrics:
        g = metrics["geometry"]
        L += ["## Geometry and solver", "",
              "- inductor2 w=%s s=%s d=%s um, nr_r=%s; solver: %s" % (g["w_um"], g["s_um"], g["d_um"], g["nr_r"], metrics["solver"]),
              "- baseline settings: `%s`" % json.dumps(metrics["baseline_settings"], sort_keys=True),
              "- port parasitic L (pH): %s; impedance route: %s; z0 = %s ohm"
              % (metrics["port_inductance_ph"], metrics["route"], metrics["z0_ohm"]), "",
              "## Definitions", "", DEFINITIONS, "",
              "## L, Q, Z at the three band frequencies (baseline 1.0 um mesh, 200 um margin)", "",
              "| f (GHz) | Z_se (ohm) | L_se (pH) | Q_se | Z_diff (ohm) | L_diff (pH) | Q_diff |",
              "|---|---|---|---|---|---|---|"]
        for r in metrics["band"]:
            lse = r["l_se_h"] * 1e12
            ldi = r["l_diff_h"] * 1e12 if not isinstance(r["l_diff_h"], str) else r["l_diff_h"]
            L.append("| %.2f | %s | %s | %s | %s | %s | %s |" % (
                r["f_hz"] / 1e9, fmt(r["zse"]), fmt(lse), fmt(r["q_se"]), fmt(r["zdiff"]), fmt(ldi), fmt(r["q_diff"])))
        s = metrics["srf_se"]
        L += ["", "- SRF (single-ended): " + (
            "%.4g GHz" % (s["hz"] / 1e9) if s["found"] else
            "NOT FOUND below the %.0f GHz search ceiling -- LOWER BOUND ONLY (>= %.4g GHz), not an SRF"
            % (s["search_ceiling_hz"] / 1e9, s["lower_bound_hz"] / 1e9))]
        d = metrics["srf_diff"]
        L += ["- SRF (differential): " + (
            "%.4g GHz" % (d["hz"] / 1e9) if d["found"] else
            "no crossing below %.0f GHz (lower bound >= %.4g GHz)" % (d["search_ceiling_hz"] / 1e9, d["lower_bound_hz"] / 1e9)), ""]
        L += ["## Convergence (limits: dL <= %g%%, dQ <= %g%%; denominator = finer mesh / larger domain)"
              % (C.L_BUDGET_PCT, C.Q_BUDGET_PCT), ""]
        for key, title in (("mesh_1p0_vs_0p5", "Mesh: 1.0 um vs 0.5 um (margin fixed at 200 um)"),
                           ("margin_200_vs_400", "Domain margin: 200 um vs 400 um (mesh fixed at 1.0 um)")):
            c = conv = metrics["convergence"][key]
            L += ["### " + title, "",
                  "| f (GHz) | dL_se (%) | dQ_se (%) | dL_diff (%) | dQ_diff (%) | status |", "|---|---|---|---|---|---|"]
            for e in c["entries"]:
                L.append("| %.2f | %s | %s | %s | %s | %s |" % (
                    e["f_hz"] / 1e9, fmt(e["dL_se_pct"]), fmt(e["dQ_se_pct"]), fmt(e["dL_diff_pct"]), fmt(e["dQ_diff_pct"]), e["status"]))
            L += ["", "Result: **%s**" % ("WITHIN BUDGET" if c["within_budget"] else
                                         ("INVALID COMPARISON" if c["invalid_denominator"] else "BUDGET EXCEEDED")), ""]
        L += ["Variant inputs (hashes):", ""]
        for n, v in metrics["variant_inputs"].items():
            L.append("- %s: `%s` sha256 `%s`, wall %ss" % (n, v["s2p"], v["s2p_sha256"], v["wall_seconds"]))
        L.append("")
    if compare:
        L += ["## Fit validation (ngspice fitted subcircuit vs de-embedded Touchstone)", "",
              "- Fixture: %s" % compare["fixture"],
              "- Limit: |Zfit - ZEM|/|ZEM| <= %g%% at each band frequency (Z_se, same port convention)."
              % C.FIT_BUDGET_PCT, "",
              "| f (GHz) | Z_EM (ohm) | Z_fit (ohm) | rel. error (%) |", "|---|---|---|---|"]
        for e in compare["zse"]["at_band"]:
            L.append("| %.2f | %s | %s | %s |" % (e["f_hz"] / 1e9, fmt(e["z_em"]), fmt(e["z_model"]), fmt(e["rel_err_pct"])))
        z = compare["zse"]
        L += ["", "- Over 17.7-21.2 GHz (%d EM points): RMS %s %%, max %s %% of |Z_se|" % (z["n_points_in_band"], fmt(z["rms_pct"]), fmt(z["max_pct"])),
              "- Two-port S residuals |S_model - S_EM| over 17.7-21.2 GHz (z0 = %g ohm, ports LA/LB, sub reference):" % compare["z0_ohm"], ""]
        L += ["| S | RMS | max |", "|---|---|---|"]
        for k, v in compare["s"].items():
            L.append("| %s | %s | %s |" % (k, fmt(v["rms_abs"]), fmt(v["max_abs"])))
        L.append("")
    if pkg_info:
        ap_ = rec["artifact_package"]
        L += ["## Frozen solver artifacts", "",
              "- Package: `%s` (record_schema 2; created exclusively at publication, never overwritten)" % ap_["path"],
              "- Manifest: `%smanifest.json`, sha256 `%s`, %d file(s)" % (ap_["path"], ap_["manifest_sha256"], ap_["files"]),
              "- The numbers above were derived from the byte-copies in this package, not from the mutable "
              "`results/`, `fit/` or `run_log/` working directories.",
              "- A matching manifest proves hash INTEGRITY of those files only. It is not numerical "
              "qualification: the status above is the verdict of the analysis against its declared limits. "
              "A re-analysis of the package (`scripts/reanalyze_frozen.py`) is a separate artifact and never "
              "edits this record.", ""]
    L += ["## Limitations (stated beside the claims)", "",
          "- p1 geometry only; fit/EM agreement holds only inside the tested band and for this exact geometry.",
          "- Nominal stackup point only: metal thickness, dielectric and conductivity come from "
          "`stackup/SG13G2.xml` (hash in the input table). Process spread, temperature coefficients and "
          "Monte Carlo are UNSUPPORTED; no corner labels are inherited from the HBT corner set.",
          "- Fit agreement is separate from solver convergence; neither is silicon validation.",
          "- Transmission lines, MIM capacitors, other geometries and validated corners are follow-on work.", "",
          "## Input hashes (`../INPUTS.json`)", "", "| file | role | sha256 | manifest ok | verbatim==source |", "|---|---|---|---|---|"]
    for p, e in rec["input_hashes"].get("files", {}).items():
        L.append("| %s | %s | `%s` | %s | %s |" % (p, e["role"], e["sha256"], e["matches_manifest"], e["verbatim_matches_source"]))
    L.append("")

    base = os.path.join(recdir, rid)
    written = []
    try:
        for path, text in ((base + ".md", "\n".join(L)), (base + ".json", json.dumps(rec, indent=2, sort_keys=True, default=str) + "\n")):
            with open(path, "x") as fh:  # exclusive: never overwrite a record
                written.append(path)
                fh.write(text)
    except BaseException:
        for path in written:  # only files this run created
            try:
                os.remove(path)
            except OSError:
                pass
        if pkg_info:
            shutil.rmtree(pkg_info["dir"], ignore_errors=True)
        raise
    print("record: %s" % (base + ".md"))
    if pkg_info:
        print("package: %s" % pkg_info["dir"])
    print("STATUS: %s" % status)
    print("DIGEST: %s" % digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
