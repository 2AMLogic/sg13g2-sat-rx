"""Cascode bias / collector-load headroom screening (issue #123).

Pure logic, no simulator: candidate netlist variants, the generated klt bodies, the parsing of
frozen logs into stress-qualified outcomes, the gates, the ranking and the outcome class. Every
rule lives in ``testbench/plan.json`` (frozen before collection); the nonlinear method itself
(available-power convention, P1dB extractor, operating limits, collector-current diagnostics) is
the committed ``sim/lna-linearity`` code and plan, reused unchanged.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
SIM_DIR = BENCH_DIR.parent
REPO_ROOT = SIM_DIR.parent
LIN_DIR = SIM_DIR / "lna-linearity"
for _p in (str(LIN_DIR), str(SIM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import linearity as L  # noqa: E402
import small_signal as SS  # noqa: E402

# the sibling bench's own run.py/analysis.py must not shadow this bench's modules
if str(LIN_DIR) in sys.path:
    sys.path.remove(str(LIN_DIR))

PLAN_PATH = BENCH_DIR / "testbench" / "plan.json"
DUT_PATH = REPO_ROOT / "design" / "netlist" / "lna_stage1.spice"
VARIANTS_DIR = BENCH_DIR / "variants"
CONTROL = "control"
SPARAM = "sparam_"
DC_NAMES = ("vc1", "ve1", "vb1", "vb2", "voc", "idd")
RE_R1B = re.compile(r"^(R1b vdd b2 )(\S+)( m=1)$", re.M)
RE_R2B = re.compile(r"^(R2b b2 gnd )(\S+)( m=1)$", re.M)
RE_RD = re.compile(r"^(Rd vdd oc )(\S+)( m=1)$", re.M)
_SI = {"k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15, "meg": 1e6}


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def spice_value(tok: str) -> float:
    m = re.fullmatch(r"([-+0-9.eE]+?)(meg|[kmunpf])?", tok.strip())
    if not m:
        raise ValueError(f"cannot parse SPICE value {tok!r}")
    return float(m.group(1)) * _SI.get(m.group(2) or "", 1.0)


def load_plans() -> tuple[dict, dict]:
    """(headroom plan, referenced lna-linearity plan); the reference hash and the DUT hash are checked."""
    hp = json.loads(PLAN_PATH.read_text())
    lp_path = REPO_ROOT / hp["linearity_plan"]["file"]
    got = sha256_bytes(lp_path.read_bytes())
    if got != hp["linearity_plan"]["sha256"]:
        raise ValueError(f"{lp_path} sha256 {got} != declared {hp['linearity_plan']['sha256']}")
    return hp, L.load_plan(lp_path)


# ---------------------------------------------------------------------------
# candidates / variant netlists
# ---------------------------------------------------------------------------


def candidates(hp: dict) -> list[dict]:
    return hp["candidates"]["table"]


def refinement(hp: dict) -> dict | None:
    """The stage-2 refinement declaration (plan version 2), or None for the stage-1 screening plan."""
    return hp.get("refinement")


def _refinement_problems(hp: dict) -> list[str]:
    ref = refinement(hp)
    out = []
    ids = {c["id"] for c in candidates(hp)}
    if "candidates" not in ref or not ref["candidates"]:
        return ["the refinement block declares no candidates"]
    for cid in ref["candidates"]:
        if cid not in ids:
            out.append(f"refinement candidate {cid} is not in the candidate table")
    if hp["candidates"]["baseline_id"] not in ref["candidates"]:
        out.append("the baseline reference candidate is not part of the refinement")
    if len(set(ref["candidates"])) != len(ref["candidates"]):
        out.append("duplicate refinement candidate ids")
    for sub in ("single_tone", "two_tone"):
        v = (ref.get(sub) or {}).get("variants")
        if not v or any(x not in L.VARIANTS for x in v):
            out.append(f"refinement {sub} declares an unknown or empty timing variant list")
    if ref.get("two_tone", {}).get("variants") != ["base"]:
        out.append("two-tone refinement must be base timing only (no two-tone convergence is claimed)")
    if not ref.get("rd_extension"):
        out.append("the refinement must declare whether an Rd < 200 ohm extension is in scope")
    ss = ref.get("small_signal") or {}
    for k in ("fixture", "manifest"):
        p = REPO_ROOT / (ss.get(k) or {}).get("file", "")
        if not p.is_file():
            out.append(f"small-signal {k} file is missing: {ss.get(k, {}).get('file')}")
        elif sha256_bytes(p.read_bytes()) != ss[k].get("sha256"):
            out.append(f"small-signal {k} sha256 differs from the one declared in the plan")
    br = ref.get("baseline_reproduction") or {}
    if not br.get("record_id"):
        out.append("the refinement declares no stage-1 baseline record id")
    elif not (BENCH_DIR / "records" / f"{br['record_id']}.json").is_file():
        out.append("the refinement's stage-1 baseline record is missing")
    return out


def plan_problems(hp: dict, lp: dict, dut_text: str) -> list[str]:
    out = []
    ids = [c["id"] for c in candidates(hp)]
    if len(set(ids)) != len(ids):
        out.append("duplicate candidate ids")
    if hp["candidates"]["baseline_id"] not in ids:
        out.append("baseline id not in the candidate table")
    if sha256_bytes(dut_text.encode()) != hp["dut"]["sha256"]:
        out.append("DUT netlist sha256 differs from the one declared in the plan")
    base = next(c for c in candidates(hp) if c["id"] == hp["candidates"]["baseline_id"])
    for name, rx, key in (("R1b", RE_R1B, "r1b_ohm"), ("R2b", RE_R2B, "r2b_ohm"), ("Rd", RE_RD, "rd_ohm")):
        m = rx.search(dut_text)
        if not m:
            out.append(f"DUT has no {name} line of the expected form")
        elif abs(spice_value(m.group(2)) - base[key]) > 1e-9:
            out.append(f"baseline candidate {key}={base[key]} differs from the DUT's {name}={m.group(2)}")
    total = {c["r1b_ohm"] + c["r2b_ohm"] for c in candidates(hp)}
    if len(total) != 1:
        out.append(f"divider total resistance is not held constant: {sorted(total)}")
    for pl in lp["placements"]:
        out += L.band_problems(lp, pl)
        out += [f"{pl['name']}: {p}" for p in L.placement_coherence(lp, pl, "base")]
    if L.current_cfg(lp) is None:
        out.append("referenced lna-linearity plan does not declare the collector-current diagnostics")
    if refinement(hp):
        out += _refinement_problems(hp)
        try:
            fixture, tb = SS.load_refs(hp)
        except ValueError as exc:
            out.append(f"small-signal references failed to load: {exc}")
        else:
            out += SS.fixture_problems(fixture, tb, dut_text)
    return out


def _num(x: float) -> str:
    return f"{x:g}"


def variant_text(dut_text: str, cand: dict, issue: str = "123") -> str:
    """The committed DUT with only R1b, R2b and Rd replaced; a comment line states the variant.

    ``issue`` appears only in the generated comment header; the default keeps the stage-1
    decks (and every stage-1 record's frozen-body regeneration) byte-identical."""
    t = dut_text
    for rx, key in ((RE_R1B, "r1b_ohm"), (RE_R2B, "r2b_ohm"), (RE_RD, "rd_ohm")):
        t, n = rx.subn(lambda m, v=cand[key]: f"{m.group(1)}{_num(v)}{m.group(3)}", t)
        if n != 1:
            raise ValueError(f"expected exactly one {key} line in the DUT netlist, found {n}")
    head = (f"* EXPERIMENTAL VARIANT {cand['id']} of design/netlist/lna_stage1.spice (issue #{issue}): R1b={_num(cand['r1b_ohm'])} "
            f"R2b={_num(cand['r2b_ohm'])} Rd={_num(cand['rd_ohm'])} ohm; everything else is the committed DUT.\n"
            "* GENERATED by sim/lna-headroom/run.py; NOT a production schematic; do not edit.\n")
    return head + t


# ---------------------------------------------------------------------------
# bodies / runs
# ---------------------------------------------------------------------------


def request_keys(hp: dict) -> list[str]:
    """Stage 1: the control and one request per candidate. Stage 2: one control per kind plus,
    per refined candidate, the single-tone request (all declared variants), the two-tone request
    (base only) and the small-signal request."""
    ref = refinement(hp)
    if not ref:
        return [CONTROL] + [c["id"] for c in candidates(hp)]
    keys = [f"{CONTROL}_{k}" for k in ("one", "two")]
    for cid in ref["candidates"]:
        keys += [f"{cid}_one", f"{cid}_two", f"{SPARAM}{cid}"]
    return keys


def runs_for_key(hp: dict, lp: dict, key: str) -> list[dict]:
    """Declared runs of one request (identical on generation and analysis); ids carry the placement."""
    ref = refinement(hp)
    out = []
    if is_control_key(hp, key):
        kind = "one" if key == CONTROL else key.rsplit("_", 1)[1]
        pl = next(p for p in lp["placements"] if p["name"] == lp["controls"]["placement"])
        for r in L.sweep_runs(lp, pl, kind, monitors=False, variants=("base",)):
            out.append(dict(r, id=f"ctl_{r['id']}", placement=pl["name"]))
        return out
    if ref:
        if key.startswith(SPARAM):
            raise KeyError(key)
        cid, kind = key.rsplit("_", 1)
        if kind not in ("one", "two"):
            raise KeyError(key)
        variants = tuple(ref["single_tone"]["variants"]) if kind == "one" else tuple(ref["two_tone"]["variants"])
        for pl in lp["placements"]:
            for r in L.sweep_runs(lp, pl, kind, monitors=True, variants=variants):
                out.append(dict(r, id=f"{pl['name']}_{r['id']}", placement=pl["name"]))
        return out
    for pl in lp["placements"]:
        for r in L.sweep_runs(lp, pl, "one", monitors=True, variants=("base",)):
            out.append(dict(r, id=f"{pl['name']}_{r['id']}", placement=pl["name"]))
    return out


def dc_lines() -> list[str]:
    return ["  * DC allocation of the candidate (operating point before any transient)",
            "  op",
            "  let m_dc_vc1 = v(xdut.c1)", "  let m_dc_ve1 = v(xdut.e1)", "  let m_dc_vb1 = v(xdut.b1)",
            "  let m_dc_vb2 = v(xdut.b2)", "  let m_dc_voc = v(xdut.oc)", "  let m_dc_idd = -i(Vdd)",
            "  print m_dc_vc1 m_dc_ve1 m_dc_vb1 m_dc_vb2 m_dc_voc m_dc_idd"]


def body_for_key(hp: dict, lp: dict, key: str, dut_text: str) -> str:
    runs = runs_for_key(hp, lp, key)
    ref = refinement(hp)
    is_control = is_control_key(hp, key)
    kind = "one" if key == CONTROL else (key.rsplit("_", 1)[1] if ref else "one")
    if is_control:
        c = lp["controls"]
        circuit = L.control_circuit(c["a1"], c["a3"])
        title = f"lna-headroom {key}"
    else:
        cid = key if not ref else key.rsplit("_", 1)[0]
        cand = next(c for c in candidates(hp) if c["id"] == cid)
        circuit = L.dut_circuit(variant_text(dut_text, cand), lp["nominal"]["vdd_v"])
        title = f"lna-headroom {key}"
    circuit += "\n" + L.options_line(lp, kind)
    body = L.body_for_runs(title, circuit, runs).replace("sim/lna-linearity/run.py", "sim/lna-headroom/run.py")
    if not is_control:
        marker = "set noaskquit\n"
        assert marker in body
        body = body.replace(marker, marker + "\n".join(dc_lines()) + "\n", 1)
    return body


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------

_ID_RE = re.compile(r"^(q\d) (V_CE peak|V_CE minimum|V_BE peak|V_BE minimum|I_C peak)")


def limit_identity(msg: str) -> str:
    m = _ID_RE.match(msg)
    return f"{m.group(1)} {m.group(2)}" if m else msg


def is_control_key(hp: dict, key: str) -> bool:
    """The stage-1 ``control`` request, or a stage-2 ``control_one``/``control_two`` one."""
    return key == CONTROL or (refinement(hp) is not None and key.startswith(f"{CONTROL}_"))


def summaries(hp: dict, lp: dict, key: str, text: str) -> tuple[list[dict], dict, list[str]]:
    vals, done = L.parse_log(text)
    aborted = any(m in text for m in L.ABORT_MARKERS)
    problems = []
    if not done:
        problems.append(f"{key}: log has no LNLIN_DONE (deck did not finish)")
    out = []
    for run in runs_for_key(hp, lp, key):
        s = L.run_summary(vals, run, log_has_abort=aborted)
        if s is None:
            problems.append(f"{key}: run {run['id']} ({run['pin_dbm']:g} dBm) is missing or non-finite")
        else:
            out.append(dict(s, placement=run["placement"]))
    dc = {}
    if not is_control_key(hp, key):
        for n in DC_NAMES:
            v = vals.get(f"m_dc_{n}")
            if v is None or not math.isfinite(v):
                problems.append(f"{key}: DC operating-point value {n} is missing or non-finite")
            else:
                dc[n] = v
    return out, dc, problems


def dc_allocation(dc: dict, re1_ohm: float = 3.0) -> dict:
    return {"vc1_v": dc["vc1"], "vb2_v": dc["vb2"], "voc_v": dc["voc"], "ve1_v": dc["ve1"],
            "vce_q1_v": dc["vc1"] - dc["ve1"], "vce_q2_v": dc["voc"] - dc["vc1"],
            "vbe_q2_v": dc["vb2"] - dc["vc1"], "vbe_q1_v": dc["vb1"] - dc["ve1"],
            "ic_q1_ma_from_re1": dc["ve1"] / re1_ohm * 1e3, "idd_ma": dc["idd"] * 1e3}


def stress_boundary(lp: dict, rows: list[dict]) -> dict:
    """First swept power where the device leaves its operating limits (or the simulator aborts),
    the last stress-valid power below it, and the limit identity. Rows are never fitted through."""
    lim = lp["extraction"]["operating_limits"]
    rows = sorted(rows, key=lambda r: r["pin_dbm"])
    for i, r in enumerate(rows):
        if r.get("sim_failed"):
            v = ["simulation failed: " + str(r["sim_failed"])]
        else:
            v = L.limit_violations(r.get("excursion_v"), lim, r.get("current_a"))
        if v:
            return {"first_violation_pin_dbm": r["pin_dbm"], "violations": v, "limit_identity": limit_identity(v[0]),
                    "stress_free_pin_dbm": rows[i - 1]["pin_dbm"] if i > 0 else None, "violated": True}
    return {"first_violation_pin_dbm": None, "violations": [], "limit_identity": None,
            "stress_free_pin_dbm": rows[-1]["pin_dbm"], "violated": False}


def placement_result(hp: dict, lp: dict, summs: list[dict]) -> dict:
    ex = lp["extraction"]
    lim = ex["operating_limits"]
    rows = L.points_from_summaries(summs, "one")
    fit = L.fit_p1db(rows, ex["p1db"], lim)
    sb = stress_boundary(lp, rows)
    drops = fit.get("gain_drop_db") or {}
    sf = sb["stress_free_pin_dbm"]
    cv = L.current_validity(rows, lim)
    res = {"p1db": {k: fit.get(k) for k in ("status", "p1db_in_dbm", "p1db_in_dbm_gt", "bracket", "reason")},
           "baseline_gain_db": (fit.get("baseline") or {}).get("gain_db"),
           "baseline_pin_dbm": (fit.get("baseline") or {}).get("pin_dbm"),
           "stress": sb,
           "gain_drop_at_stress_free_db": drops.get(f"{sf:g}") if sf is not None else None,
           "gap_to_row8_target_db": (hp["targets"]["p1db_dbm"] - sf) if sf is not None else None,
           "current_diagnostics": {"status": cv["status"], "complete_envelope": cv["complete_envelope"],
                                   "extrema_frac_of_box": {q: {"max": e["max_frac_of_box"], "min": e["min_frac_of_box"]}
                                                           for q, e in cv["extrema"].items()},
                                   "points_over_box_pin_dbm": cv["points_over_box_pin_dbm"]},
           "vce_q2_peak_v": {f"{r['pin_dbm']:g}": r["excursion_v"]["vce_q2_max"] for r in rows if r.get("excursion_v")}}
    return res


def reproduce_baseline(cfg: dict, lp: dict, base_by_pl: dict, historical: dict, hist_sweeps: dict) -> dict:
    """The baseline candidate must reproduce the anchored prior outcome within the declared tolerances.

    ``cfg`` is the declaring block (stage 1: vs the lna-linearity record; stage 2: vs the stage-1 record)."""
    checks, ok = {}, True
    for name, res in base_by_pl.items():
        h = historical["placements"][name]["first_limit_violation"]["single_tone"]
        got = res["stress"]
        c = {"historical_first_violation_pin_dbm": h["pin_dbm"] if h else None,
             "first_violation_pin_dbm": got["first_violation_pin_dbm"],
             "historical_identity": limit_identity(h["violations"][0]) if h else None,
             "identity": got["limit_identity"]}
        good = bool(h) and got["violated"] and abs(got["first_violation_pin_dbm"] - h["pin_dbm"]) <= cfg["pin_tolerance_db"] \
            and c["historical_identity"] == c["identity"]
        worst_v, worst_g = 0.0, 0.0
        hrows = {f"{r['pin_dbm']:g}": r for r in hist_sweeps[name]["base"]["one"]}
        for r in res["_rows"]:
            hr = hrows.get(f"{r['pin_dbm']:g}")
            if hr is None or not hr.get("excursion_v") or not r.get("excursion_v"):
                good = False
                continue
            worst_v = max(worst_v, abs(r["excursion_v"]["vce_q2_max"] - hr["excursion_v"]["vce_q2_max"]))
            if r.get("p_f0_dbm") is not None and hr.get("p_f0_dbm") is not None:
                worst_g = max(worst_g, abs(r["p_f0_dbm"] - hr["p_f0_dbm"]))
        c.update(max_vce_q2_peak_delta_v=worst_v, max_delivered_power_delta_db=worst_g)
        good = good and worst_v <= cfg["vce_q2_peak_tol_v"] and worst_g <= cfg["gain_tol_db"]
        c["reproduced"] = good
        ok &= good
        checks[name] = c
    return {"reproduced": ok, "record": cfg["record"], "tolerances": {k: cfg[k] for k in ("pin_tolerance_db", "vce_q2_peak_tol_v", "gain_tol_db")},
            "per_placement": checks}


def gates(hp: dict, lp: dict, cid: str, dc: dict, per: dict, base_per: dict) -> dict:
    g = hp["gates"]
    alloc = dc_allocation(dc)
    lo, hi = lp["extraction"]["operating_limits"]["vce_window_v"][0], lp["extraction"]["operating_limits"]["vce_max_v"] - g["dc_vce_margin_v"]
    g_dc = all(lo <= alloc[k] <= hi for k in ("vce_q1_v", "vce_q2_v"))
    g_base = all(p["baseline_gain_db"] is not None for p in per.values())
    loss = {n: (base_per[n]["baseline_gain_db"] - p["baseline_gain_db"]) if g_base else None for n, p in per.items()}
    g_gain = g_base and all(v <= g["gain_loss_max_db"] for v in loss.values())
    failed = [n for n, v in (("G_dc", g_dc), ("G_base", g_base), ("G_gain", g_gain)) if not v]
    return {"G_dc": g_dc, "G_gain": g_gain, "G_base": g_base, "failed": failed, "gain_loss_db": loss,
            "dc_window_v": [lo, hi]}


def metrics(hp: dict, per: dict, base_per: dict) -> dict:
    sf = {n: p["stress"]["stress_free_pin_dbm"] for n, p in per.items()}
    worst = None if any(v is None for v in sf.values()) else min(sf.values())
    bsf = {n: p["stress"]["stress_free_pin_dbm"] for n, p in base_per.items()}
    bworst = None if any(v is None for v in bsf.values()) else min(bsf.values())
    out = {"stress_free_pin_dbm": sf, "worst_stress_free_pin_dbm": worst, "headroom_gain_db": None, "net_output_headroom_db": None}
    if worst is not None and bworst is not None:
        out["headroom_gain_db"] = worst - bworst
        nets = []
        for n, p in per.items():
            if p["baseline_gain_db"] is None or base_per[n]["baseline_gain_db"] is None:
                nets = None
                break
            nets.append((sf[n] - bsf[n]) + (p["baseline_gain_db"] - base_per[n]["baseline_gain_db"]))
        out["net_output_headroom_db"] = min(nets) if nets else None
    return out


def rank(hp: dict, cands: dict) -> dict:
    """cands: id -> {gates, metrics, placements}. Deterministic ranking, shortlist, outcome class."""
    admitted = [cid for cid, c in cands.items() if not c["gates"]["failed"] and c["metrics"]["worst_stress_free_pin_dbm"] is not None]

    def key(cid):
        c = cands[cid]
        g = min(p["baseline_gain_db"] for p in c["placements"].values())
        return (-c["metrics"]["worst_stress_free_pin_dbm"], -g, cid)

    order = sorted(admitted, key=key)
    sl = hp["shortlist"]
    short = [cid for cid in order
             if cands[cid]["metrics"]["headroom_gain_db"] is not None
             and cands[cid]["metrics"]["headroom_gain_db"] >= sl["min_headroom_gain_db"]
             and (cands[cid]["metrics"]["net_output_headroom_db"] or 0.0) > 0][: sl["size"]]
    tgt = hp["targets"]["p1db_dbm"]

    def p1db_all_ok(cid):
        ps = cands[cid]["placements"]
        return all(p["p1db"]["status"] == "ok" for p in ps.values())

    if any(p1db_all_ok(c) and all(p["p1db"]["p1db_in_dbm"] >= tgt for p in cands[c]["placements"].values()) for c in order):
        cls = "stress_valid_p1db_meets_row8"
    elif any(p1db_all_ok(c) for c in order):
        cls = "stress_valid_p1db_below_row8"
    elif short:
        cls = "headroom_improved_p1db_undetermined"
    else:
        cls = "no_feasible_candidate"
    return {"admitted": order, "shortlist": short, "outcome_class": cls,
            "not_ranked": {cid: c["gates"]["failed"] for cid, c in cands.items() if c["gates"]["failed"]}}


def analyze(hp: dict, lp: dict, texts: dict, historical: dict, hist_sweeps: dict, refs=None) -> dict:
    if refinement(hp):
        return analyze_refined(hp, lp, texts, historical, hist_sweeps, refs)
    problems = []
    summ, dcs = {}, {}
    for key in request_keys(hp):
        if key not in texts:
            problems.append(f"{key}: no log")
            continue
        s, dc, pr = summaries(hp, lp, key, texts[key])
        summ[key], dcs[key] = s, dc
        problems += pr
    out: dict = {"problems": problems}
    if problems:
        return out
    ctl = lp["controls"]
    rows = L.points_from_summaries(summ[CONTROL], "one")
    ev = L.evaluate_control(lp, "one", rows, ctl["a1"], ctl["a3"])
    out["ngspice_control"] = {"a1": ctl["a1"], "a3": ctl["a3"], "kind": "one", "pass": bool(ev["pass"]),
                              "expected_dbm": ev["expected_dbm"], "error_db": ev["error_db"],
                              "expected_gain_db": ev["expected_gain_db"], "gain_error_db": ev["gain_error_db"],
                              "tol_db": ev["tol_db"], "gain_tol_db": ev["gain_tol_db"]}
    per_c, rows_c = {}, {}
    for c in candidates(hp):
        cid = c["id"]
        per, hold = {}, {}
        for pl in lp["placements"]:
            ss = [s for s in summ[cid] if s["placement"] == pl["name"]]
            per[pl["name"]] = placement_result(hp, lp, ss)
            hold[pl["name"]] = L.points_from_summaries(ss, "one")
        per_c[cid], rows_c[cid] = per, hold
    bid = hp["candidates"]["baseline_id"]
    base_per = per_c[bid]
    reps = {n: dict(base_per[n], _rows=rows_c[bid][n]) for n in base_per}
    repro = reproduce_baseline(hp["baseline_reproduction"], lp, reps, historical, hist_sweeps)
    cands = {}
    for c in candidates(hp):
        cid = c["id"]
        cands[cid] = {"candidate": c, "dc": dc_allocation(dcs[cid]), "placements": per_c[cid],
                      "gates": gates(hp, lp, cid, dcs[cid], per_c[cid], base_per),
                      "metrics": metrics(hp, per_c[cid], base_per)}
    out["baseline_reproduction"] = repro
    out["candidates"] = cands
    out["ranking"] = rank(hp, cands) if repro["reproduced"] else {
        "admitted": [], "shortlist": [], "outcome_class": "BASELINE_NOT_REPRODUCED", "not_ranked": {}}
    out["sweeps"] = {cid: {n: rows_c[cid][n] for n in rows_c[cid]} for cid in rows_c}
    return out


def roundtrip(x, sig: int = 9):
    if isinstance(x, float):
        return float(f"{x:.{sig}g}") if math.isfinite(x) else (None if math.isnan(x) else ("+inf" if x > 0 else "-inf"))
    if isinstance(x, dict):
        return {k: roundtrip(v, sig) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [roundtrip(v, sig) for v in x]
    return x


def load_historical(rid: str) -> tuple[dict, dict]:
    rec = json.loads((LIN_DIR / "records" / f"{rid}.json").read_text())
    with gzip.open(LIN_DIR / "records" / f"{rid}-sweeps.json.gz", "rt", encoding="utf-8") as fh:
        sw = json.load(fh)
    return rec, sw


def sparam_deck(hp: dict, fixture_text: str, dut_text: str, cid: str) -> str:
    """The small-signal fixture text for one candidate.

    The baseline candidate IS the committed DUT, so its deck is the production bench's own fixture
    byte-identical; any other candidate gets the embedded verbatim DUT replaced by its frozen
    variant deck (the only difference from the production deck)."""
    if cid == hp["candidates"]["baseline_id"]:
        return fixture_text
    cand = next(c for c in candidates(hp) if c["id"] == cid)
    return SS.variant_fixture(fixture_text, variant_text(dut_text, cand, issue="132"))


def load_stage1_historical(hp: dict) -> tuple[dict, dict]:
    """The stage-1 record's baseline outcome and base sweep, in the shape reproduce_baseline expects."""
    rid = refinement(hp)["baseline_reproduction"]["record_id"]
    rec = json.loads((BENCH_DIR / "records" / f"{rid}.json").read_text())
    with gzip.open(BENCH_DIR / "records" / f"{rid}-sweeps.json.gz", "rt", encoding="utf-8") as fh:
        sw = json.load(fh)
    bid = hp["candidates"]["baseline_id"]
    historical, hist_sweeps = {"placements": {}}, {}
    for name, p in rec["candidates"][bid]["placements"].items():
        st = p["stress"]
        historical["placements"][name] = {"first_limit_violation": {"single_tone": {
            "pin_dbm": st["first_violation_pin_dbm"], "violations": st["violations"]}}}
    for name, rows in sw[bid].items():
        hist_sweeps[name] = {"base": {"one": rows}}
    return historical, hist_sweeps


def _first_violation(rows: list[dict], limits: dict) -> dict | None:
    for r in sorted(rows, key=lambda x: x["pin_dbm"]):
        if r.get("sim_failed"):
            continue
        v = L.limit_violations(r.get("excursion_v"), limits, r.get("current_a"))
        if v:
            return {"pin_dbm": r["pin_dbm"], "violations": v}
    return None


def analyze_refined(hp: dict, lp: dict, texts: dict, historical: dict, hist_sweeps: dict, refs=None) -> dict:
    """Stage 2: the frozen-log analysis of the refined shortlist (issue #132).

    ``refs`` is the (fixture text, parsed manifest) pair for the small-signal decks; run.py passes
    the live pair at collection time and the frozen snapshot pair at verify time."""
    ref = refinement(hp)
    problems = []
    fixture_text, tb = refs if refs is not None else SS.load_refs(hp)
    names = SS.measure_names(tb)
    summ, dcs, sp = {}, {}, {}
    for key in request_keys(hp):
        if key.startswith(SPARAM):
            m, pr = SS.parse_measurements(texts.get(key), names)
            sp[key[len(SPARAM):]] = m
            problems += [f"{key}: {p}" for p in pr]
            continue
        if key not in texts:
            problems.append(f"{key}: no log")
            continue
        s, dc, pr = summaries(hp, lp, key, texts[key])
        summ[key], dcs[key] = s, dc
        problems += pr
    out: dict = {"problems": problems}
    if problems:
        return out
    # ---- analytic controls, both kinds
    ctl = lp["controls"]
    ev = {}
    for kind in ("one", "two"):
        rows = L.points_from_summaries(summ[f"{CONTROL}_{kind}"], kind)
        e = L.evaluate_control(lp, kind, rows, ctl["a1"], ctl["a3"])
        ev[kind] = {k: e[k] for k in ("expected_dbm", "expected_gain_db", "error_db", "gain_error_db",
                                      "tol_db", "gain_tol_db", "pass")}
    out["ngspice_control"] = {"pass": all(e["pass"] for e in ev.values()), "evaluations": ev}
    # ---- per candidate: base single-tone outcome, convergence, two-tone
    lim = lp["extraction"]["operating_limits"]
    per_c, rows_c, conv_c, two_c = {}, {}, {}, {}
    for cid in ref["candidates"]:
        one_summ, two_summ = summ[f"{cid}_one"], summ[f"{cid}_two"]
        per, hold, conv, two = {}, {}, {}, {}
        for pl in lp["placements"]:
            base = [s for s in one_summ if s["placement"] == pl["name"] and s["variant"] == "base"]
            per[pl["name"]] = placement_result(hp, lp, base)
            hold[pl["name"]] = {}
            for v in ref["single_tone"]["variants"]:
                sv = [s for s in one_summ if s["placement"] == pl["name"] and s["variant"] == v]
                hold[pl["name"]][v] = L.points_from_summaries(sv, "one")
            base_res = per[pl["name"]]["p1db"]
            conv[pl["name"]] = [
                L.convergence_verdict(lp, "p1db", hold[pl["name"]]["base"], base_res, hold[pl["name"]][v],
                                      L.fit_p1db(hold[pl["name"]][v], lp["extraction"]["p1db"], lim), v)
                for v in ("half_step", "double_window")]
            trows = L.points_from_summaries([s for s in two_summ if s["placement"] == pl["name"]], "two")
            hold[pl["name"]]["two"] = trows
            two[pl["name"]] = {"iip3": L.fit_iip3(trows, lp["extraction"]["iip3"], lim),
                               "first_violation": _first_violation(trows, lim)}
        per_c[cid], rows_c[cid], conv_c[cid], two_c[cid] = per, hold, conv, two
    # ---- stage-1 reproduction of the reference candidate
    bid = hp["candidates"]["baseline_id"]
    reps = {n: dict(per_c[bid][n], _rows=rows_c[bid][n]["base"]) for n in per_c[bid]}
    repro = reproduce_baseline(ref["baseline_reproduction"], lp, reps, historical, hist_sweeps)
    out["baseline_reproduction"] = repro
    # ---- candidates: gates (as declared for the table), metrics vs C00, validity, small signal
    cands = {}
    v_conv = {}
    for cid in ref["candidates"]:
        v_conv[cid] = all(c["ok"] for conv in conv_c[cid].values() for c in conv)
        cands[cid] = {"candidate": next(c for c in candidates(hp) if c["id"] == cid),
                      "dc": dc_allocation(dcs[f"{cid}_one"]), "placements": per_c[cid], "convergence": conv_c[cid],
                      "two_tone": two_c[cid],
                      "gates": gates(hp, lp, cid, dcs[f"{cid}_one"], per_c[cid], per_c[bid]),
                      "metrics": metrics(hp, per_c[cid], per_c[bid]),
                      "validity": {"V_conv": v_conv[cid], "failed": [] if v_conv[cid] else ["V_conv"]},
                      "small_signal": {"measurements": sp[cid],
                                       "vs_baseline": SS.compare(sp[cid], sp[bid]) if cid != bid else None}}
    out["candidates"] = cands
    # ---- ranking and outcome (frozen rules)
    ranked = [cid for cid in ref["candidates"] if v_conv[cid]] \
        if (out["ngspice_control"]["pass"] and repro["reproduced"]) else []

    def key(cid):
        m = cands[cid]["metrics"]
        gains = [p["baseline_gain_db"] for p in per_c[cid].values()]
        g = min((v for v in gains if v is not None), default=None)
        worst = m["worst_stress_free_pin_dbm"]
        return (-(worst if worst is not None else -1e9), -(g if g is not None else -1e9), cid)

    order = sorted(ranked, key=key)
    tgt = hp["targets"]["p1db_dbm"]

    def p1db_all_ok(cid):
        return all(p["p1db"]["status"] == "ok" for p in per_c[cid].values())

    if not out["ngspice_control"]["pass"] or not repro["reproduced"]:
        cls = "refinement_invalid"
    elif any(p1db_all_ok(c) and all(p["p1db"]["p1db_in_dbm"] >= tgt for p in per_c[c].values()) for c in order):
        cls = "refined_stress_valid_p1db_meets_row8"
    elif any(p1db_all_ok(c) for c in order):
        cls = "refined_stress_valid_p1db_below_row8"
    elif order:
        cls = "refined_converged_p1db_still_bounded"
    else:
        cls = "refined_unconverged"
    out["ranking"] = {"ranked": order, "outcome_class": cls,
                      "validity": {cid: cands[cid]["validity"] for cid in ref["candidates"]},
                      "not_ranked": {cid: cands[cid]["validity"]["failed"] for cid in ref["candidates"]
                                     if cands[cid]["validity"]["failed"]}}
    out["sweeps"] = {cid: {n: dict(rows_c[cid][n]) for n in rows_c[cid]} for cid in rows_c}
    return out
