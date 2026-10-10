#!/usr/bin/env python3
"""Driver for the mixer-core topology feasibility study (issue #35).

    python3 sim/mixer-topology-feasibility/run.py plan
    python3 sim/mixer-topology-feasibility/run.py smoke
    python3 sim/mixer-topology-feasibility/run.py selftest
    python3 sim/mixer-topology-feasibility/run.py converge [--candidate NAME]
    python3 sim/mixer-topology-feasibility/run.py collect [--dry-run] [--backend batch] [--workdir DIR]

All four modes are LOCAL and SINGLE-CORNER (hbt_typ / 27 C / 2.25 V, plus
the one-corner process, sabotage and mismatch controls in selftest), one
ngspice process at a time, and NEVER write evidence:

- plan      prints the declared matrices and the cell count every accepted
            record must account for. No simulation.
- smoke     analytic-control extraction check, then every candidate at the
            smoke band and trial LO drive (RF -60/-66 dBm and RF off): real
            model selection, netlisting, measurement parsing, stress table.
- selftest  negative controls: analytic control incl. a swept two-tone IIP3
            against its closed form; process corners move the result and
            sabotaged corners do not; the mismatch card realizes a fixed seed
            reproducibly; a deck with a deleted measurement is rejected; the
            collection gate rejects missing/duplicate/NaN cells, typical-forced
            corners and inconsistent stress classification.
- converge  window/timestep convergence control at the nominal cell for each
            candidate (doubled retained window, halved maximum timestep;
            gain and leakage within 0.2 dB).

The first four modes never write evidence. `collect` is the full comparison
(LO-selection sweep, 243-cell main matrix, 243-cell mismatch leakage matrix,
IIP3 sweeps): it is expressed as `klt sim` requests (collect.py), never as a
local ngspice grid, and writes ONE append-only record only if the whole
collection passes the acceptance gate.

Exit status: 0 on success; 1 on any failure. A failed run is never recorded.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
SIM_DIR = BENCH_DIR.parent
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(BENCH_DIR))

import mixfeas as mf  # noqa: E402
from harness.corners import (  # noqa: E402
    CORNERS, PvtPoint, build_grid, register_corner, resolve_corners, sabotage,
)
from harness import klt_driver  # noqa: E402
from harness.runner import NgspiceMissing, ngspice_version, run_point  # noqa: E402
from harness.testbench import load  # noqa: E402

SCRATCH = BENCH_DIR / "_build"
TB_DIR = BENCH_DIR / "testbench"

# Bench-local extension (sim/harness/corners.py docstring: register, do not
# edit the shared table): cornerHBT.lib's mismatch sections.
for _name, _desc in (("hbt_typ_mismatch", "typical HBT + per-instance area mismatch (agauss)"),
                     ("hbt_bcs_mismatch", "best-case-speed HBT + per-instance area mismatch"),
                     ("hbt_wcs_mismatch", "worst-case-speed HBT + per-instance area mismatch")):
    if _name not in CORNERS:
        register_corner(_name, (_name,), _desc)


def _load():
    tb = load(BENCH_DIR)
    manifest = json.loads((tb.directory / "tb.json").read_text())
    return tb, mf.study_from_manifest(manifest)


def _pdk():
    return klt_driver.find_pdk_or_exit(SIM_DIR)


def compose_fragment(cand: mf.Candidate, workdir: Path) -> Path:
    """ports_common.spice + the candidate fragment, as one harness fragment."""
    workdir.mkdir(parents=True, exist_ok=True)
    text = (TB_DIR / "ports_common.spice").read_text() + "\n" + (TB_DIR / cand.fragment).read_text()
    path = workdir / f"{cand.name}.fragment.spice"
    path.write_text(text)
    return path


def nominal_point(corner: str = "hbt_typ", temp: float = 27.0, vdd: float = 2.25) -> PvtPoint:
    return build_grid(resolve_corners([corner]), [temp], [vdd])[0]


def run_deck(tb, study, pdk, cand, point: PvtPoint, runs: list[mf.RunSpec], workdir: Path, *,
             seed: int | None = None, drop_key: str | None = None, timeout_s: int = 3600):
    """One PVT point, one local ngspice process, several transient runs.

    Returns (results by run id, problems, raw parsed values by run id)."""
    fragment = compose_fragment(cand, workdir)
    options = tuple(tb.options) + ((f"seed={seed}",) if seed is not None else ())
    tb_run = dataclasses.replace(
        tb, netlist=fragment, measure={}, options=options,
        params={k: repr(float(v)) for k, v in mf.deck_params(study, cand).items()},
        analyses=tuple(mf.build_control_lines(runs, cand.devices, sink_nodes=cand.sink_nodes,
                                              drop_key=drop_key)),
    )
    result = run_point(tb_run, pdk, point, workdir, timeout_s=timeout_s, num_threads=1)
    text = (workdir / result.log).read_text() if result.log else ""
    parsed = mf.parse_log(text)
    problems = list(parsed.problems)
    if result.status != "ok":
        problems.append(f"runner: {result.status} {result.message}")
    out = {}
    for run in runs:
        values = parsed.runs.get(run.run_id, {})
        res = mf.analyze_run(run, values, cand.devices, study.stress, abs_floor_dbm=study.abs_floor_dbm,
                             floor_margin_db=study.floor_margin_db, sink_nodes=cand.sink_nodes)
        mf.with_dc_power(res, values, point.vdd)
        res.update(corner=point.corner.name, model_section=point.corner.sections[0],
                   temp_c=point.temp_c, vdd_v=point.vdd, candidate=cand.name, seed=seed)
        out[run.run_id] = res
    return out, problems, parsed.runs


def make_run(study, run_id, kind, band, vlo_dbm, rf_dbm, *, window_scale=1.0, step_scale=1.0):
    t = study.timing
    window = (t.window_two_tone_s if kind == "two_tone" else t.window_single_s) * window_scale
    return mf.RunSpec(run_id=run_id, kind=kind, band=band, vlo_dbm=vlo_dbm,
                      rf_dbm=None if kind == "rfoff" else rf_dbm, window_s=window, settle_s=t.settle_s,
                      tmax_s=t.tmax_s * step_scale, tstep_s=t.tstep_s * step_scale, if_hz=study.if_hz)


def _f(x, fmt="{:.3f}"):
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else fmt.format(x)


def print_result(res: dict, indent: str = "    "):
    if res["status"] == "invalid":
        print(f"{indent}{res['run_id']}: INVALID {res['problems']}")
        return
    parts = [f"{res['run_id']}: {res['status']}"]
    if "gain_db" in res:
        parts.append(f"G={_f(res['gain_db'])} dB")
    for key, label, fkey in (("lo_if_dbm", "LO->IF", "loif"), ("lo_rf_dbm", "LO->RF", "lorf")):
        if key not in res:
            continue
        floor = res["floor_dbm"][fkey]
        if res["resolved"][fkey]:
            parts.append(f"{label}={res[key]:.1f} dBm (floor {floor:.0f})")
        else:
            parts.append(f"{label}<={floor + res['floor_margin_db']:.0f} dBm (unresolved, floor {floor:.0f})")
    if "p_im3l_dbm" in res:
        parts.append(f"IF1/IF2={_f(res['p_if1_dbm'], '{:.2f}')}/{_f(res['p_if2_dbm'], '{:.2f}')} "
                     f"IM3 L/H={_f(res['p_im3l_dbm'], '{:.2f}')}/{_f(res['p_im3h_dbm'], '{:.2f}')} dBm")
    parts.append(f"LO {res['lo_avail_dbm']:g} dBm avail, Vdiff open/loaded "
                 f"{res['lo_vdiff_open_peak_v']:.3f}/{res['lo_vdiff_loaded_peak_v']:.3f} V pk")
    parts.append(f"P_rail={_f(res['rail_power_mw'])} mW (DC {_f(res['dc_rail_power_mw'])})")
    for node, v in res.get("ideal_sink_v", {}).items():
        parts.append(f"ideal sink {node}: DC {v['dc']:.3f} V, retained min {v['retained_min']:.3f} V")
    print(f"{indent}" + "; ".join(parts))
    for v in res["stress"]["violations"]:
        tag = "REJECT" if v in res["stress"]["rejecting"] else "flag"
        print(f"{indent}  [{tag}] {v['device']} {v['interval']} {v['quantity']} {v['kind']} "
              f"{_f(v['value'], '{:.4g}')} (limit {_f(v['limit'], '{:.4g}')})")


def print_stress_table(res: dict, indent: str = "    "):
    if res["status"] == "invalid":
        return
    for row in res["stress"]["table"]:
        cells = []
        for iv in mf.STRESS_INTERVALS:
            cells.append(f"{iv}: VCE {row[f'{iv}_vce_min']:.3f}..{row[f'{iv}_vce_max']:.3f} "
                         f"VBE {row[f'{iv}_vbe_min']:.3f}..{row[f'{iv}_vbe_max']:.3f} "
                         f"Ic {row[f'{iv}_ic_min'] * 1e3:.3f}..{row[f'{iv}_ic_max'] * 1e3:.3f} mA")
        print(f"{indent}{row['device']} (Nx={row['nx']}): " + " | ".join(cells))


# ---------------------------------------------------------------------------
# analytic control
# ---------------------------------------------------------------------------

#: Closed-form agreement required of the analytic control, ON TOP of the
#: linear-interpolation bound of mixfeas.interp_bound_db at the quantity's
#: own frequency (the only known systematic error of the extraction).
ANALYTIC_TOL_DB = 0.01


def analytic_check(tb, study, pdk, workdir: Path, *, iip3_sweep: bool) -> list[str]:
    """Run the behavioural control through the real extraction chain and
    compare every quantity with its closed form."""
    ctrl = study.control
    band = study.band(study.smoke.get("band", study.bands[1].name))
    drive = float(study.smoke.get("trial_lo_dbm", 0.0))
    runs = [make_run(study, "a_single", "single", band, drive, study.rf_dbm),
            make_run(study, "a_rfoff", "rfoff", band, drive, None),
            make_run(study, "a_tt", "two_tone", band, drive, -30.0)]
    sweep = [-45.0, -40.0, -35.0, -30.0, -25.0] if iip3_sweep else []
    runs += [make_run(study, f"a_ip{int(-p)}", "two_tone", band, drive, p) for p in sweep]
    results, problems, _ = run_deck(tb, study, pdk, ctrl, nominal_point(), runs, workdir / "analytic")
    failures = [f"analytic deck: {p}" for p in problems]
    for run in runs:
        res = results[run.run_id]
        if res["status"] != "ok":
            failures.append(f"analytic {run.run_id}: {res['status']} {res.get('problems')}")
            continue
        exp = mf.analytic_expectations(ctrl.params, run)
        worst = 0.0
        for key, want in exp.items():
            got = res.get(key)
            tol = ANALYTIC_TOL_DB + mf.interp_bound_db(mf.quantity_freq_hz(run, key), run.tmax_s)
            if got is None or abs(got - want) > tol:
                failures.append(f"analytic {run.run_id}: {key} = {got} vs closed form {want:.4f} "
                                f"(tolerance {tol:.4f} dB)")
            else:
                worst = max(worst, abs(got - want))
        if run.run_id in ("a_single", "a_rfoff", "a_tt"):
            print_result(res, "      ")
            print(f"        closed-form agreement: max |delta| {worst:.2e} dB over {', '.join(exp)}")
    if sweep:
        pts = []
        for p in sweep:
            res = results[f"a_ip{int(-p)}"]
            pts.append(dict(pin_dbm=p, status=res["status"], p_if1_dbm=res.get("p_if1_dbm"),
                            p_if2_dbm=res.get("p_if2_dbm"), p_im3l_dbm=res.get("p_im3l_dbm"),
                            p_im3h_dbm=res.get("p_im3h_dbm"),
                            floor_dbm=(res.get("floor_dbm") or {}).get("im3")))
        rules = {k: v for k, v in study.iip3_rules.items()}
        fit = mf.fit_iip3(pts, slope_fund=tuple(rules["slope_fund"]), slope_im3=tuple(rules["slope_im3"]),
                          min_points=rules["min_points"], floor_margin_db=rules["floor_margin_db"],
                          compression_db=rules["compression_db"], max_residual_db=rules["max_residual_db"])
        want = mf.analytic_iip3_dbm(ctrl.params)
        if fit["status"] != "ok":
            failures.append(f"analytic IIP3 sweep: {fit.get('reason')}")
        else:
            print(f"      analytic IIP3: extracted {fit['iip3_dbm']:.3f} dBm (interval "
                  f"{fit['sidebands']['low']['interval_dbm']}) vs small-signal closed form {want:.3f} dBm")
            # the fitted interval carries a little compression (k3 term on
            # the fundamental), so allow a bounded difference
            if abs(fit["iip3_dbm"] - want) > 0.5:
                failures.append(f"analytic IIP3 {fit['iip3_dbm']:.3f} dBm vs closed form {want:.3f} dBm")
    return failures


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def cmd_plan(args) -> int:
    tb, study = _load()
    cells = mf.expected_cells(study)
    print(f"{tb.name}: {len(study.candidates)} topologies "
          f"({', '.join(f'{c.name} [{c.role}]' for c in study.candidates)}) + analytic control")
    print("bands: " + ", ".join(f"{b.name}: RF {b.rf_hz / 1e9:g} GHz / LO {b.lo_hz / 1e9:g} GHz; "
                                 f"two-tone {b.two_tone_hz[0] / 1e9:g}/{b.two_tone_hz[1] / 1e9:g} GHz, "
                                 f"LO {b.two_tone_lo_hz / 1e9:g} GHz" for b in study.bands))
    print(f"LO sweep (total available, 100 ohm diff): {study.lo_sweep_dbm[0]:g}..{study.lo_sweep_dbm[-1]:g} dBm, "
          f"{len(study.lo_sweep_dbm)} points; RF {study.rf_dbm:g} dBm (check {study.rf_check_dbm:g} dBm)")
    for name, m in study.matrices.items():
        n = sum(1 for c in cells if c["matrix"] == name)
        print(f"matrix {name}: corners {', '.join(m.corners)}; T {', '.join(f'{t:g}' for t in m.temperatures_c)} C; "
              f"V {', '.join(f'{v:g}' for v in m.supplies_v)}; bands {', '.join(m.bands)}"
              + (f"; seed {m.seed}" if m.seed is not None else "") + f" -> {n} cells")
    print(f"total declared cells: {len(cells)}")
    return 0


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------


def cmd_smoke(args) -> int:
    tb, study = _load()
    pdk = _pdk()
    print(f"ngspice: {ngspice_version()}")
    failures = []
    for cand in study.candidates:
        failures += mf.check_fragment_devices((TB_DIR / cand.fragment).read_text(), cand)
    print("[1/2] analytic control through the extraction chain")
    failures += analytic_check(tb, study, pdk, SCRATCH / "smoke", iip3_sweep=False)
    band = study.band(study.smoke["band"])
    drive = float(study.smoke["trial_lo_dbm"])
    point = nominal_point()
    print(f"[2/2] candidates at {point.corner_id}, {band.name}, trial LO {drive:g} dBm (NOT a selected drive)")
    for cand in study.candidates:
        if args.candidate and cand.name != args.candidate:
            continue
        runs = [make_run(study, "rf60", "single", band, drive, study.rf_dbm),
                make_run(study, "rf66", "single", band, drive, study.rf_check_dbm),
                make_run(study, "rfoff", "rfoff", band, drive, None)]
        results, problems, _ = run_deck(tb, study, pdk, cand, point, runs, SCRATCH / "smoke" / cand.name)
        print(f"  {cand.name} [{cand.role}]")
        failures += [f"{cand.name}: {p}" for p in problems]
        for run in runs:
            res = results[run.run_id]
            print_result(res)
            if res["status"] == "invalid":
                failures.append(f"{cand.name}/{run.run_id}: invalid ({res['problems']})")
        print_stress_table(results["rf60"])
        ss = mf.small_signal_check(results["rf60"].get("gain_db"), results["rf66"].get("gain_db"),
                                   study.small_signal_tol_db)
        print(f"    small-signal check: |G(-60) - G(-66)| = {_f(ss['delta_db'] and abs(ss['delta_db']), '{:.4f}')} dB "
              f"-> {'pass' if ss['ok'] else 'FAIL' if ss['ok'] is False else 'n/a'}")
    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        print(f"smoke: FAILED ({len(failures)} problem(s)); nothing recorded", file=sys.stderr)
        return 1
    print("smoke: ok (netlisting, real models, parsing, analytic extraction); nothing recorded")
    return 0


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------


def synthetic_collection(study) -> list[dict]:
    """A complete, internally consistent fake collection for the gate's
    negative controls (no simulation)."""
    cells = []
    corner_offset = {"hbt_typ": 0.0, "hbt_bcs": 0.4, "hbt_wcs": -0.6}
    for c in mf.expected_cells(study):
        cell = dict(c, status="ok", model_section=c["corner"], stress={"rejecting": [], "violations": []},
                    gain_db=5.0 + corner_offset.get(c["corner"], 0.0), rail_power_mw=4.5,
                    dc_rail_power_mw=4.5, lo_vdiff_loaded_peak_v=0.3, lo_rf_dbm=-60.0, lo_if_dbm=-50.0,
                    p_if1_dbm=-30.0, p_if2_dbm=-30.0, p_im3l_dbm=-80.0, p_im3h_dbm=-80.0)
        if c["matrix"] != "leakage":
            cell.pop("seed", None)
        cells.append(cell)
    return cells


def gate_controls(study) -> list[str]:
    failures = []
    good = synthetic_collection(study)
    if mf.validate_collection(study, good):
        failures.append("gate rejects a complete synthetic collection: "
                        f"{mf.validate_collection(study, good)[:3]}")
    cases = {
        "deleted cell": lambda cs: cs[1:],
        "duplicated cell": lambda cs: cs + [dict(cs[0])],
        "NaN measurement": lambda cs: [dict(cs[0], gain_db=float("nan"))] + cs[1:],
        "missing measurement": lambda cs: [{k: v for k, v in cs[0].items() if k != "gain_db"}] + cs[1:],
        "corners forced to typical": lambda cs: [dict(c, gain_db=5.0) for c in cs],
        "wrong model section": lambda cs: [dict(cs[0], model_section="hbt_typ" if cs[0]["corner"] != "hbt_typ"
                                                else "hbt_wcs")] + cs[1:],
        "ok despite stress violation": lambda cs: [dict(cs[0], stress={"rejecting": [{"device": "q1"}]})] + cs[1:],
        "rejected without violation": lambda cs: [dict(cs[0], status="rejected_stress")] + cs[1:],
        "corrupt status": lambda cs: [dict(cs[0], status="error")] + cs[1:],
        "wrong mismatch seed": lambda cs: [dict(c, seed=1) if c["matrix"] == "leakage" else c for c in cs],
    }
    for name, mutate in cases.items():
        problems = mf.validate_collection(study, mutate([dict(c) for c in good]))
        if problems:
            print(f"      gate rejects {name}: {problems[0]}")
        else:
            failures.append(f"gate ACCEPTED a collection with {name}")
    # physical violations stay explicit outcomes and block a recommendation
    per = {}
    for cand in study.candidates:
        main = [c for c in good if c["matrix"] == "main" and c["candidate"] == cand.name]
        per[cand.name] = {"lo_selection": {"status": "selected", "drive_dbm": 0.0}, "main_cells": main}
    base = mf.conclude(study, per)
    first = study.candidates[0].name
    per[first]["main_cells"] = [dict(per[first]["main_cells"][0], status="rejected_stress")] + \
        per[first]["main_cells"][1:]
    stressed = mf.conclude(study, per)
    if stressed["verdicts"][first]["verdict"].startswith("feasible"):
        failures.append("a stress-rejected main cell still produced a feasible verdict")
    else:
        print(f"      stress-rejected cell -> {first}: {stressed['verdicts'][first]['verdict']}; "
              f"recommendation {stressed['recommendation']['draw_first']} (was {base['recommendation']['draw_first']})")
    floor = [c.name for c in study.candidates if c.role == "floor"][0]
    if base["recommendation"]["draw_first"] == floor or stressed["recommendation"]["draw_first"] == floor:
        failures.append("the labelled floor was recommended")
    return failures


def cmd_selftest(args) -> int:
    tb, study = _load()
    pdk = _pdk()
    print(f"ngspice: {ngspice_version()}")
    failures = []
    work = SCRATCH / "selftest"
    band = study.band(study.smoke["band"])
    drive = float(study.smoke["trial_lo_dbm"])
    gilbert = study.candidate("gilbert_stacked")

    print("[1/5] analytic control, incl. a swept two-tone IIP3, against closed forms")
    failures += analytic_check(tb, study, pdk, work, iip3_sweep=True)

    print("[2/5] process corners take effect; sabotaged corners collapse to typical")
    run = [make_run(study, "rf60", "single", band, drive, study.rf_dbm)]
    normal = resolve_corners(["hbt_typ", "hbt_wcs"])
    gains = {}
    for label, corners in (("normal", normal), ("sabotaged", sabotage(normal))):
        for corner in corners:
            point = build_grid([corner], [27.0], [2.25])[0]
            res, problems, _ = run_deck(tb, study, pdk, gilbert, point, run, work / label / corner.name)
            failures += [f"{label} {corner.name}: {p}" for p in problems]
            gains[(label, corner.name)] = res["rf60"].get("gain_db")
    print("      " + ", ".join(f"{k[0]}/{k[1]}: G={_f(v, '{:.4f}')} dB" for k, v in gains.items()))
    try:
        d_norm = abs(gains[("normal", "hbt_wcs")] - gains[("normal", "hbt_typ")])
        d_sab = abs(gains[("sabotaged", "hbt_wcs")] - gains[("sabotaged", "hbt_typ")])
        if not d_norm > 1e-3:
            failures.append(f"hbt_wcs vs hbt_typ gain differs by only {d_norm:.2e} dB: corners not taking effect")
        if not d_sab < 1e-9:
            failures.append(f"sabotaged corners still differ by {d_sab:.2e} dB")
        if abs(gains[("sabotaged", "hbt_typ")] - gains[("normal", "hbt_typ")]) > 1e-9:
            failures.append("sabotaged hbt_typ differs from normal hbt_typ")
    except TypeError:
        failures.append(f"process control incomplete: {gains}")

    print("[3/5] mismatch card: fixed seed reproducible, differs from typical and from another seed")
    rfoff = [make_run(study, "rfoff", "rfoff", band, drive, None)]
    seed = study.matrices["leakage"].seed
    variants = (("typ", "hbt_typ", None), ("mm_a", "hbt_typ_mismatch", seed),
                ("mm_b", "hbt_typ_mismatch", seed), ("mm_c", "hbt_typ_mismatch", seed + 1))
    mm = {}
    for label, corner, s in variants:
        res, problems, raw = run_deck(tb, study, pdk, gilbert, nominal_point(corner), rfoff,
                                      work / "mismatch" / label, seed=s)
        failures += [f"mismatch {label}: {p}" for p in problems]
        r = res["rfoff"]
        ics = tuple(raw.get("rfoff", {}).get(f"mf_dc_ic_{d.name}") for d in gilbert.devices)
        mm[label] = (ics, r.get("lo_if_dbm"), r.get("lo_rf_dbm"), (r.get("floor_dbm") or {}).get("loif"))
        print(f"      {label} ({corner}, seed {s}): LO->IF {_f(r.get('lo_if_dbm'), '{:.1f}')} dBm, "
              f"LO->RF {_f(r.get('lo_rf_dbm'), '{:.1f}')} dBm; DC Ic "
              + "/".join(_f(x and x * 1e3, '{:.4f}') for x in ics) + " mA")
    if None in mm["mm_a"][0] or None in mm["typ"][0]:
        failures.append("mismatch control: DC currents missing")
    else:
        if mm["mm_a"][0] != mm["mm_b"][0]:
            failures.append("same mismatch seed gave different realizations")
        if mm["mm_a"][0] == mm["typ"][0]:
            failures.append("mismatch card gave the typical realization (mismatch not applied)")
        if mm["mm_a"][0] == mm["mm_c"][0]:
            failures.append("different seeds gave identical realizations")

    print("[4/5] deck with a deleted required measurement is rejected")
    run = [make_run(study, "rf60", "single", band, drive, study.rf_dbm)]
    res, problems, _ = run_deck(tb, study, pdk, gilbert, nominal_point(), run, work / "invalid",
                                drop_key="mf_if_re")
    if res["rf60"]["status"] == "invalid":
        print(f"      rejected as expected: {res['rf60']['problems'][0]}")
    else:
        failures.append("a deck missing mf_if_re was NOT rejected")

    print("[5/5] collection gate and conclusion negative controls (no simulation)")
    failures += gate_controls(study)

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        print("selftest: FAILED; nothing recorded", file=sys.stderr)
        return 1
    print("selftest: ok (analytic extraction + IIP3, process sensitivity, sabotage collapse, mismatch seed, "
          "invalid-deck rejection, gate controls); nothing recorded")
    return 0


# ---------------------------------------------------------------------------
# converge
# ---------------------------------------------------------------------------


def converge_candidate(tb, study, pdk, cand, drive: float, *, quiet: bool = False) -> dict:
    """Window / timestep convergence control for one candidate at one LO
    drive (local, nominal band centre): gain on hbt_typ at the nominal
    corner, leakage (RF off) on the leakage matrix's first mismatch card with
    its declared seed; doubled retained window and halved maximum timestep
    against the baseline. Returns {"checks", "failures", "results"}."""
    band = study.band(study.smoke["band"])
    point = nominal_point()
    leak = study.matrices["leakage"]
    leak_point = nominal_point(leak.corners[0])
    say = (lambda *a, **k: None) if quiet else print
    variants = {"base": (1.0, 1.0), "window2x": (2.0, 1.0), "step0.5x": (1.0, 0.5)}
    on_runs, off_runs = [], []
    for v, (ws, ss) in variants.items():
        on_runs.append(make_run(study, f"{v}_on", "single", band, drive, study.rf_dbm, window_scale=ws,
                                step_scale=ss))
        off_runs.append(make_run(study, f"{v}_off", "rfoff", band, drive, None, window_scale=ws,
                                 step_scale=ss))
    results, problems, _ = run_deck(tb, study, pdk, cand, point, on_runs,
                                    SCRATCH / "converge" / cand.name / "gain")
    res_off, problems_off, _ = run_deck(tb, study, pdk, cand, leak_point, off_runs,
                                        SCRATCH / "converge" / cand.name / "leakage", seed=leak.seed)
    results.update(res_off)
    problems += problems_off
    say(f"  {cand.name} [{cand.role}]")
    failures = [f"{cand.name}: {p}" for p in problems]
    checks_out = []
    bad = [r for r in results.values() if r["status"] == "invalid"]
    if bad:
        failures += [f"{cand.name}/{r['run_id']}: invalid {r['problems']}" for r in bad]
        return {"checks": checks_out, "failures": failures, "results": results}
    for v in ("window2x", "step0.5x"):
        checks = []
        on_b, on_v = results["base_on"], results[f"{v}_on"]
        off_b, off_v = results["base_off"], results[f"{v}_off"]
        floor = max(on_b["floor_dbm"]["if"], on_v["floor_dbm"]["if"])
        checks.append(mf.compare_converged("gain_db", on_b["gain_db"], on_v["gain_db"],
                                           floor - study.rf_dbm, tol_db=study.convergence_tol_db,
                                           floor_margin_db=study.floor_margin_db))
        for key, fkey in (("lo_if_dbm", "loif"), ("lo_rf_dbm", "lorf")):
            fl = max(off_b["floor_dbm"][fkey], off_v["floor_dbm"][fkey])
            checks.append(mf.compare_converged(f"{key} (RF off)", off_b[key], off_v[key], fl,
                                               tol_db=study.convergence_tol_db,
                                               floor_margin_db=study.floor_margin_db))
        for c in checks:
            d = "n/a" if c.get("delta_db") is None else f"{c['delta_db']:+.4f} dB"
            say(f"    {v:9s} {c['quantity']:18s} delta {d:14s} {'ok' if c['ok'] else 'FAIL'} {c['reason']}")
            checks_out.append(dict(c, variant=v))
            if not c["ok"]:
                failures.append(f"{cand.name} {v} {c['quantity']}: {c['reason']}")
    if not quiet:
        print_result(results["base_on"])
        print_result(results["base_off"])
    return {"checks": checks_out, "failures": failures, "results": results}


def cmd_converge(args) -> int:
    tb, study = _load()
    pdk = _pdk()
    band = study.band(study.smoke["band"])
    drive = float(study.smoke["trial_lo_dbm"]) if args.drive is None else args.drive
    point = nominal_point()
    leak = study.matrices["leakage"]
    leak_point = nominal_point(leak.corners[0])
    print(f"ngspice: {ngspice_version()}")
    print(f"convergence control, {band.name}, LO {drive:g} dBm: gain at {point.corner_id}; leakage (RF off) at "
          f"{leak_point.corner_id} (seed {leak.seed}; the leakage matrix's card) "
          f"(baseline: settle {study.timing.settle_s:g} s, window {study.timing.window_single_s:g} s, "
          f"tmax {study.timing.tmax_s:g} s)")
    failures = []
    for cand in study.candidates:
        if args.candidate and cand.name != args.candidate:
            continue
        failures += converge_candidate(tb, study, pdk, cand, drive)["failures"]
    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        print("converge: FAILED; nothing recorded", file=sys.stderr)
        return 1
    print("converge: ok; nothing recorded")
    return 0


def cmd_collect(args) -> int:
    import collect
    return collect.collect(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("plan").set_defaults(func=cmd_plan)
    ps = sub.add_parser("smoke")
    ps.add_argument("--candidate", default="")
    ps.set_defaults(func=cmd_smoke)
    sub.add_parser("selftest").set_defaults(func=cmd_selftest)
    pc = sub.add_parser("converge")
    pc.add_argument("--candidate", default="")
    pc.add_argument("--drive", type=float, default=None, help="LO available power, dBm (default: smoke trial)")
    pc.set_defaults(func=cmd_converge)
    pk = sub.add_parser("collect", help="submit the full study as klt sim requests and, if the acceptance "
                                         "gate passes, write the append-only record")
    pk.add_argument("--klt-cmd", default="klt", help="klt client command (e.g. 'uvx --from klayout-tools==X klt')")
    pk.add_argument("--backend", default="batch", help="klt sim backend (default batch; the host exports "
                    "KLT_SIM_BACKEND=batch). A failed submit is an error, never a local fallback.")
    pk.add_argument("--timeout-s", type=int, default=3600, help="klt per-corner timeout")
    pk.add_argument("--no-stage-models", action="store_true")
    pk.add_argument("--runner-version-check", default="", choices=("", "enforce", "warn"))
    pk.add_argument("--workdir", default="", help="reuse/resume a working directory (existing reports are reused)")
    pk.add_argument("--claim", default="")
    pk.add_argument("--supersedes", default="")
    pk.add_argument("--dry-run", action="store_true", help="write first-stage requests, submit nothing")
    pk.add_argument("--stage1-only", action="store_true",
                    help="submit only the LO-selection sweep and print the selection (diagnostic, no record)")
    pk.set_defaults(func=cmd_collect)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except NgspiceMissing as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
