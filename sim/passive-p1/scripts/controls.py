#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Controls for the analysis chain.  None of this needs an EM solver.

  known-answer   synthetic lossless series-L two-port through the same chain
                 the EM data use (strict Touchstone parse -> impedance ->
                 L/Q/SRF -> ngspice two-port comparison).  Must recover L and
                 complex Z within 1% and report lossless Q as infinite.
  wrong-value    the same checker with a deliberately wrong L (in the ngspice
                 model, and separately in the claimed truth).  Must FAIL.
  malformed      NaN/Inf/truncated/non-monotonic/... Touchstone files.  Every
                 one must be rejected, and the post stage run on a malformed
                 baseline must exit nonzero and leave no success artefact.
  pipeline       post -> fit -> compare -> record on generated (clearly
                 labelled SYNTHETIC) lossy 2-pi data: success path, exceeded-
                 mesh-limit path, wrong-fit path, unavailable-tool path, and
                 a re-run that must reproduce the numerical digest.
  all            run every group; with --write-record also write one
                 append-only controls record under records/.

Exit status is 0 only if every control behaved as required (a "must fail"
control passes when the checker fails it).
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import emlib  # noqa: E402
import make_synthetic as M  # noqa: E402
import p1chain as C  # noqa: E402

CAMPAIGN = os.path.dirname(HERE)
FIXTURE = os.path.join(CAMPAIGN, "fixtures", "lossless_L_100pH.s2p")
PY = sys.executable


# ------------------------------------------------------------- the checker
def check_known_answer(fixture, model_file, model_name, truth_L, workdir):
    """Return (ok, details).  Raises C.DataError on malformed data."""
    f, S, z0 = C.read_snp_strict(fixture)
    tab = C.band_table(f, S, z0)
    det = {"route": tab["route"], "bands": [], "truth_L_h": truth_L}
    ok = True
    for r in tab["rows"]:
        z_true = 1j * 2 * np.pi * r["f_hz"] * truth_L
        ez = abs(r["zse"] - z_true) / abs(z_true) * 100
        el = abs(r["l_se_h"] - truth_L) / truth_L * 100
        q_inf = r["q_se"] == float("inf")
        det["bands"].append({"f_hz": r["f_hz"], "z_err_pct": ez, "L_err_pct": el, "q_se": r["q_se"]})
        ok &= ez <= C.CTRL_L_TOL_PCT and el <= C.CTRL_L_TOL_PCT and q_inf
    det["srf_se"] = tab["srf_se"]
    ok &= (not tab["srf_se"]["found"])  # lossless L: no resonance, lower bound only
    # ngspice comparison on the same port convention
    f2, zse, _, _ = C.impedances(f, S, z0)
    fg, Y, Smod, _ = C.ngspice_two_port(model_file, model_name, f2, workdir, "", z0)
    zr = C.zse_residuals(fg, 1.0 / Y[:, 0, 0], f2, zse)
    ff = f > 0
    sr = C.s_residuals(fg, Smod, f2, S[ff])
    det["ngspice_zse"] = zr
    det["ngspice_s"] = sr
    ok &= all(e["rel_err_pct"] <= C.CTRL_L_TOL_PCT for e in zr["at_band"])
    return bool(ok), det


# ------------------------------------------------------------- controls
def ctl_known_answer(tmp):
    model = os.path.join(tmp, "synth_true.spice")
    M.write_spice_L(model, M.L_TRUE_H)
    ok, det = check_known_answer(FIXTURE, model, "synth_l", M.L_TRUE_H, os.path.join(tmp, "ka"))
    # also the Q handling in isolation: no division error, inf for lossless
    L, Q = C.lq(np.array([0.0, 1e9]), np.array([0j, 1j * 2 * np.pi * 1e9 * 1e-10]))
    ok &= bool(np.isnan(L[0]) and np.isposinf(Q[1]))
    return ok, det


