"""Collection and append-only record writer for lna-match-tradeoff (#74).

Two phases, both expressed as ``klt sim`` requests:

1. **screen**: one single-unit request at the nominal point (hbt_typ,
   27 C, 2.5 V) with every declared network (baseline, family, probes) in
   one deck. A single unit runs locally (``--screen-backend``, default
   ``local``), as klt itself would keep it and as the host rules allow.
2. **corners**: the declared shortlist (from the screen, by the rule in
   ``study.json``) plus the probes, one request per supply with every
   process x temperature unit, on ``--backend`` (default ``batch``). A failed
   batch submit is an error: the collection stops, nothing is recorded and
   nothing falls back to a local grid.

Then: baseline reproduction against sim/lna-sparam-nf record
20261010-012923-6cad7fc at every shared point, a fleet-vs-screen
cross-check of the nominal unit, the local normalization controls, the
acceptance gate (``matchstudy.validate_collection``), and only then one
append-only record: ``records/<id>.md``, ``<id>.json``,
``<id>-cells.json.gz``, ``corners/<id>/*.log.gz`` and
``netlist-snapshots/<id>/`` (frozen DUT, declaration, bodies, requests,
reports).
"""

from __future__ import annotations

import datetime as _dt
import gzip
import hashlib
import json
import math
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
SIM_DIR = BENCH_DIR.parent
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(BENCH_DIR))
sys.path.insert(0, str(SIM_DIR / "lna-sparam-nf"))

import matchstudy as ms  # noqa: E402
from harness import klt_driver  # noqa: E402
from harness.report import RecordExists, allocate_record_id, git_provenance  # noqa: E402

TB_DIR = BENCH_DIR / "testbench"
SCRATCH = BENCH_DIR / "_build"
RECORDS = BENCH_DIR / "records"
CORNER_LOGS = BENCH_DIR / "corners"
SNAPSHOTS = BENCH_DIR / "netlist-snapshots"
FROZEN = REPO_ROOT / "design" / "netlist" / "lna_stage1.spice"
BASELINE_RECORD = "20261010-012923-6cad7fc"
BASELINE_LOGS = SIM_DIR / "lna-sparam-nf" / "corners" / BASELINE_RECORD
MODEL_FILES = ("cornerHBT.lib", "sg13g2_hbt_mod.lib")
SCOPE = ("ideal-element input-match feasibility screen; no spec row is claimed met (rows 2, 3, 4, 6 and 17 "
         "are screens, not compliance)")


class CollectionError(RuntimeError):
    """Corrupt or incomplete collection: exit non-zero, write nothing."""


@dataclass
class RequestSpec:
    key: str
    phase: str
    vdd: float
    processes: list[str]
    temps: list[float]
    networks: list[str]

    def as_dict(self) -> dict:
        return dict(self.__dict__)

    @property
    def units(self) -> int:
        return len(self.processes) * len(self.temps)


def screen_spec(st: ms.Study) -> RequestSpec:
    n = st.nominal
    return RequestSpec(key=f"screen__{float(n['vdd']):.3f}v", phase="screen", vdd=float(n["vdd"]),
                       processes=[n["process"]], temps=[float(n["temp_c"])],
                       networks=[c.name for c in st.candidates])


def corner_specs(st: ms.Study, shortlist_names: list[str]) -> list[RequestSpec]:
    nets = ms.corner_deck_names(st, shortlist_names)
    return [RequestSpec(key=f"corners__{v:.3f}v", phase="corners", vdd=v, processes=list(st.processes),
                        temps=list(st.temps_c), networks=nets) for v in st.supplies_v]


def backend_for(spec: RequestSpec, args) -> str:
    return args.screen_backend if spec.phase == "screen" else args.backend


def klt_request(body_name: str, spec: RequestSpec, backend: str, args) -> dict:
    return klt_driver.klt_request(body_name, spec.processes, spec.temps, backend, args.timeout_s,
                                  sentinel_name="lm_rail_v", sentinel_node="v(vdd)",
                                  stage_models=not args.no_stage_models,
                                  runner_version_check=args.runner_version_check)


