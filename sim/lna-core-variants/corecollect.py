"""Collection and append-only record writer for lna-core-variants (#79).

The PVT campaign is one ``klt sim`` request per (variant, supply), each with
the 9 process x temperature units, on ``--backend`` (default ``batch``, the
Spot fleet). A failed submit stops the collection: nothing is recorded and
nothing falls back to a local grid. Two single-point local controls follow
(the #74 normalization pad at 27 C, and the frozen core at the nominal point
run locally vs the fleet's unit), then the acceptance gate, then one record:
``records/<id>.md``, ``<id>.json``, ``<id>-points.json.gz``,
``corners/<id>/*.log.gz`` and ``netlist-snapshots/<id>/``.
"""

from __future__ import annotations

import datetime as _dt
import gzip
import json
import math
import shutil
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
SIM_DIR = BENCH_DIR.parent
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(BENCH_DIR))
sys.path.insert(0, str(SIM_DIR / "lna-match-tradeoff"))

import corestudy as cs  # noqa: E402
import matchcollect as mc  # noqa: E402
import matchstudy as ms  # noqa: E402
from harness import klt_driver  # noqa: E402
from harness.report import RecordExists, allocate_record_id, git_provenance  # noqa: E402

SCRATCH = BENCH_DIR / "_build"
RECORDS = BENCH_DIR / "records"
CORNER_LOGS = BENCH_DIR / "corners"
SNAPSHOTS = BENCH_DIR / "netlist-snapshots"
BASELINE_RECORD_JSON = SIM_DIR / "lna-match-tradeoff" / "records" / "20261010-042556-dae8519.json"
SCOPE = ("ideal-element core-variant feasibility screen; no spec row is claimed met (rows 2, 3, 4, 6 and 17 are "
         "screens, not compliance)")


class CollectionError(mc.CollectionError):
    pass


def check_inputs(dec: cs.Declaration) -> None:
    """The method declaration and the frozen DUT must be the ones declared."""
    got = klt_driver.sha256_file(cs.METHOD_STUDY)
    if got != dec.raw["method"]["study_json_sha256"]:
        raise CollectionError(f"#74 study.json sha256 {got} != declared {dec.raw['method']['study_json_sha256']}")
    got = klt_driver.sha256_file(cs.FROZEN)
    if got != dec.raw["frozen_dut"]["sha256"]:
        raise CollectionError(f"frozen DUT sha256 {got} != declared {dec.raw['frozen_dut']['sha256']} "
                              "(the design moved: re-declare the study)")


def request_specs(st: ms.Study, dec: cs.Declaration) -> list[mc.RequestSpec]:
    nets = [c.name for c in cs.networks(st)]
    return [mc.RequestSpec(key=f"{v.name}__{vdd:.3f}v", phase=v.name, vdd=vdd, processes=list(st.processes),
                           temps=list(st.temps_c), networks=nets) for v in dec.variants for vdd in st.supplies_v]


def write_request(st: ms.Study, dec: cs.Declaration, spec: mc.RequestSpec, work: Path, args) -> Path:
    v = dec.variant(spec.phase)
    net = cs.variant_netlist(cs.FROZEN.read_text(), dec, v)
    (work / f"netlist_{v.name}.spice").write_text(net)
    body = work / f"body_{spec.key}.spice"
    body.write_text(ms.body_text(st, net, cs.networks(st), spec.vdd, title=f"core variant {spec.key} (klt sim body)",
                                 devices=cs.devices_of(net)))
    req = work / f"request_{spec.key}.json"
    req.write_text(json.dumps(mc.klt_request(body.name, spec, args.backend, args), indent=2) + "\n")
    (work / f"spec_{spec.key}.json").write_text(json.dumps(spec.as_dict(), indent=2) + "\n")
    return req