def ctl_wrong_value(tmp):
    res = {}
    wrong = os.path.join(tmp, "synth_wrong.spice")
    M.write_spice_L(wrong, M.L_TRUE_H * 1.03)  # 3% too large, limit is 1%
    ok_model, _ = check_known_answer(FIXTURE, wrong, "synth_l", M.L_TRUE_H, os.path.join(tmp, "wv1"))
    res["wrong_model_L_plus3pct_checker_passed"] = ok_model
    true_m = os.path.join(tmp, "synth_true2.spice")
    M.write_spice_L(true_m, M.L_TRUE_H)
    ok_truth, _ = check_known_answer(FIXTURE, true_m, "synth_l", M.L_TRUE_H * 0.97, os.path.join(tmp, "wv2"))
    res["wrong_claimed_truth_L_minus3pct_checker_passed"] = ok_truth
    # wrong fixture (data are 3% off the model) -- caught the same way
    bad_fx = os.path.join(tmp, "fx_wrong.s2p")
    M.write_lossless(bad_fx, M.L_TRUE_H * 1.03)
    ok_fx, _ = check_known_answer(bad_fx, true_m, "synth_l", M.L_TRUE_H, os.path.join(tmp, "wv3"))
    res["wrong_fixture_L_plus3pct_checker_passed"] = ok_fx
    return (not ok_model) and (not ok_truth) and (not ok_fx), res


def _mutations(good_text):
    lines = good_text.splitlines()
    data = [i for i, l in enumerate(lines) if l.strip() and not l.startswith(("!", "#"))]
    k = data[300]

    def rep(i, fn):
        out = list(lines)
        out[i] = fn(out[i])
        return "\n".join(out) + "\n"

    def nan(l):
        t = l.split(); t[3] = "nan"; return " ".join(t)

    def inf(l):
        t = l.split(); t[2] = "inf"; return " ".join(t)

    def trunc(l):
        return " ".join(l.split()[:5])

    def word(l):
        t = l.split(); t[4] = "0.1x"; return " ".join(t)

    def big(l):
        t = l.split(); t[1] = "7.5"; return " ".join(t)

    swap = list(lines); swap[data[10]], swap[data[11]] = swap[data[11]], swap[data[10]]
    dup = list(lines); dup[data[11]] = dup[data[10]]
    nohdr = [l for l in lines if not l.startswith("#")]
    badfmt = [l.replace("# Hz S RI R 50", "# Hz S XX R 50") for l in lines]
    badz0 = [l.replace("R 50", "R 0") for l in lines]
    badunit = [l.replace("# Hz", "# THz") for l in lines]
    twohdr = list(lines); twohdr.insert(data[5], "# Hz S RI R 50")
    return {
        "nan_value": rep(k, nan), "inf_value": rep(k, inf), "truncated_row": rep(k, trunc),
        "non_numeric_token": rep(k, word), "S_magnitude_nonphysical": rep(k, big),
        "frequency_not_monotonic": "\n".join(swap) + "\n", "duplicate_frequency": "\n".join(dup) + "\n",
        "missing_option_line": "\n".join(nohdr) + "\n", "unsupported_format_token": "\n".join(badfmt) + "\n",
        "zero_reference_impedance": "\n".join(badz0) + "\n", "unsupported_unit": "\n".join(badunit) + "\n",
        "second_option_line": "\n".join(twohdr) + "\n",
        "single_data_row": "\n".join(lines[: data[0] + 1]) + "\n", "empty_file": "",
    }


def ctl_malformed(tmp):
    good = open(FIXTURE).read()
    res, ok = {}, True
    for name, text in _mutations(good).items():
        p = os.path.join(tmp, "bad_%s.s2p" % name)
        open(p, "w").write(text)
        try:
            C.read_snp_strict(p)
            res[name] = "ACCEPTED (BAD)"
            ok = False
        except C.DataError as exc:
            res[name] = "rejected: " + str(exc).replace(p, "<file>")[:90]
    # the unmodified file must still parse (the mutations are the only difference)
    C.read_snp_strict(FIXTURE)
    # end-to-end: post stage on a malformed baseline exits nonzero, writes no metrics
    wd = os.path.join(tmp, "mal_campaign")
    M.lossy_campaign(wd)
    bad = os.path.join(wd, "results", "inductor_p1.s2p")
    lines = open(bad).read().splitlines()
    lines[200] = " ".join(lines[200].split()[:4])
    open(bad, "w").write("\n".join(lines) + "\n")
    rc = subprocess.run([PY, os.path.join(HERE, "postprocess_p1.py"), "--dir", wd],
                        capture_output=True, text=True).returncode
    res["post_stage_on_malformed_baseline_exit"] = rc
    res["no_metrics_written"] = not os.path.exists(os.path.join(wd, "results", "p1_metrics.json"))
    res["no_record_written"] = not os.path.isdir(os.path.join(wd, "records"))
    ok &= rc == 2 and res["no_metrics_written"] and res["no_record_written"]
    return ok, res