def write_request(st: ms.Study, spec: RequestSpec, work: Path, args) -> tuple[Path, Path]:
    cands = [st.candidate(n) for n in spec.networks]
    body = work / f"body_{spec.key}.spice"
    body.write_text(ms.body_text(st, FROZEN.read_text(), cands, spec.vdd, title=f"{spec.key} (klt sim body)"))
    req = work / f"request_{spec.key}.json"
    req.write_text(json.dumps(klt_request(body.name, spec, backend_for(spec, args), args), indent=2) + "\n")
    (work / f"spec_{spec.key}.json").write_text(json.dumps(spec.as_dict(), indent=2) + "\n")
    return req, body


def submit(spec: RequestSpec, req: Path, work: Path, args) -> Path:
    """Run one klt request; reuse an existing complete report (resume).
    Raises CollectionError on any klt failure (never a local fallback)."""
    report = work / f"report_{spec.key}.json"
    if report.is_file():
        try:
            if "corners" in json.loads(report.read_text()):
                print(f"  reuse {report.name}", flush=True)
                return report
        except ValueError:
            pass
    backend = backend_for(spec, args)
    out = (work / f"out_{spec.key}").resolve()
    cmd = shlex.split(args.klt_cmd) + ["sim", str(req), "--backend", backend, "-o", str(out), "--format", "json"]
    print("$ " + " ".join(cmd), flush=True)
    with report.open("w") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, text=True)
    if proc.stderr:
        (work / f"stderr_{spec.key}.log").write_text(proc.stderr)
    if proc.returncode != 0:
        report.rename(work / f"report_{spec.key}.failed.json")
        raise CollectionError(f"klt sim failed for {spec.key} (exit {proc.returncode}, backend {backend}): "
                              f"{proc.stderr[-3000:]}")
    return report


def read_units(report: Path) -> tuple[dict, list[dict]]:
    data = json.loads(report.read_text())
    if "corners" not in data:
        raise CollectionError(f"{report.name}: no corners in klt report ({data.get('error')})")
    units = []
    for corner in data["corners"]:
        log = (corner.get("artifacts") or {}).get("log")
        if not log:
            raise CollectionError(f"{report.name}: {corner.get('process')}/{corner.get('temperature_c')}: "
                                  f"no log ({corner.get('diagnostics')})")
        path = Path(log)
        if not path.is_absolute():
            path = (report.parent / path).resolve()
        units.append({"process": corner["process"], "temp_c": float(corner["temperature_c"]),
                      "status": corner.get("status"), "text": path.read_text()})
    meta = {k: data.get(k) for k in ("status", "environment", "provenance")}
    return meta, units


def _r(x, sig: int = 7):
    """Round floats for the cells sidecar (raw logs keep full precision)."""
    if isinstance(x, float):
        if math.isfinite(x):
            return float(f"{x:.{sig}g}")
        return None if math.isnan(x) else ("+inf" if x > 0 else "-inf")
    if isinstance(x, dict):
        return {k: _r(v, sig) for k, v in x.items()}
    if isinstance(x, list):
        return [_r(v, sig) for v in x]
    return x


def unit_cells(st: ms.Study, spec: RequestSpec, unit: dict) -> tuple[list[dict], dict, list[str]]:
    """Cells and the point bound of one unit's log. Problems are corruption."""
    pl = ms.parse_log(unit["text"])
    cid = ms.corner_id(unit["process"], unit["temp_c"], spec.vdd)
    problems = [f"{spec.key}/{cid}: {p}" for p in pl.problems]
    if not pl.done:
        problems.append(f"{spec.key}/{cid}: deck did not reach LM_DONE")
    missing = [n for n in spec.networks if n not in pl.tables]
    extra = sorted(set(pl.tables) - set(spec.networks))
    if missing or extra:
        problems.append(f"{spec.key}/{cid}: networks missing {missing[:5]} / unexpected {extra[:5]}")
    # a missing or extra printed block is a broken run (corruption), never a
    # scientific rejection; non-finite values and refined-grid failures are
    # scientific and become rejected_invalid cells
    for n in spec.networks:
        if n in pl.tables:
            want = set(ms.sections_for(st.candidate(n)))
            got = set(pl.tables[n])
            if want != got:
                problems.append(f"{spec.key}/{cid}/{n}: printed blocks missing {sorted(want - got)} / "
                                f"unexpected {sorted(got - want)}")
    if problems:
        return [], {}, problems
    cands = [st.candidate(n) for n in spec.networks]
    cells = [ms.make_cell(st, spec.phase, c, unit["process"], unit["temp_c"], spec.vdd, pl.tables[c.name], pl.op)
             for c in cands]
    for c in cells:
        c["request"] = spec.key
        if c["role"] == "probe":
            for k in ("band", "mid", "wide"):
                c.pop(k, None)
        else:
            c.pop("mid", None)
    bound = ms.point_bound(st, pl.tables, cands)
    bound.update(point=cid, phase=spec.phase)
    return cells, bound, []


