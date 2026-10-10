"""From raw ``klt sim`` logs to the published verdicts (issue #57).

Pure and deterministic: the same frozen logs and the same ``plan.json`` always
give the same result, which is what ``run.py verify`` re-checks for a committed
record. No simulator is needed here.
"""

from __future__ import annotations

import math

import linearity as L

CONTROL = "control"
KINDS = ("two", "one")


def request_keys(plan: dict) -> list[str]:
    """One klt request per (subject, kind): the analytic control and each placement, two-tone and
    single-tone, every convergence variant inside the request."""
    return [f"{who}_{k}" for who in [CONTROL] + [p["name"] for p in plan["placements"]] for k in KINDS]


def control_placement(plan: dict) -> dict:
    return next(p for p in plan["placements"] if p["name"] == plan["controls"]["placement"])


def split_key(key: str) -> tuple[str, str]:
    who, kind = key.rsplit("_", 1)
    return who, kind


def runs_for_key(plan: dict, key: str) -> list[dict]:
    """The declared runs of one klt request (identical on generation and analysis)."""
    who, kind = split_key(key)
    if who == CONTROL:
        return L.sweep_runs(plan, control_placement(plan), kind, monitors=False, variants=("base",))
    for pl in plan["placements"]:
        if pl["name"] == who:
            return L.sweep_runs(plan, pl, kind, monitors=True)
    raise KeyError(key)


def _round(x, sig: int = 9):
    if isinstance(x, float):
        return float(f"{x:.{sig}g}") if math.isfinite(x) else (None if math.isnan(x) else ("+inf" if x > 0 else "-inf"))
    if isinstance(x, dict):
        return {k: _round(v, sig) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_round(v, sig) for v in x]
    return x


def summaries_for_key(plan: dict, key: str, text: str) -> tuple[list[dict], list[str]]:
    """Per-run summaries of one log and the problems found (corruption, never science)."""
    vals, done = L.parse_log(text)
    aborted = any(m in text for m in L.ABORT_MARKERS)
    problems = []
    if not done:
        problems.append(f"{key}: log has no LNLIN_DONE (deck did not finish)")
    out = []
    for run in runs_for_key(plan, key):
        s = L.run_summary(vals, run, log_has_abort=aborted)
        if s is None:
            problems.append(f"{key}: run {run['id']} ({run['kind']}, {run['pin_dbm']:g} dBm) is missing or non-finite")
        else:
            out.append(s)
    return out, problems


def first_limit_violation(plan: dict, rows: list[dict]) -> dict | None:
    lim = plan["extraction"]["operating_limits"]
    for r in sorted(rows, key=lambda x: x["pin_dbm"]):
        if r.get("sim_failed"):
            continue
        v = L.limit_violations(r.get("excursion_v"), lim)
        if v:
            return {"pin_dbm": r["pin_dbm"], "violations": v}
    return None


def assess_target(kind: str, result: dict, target: float, conv_delta_db: float) -> dict:
    """Pass/fail against the UNCHANGED ratified target, with the demonstrated
    convergence spread as the uncertainty. Never relaxes the target."""
    if result["status"] == "ok":
        v = result["iip3_dbm"] if kind == "iip3" else result["p1db_in_dbm"]
        if v - conv_delta_db >= target:
            verdict = "meets"
        elif v + conv_delta_db < target:
            verdict = "fails"
        else:
            verdict = "marginal"
        return {"verdict": verdict, "value_dbm": v, "target_dbm": target, "margin_db": v - target,
                "uncertainty_db": conv_delta_db}
    if result["status"] == "bounded" and result.get("p1db_in_dbm_gt") is not None:
        b = result["p1db_in_dbm_gt"]
        return {"verdict": "meets" if b >= target else "not_determined", "lower_bound_dbm": b,
                "target_dbm": target, "uncertainty_db": conv_delta_db}
    return {"verdict": "not_determined", "target_dbm": target}