def _run(args, **kw):
    return subprocess.run([PY] + args, capture_output=True, text=True, **kw)


def _digest(out):
    m = re.search(r"DIGEST: (\w+)", out)
    return m.group(1) if m else None


def _status(out):
    m = re.search(r"STATUS: (\S+)", out)
    return m.group(1) if m else None


def _pipeline_once(wd, **campaign_kw):
    M.lossy_campaign(wd, **campaign_kw)
    rc = {}
    rc["post"] = _run([os.path.join(HERE, "postprocess_p1.py"), "--dir", wd]).returncode
    rc["fit"] = _run([os.path.join(HERE, "fit_p1.py"), "--dir", wd]).returncode
    rc["compare"] = _run([os.path.join(HERE, "compare_p1.py"), "--dir", wd]).returncode
    r = _run([os.path.join(HERE, "make_record.py"), "--dir", wd, "--synthetic", "--stages", "post fit compare"])
    return rc, r.stdout + r.stderr


def ctl_pipeline(tmp):
    res, ok = {}, True
    # 1. success path + re-run reproduces the digest, earlier record untouched
    wd = os.path.join(tmp, "pipe_ok")
    rc, out = _pipeline_once(wd)
    res["success_stage_exit_codes"] = rc
    res["success_status"] = _status(out)
    d1 = _digest(out)
    recs1 = sorted(os.listdir(os.path.join(wd, "records")))
    snap = {n: open(os.path.join(wd, "records", n)).read() for n in recs1}
    rc2 = {k: _run([os.path.join(HERE, s), "--dir", wd]).returncode
           for k, s in (("post", "postprocess_p1.py"), ("fit", "fit_p1.py"), ("compare", "compare_p1.py"))}
    out2 = _run([os.path.join(HERE, "make_record.py"), "--dir", wd, "--synthetic",
                 "--stages", "post fit compare"])
    d2 = _digest(out2.stdout)
    recs2 = sorted(os.listdir(os.path.join(wd, "records")))
    unchanged = all(open(os.path.join(wd, "records", n)).read() == t for n, t in snap.items())
    res["rerun_exit_codes"] = rc2
    res["rerun_digest_equal"] = d1 is not None and d1 == d2
    res["rerun_added_new_record_prior_unchanged"] = len(recs2) == 2 * len(recs1) and unchanged
    ok &= (all(v == 0 for v in rc.values()) and res["success_status"] == "SYNTHETIC-QUALIFIED"
           and res["rerun_digest_equal"] and res["rerun_added_new_record_prior_unchanged"])
    m = json.load(open(os.path.join(wd, "results", "p1_compare.json")))
    res["fit_rel_err_pct_at_band"] = [e["rel_err_pct"] for e in m["zse"]["at_band"]]
    # 2. exceeded mesh limit -> UNCONVERGED
    wd2 = os.path.join(tmp, "pipe_unconv")
    rc, out = _pipeline_once(wd2, mesh_scale_L=0.8)
    res["exceeded_mesh_status"] = _status(out)
    ok &= res["exceeded_mesh_status"] == "SYNTHETIC-UNCONVERGED"
    # 3. wrong fit (candidate with L perturbed) -> FIT_FAILED
    wd3 = os.path.join(tmp, "pipe_fitfail")
    _pipeline_once(wd3)
    cand = os.path.join(wd3, "fit", "p1_fit_candidate.spice")
    txt = open(cand).read()
    txt = re.sub(r"^(Lmain \S+ lb )(\S+)", lambda m: m.group(1) + "%.9g" % (float(m.group(2)) * 2.0), txt, flags=re.M)
    open(cand, "w").write(txt)
    _run([os.path.join(HERE, "compare_p1.py"), "--dir", wd3])
    out3 = _run([os.path.join(HERE, "make_record.py"), "--dir", wd3, "--synthetic"]).stdout
    res["wrong_fit_status"] = _status(out3)
    ok &= res["wrong_fit_status"] == "SYNTHETIC-FIT_FAILED"
    # 4. unavailable-tool path: missing solver output -> post exits 3; record says so, no numbers
    wd4 = os.path.join(tmp, "pipe_unavail")
    os.makedirs(os.path.join(wd4, "results"))
    rc4 = _run([os.path.join(HERE, "postprocess_p1.py"), "--dir", wd4]).returncode
    out4 = _run([os.path.join(HERE, "make_record.py"), "--dir", wd4, "--synthetic", "--unavailable",
                 "--failed-command", "python3 -I -c 'import CSXCAD'", "--detail", "control: solver absent"]).stdout
    res["missing_output_post_exit"] = rc4
    res["unavailable_status"] = _status(out4)
    rec4 = [n for n in os.listdir(os.path.join(wd4, "records")) if n.endswith(".json")][0]
    j4 = json.load(open(os.path.join(wd4, "records", rec4)))
    res["unavailable_record_has_no_numbers"] = j4["metrics"] is None and j4["compare"] is None
    ok &= (rc4 == 3 and res["unavailable_status"] == "SYNTHETIC-CAPABILITY_UNAVAILABLE"
           and res["unavailable_record_has_no_numbers"])
    return ok, res