def baseline_reproduction(st: ms.Study, cells: list[dict]) -> dict:
    import lna_nf  # noqa: PLC0415 - read-only use of sim/lna-sparam-nf
    per = {}
    problems = []
    worst = {"s_db": 0.0, "nf_db": 0.0, "k": 0.0}
    for c in cells:
        if c["candidate"] != st.baseline.name or c["status"] != "ok":
            continue
        log = BASELINE_LOGS / f"{c['corner_id']}.log"
        if not log.is_file():
            problems.append(f"{c['id']}: no baseline log {log.name}")
            continue
        r = ms.compare_baseline(st, c, lna_nf.parse_log(log.read_text()))
        per[c["id"]] = r["worst"]
        for k in worst:
            worst[k] = max(worst[k], r["worst"][k])
        problems += [f"{c['id']}: {p}" for p in r["problems"]]
    return {"record": f"sim/lna-sparam-nf/records/{BASELINE_RECORD}.md", "compared_points": len(per),
            "worst": worst, "per_cell": per, "problems": problems,
            "tolerances": {"db": st.tolerances["baseline_db"], "k": st.tolerances["baseline_k"]}}


def crosscheck(st: ms.Study, cells: list[dict]) -> dict:
    """Screen (nominal unit, screen backend) vs corner campaign (same point,
    corner backend) for every shortlisted network: dense-grid S/NF arrays."""
    n = st.nominal
    nom = ms.corner_id(n["process"], float(n["temp_c"]), float(n["vdd"]))
    scr = {c["candidate"]: c for c in cells if c["phase"] == "screen" and c["status"] == "ok"}
    worst = 0.0
    compared = 0
    for c in cells:
        if c["phase"] != "corners" or c["corner_id"] != nom or c["status"] != "ok" or "band" not in c:
            continue
        s = scr.get(c["candidate"])
        if s is None or "band" not in s:
            continue
        for k in ("nf_db", "s11_db", "s21_db", "s22_db"):
            worst = max(worst, max(abs(x - y) for x, y in zip(c["band"][k], s["band"][k])))
        compared += 1
    tol = float(st.tolerances["crosscheck_db"])
    return {"point": nom, "compared_networks": compared, "worst_db": worst, "tol_db": tol,
            "ok": compared > 0 and worst <= tol}


def execution(meta: dict, spec: RequestSpec, backend: str) -> dict:
    env = (meta.get("environment") or {})
    return {"key": spec.key, "phase": spec.phase, "backend": backend, "units": spec.units,
            "status": meta.get("status"), "engine": env.get("engine"), "engine_version": env.get("engine_version"),
            "models_lib_sha256": env.get("models_lib_sha256"), "netlist_sha256": env.get("netlist_sha256"),
            "remote": env.get("remote"), "klt_version": (meta.get("provenance") or {}).get("klt_version")}


@dataclass
class Collected:
    cells: list[dict]
    bounds: dict
    shortlist: dict
    requests: list[dict]
    units_text: dict          # file stem -> log text
    work: Path