def unit_points(st: ms.Study, dec: cs.Declaration, spec: mc.RequestSpec, unit: dict) -> tuple[dict | None, list[str]]:
    v = dec.variant(spec.phase)
    devs = cs.devices_of(cs.variant_netlist(cs.FROZEN.read_text(), dec, v))
    pl = ms.parse_log(unit["text"])
    cid = ms.corner_id(unit["process"], unit["temp_c"], spec.vdd)
    problems = [f"{spec.key}/{cid}: {p}" for p in pl.problems]
    if not pl.done:
        problems.append(f"{spec.key}/{cid}: deck did not reach LM_DONE")
    for c in cs.networks(st):
        want = set(ms.sections_for(c))
        got = set(pl.tables.get(c.name, {}))
        if want != got:
            problems.append(f"{spec.key}/{cid}/{c.name}: printed blocks missing {sorted(want - got)} / "
                            f"unexpected {sorted(got - want)}")
    extra = sorted(set(pl.tables) - {c.name for c in cs.networks(st)})
    if extra:
        problems.append(f"{spec.key}/{cid}: unexpected networks {extra[:5]}")
    if problems:
        return None, problems
    pt = cs.analyze_point(st, v, devs, unit["process"], unit["temp_c"], spec.vdd, pl.tables, pl.op)
    pt["request"] = spec.key
    return pt, []


def run_collection(st: ms.Study, dec: cs.Declaration, work: Path, args) -> dict:
    points: list[dict] = []
    requests: list[dict] = []
    texts: dict = {}
    problems: list[str] = []
    for spec in request_specs(st, dec):
        req = write_request(st, dec, spec, work, args)
        if args.dry_run:
            continue
        report = mc.submit(spec, req, work, args)
        meta, units = mc.read_units(report)
        requests.append(mc.execution(meta, spec, args.backend))
        for u in units:
            pt, pr = unit_points(st, dec, spec, u)
            problems += pr
            if pt is not None:
                points.append(pt)
            texts[f"{spec.key}__{u['process']}_{u['temp_c']:g}c"] = u["text"]
    if problems:
        raise CollectionError("campaign corrupt: " + "; ".join(problems[:10]))
    return {"points": points, "requests": requests, "texts": texts, "work": work}


def local_controls(st: ms.Study, dec: cs.Declaration, points: list[dict]) -> dict:
    """Single-point local controls: the #74 normalization pad at 27 C, and the
    frozen core at the nominal point (local ngspice) vs the fleet's unit."""
    import localrun  # noqa: PLC0415 - one local ngspice at one PVT point per call
    out = {"pad_27c": localrun.pad_control(st, 27.0)}
    n = st.nominal
    p, t, v = n["process"], float(n["temp_c"]), float(n["vdd"])
    base = dec.baseline
    net = cs.variant_netlist(cs.FROZEN.read_text(), dec, base)
    devs = cs.devices_of(net)
    text = localrun.run_point(ms.body_text(st, net, cs.networks(st), v, title="local cross-check", devices=devs),
                              p, t, "crosscheck_core0")
    pl = ms.parse_log(text)
    loc = cs.analyze_point(st, base, devs, p, t, v, pl.tables, pl.op)
    fleet = next((x for x in points if x["id"] == cs.point_id(base.name, p, t, v)), None)
    worst = float("inf")
    if fleet and fleet["status"] == "ok" and loc["status"] == "ok":
        worst = max(abs(a - b) for k in ("nf_bound_db", "fmin_db", "gt_at_nf_bound_db")
                    for a, b in zip(loc["bound"][k], fleet["bound"][k]))
    tol = float(st.tolerances["crosscheck_db"])
    out["local_vs_fleet_core0_nominal"] = {"ok": worst <= tol, "worst_db": worst, "tol_db": tol,
                                           "ngspice": localrun.version()}
    return out


def assemble(st: ms.Study, dec: cs.Declaration, points: list[dict], controls: dict) -> dict:
    base_bounds = json.loads(BASELINE_RECORD_JSON.read_text())["bounds"]
    rep = cs.reproduction(points, base_bounds, dec.baseline.name, float(dec.raw["reproduction_tol_db"]))
    gate = cs.validate_collection(st, dec, points)
    gate += [f"control {k} failed" for k, c in controls.items() if not c.get("ok")]
    gate += [f"reproduction: {x}" for x in rep["problems"]]
    if rep["compared_points"] != len(st.pvt_points()):
        gate.append(f"reproduction compared {rep['compared_points']} points, expected {len(st.pvt_points())}")
    summaries = {v.name: cs.summarize_variant(st, dec, v, points) for v in dec.variants}
    sel = cs.select(dec, summaries)
    return {"rep": rep, "gate": gate, "summaries": summaries, "selection": sel}


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------


def _f(x, fmt="{:.2f}") -> str:
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else fmt.format(x)