GROUPS = {"known-answer": ctl_known_answer, "wrong-value": ctl_wrong_value,
          "malformed": ctl_malformed, "pipeline": ctl_pipeline}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("group", choices=list(GROUPS) + ["all"])
    ap.add_argument("--write-record", action="store_true")
    a = ap.parse_args()
    names = list(GROUPS) if a.group == "all" else [a.group]
    out, allok = {}, True
    tmp = tempfile.mkdtemp(prefix="p1ctl_")
    try:
        for n in names:
            try:
                os.makedirs(os.path.join(tmp, n), exist_ok=True)
                ok, det = GROUPS[n](os.path.join(tmp, n))
            except Exception as exc:  # a crash is a failed control, never a pass
                ok, det = False, {"exception": repr(exc)}
            out[n] = {"pass": bool(ok), "details": det}
            allok &= ok
            print("%-13s %s" % (n, "PASS" if ok else "FAIL"))
            if not ok:
                print(json.dumps(det, indent=1, sort_keys=True, default=str)[:3000])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if a.write_record:
        rd = os.path.join(CAMPAIGN, "records")
        os.makedirs(rd, exist_ok=True)
        now = datetime.datetime.now(datetime.timezone.utc)
        sha = subprocess.run(["git", "-C", CAMPAIGN, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        rid = "%s-%s-CONTROLS-%s" % (now.strftime("%Y%m%d-%H%M%S"), sha, "PASS" if allok else "FAIL")
        ngv = subprocess.run("ngspice -v 2>&1 | grep -m1 ngspice-", shell=True, capture_output=True, text=True).stdout.strip()
        import numpy
        body = {"record_id": rid, "kind": "analysis-chain controls (no EM solver involved)",
                "all_pass": bool(allok), "ngspice": ngv, "numpy": numpy.__version__,
                "fixture": "fixtures/lossless_L_100pH.s2p", "fixture_sha256": emlib.sha256(FIXTURE),
                "limits": {"L_Z_tol_pct": C.CTRL_L_TOL_PCT}, "groups": out}
        with open(os.path.join(rd, rid + ".json"), "x") as fh:
            json.dump(body, fh, indent=2, sort_keys=True, default=str)
            fh.write("\n")
        L = ["# passive-p1 controls record %s" % rid, "",
             "**Scope**: analysis-chain controls only (Touchstone parse, S->Z/Y, L/Q/SRF, ngspice comparison, "
             "record/verdict plumbing). These checks use generated data; they say nothing about EM geometry, "
             "mesh accuracy or the p1 inductor itself, and are not a substitute for the EM campaign.", "",
             "- Overall: **%s**" % ("ALL CONTROLS BEHAVED AS REQUIRED" if allok else "FAILURE"),
             "- ngspice: %s; numpy %s; fixture sha256 `%s`" % (ngv, numpy.__version__, body["fixture_sha256"]),
             "- Synthetic truth: lossless series L = 100 pH (arbitrary round number, not a p1 estimate); "
             "limit 1% on L and complex Z_se at 17.7 / 19.45 / 21.2 GHz; lossless Q must be infinite.", ""]
        for n, v in out.items():
            L += ["## %s -- %s" % (n, "PASS" if v["pass"] else "FAIL"), "", "```json",
                  json.dumps(v["details"], indent=1, sort_keys=True, default=str), "```", ""]
        with open(os.path.join(rd, rid + ".md"), "x") as fh:
            fh.write("\n".join(L))
        print("record:", os.path.join(rd, rid + ".md"))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