def run_collection(st: ms.Study, work: Path, args) -> Collected:
    cells: list[dict] = []
    bounds: dict = {}
    requests: list[dict] = []
    texts: dict = {}
    problems: list[str] = []

    def do(spec: RequestSpec):
        req, _ = write_request(st, spec, work, args)
        if args.dry_run:
            return
        report = submit(spec, req, work, args)
        meta, units = read_units(report)
        requests.append(execution(meta, spec, backend_for(spec, args)))
        for u in units:
            cs, b, pr = unit_cells(st, spec, u)
            problems.extend(pr)
            cells.extend(cs)
            if b:
                bounds[f"{spec.phase}__{b['point']}"] = b
            texts[f"{spec.key}__{u['process']}_{u['temp_c']:g}c"] = u["text"]

    do(screen_spec(st))
    if args.dry_run:
        print(f"--dry-run: screen request written under {work} (corner requests need the screen's shortlist)")
        return Collected(cells, bounds, {}, requests, texts, work)
    if problems:
        raise CollectionError("screen corrupt: " + "; ".join(problems[:10]))
    sl = ms.shortlist(st, [c for c in cells if c["phase"] == "screen"])
    print(f"shortlist ({len(sl['names'])}): " + ", ".join(f"{n} [{'; '.join(sl['why'][n])}]" for n in sl["names"]))
    if getattr(args, "screen_only", False):
        return Collected(cells, bounds, sl, requests, texts, work)
    for spec in corner_specs(st, sl["names"]):
        do(spec)
    if problems:
        raise CollectionError("corner campaign corrupt: " + "; ".join(problems[:10]))
    return Collected(cells, bounds, sl, requests, texts, work)


# ---------------------------------------------------------------------------
# Record rendering
# ---------------------------------------------------------------------------


def _kmin(sm: dict):
    """In-band and (when swept) wide-sweep minimum k; probes have no wide sweep."""
    if not sm:
        return None
    return min(sm["k_min"], sm.get("wide_k_min", math.inf))


def _f(x, fmt="{:.2f}") -> str:
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else fmt.format(x)