def analyze(plan: dict, texts: dict[str, str]) -> dict:
    """Everything the record publishes, from the raw logs."""
    problems: list[str] = []
    summ: dict[str, list[dict]] = {}
    for key in request_keys(plan):
        if key not in texts:
            problems.append(f"{key}: no log")
            continue
        s, pr = summaries_for_key(plan, key, texts[key])
        summ[key] = s
        problems += pr
    out: dict = {"problems": problems}
    if problems:
        return out
    ex = plan["extraction"]
    lim = ex["operating_limits"]
    ctl = plan["controls"]
    # ---- ngspice analytic control (same generated block and extractor as the DUT)
    controls = {}
    for kind in KINDS:
        rows = L.points_from_summaries(summ[f"{CONTROL}_{kind}"], kind)
        ev = L.evaluate_control(plan, kind, rows, ctl["a1"], ctl["a3"])
        ev["rows"] = rows
        controls[kind] = ev
    out["ngspice_control"] = {"a1": ctl["a1"], "a3": ctl["a3"], "placement": ctl["placement"],
                               "pass": all(c["pass"] for c in controls.values()), "evaluations": controls}
    # ---- DUT
    placements = {}
    for pl in plan["placements"]:
        n = pl["name"]
        sweeps, results = {}, {}
        for v in L.VARIANTS:
            sweeps[v] = {}
            for kind in KINDS:
                sweeps[v][kind] = L.points_from_summaries([s for s in summ[f"{n}_{kind}"] if s["variant"] == v], kind)
            results[v] = {"iip3": L.fit_iip3(sweeps[v]["two"], ex["iip3"], lim),
                          "p1db": L.fit_p1db(sweeps[v]["one"], ex["p1db"], lim)}
        base = results["base"]
        conv = {"iip3": [], "p1db": []}
        for v in ("half_step", "double_window"):
            conv["iip3"].append(L.convergence_verdict(plan, "iip3", sweeps["base"]["two"], base["iip3"],
                                                      sweeps[v]["two"], results[v]["iip3"], v))
            conv["p1db"].append(L.convergence_verdict(plan, "p1db", sweeps["base"]["one"], base["p1db"],
                                                      sweeps[v]["one"], results[v]["p1db"], v))
        entry = {"placement": pl, "frequencies_hz": L.placement_freqs(pl), "results": results["base"],
                 "convergence": conv,
                 "unrestricted_reference": {
                     "label": "NOT A RESULT: fits that ignore the operating limits (points outside them included); "
                              "shown only to locate where the limit-free curve would cross",
                     "iip3": L.fit_iip3(sweeps["base"]["two"], ex["iip3"], lim, enforce_limits=False),
                     "p1db": L.fit_p1db(sweeps["base"]["one"], ex["p1db"], lim, enforce_limits=False)},
                 "first_limit_violation": {"two_tone": first_limit_violation(plan, sweeps["base"]["two"]),
                                           "single_tone": first_limit_violation(plan, sweeps["base"]["one"])},
                 "sweeps": sweeps}
        final = {}
        for kind, tkey in (("iip3", "iip3_dbm"), ("p1db", "p1db_dbm")):
            cv = conv[kind]
            converged = all(c["ok"] for c in cv)
            deltas = [abs(c["estimator"].get("delta_db") or 0.0) for c in cv]
            status = base[kind]["status"] if converged else "unconverged"
            final[kind] = {"status": status, "converged": converged,
                           "max_estimator_delta_db": max(deltas) if deltas else 0.0,
                           "assessment": assess_target(kind, base[kind], plan["targets"][tkey],
                                                       max(deltas) if deltas else 0.0)
                           if converged else {"verdict": "not_determined", "target_dbm": plan["targets"][tkey],
                                              "reason": "convergence checks failed"}}
        entry["final"] = final
        placements[n] = entry
    out["placements"] = placements
    out["rows"] = row_summary(plan, placements)
    return out


def row_summary(plan: dict, placements: dict) -> dict:
    """Row 7 (IIP3) and row 8 (P1dB): the worst placement decides; unavailable/unconverged stay explicit."""
    rank = {"fails": 0, "marginal": 1, "not_determined": 2, "meets": 3}
    rows = {}
    for row, kind in (("7", "iip3"), ("8", "p1db")):
        per = {n: p["final"][kind] for n, p in placements.items()}
        verdicts = {n: f["assessment"]["verdict"] for n, f in per.items()}
        worst = min(verdicts.values(), key=lambda v: rank[v])
        rows[row] = {"kind": kind, "target_dbm": plan["targets"]["iip3_dbm" if kind == "iip3" else "p1db_dbm"],
                     "per_placement": {n: {"status": f["status"], "verdict": verdicts[n]} for n, f in per.items()},
                     "worst_verdict": worst}
    return rows