def _rng(r) -> str:
    return f"{r[0]:.2f}-{r[1]:.2f}" if r else "n/a"


def render_md(*, rid: str, st: ms.Study, dec: cs.Declaration, col: dict, a: dict, controls: dict, started: str,
              git: dict, ngspice: str, klt_version: str, decl_sha: str) -> str:
    L: list[str] = []
    w = L.append
    sel = a["selection"]
    S = a["summaries"]
    w(f"# lna-core-variants record {rid}")
    w("")
    w(f"**Started (UTC)**: {started}")
    w("**Experiment**: lna-core-variants (issue #79)")
    w("**Spec rows claimed met**: none")
    w(f"**Claim**: {dec.raw['claim']}")
    w(f"**Declaration**: `testbench/variants.json` sha256 `{decl_sha}` (frozen copy in "
      f"`netlist-snapshots/{rid}/variants.json`; rationale in `STUDY.md`)")
    w(f"**Method**: `{dec.raw['method']['study_json']}` sha256 `{dec.raw['method']['study_json_sha256']}` (the #74 "
      "declaration: grids, thresholds, probes, fixture, NF convention), executed by "
      "`sim/lna-match-tradeoff/matchstudy.py`; baseline record "
      f"`{dec.raw['method']['baseline_record']}.md`")
    w(f"**Frozen DUT**: `design/netlist/lna_stage1.spice` sha256 `{dec.raw['frozen_dut']['sha256']}`; each variant "
      "is this netlist with only its declared edits (`netlist-snapshots/<id>/netlist_<variant>.spice`)")
    w(f"**Outcome**: {sel['outcome']}")
    w("")
    w("## Method")
    w("")
    w("- Per variant and PVT point, one deck runs the #74 drawn (baseline) input network and the 9 #74 probe networks. "
      "Analyses, each printed between markers: `op` (operating point, row 17 checks); per network `ac lin 71` "
      "17.7-21.2 GHz forward and reverse (S-parameters from port voltages: S11 = 2 V1 - 1, S21 = 2 V2) and `noise "
      "v(p2) vs1 lin 71` (F = 1 + inoise^2 / (4 k T0 50), T0 = 300.15 K, noiseless reference source, noisy 50 ohm "
      "load at the circuit temperature: the #74 / lna-sparam-nf bench convention); for the drawn network also the "
      "70 midpoints and `ac dec 100` 1-100 GHz forward and reverse.")
    w("- Network-independent bound (#74, unchanged): Fmin, Rn, Yopt fitted at each of the 71 dense frequencies from the "
      "probe NFs; core S-parameters at node in2 from `probe_thru`; for ANY lossless input network the port NF and "
      "|S11| depend only on the source reflection presented to the core, so the smallest NF with |S11| <= -10 dB is "
      "a minimum over a mismatch circle. Model check: the drawn network's simulated NF and S11 must equal the "
      f"prediction within {st.tolerances['model_db']} dB, and the fit rms must too, or the point is rejected.")
    w("- GT at the bound: transducer gain into the 50 ohm load with the source reflection that attains the NF bound "
      "(`ac lin 71` S21/S11 of the core). Stability: k and |Delta| of the drawn network over the dense band and "
      "1-100 GHz (k is invariant under a lossless input network, so it stands for every network).")
    w("- Variant values were derived before the campaign by one local single-point scan each "
      "(`run.py derive`, declared rules in `variants.json` `derivations`).")
    w("")
    w("## Intentional reductions")
    w("")
    w("- Ideal elements: every matching element and the degeneration inductor Le1 are ideal (no PDK inductor model; "
      "#46). Real loss adds to NF dB for dB; every number here is optimistic.")
    w("- The bound is a per-frequency necessary condition. Closing it does not imply a realizable input network: the "
      "network must still track the feasible region across the band (Foster), and none is sized here.")
    w("- One stage into 50 ohm; row 2 assumes two stages; the output network (Lfeed, Rd, Cm) stays as drawn, so a "
      "variant that moves the output capacitance (b_nx10) is also detuned at the output.")
    w("- The band (row 1) is OPEN; 17.7-21.2 GHz is DRAFT. No wideband claim is made.")
    w("")
    w("## Variant declarations")
    w("")
    w("| variant | role | change(s) | derived values |")
    w("|---|---|---|---|")
    for v in dec.variants:
        pv = cs.variant_params(dec, v)
        w(f"| {v.name} | {v.role} | {v.summary}; " + ("; ".join(
            f"{c}: {dec.changes[c]['title']}" for c in v.changes) or "none") + " | " +
          (", ".join(f"{k} = {x:.4g}" for k, x in pv.items()) or "-") + " |")
    w("")
    w("## Controls")
    w("")
    for name, c in controls.items():
        w(f"- {name}: {'ok' if c.get('ok') else 'FAILED'} -- " + ", ".join(
            f"{k} {_f(x, '{:.3g}')}" if isinstance(x, float) else f"{k} {x}"
            for k, x in c.items() if k not in ("ok", "problems")))
    rep = a["rep"]
    w(f"- Reproduction of `{dec.raw['method']['baseline_record']}` by core0 ({rep['compared_points']} PVT points; "
      f"NF-bound max and Fmin range): worst {_f(rep['worst_db'], '{:.2e}')} dB (tolerance {rep['tol_db']} dB), "
      f"jointly-infeasible counts {'equal' if not [x for x in rep['problems'] if 'infeasible' in x] else 'DIFFER'} -> "
      f"{'ok' if rep['ok'] else 'FAILED: ' + '; '.join(rep['problems'][:5])}")
    w(f"- Acceptance gate (`validate_collection`): {'passed' if not a['gate'] else 'FAILED'}")
    w("")
    w("## Per-variant comparison (18 in-rail points)")
    w("")
    w("Baselines quoted by issue #79 from `sim/lna-match-tradeoff/records/20261010-042556-dae8519.md`: 8 of 18 "
      "in-rail points jointly infeasible; core Fmin 2.43-2.73 dB at hbt_wcs / 125 C (2.25 V); nominal margin "
      "0.03 dB at 21.2 GHz. core0 below is the reproduction of those numbers.")
    w("")
    w("| variant | infeasible in-rail points | worst NF bound (dB) at | worst margin (dB) | Fmin hbt_wcs/125 C 2.25 V | "
      "Fmin hbt_wcs/125 C 2.50 V | NF bound hbt_wcs/125 C 2.25 / 2.50 V | nominal margin @21.2 GHz (dB) | "
      "min GT at bound (dB) | k min | |Delta| max | V_CE max (V) | row 17 in rail | eligible |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for v in dec.variants:
        s = S[v.name]
        if "worst_nf_bound_db" not in s:
            w(f"| {v.name} | {s.get('verdict')} |" + " |" * 13)
            continue
        bf, bb = s["binding_fmin_db"], s["binding_nf_bound_db"]
        w(f"| {v.name} | {s['n_infeasible']}/{s['in_rail_points']} | {s['worst_nf_bound_db']:.3f} at "
          f"{s['worst_point']} | {s['worst_margin_db']:+.3f} | {_rng(bf.get('2.25v'))} | {_rng(bf.get('2.50v'))} | "
          f"{_f(bb.get('2.25v'), '{:.3f}')} / {_f(bb.get('2.50v'), '{:.3f}')} | "
          f"{_f(s['nominal_margin_top_db'], '{:+.3f}')} | {s['gt_at_nf_bound_min_db']:.2f} | {s['k_min']:.2f} | "
          f"{s['delta_max']:.3f} | {s['vce_max_v']:.3f} | "
          f"{'pass' if not s['op_fail_in_rail'] else 'FAIL ' + ', '.join(s['op_fail_in_rail'])} | "
          f"{'yes' if s['eligible'] else 'no: ' + '; '.join(s['ineligible_reasons'])} |")
    w("")
    w("Analyses behind each column: NF bound and Fmin from the probe fit on the `ac lin 71` + `noise lin 71` grid "
      "(bench-convention NF); margin = 2.5 dB - NF bound; GT from the core's `ac lin 71` S-parameters at the "
      "bound's source reflection; k and |Delta| from the drawn network's `ac lin 71` and `ac dec 100` 1-100 GHz "
      "sweeps; V_CE and row 17 from `op`.")
    w("")
    w("## Selection (declared rule)")
    w("")
    w(f"**{sel['outcome']}.**")
    w("")
    if sel["ranking"]:
        w("Eligible, in rule order: " + ", ".join(f"`{n}`" for n in sel["ranking"]))
        w("")
    for v in dec.variants:
        s = S[v.name]
        w(f"- `{v.name}` ({v.role}): {s.get('verdict')}" + (
            f"; infeasible at {', '.join(s['infeasible_points'])}" if s.get("infeasible_points") else ""))
    w("")
    w("## Per-point bound")
    w("")
    w("Every variant at every PVT point. 2.75 V is a labelled EXCURSION above the row-17 rail ceiling and never "
      "enters the choice. `infeasible` counts the dense band points (of 71) where the NF bound exceeds 2.5 dB.")
    w("")
    w("| variant | point | class | status | NF bound max (dB) | at (GHz) | Fmin range (dB) | infeasible | "
      "margin @21.2 GHz (dB) | min GT at bound (dB) | Re/Im Z_in core @f0 (ohm) | k min | Ic(Q1) (mA) | V_CE max (V) | "
      "op | model check (dB) |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for p in sorted(col["points"], key=lambda p: ([v.name for v in dec.variants].index(p["variant"]), p["corner_id"])):
        cls = "EXCURSION" if p["supply_class"] == "excursion" else "in rail"
        if p["status"] != "ok":
            w(f"| {p['variant']} | {p['corner_id']} | {cls} | {p['status']}: {p.get('reason', '')} |" + " |" * 12)
            continue
        s = p["summary"]
        op = p["op"]
        w(f"| {p['variant']} | {p['corner_id']} | {cls} | ok | {s['nf_bound_max_db']:.3f} | "
          f"{s['f_at_nf_bound_max_hz'] / 1e9:.2f} | {s['fmin_min_db']:.2f}-{s['fmin_max_db']:.2f} | "
          f"{s['n_freq_jointly_infeasible']}/{s['n_freq']} | {s['margin_top_db']:+.3f} | "
          f"{s['gt_at_nf_bound_min_db']:.2f} | {s['zin_core_f0_ohm'][0]:.1f} / {s['zin_core_f0_ohm'][1]:.1f} | "
          f"{s['k_min']:.2f} | {s['q1_ic_ma']:.3f} | {s['vce_max_v']:.3f} | "
          f"{'pass' if op.get('pass') else 'FAIL ' + ', '.join(op.get('failures', []))} | "
          f"{s['model_check_worst_db']:.1e} |")
    w("")
    w("## Conclusion")
    w("")
    w(f"**{sel['outcome']}.**")
    w("")
    w("This is a necessary condition on ideal elements. It claims no spec row. It stays contingent on: passive loss "
      "(#46), including the degeneration inductor; a realizable input network that tracks the feasible region across "
      "the band; second-stage loading and the interstage convention; and the open band decision (row 1).")
    w("")
    w("## Provenance and raw artifacts")
    w("")
    w(f"- git {git.get('commit')} (branch {git.get('branch')}, dirty={git.get('dirty')})")
    w(f"- klt client: `{klt_version}`; ingesting host ngspice: {ngspice}")
    for r in col["requests"]:
        rem = r.get("remote") or {}
        w(f"- request `{r['key']}`: backend {r['backend']}, {r['units']} unit(s), status {r['status']}, engine "
          f"{r['engine']} {r['engine_version']}, models_lib_sha256 {r['models_lib_sha256']}"
          + (f", remote job {rem.get('job_id')} ({rem.get('provider')}, {rem.get('instance_type')}, runner klt "
             f"{rem.get('runner_klt_version')}, compatibility {rem.get('runner_compatibility')})" if rem else
             ", ran on this host"))
    w(f"- raw logs: `corners/{rid}/*.log.gz`; variant netlists, bodies, requests, reports and the frozen "
      f"declarations/DUT: `netlist-snapshots/{rid}/`; per-point per-frequency data: `records/{rid}-points.json.gz`; "
      f"summary JSON: `records/{rid}.json`.")
    w("")
    return "\n".join(L)


def write_record(st: ms.Study, dec: cs.Declaration, col: dict, a: dict, controls: dict, *, pdk_prov: dict,
                 ngspice: str, klt_version: str, started: _dt.datetime, git: dict) -> str:
    if a["gate"]:
        raise CollectionError("acceptance gate failed; no record: " + "; ".join(a["gate"][:10]))
    RECORDS.mkdir(parents=True, exist_ok=True)
    rid = allocate_record_id(REPO_ROOT, RECORDS, started, git)
    for d in (CORNER_LOGS / rid, SNAPSHOTS / rid):
        if d.exists():
            raise RecordExists(f"{d} exists; append-only evidence is never rewritten")
    decl_sha = klt_driver.sha256_file(cs.DECLARATION)
    (CORNER_LOGS / rid).mkdir(parents=True)
    for stem, text in sorted(col["texts"].items()):
        with gzip.open(CORNER_LOGS / rid / f"{stem}.log.gz", "wt", compresslevel=9) as fh:
            fh.write(text)
    snap = SNAPSHOTS / rid
    snap.mkdir(parents=True)
    shutil.copyfile(cs.DECLARATION, snap / "variants.json")
    shutil.copyfile(cs.METHOD_STUDY, snap / "study.json")
    shutil.copyfile(cs.FROZEN, snap / "lna_stage1.spice")
    for p in sorted(col["work"].iterdir()):
        if p.is_file() and p.name.split("_", 1)[0] in ("body", "request", "report", "spec", "netlist") \
                and not p.name.endswith(".failed.json"):
            shutil.copyfile(p, snap / p.name)
    points_name = f"{rid}-points.json.gz"
    with gzip.open(RECORDS / points_name, "wt", compresslevel=9) as fh:
        json.dump(mc._r(col["points"]), fh, separators=(",", ":"))
    data = {
        "record_id": rid, "experiment": "lna-core-variants", "issue": 79, "scope": SCOPE,
        "claim": dec.raw["claim"], "spec_rows_claimed_met": [],
        "declaration": {"path": "sim/lna-core-variants/testbench/variants.json", "sha256": decl_sha},
        "method": dec.raw["method"],
        "gate": {"validate_collection": "passed", "problems": []},
        "declared_points": len(cs.expected_points(st, dec)), "accepted_points": len(col["points"]),
        "points_file": points_name,
        "variants": {v.name: {"role": v.role, "changes": list(v.changes), "params": cs.variant_params(dec, v)}
                     for v in dec.variants},
        "summaries": mc._r(a["summaries"]), "selection": a["selection"], "reproduction": mc._r(a["rep"]),
        "controls": mc._r(controls),
        "provenance": {"git": git, "ngspice": ngspice, "klt": klt_version, "pdk": pdk_prov,
                       "klt_requests": col["requests"],
                       "frozen_inputs": {"design_netlist_sha256": klt_driver.sha256_file(cs.FROZEN),
                                         "method_study_sha256": klt_driver.sha256_file(cs.METHOD_STUDY),
                                         "variants_json_sha256": decl_sha}},
    }
    (RECORDS / f"{rid}.json").write_text(json.dumps(data, indent=1, allow_nan=False) + "\n")
    (RECORDS / f"{rid}.md").write_text(render_md(rid=rid, st=st, dec=dec, col=col, a=a, controls=controls,
                                                 started=started.isoformat(), git=git, ngspice=ngspice,
                                                 klt_version=klt_version, decl_sha=decl_sha))
    return rid


def collect(args) -> int:
    st = ms.load_study(cs.METHOD_STUDY)
    dec = cs.load_declaration()
    started = _dt.datetime.now(_dt.timezone.utc)
    work = Path(args.workdir).resolve() if args.workdir else (SCRATCH / f"collect-{started:%Y%m%d-%H%M%S}").resolve()
    work.mkdir(parents=True, exist_ok=True)
    print(f"workdir {work}")
    git = git_provenance(REPO_ROOT)
    try:
        check_inputs(dec)
        col = run_collection(st, dec, work, args)
        if args.dry_run:
            print(f"--dry-run: {len(request_specs(st, dec))} requests written under {work}")
            return 0
        controls = local_controls(st, dec, col["points"])
        a = assemble(st, dec, col["points"], controls)
        import localrun  # noqa: PLC0415
        pdk = klt_driver.find_pdk_or_exit(SIM_DIR)
        rid = write_record(st, dec, col, a, controls, pdk_prov=klt_driver.pdk_provenance(pdk, mc.MODEL_FILES),
                           ngspice=localrun.version(), klt_version=mc.klt_version_text(args.klt_cmd),
                           started=started, git=git)
    except mc.CollectionError as exc:
        print(f"collect: {exc}\nNo record written; work directory kept: {work}", file=sys.stderr)
        return 1
    print(f"wrote records/{rid}.md")
    print(a["selection"]["outcome"])
    return 0