def render_md(*, rid: str, st: ms.Study, col: Collected, rep: dict, xc: dict, controls: dict, concl: dict,
              started: str, git: dict, ngspice: str, klt_version: str, decl_sha: str, gate: list[str]) -> str:
    L: list[str] = []
    a = L.append
    a(f"# lna-match-tradeoff record {rid}")
    a("")
    a(f"**Started (UTC)**: {started}")
    a("**Experiment**: lna-match-tradeoff (issue #74)")
    a("**Spec rows claimed met**: none")
    a(f"**Claim**: {st.raw['claim']}")
    a(f"**Declaration**: `testbench/study.json` sha256 `{decl_sha}` (frozen copy in "
      f"`netlist-snapshots/{rid}/study.json`; rationale in `STUDY.md`)")
    a(f"**DUT**: `design/netlist/lna_stage1.spice` sha256 `{klt_driver.sha256_file(FROZEN)}`; only `Cshunt` and "
      "`Lin` are parameterized and `Csh2` is added (c_sh2 = 0 is the baseline topology). Rd, bias network, device "
      "sizing and the output network are unchanged.")
    a(f"**Outcome**: {concl['outcome']}")
    a("")
    a("## Method")
    a("")
    a(f"- Ports: 50 ohm Thevenin per port, noiseless reference source; F = 1 + inoise^2 / (4 k T0 50) with "
      f"T0 = {st.t0_k} K (sim/lna-sparam-nf convention, issue #22). The 50 ohm output load stays noisy at the "
      "circuit temperature (same convention); its share (T/T0)|1+S22|^2/|S21|^2 is removed in the "
      "`NF excl. load` column. Screens use the bench-convention NF (conservative).")
    a(f"- Frequency grids: dense `ac lin {st.grid.dense_n}` 17.7-21.2 GHz (50 MHz), refined-grid control adds the "
      f"{st.grid.mid_n} midpoints (25 MHz union); wide stability sweep `ac dec {st.grid.wide_per_decade}` "
      f"{st.grid.wide_start_hz / 1e9:g}-{st.grid.wide_stop_hz / 1e9:g} GHz ({st.wide_count()} points), forward and reverse.")
    a("- S-parameters from printed port voltages (S11 = 2 V1 - 1, S21 = 2 V2; reverse likewise); k, |Delta|, mu "
      "from them in `matchstudy.py`. Transducer gain into the 50 ohm load = |S21|^2.")
    a("- Network-independent bound: noise parameters (Fmin, Rn, Yopt) fitted at every dense frequency from the "
      "probe networks, core S-parameters from `probe_thru`; for any LOSSLESS input network the port NF and |S11| "
      "depend only on the source reflection presented to the core, so the smallest NF reachable with "
      f"|S11| <= {st.screen['s11_max_db']} dB is a minimum over a mismatch circle. A model check requires every "
      f"selectable network's simulated NF and S11 to match the prediction within {st.tolerances['model_db']} dB.")
    a("")
    a("## Intentional reductions")
    a("")
    a("- Ideal lossless L/C networks only (no inductor model exists; real loss adds directly to NF). A "
      "candidate here is an optimistic feasibility point, contingent on passive qualification (#46).")
    a("- The family is two-element lowpass L-sections; the bound covers every lossless network but is a "
      "per-frequency necessary condition, not a realizable network.")
    a("- One stage only (row 2 assumes two); no second-stage loading; the band (row 1) is OPEN and DRAFT.")
    a("- Corner campaign = shortlist + probes only; the screen is at the nominal point only.")
    a("")
    a("## Controls")
    a("")
    for name, c in controls.items():
        a(f"- {name}: {'ok' if c.get('ok') else 'FAILED'} -- " + ", ".join(
            f"{k} {_f(v, '{:.3g}')}" if isinstance(v, float) else f"{k} {v}"
            for k, v in c.items() if k not in ("ok", "problems")))
    a(f"- Baseline reproduction vs `{rep['record']}` ({rep['compared_points']} shared PVT points, 17.7 / 19.45 / "
      f"21.2 GHz): worst |dS| {_f(rep['worst']['s_db'], '{:.2e}')} dB, |dNF| {_f(rep['worst']['nf_db'], '{:.2e}')} dB, "
      f"|dk| {_f(rep['worst']['k'], '{:.2e}')} (tolerances {rep['tolerances']['db']} dB / {rep['tolerances']['k']}); "
      f"{'ok' if not rep['problems'] else 'FAILED: ' + '; '.join(rep['problems'][:5])}")
    a(f"- Screen vs corner-campaign cross-check at {xc['point']}: {xc['compared_networks']} networks, worst "
      f"{_f(xc['worst_db'], '{:.2e}')} dB (tolerance {xc['tol_db']} dB) -> {'ok' if xc['ok'] else 'FAILED'}")
    a(f"- Acceptance gate (`validate_collection`): {'passed' if not gate else 'FAILED'}")
    a("")
    a("## Nominal screen (hbt_typ, 27 C, 2.5 V)")
    a("")
    a("All declared networks, including rejected ones and the reason. Band = 71 dense points 17.7-21.2 GHz.")
    a("")
    a("| network | role | topology | C_sh1 (fF) | L_in (nH) | C_sh2 (fF) | status | NF max | NF excl. load max | "
      "NF @f0 | S11 max | S21 min | k min (1-100 GHz) | refined dNF/dS11/dS21 | screen |")
    a("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    scr = [c for c in col.cells if c["phase"] == "screen"]
    for c in sorted(scr, key=lambda c: ({"baseline": 0, "candidate": 1, "probe": 2}[c["role"]], c["candidate"])):
        cand = st.candidate(c["candidate"])
        sm = c.get("summary") or {}
        rf = (c.get("refined") or {}).get("delta") or {}
        scr_txt = "pass" if c["screen"]["pass"] else "; ".join(c["screen"]["reasons"])
        a(f"| {c['candidate']} | {c['role']} | {cand.topology} | {cand.c_sh1 * 1e15:.4g} | {cand.l_in * 1e9:.4g} | "
          f"{cand.c_sh2 * 1e15:.4g} | {c['status']} | {_f(sm.get('nf_max_db'))} | {_f(sm.get('nf_max_excl_load_db'))} | "
          f"{_f(sm.get('nf_f0_db'))} | {_f(sm.get('s11_max_db'))} | {_f(sm.get('s21_min_db'))} | "
          f"{_f(_kmin(sm))} | "
          f"{'/'.join(_f(rf.get(k), '{:+.3f}') for k in ('nf_max_db', 's11_max_db', 's21_min_db'))} | {scr_txt} |")
    a("")
    a(f"Excluded (unrealizable as a lowpass L-section, or |Gamma| >= {ms.GAMMA_MAX}): {len(st.excluded_targets)} "
      "target/orientation pairs, listed with reasons in the frozen `study.json` (`excluded_targets`).")
    a("")
    a("## Shortlist (declared rule applied to the screen)")
    a("")
    for n in col.shortlist["names"]:
        a(f"- `{n}`: {'; '.join(col.shortlist['why'][n])}")
    a("")
    a("## Network-independent bound per PVT point")
    a("")
    a(f"Smallest NF any lossless input network could give with |S11| <= {st.screen['s11_max_db']} dB, worst over "
      "the dense band (bench-convention NF), and the core's Fmin range. `jointly infeasible` counts band points "
      f"where even that bound exceeds {st.screen['nf_max_db']} dB.")
    a("")
    a("| point | supply class | bound valid | NF bound max (dB) | at (GHz) | Fmin range (dB) | jointly infeasible "
      "points | model check worst (dB) |")
    a("|---|---|---|---|---|---|---|---|")
    for key in sorted(col.bounds):
        b = col.bounds[key]
        s = b.get("summary") or {}
        vdd = float(b["point"].rsplit("_", 1)[1].rstrip("v"))
        cls = "EXCURSION" if vdd > st.rail_ceiling_v + 1e-9 else "in rail"
        a(f"| {key} | {cls} | {'yes' if b.get('valid') else 'NO'} | {_f(s.get('nf_bound_max_db'), '{:.3f}')} | "
          f"{_f((s.get('f_at_nf_bound_max_hz') or float('nan')) / 1e9, '{:.2f}')} | "
          f"{_f(s.get('fmin_min_db'), '{:.2f}')}-{_f(s.get('fmin_max_db'), '{:.2f}')} | "
          f"{s.get('n_freq_jointly_infeasible', 'n/a')}/{s.get('n_freq', 'n/a')} | "
          f"{_f(s.get('model_check_worst_db'), '{:.1e}')} |")
    a("")
    a("## Corner campaign: shortlisted networks")
    a("")
    a("Every PVT point for every shortlisted network. 2.75 V cells are a labelled EXCURSION above the row-17 "
      "rail ceiling and never enter a verdict.")
    a("")
    a("| network | point | class | status | NF max | NF excl. load max | S11 max | S21 min | k min | |Delta| max | "
      "op (row 17 / card) | screen |")
    a("|---|---|---|---|---|---|---|---|---|---|---|---|")
    cor = [c for c in col.cells if c["phase"] == "corners" and c["role"] != "probe"]
    for c in sorted(cor, key=lambda c: (c["candidate"], c["corner_id"])):
        sm = c.get("summary") or {}
        op = c.get("op") or {}
        a(f"| {c['candidate']} | {c['corner_id']} | {'EXCURSION' if c['supply_class'] == 'excursion' else 'in rail'} | "
          f"{c['status']} | {_f(sm.get('nf_max_db'))} | {_f(sm.get('nf_max_excl_load_db'))} | {_f(sm.get('s11_max_db'))} | "
          f"{_f(sm.get('s21_min_db'))} | {_f(_kmin(sm))} | "
          f"{_f(max(sm['delta_max'], sm['wide_delta_max']) if sm else None, '{:.3f}')} | "
          f"{'pass' if op.get('pass') else 'FAIL ' + ', '.join(op.get('failures', []))} | "
          f"{'pass' if c['screen']['pass'] else '; '.join(c['screen']['reasons'])} |")
    a("")
    a("## Conclusion")
    a("")
    a(f"**{concl['outcome']}.**")
    a("")
    for n, v in concl["per_candidate"].items():
        w = v["worst_in_rail"]
        a(f"- `{n}`: {v['verdict']}; worst in-rail NF max {_f(w.get('nf_max_db'))} dB, S11 max "
          f"{_f(w.get('s11_max_db'))} dB, S21 min {_f(w.get('s21_min_db'))} dB, k min {_f(w.get('k_min'))}; "
          f"excursion cells failing: {len(v['excursion_fail'])}")
    bnd = concl.get("bound") or {}
    if bnd:
        a(f"- Network-independent bound (in-rail points with a valid bound): {bnd['summary']}")
    a("")
    a("Ideal matching claims no spec row. Whatever this record shows remains contingent on passive loss (#46), "
      "the open band decision (row 1) and second-stage loading.")
    a("")
    a("## Provenance and raw artifacts")
    a("")
    a(f"- git {git.get('commit')} (branch {git.get('branch')}, dirty={git.get('dirty')})")
    a(f"- klt client: `{klt_version}`; ingesting host ngspice: {ngspice}")
    for r in col.requests:
        rem = r.get("remote") or {}
        a(f"- request `{r['key']}`: backend {r['backend']}, {r['units']} unit(s), status {r['status']}, engine "
          f"{r['engine']} {r['engine_version']}, models_lib_sha256 {r['models_lib_sha256']}"
          + (f", remote job {rem.get('job_id')} ({rem.get('provider')}, {rem.get('instance_type')}, runner klt "
             f"{rem.get('runner_klt_version')}, compatibility {rem.get('runner_compatibility')})" if rem else
             ", ran on this host"))
    a(f"- raw logs: `corners/{rid}/*.log.gz`; bodies/requests/reports/declaration/DUT: `netlist-snapshots/{rid}/`; "
      f"per-cell per-frequency data: `records/{rid}-cells.json.gz`; summary JSON: `records/{rid}.json`.")
    a("")
    return "\n".join(L)


def write_record(st: ms.Study, col: Collected, *, rep: dict, xc: dict, controls: dict, concl: dict, gate: list[str],
                 pdk_prov: dict, ngspice: str, klt_version: str, started: _dt.datetime, git: dict) -> str:
    if gate:
        raise CollectionError("acceptance gate failed; no record: " + "; ".join(gate[:10]))
    RECORDS.mkdir(parents=True, exist_ok=True)
    rid = allocate_record_id(REPO_ROOT, RECORDS, started, git)
    for d in (CORNER_LOGS / rid, SNAPSHOTS / rid):
        if d.exists():
            raise RecordExists(f"{d} exists; append-only evidence is never rewritten")
    decl = TB_DIR / "study.json"
    decl_sha = klt_driver.sha256_file(decl)
    # raw logs
    (CORNER_LOGS / rid).mkdir(parents=True)
    for stem, text in sorted(col.units_text.items()):
        with gzip.open(CORNER_LOGS / rid / f"{stem}.log.gz", "wt", compresslevel=9) as fh:
            fh.write(text)
    # snapshots
    snap = SNAPSHOTS / rid
    snap.mkdir(parents=True)
    shutil.copyfile(decl, snap / "study.json")
    shutil.copyfile(FROZEN, snap / "lna_stage1.spice")
    for p in sorted(col.work.iterdir()):
        if p.is_file() and p.name.split("_", 1)[0] in ("body", "request", "report", "spec") \
                and not p.name.endswith(".failed.json"):
            shutil.copyfile(p, snap / p.name)
    cells_name = f"{rid}-cells.json.gz"
    with gzip.open(RECORDS / cells_name, "wt", compresslevel=9) as fh:
        json.dump(_r(col.cells), fh, separators=(",", ":"))
    bounds = {k: _r({kk: vv for kk, vv in b.items()}) for k, b in col.bounds.items()}
    data = {
        "record_id": rid, "experiment": "lna-match-tradeoff", "issue": 74, "scope": SCOPE,
        "claim": st.raw["claim"], "spec_rows_claimed_met": [],
        "declaration": {"path": "sim/lna-match-tradeoff/testbench/study.json", "sha256": decl_sha},
        "gate": {"validate_collection": "passed", "problems": []},
        "declared_cells": len(ms.expected_cells(st, col.shortlist["names"])), "accepted_cells": len(col.cells),
        "cells_file": cells_name, "shortlist": col.shortlist, "bounds": bounds,
        "baseline_reproduction": _r(rep), "crosscheck": _r(xc), "controls": _r(controls), "conclusion": _r(concl),
        "provenance": {"git": git, "ngspice": ngspice, "klt": klt_version, "pdk": pdk_prov,
                       "klt_requests": col.requests,
                       "frozen_inputs": {"design_netlist_sha256": klt_driver.sha256_file(FROZEN),
                                         "study_json_sha256": decl_sha}},
    }
    (RECORDS / f"{rid}.json").write_text(json.dumps(data, indent=1, allow_nan=False) + "\n")
    md = render_md(rid=rid, st=st, col=col, rep=rep, xc=xc, controls=controls, concl=concl,
                   started=started.isoformat(), git=git, ngspice=ngspice, klt_version=klt_version,
                   decl_sha=decl_sha, gate=gate)
    (RECORDS / f"{rid}.md").write_text(md)
    return rid


def bound_conclusion(st: ms.Study, bounds: dict) -> dict:
    """Summary of the network-independent bound over in-rail corner points."""
    inr = {k: b for k, b in bounds.items() if k.startswith("corners__")
           and float(b["point"].rsplit("_", 1)[1].rstrip("v")) <= st.rail_ceiling_v + 1e-9}
    valid = {k: b for k, b in inr.items() if b.get("valid")}
    if not valid:
        return {"summary": "no valid in-rail bound"}
    worst = max(valid.values(), key=lambda b: b["summary"]["nf_bound_max_db"])
    infeasible = sorted(b["point"] for b in valid.values() if b["summary"]["n_freq_jointly_infeasible"] > 0)
    return {"points": len(inr), "valid_points": len(valid), "worst_point": worst["point"],
            "worst_nf_bound_db": worst["summary"]["nf_bound_max_db"], "infeasible_points": infeasible,
            "summary": (f"{len(valid)}/{len(inr)} in-rail points valid; worst NF bound "
                        f"{worst['summary']['nf_bound_max_db']:.3f} dB at {worst['point']}; "
                        f"{len(infeasible)} point(s) where no lossless input network can reach NF <= "
                        f"{st.screen['nf_max_db']} dB with S11 <= {st.screen['s11_max_db']} dB at some band "
                        "frequency")}


def klt_version_text(klt_cmd: str) -> str:
    p = subprocess.run(shlex.split(klt_cmd) + ["--version"], capture_output=True, text=True)
    return (p.stdout or p.stderr).strip()


def assemble(st: ms.Study, col: Collected, controls: dict) -> dict:
    """Everything the record states besides the cells: baseline
    reproduction, cross-check, the gate (incl. controls), the conclusion."""
    rep = baseline_reproduction(st, col.cells)
    xc = crosscheck(st, col.cells)
    gate = ms.validate_collection(st, col.cells, col.shortlist["names"])
    gate += [f"control {k} failed" for k, v in controls.items() if not v["ok"]]
    gate += rep["problems"]
    if rep["compared_points"] != len(st.pvt_points()) + 1:
        gate.append(f"baseline reproduction compared {rep['compared_points']} points, expected "
                    f"{len(st.pvt_points()) + 1} (27 corners + the screen)")
    if not xc["ok"]:
        gate.append(f"cross-check failed: {xc}")
    missing_bounds = [k for k in (f"{c['phase']}__{c['corner_id']}" for c in col.cells) if k not in col.bounds]
    if missing_bounds:
        gate.append(f"no bound computed for {sorted(set(missing_bounds))[:5]}")
    concl = ms.conclude(st, col.cells, col.shortlist)
    concl["bound"] = bound_conclusion(st, col.bounds)
    return {"rep": rep, "xc": xc, "gate": gate, "concl": concl}


def collect(args) -> int:
    import localrun  # noqa: PLC0415 - single-point local controls (needs ngspice + PDK)
    st = ms.load_study()
    started = _dt.datetime.now(_dt.timezone.utc)
    work = Path(args.workdir).resolve() if args.workdir else (SCRATCH / f"collect-{started:%Y%m%d-%H%M%S}").resolve()
    work.mkdir(parents=True, exist_ok=True)
    print(f"workdir {work}")
    git = git_provenance(REPO_ROOT)
    try:
        col = run_collection(st, work, args)
        if args.dry_run or getattr(args, "screen_only", False):
            return 0
        controls = {f"pad_{t:g}c": localrun.pad_control(st, t) for t in (27.0, -40.0)}
        a = assemble(st, col, controls)
        pdk = klt_driver.find_pdk_or_exit(SIM_DIR)
        rid = write_record(st, col, rep=a["rep"], xc=a["xc"], controls=controls, concl=a["concl"], gate=a["gate"],
                           pdk_prov=klt_driver.pdk_provenance(pdk, MODEL_FILES), ngspice=localrun.version(),
                           klt_version=klt_version_text(args.klt_cmd), started=started, git=git)
    except CollectionError as exc:
        print(f"collect: {exc}\nNo record written; work directory kept: {work}", file=sys.stderr)
        return 1
    print(f"wrote records/{rid}.md")
    return 0


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
