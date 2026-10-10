"""Tests for the collection half (collect.py): request generation, ingest of
klt reports into declared cells, staged selection, and the no-record paths.

Pure Python, no simulator, no PDK, no klt: ``collect.submit`` is replaced by a
fake that writes a klt-shaped report plus per-unit logs computed from a
closed-form device model. Run from the repo root:

    python3 -m pytest sim/mixer-topology-feasibility/tests/test_collect.py -q
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))

import collect  # noqa: E402
import mixfeas as mf  # noqa: E402

PROCESS_OFFSET_DB = {"hbt_typ": 0.0, "hbt_bcs": 0.4, "hbt_wcs": -0.6,
                     "hbt_typ_mismatch": 0.0, "hbt_bcs_mismatch": 0.4, "hbt_wcs_mismatch": -0.6}


@pytest.fixture(scope="module")
def study():
    return mf.study_from_manifest(json.loads((BENCH / "testbench" / "tb.json").read_text()))


def amp_for_dbm(p_dbm):
    return math.sqrt(2 * 50.0 * 1e-3 * 10 ** (p_dbm / 10.0))


def fake_values(run, cand, process, temp, *, gain_fn, stress_fn=None, nan_key=None):
    """mf_ values from a closed-form model (bin re = amplitude, im = 0)."""
    gain = gain_fn(cand.name, process, temp, run)
    amps = {"lodiff": 0.3}
    if run.kind == "single":
        amps.update({"if": amp_for_dbm(run.rf_dbm + gain), "loif": amp_for_dbm(-100.0),
                     "lorf": amp_for_dbm(-95.0)})
    elif run.kind == "rfoff":
        amps.update({"loif": amp_for_dbm(-90.0), "lorf": amp_for_dbm(-85.0)})
    else:
        p = run.rf_dbm
        iip3 = -5.0
        im3 = 3 * p + gain - 2 * iip3
        amps.update({"if1": amp_for_dbm(p + gain), "if2": amp_for_dbm(p + gain),
                     "im3l": amp_for_dbm(im3), "im3h": amp_for_dbm(im3 - 0.2)})
    n = run.n_samples
    values = {"mf_l": float(2 * n + 1), "mf_n": float(n), "mf_dcirail": 2e-3, "mf_prail": 4.5e-3}
    for name in run.bins():
        values[f"mf_{name}_re"] = amps.get(name, 0.0)
        values[f"mf_{name}_im"] = 0.0
    for node in cand.sink_nodes:
        values[f"mf_dc_sink_{node}"] = 0.5
        values[f"mf_su_sinkmin_{node}"] = 0.4
        values[f"mf_ss_sinkmin_{node}"] = 0.45
    for dev in cand.devices:
        st = (stress_fn(cand.name, process, temp, run, dev.name) if stress_fn else None) or {}
        for q, (lo, hi) in (("vce", (0.6, 1.1)), ("vbe", (0.75, 0.9)), ("ic", (2e-4, 1e-3))):
            lo, hi = st.get(q, (lo, hi))
            values[f"mf_dc_{q}_{dev.name}"] = (lo + hi) / 2
            for iv in ("su", "ss"):
                values[f"mf_{iv}_{q}max_{dev.name}"] = hi
                values[f"mf_{iv}_{q}min_{dev.name}"] = lo
    if nan_key:
        values[nan_key] = float("nan")
    return values


def log_text(runs_values):
    lines = ["MF_DECK_BEGIN"]
    for rid, vals in runs_values.items():
        lines.append(f"MFRUN {rid}")
        lines += [f"{k} = {v:.10e}" if math.isfinite(v) else f"{k} = nan" for k, v in vals.items()]
        lines.append(f"MFEND {rid}")
    lines.append("MF_DECK_END")
    lines.append("sentinel_rail_v = 2.2500000000e+00")  # klt's own trailing .meas, printed after the deck
    return "\n".join(lines) + "\n"


def default_gain(cand, process, temp, run):
    # gain rises 0.75 dB/dB with LO drive and saturates at 6 dB (plateau from -6 dBm up)
    g = min(6.0, -12.0 + 0.75 * (run.vlo_dbm + 30.0))
    return g + PROCESS_OFFSET_DB[process] - 0.01 * (temp - 27.0)


class Fake:
    """Replaces collect.submit; records what was submitted."""

    def __init__(self, study, tmp_path, *, gain_fn=default_gain, stress_fn=None, drop_unit=None,
                 drop_run=None, nan_run=None, swap_process=None):
        self.study, self.tmp, self.gain_fn, self.stress_fn = study, tmp_path, gain_fn, stress_fn
        self.drop_unit, self.drop_run, self.nan_run, self.swap_process = drop_unit, drop_run, nan_run, swap_process
        self.submitted: list[collect.RequestSpec] = []

    def __call__(self, spec, req, work, args):
        self.submitted.append(spec)
        cand = self.study.candidate(spec.candidate)
        runs = collect.stage_runs(self.study, spec.matrix, spec.drive_dbm)
        corners = []
        for process in spec.corners:
            for temp in spec.temps:
                if self.drop_unit and self.drop_unit == (spec.matrix, process, temp):
                    continue
                vals = {}
                for rid, run in runs.items():
                    if self.drop_run and self.drop_run == (spec.matrix, rid):
                        continue
                    nan_key = "mf_prail" if self.nan_run == (spec.matrix, rid) else None
                    vals[rid] = fake_values(run, cand, process, temp, gain_fn=self.gain_fn,
                                            stress_fn=self.stress_fn, nan_key=nan_key)
                log = self.tmp / f"{spec.key}_{process}_{temp:g}.log"
                log.write_text(log_text(vals))
                reported = self.swap_process or process
                corners.append({"process": reported, "temperature_c": temp, "artifacts": {"log": str(log)}})
        report = work / f"report_{spec.key}.json"
        report.write_text(json.dumps({"status": "ok", "corners": corners, "environment": {"remote": "fake"}}))
        return report


CONV = {"drive_dbm": -6.0, "drive_kind": "selected", "ok": True, "checks": [], "failures": [], "baseline": {}}


def args(**kw):
    base = dict(dry_run=False, stage1_only=False, backend="batch", klt_cmd="klt", timeout_s=60,
                runner_version_check="", no_stage_models=False)
    base.update(kw)
    return SimpleNamespace(**base)


def collect_with(study, tmp_path, monkeypatch, **fake_kw):
    fake = Fake(study, tmp_path, **fake_kw)
    monkeypatch.setattr(collect, "submit", fake)
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    col = collect.run_collection(study, ["reltol=1e-5"], work, args())
    return col, fake


# ---------------------------------------------------------------------------
# request generation
# ---------------------------------------------------------------------------


def test_stage_run_lists_cover_the_declared_sweeps(study):
    ls = collect.stage_runs(study, "lo_select")
    assert len(ls) == 3 * 13 * 2 and len(set(ls)) == len(ls)
    assert {r.rf_dbm for r in ls.values()} == {-60.0, -66.0} and all(r.kind == "single" for r in ls.values())
    ip = collect.stage_runs(study, "iip3", -6.0)
    assert len(ip) == 3 * 13 and all(r.kind == "two_tone" and r.vlo_dbm == -6.0 for r in ip.values())
    assert [r.rf_dbm for r in ip.values()][:13] == list(study.iip3_pin_dbm)
    mn, lk = collect.stage_runs(study, "main", -6.0), collect.stage_runs(study, "leakage", -6.0)
    assert len(mn) == len(lk) == 3
    assert all(r.rf_dbm == -60.0 for r in mn.values()) and all(r.rf_dbm is None for r in lk.values())
    assert all(r.window_s == study.timing.window_single_s for r in list(mn.values()) + list(lk.values()))


def test_request_plan_counts_and_units(study):
    cand = study.candidates[0]
    main = collect.plan_requests(study, "main", cand, -6.0)
    leak = collect.plan_requests(study, "leakage", cand, -6.0)
    assert [r.vdd for r in main] == [2.025, 2.25, 2.475] and len(leak) == 3
    assert all(len(r.corners) * len(r.temps) == 9 for r in main + leak)
    assert leak[0].corners == ["hbt_typ_mismatch", "hbt_bcs_mismatch", "hbt_wcs_mismatch"]
    assert leak[0].seed == 35001 and main[0].seed is None
    (ls,) = collect.plan_requests(study, "lo_select", cand, None)
    assert ls.vdd == 2.25 and ls.corners == ["hbt_typ"] and ls.temps == [27.0]
    keys = [r.key for r in main + leak + [ls]]
    assert len(set(keys)) == len(keys)


def test_backend_single_unit_local_multi_unit_requested(study):
    cand = study.candidates[0]
    (ls,) = collect.plan_requests(study, "lo_select", cand, None)
    main = collect.plan_requests(study, "main", cand, -6.0)[0]
    assert collect.backend_for(ls, args()) == "local"
    assert collect.backend_for(main, args()) == "batch"
    assert collect.backend_for(main, args(backend="local-parallel")) == "local-parallel"


def test_body_and_request_content(study, tmp_path):
    cand = study.candidates[0]
    leak = collect.plan_requests(study, "leakage", cand, -6.0)[0]
    runs = list(collect.stage_runs(study, "leakage", -6.0).values())
    body = collect.klt_body(study, ["reltol=1e-5"], cand, leak.vdd, runs, leak.seed)
    assert ".param vdd_val=2.025" in body and ".options reltol=1e-5" in body and ".options seed=35001" in body
    assert ".control" in body and body.count("MFRUN lk_") == 3 and "MF_DECK_END" in body
    assert ".lib" not in body.replace(".lib/", "")  # models are klt's, never inlined
    main_body = collect.klt_body(study, ["reltol=1e-5"], cand, 2.25,
                                 list(collect.stage_runs(study, "main", -6.0).values()), None)
    assert "seed" not in main_body
    req = collect.klt_request("b.spice", leak.corners, leak.temps, "batch", 60, runner_version_check="warn")
    # klt's sentinel .meas lands in the same log: it must not look like a deck value
    assert not any(m["name"].startswith("mf_") for m in req["measurements"])
    assert req["models"]["lib"].endswith("cornerHBT.lib") and req["batch"]["runner_version_check"] == "warn"
    assert req["corners"]["process"] == leak.corners and req["corners"]["temperature_c"] == leak.temps


def test_dry_run_writes_first_stage_only(study, tmp_path, monkeypatch):
    monkeypatch.setattr(collect, "submit", lambda *a, **k: pytest.fail("dry run submitted a request"))
    work = tmp_path / "w"
    work.mkdir()
    assert collect.run_collection(study, ["reltol=1e-5"], work, args(dry_run=True)) is None
    assert len(list(work.glob("request_lo_select__*.json"))) == 3
    assert not list(work.glob("request_main__*"))


# ---------------------------------------------------------------------------
# ingest and gate
# ---------------------------------------------------------------------------


def test_full_synthetic_collection_passes_the_gate_and_selects(study, tmp_path, monkeypatch):
    col, fake = collect_with(study, tmp_path, monkeypatch)
    assert mf.validate_collection(study, col.cells) == []
    assert len(col.cells) == len(mf.expected_cells(study))
    for cand in study.candidates:
        sel = col.selections[cand.name]
        assert sel["status"] == "selected" and sel["drive_dbm"] == -6.0
        assert all(f["status"] == "ok" for f in col.iip3[cand.name].values())
        assert all(abs(f["iip3_dbm"] - -5.0) < 0.6 for f in col.iip3[cand.name].values())
    # 3 candidates x (1 lo_select + 1 iip3 + 3 main + 3 leakage) requests
    assert len(fake.submitted) == 3 * 8
    concl = mf.conclude(study, collect.per_candidate(study, col))
    assert concl["recommendation"]["draw_first"] in {c.name for c in study.candidates if c.role == "candidate"}
    seeds = {c["seed"] for c in col.cells if c["matrix"] == "leakage"}
    assert seeds == {35001} and all(c["seed"] is None for c in col.cells if c["matrix"] == "main")
    assert all(c["lo_selected_dbm"] == -6.0 for c in col.cells if c["matrix"] in ("main", "leakage", "iip3"))


def test_no_acceptable_drive_gives_explicit_cells_and_no_stage2_requests(study, tmp_path, monkeypatch):
    floor = [c.name for c in study.candidates if c.role == "floor"][0]

    def gain(cand, process, temp, run):
        g = default_gain(cand, process, temp, run)
        # the small-signal check fails everywhere for the floor: RF -66 dBm gain differs by 1 dB
        return g + (1.0 if cand == floor and run.rf_dbm == -66.0 else 0.0)

    col, fake = collect_with(study, tmp_path, monkeypatch, gain_fn=gain)
    assert col.selections[floor]["status"] == "no acceptable drive in declared sweep"
    assert not [s for s in fake.submitted if s.candidate == floor and s.matrix != "lo_select"]
    na = [c for c in col.cells if c["candidate"] == floor and c["matrix"] != "lo_select"]
    assert na and all(c["status"] == "not_applicable_no_drive" for c in na)
    assert mf.validate_collection(study, col.cells) == []
    assert all(f["status"] == "IIP3 unavailable" for f in col.iip3[floor].values())
    concl = mf.conclude(study, collect.per_candidate(study, col))
    assert concl["verdicts"][floor]["verdict"] != "feasible (device-level, conditional)"


def test_stress_rejection_is_an_explicit_outcome_not_a_recommendation(study, tmp_path, monkeypatch):
    victim = study.candidates[0]

    def stress(cand, process, temp, run, dev):
        # V_CE over the 1.4 V limit in one hot, slow corner main cell only
        if cand == victim.name and process == "hbt_wcs" and temp == 125.0 and run.run_id.startswith("mn_") \
                and dev == "q1":
            return {"vce": (0.6, 1.6)}
        return None

    col, _ = collect_with(study, tmp_path, monkeypatch, stress_fn=stress)
    assert mf.validate_collection(study, col.cells) == []
    rej = [c for c in col.cells if c["status"] == "rejected_stress"]
    assert rej and all(c["candidate"] == victim.name and c["matrix"] == "main" for c in rej)
    assert any(v["quantity"] == "vce" and v["kind"] == "above" for c in rej for v in c["stress"]["rejecting"])
    concl = mf.conclude(study, collect.per_candidate(study, col))
    assert concl["verdicts"][victim.name]["verdict"] == "infeasible at the declared sizing"
    assert concl["recommendation"]["draw_first"] != victim.name


@pytest.mark.parametrize("kw,match", [
    ({"drop_unit": ("main", "hbt_bcs", -40.0)}, "no unit returned"),
    ({"drop_run": ("main", "mn_f19p45")}, "missing from the log"),
    ({"nan_run": ("leakage", "lk_f21p20")}, "invalid run"),
    ({"drop_run": ("lo_select", "ls_f19p45_m3_rf66")}, "missing from the log"),
    ({"swap_process": "hbt_typ"}, "duplicate unit|undeclared|no unit returned"),
])
def test_corrupt_collections_raise_and_never_reach_a_record(study, tmp_path, monkeypatch, kw, match):
    with pytest.raises(collect.CollectionError, match=match):
        collect_with(study, tmp_path, monkeypatch, **kw)


def test_typical_forced_corners_fail_the_gate(study, tmp_path, monkeypatch):
    col, _ = collect_with(study, tmp_path, monkeypatch,
                          gain_fn=lambda c, p, t, r: default_gain(c, "hbt_typ", 27.0, r))
    problems = mf.validate_collection(study, col.cells)
    assert any("corner switching is not taking effect" in p for p in problems)


def test_duplicate_and_deleted_cells_fail_the_gate(study, tmp_path, monkeypatch):
    col, _ = collect_with(study, tmp_path, monkeypatch)
    assert any("duplicate cell" in p for p in mf.validate_collection(study, col.cells + [dict(col.cells[5])]))
    assert any("missing cell" in p for p in mf.validate_collection(study, col.cells[1:]))
    nan = [dict(c) for c in col.cells]
    nan[3]["gain_db"] = float("nan")
    assert mf.validate_collection(study, nan)


def test_sweep_points_pair_small_signal_check(study, tmp_path, monkeypatch):
    col, _ = collect_with(study, tmp_path, monkeypatch)
    pts = collect.sweep_points(study, col.cells, study.candidates[0].name)
    assert len(pts) == 39 and all(p["ss_ok"] for p in pts)
    assert all(p["status"] == "ok" for p in pts)


def test_summary_and_render_cover_every_section(study, tmp_path, monkeypatch):
    col, _ = collect_with(study, tmp_path, monkeypatch)
    concl = mf.conclude(study, collect.per_candidate(study, col))
    summary = collect.build_summary(study, col, concl)
    manifest = json.loads((BENCH / "testbench" / "tb.json").read_text())
    import datetime as dt
    md = collect.render_md(
        record_id="20000101-000000-abcdef0", study=study, tb=manifest, col=col, summary=summary,
        started=dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc),
        git={"commit": "x", "branch": "b", "dirty": False}, ngspice="ngspice-test", klt_version="klt-test",
        pdk_prov={"fetched_version_file": "v", "model_sha256": {"cornerHBT.lib": "0" * 64}},
        crosscheck={"summary": "n/a"}, converge={c.name: CONV for c in study.candidates},
        claim=manifest["claim"], supersedes="")
    for heading in ("## Intentional reductions", "## LO-drive selection", "## Main matrix", "## LO leakage",
                    "## IIP3", "## Conclusion", "## Provenance"):
        assert heading in md
    assert "no spec row is met" in md or "claims no spec row is met" in md
    assert "Spec rows claimed met**: none" in md


def test_nothing_selectable_still_yields_a_complete_honest_record(study, tmp_path, monkeypatch):
    """Gain that keeps climbing to the sweep end has no plateau: every
    candidate gets 'no acceptable drive', stage 2 is never submitted, every
    declared cell is still accounted for, nothing is recommended."""
    col, fake = collect_with(study, tmp_path, monkeypatch,
                             gain_fn=lambda c, p, t, r: -12.0 + 0.75 * (r.vlo_dbm + 30.0)
                             + PROCESS_OFFSET_DB[p])
    assert {s.matrix for s in fake.submitted} == {"lo_select"} and len(fake.submitted) == 3
    assert all(s["status"] == "no acceptable drive in declared sweep" for s in col.selections.values())
    assert mf.validate_collection(study, col.cells) == []
    concl = mf.conclude(study, collect.per_candidate(study, col))
    assert concl["recommendation"]["draw_first"] is None
    summary = collect.build_summary(study, col, concl)
    manifest = json.loads((BENCH / "testbench" / "tb.json").read_text())
    import datetime as dt
    md = collect.render_md(
        record_id="20000101-000000-abcdef0", study=study, tb=manifest, col=col, summary=summary,
        started=dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc),
        git={"commit": "x", "branch": "b", "dirty": False}, ngspice="n", klt_version="k",
        pdk_prov={"fetched_version_file": "v", "model_sha256": {"cornerHBT.lib": "0" * 64}},
        crosscheck={"summary": "n/a"}, converge={c.name: dict(CONV, drive_kind="trial") for c in study.candidates},
        claim=manifest["claim"], supersedes="")
    assert "no acceptable drive in declared sweep" in md and "draw first: **none**" in md
    assert "no selected drive" in md


# ---------------------------------------------------------------------------
# data provenance is derived from what ran, never asserted
# ---------------------------------------------------------------------------


def _render(study, col, crosscheck_summary="n/a"):
    import datetime as dt
    concl = mf.conclude(study, collect.per_candidate(study, col))
    summary = collect.build_summary(study, col, concl)
    manifest = json.loads((BENCH / "testbench" / "tb.json").read_text())
    return collect.render_md(
        record_id="20000101-000000-abcdef0", study=study, tb=manifest, col=col, summary=summary,
        started=dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc),
        git={"commit": "x", "branch": "b", "dirty": False}, ngspice="n", klt_version="k",
        pdk_prov={"fetched_version_file": "v", "model_sha256": {"cornerHBT.lib": "0" * 64}},
        crosscheck={"summary": crosscheck_summary},
        converge={c.name: dict(CONV, drive_kind="trial") for c in study.candidates},
        claim=manifest["claim"], supersedes="")


def _line(md: str, prefix: str) -> str:
    (line,) = [ln for ln in md.splitlines() if ln.startswith(prefix)]
    return line


def test_provenance_cannot_claim_off_host_or_multi_unit_when_none_ran(study, tmp_path, monkeypatch):
    """Stage 1 only (no drive selected): three single-unit local requests.
    The record must say so and must not claim an off-host / batch /
    multi-unit run, even though the caller's backend is ``batch``."""
    col, fake = collect_with(study, tmp_path, monkeypatch,
                             gain_fn=lambda c, p, t, r: -12.0 + 0.75 * (r.vlo_dbm + 30.0)
                             + PROCESS_OFFSET_DB[p])
    assert {m["backend"] for m in col.klt_meta} == {"local"} and {m["units"] for m in col.klt_meta} == {1}
    exe = collect.execution_provenance(col.klt_meta, col.cells)
    assert exe["off_host_requests"] == [] and exe["multi_unit_requests"] == [] and not exe["fleet_exercised"]
    assert exe["not_simulated_cells"] == {"main": 243, "leakage": 243, "iip3": 117}
    md = _render(study, col)
    prov = _line(md, "- **Data provenance**: ")
    for forbidden in ("ran off-host", "off-host `klt sim`", "backend `batch`", "multi-unit requests"):
        assert forbidden not in prov
    assert "on this host only" in prov and "No multi-unit request was submitted" in prov
    assert "batch path was NOT exercised against the real fleet" in prov
    assert "main 243, leakage 243, iip3 117" in prov and "No stage-2 request was submitted" in prov
    assert "cross-check is local-vs-local" in _line(md, "- **Simulator**: ")


def test_provenance_states_off_host_only_when_a_batch_request_ran(study, tmp_path, monkeypatch):
    col, _ = collect_with(study, tmp_path, monkeypatch)
    exe = collect.execution_provenance(col.klt_meta, col.cells)
    assert exe["fleet_exercised"] and exe["backends"] == ["batch", "local"]
    # 3 candidates x (3 main + 3 leakage) multi-unit requests went to batch
    assert len(exe["off_host_requests"]) == len(exe["multi_unit_requests"]) == 18
    prov = _line(_render(study, col), "- **Data provenance**: ")
    assert "18 ran off-host (backend(s) `batch`)" in prov and "NOT exercised" not in prov
    assert "Not simulated" not in prov


def test_provenance_refuses_requests_without_a_recorded_backend():
    with pytest.raises(collect.CollectionError, match="provenance underivable"):
        collect.execution_provenance([{"request": "r", "units": 1, "matrix": "lo_select", "stage": 1}], [])


def test_crosscheck_summary_names_local_vs_local():
    s = collect.crosscheck_summary(3, 0.0, 1e-3, ["local"])
    assert "LOCAL-vs-LOCAL" in s and "NOT a fleet-vs-local check" in s
    assert "LOCAL-vs-LOCAL" not in collect.crosscheck_summary(3, 0.0, 1e-3, ["batch"])


@pytest.mark.parametrize("md", sorted((BENCH / "records").glob("*.md")), ids=lambda p: p.stem)
def test_committed_records_provenance_matches_what_ran(md):
    """Every committed record's data-provenance and cross-check lines are
    exactly what its own request metadata and cells derive."""
    import gzip
    data = json.loads(md.with_suffix(".json").read_text())
    cells = json.loads(gzip.open(md.parent / data["cells_file"]).read())
    meta = data["provenance"]["klt_requests"]
    snap = BENCH / "netlist-snapshots" / data["record_id"]
    for m in meta:  # the recorded backend is the one in the frozen request
        assert json.loads((snap / f"request_{m['request']}.json").read_text())["backend"] == m["backend"]
    exe = collect.execution_provenance(meta, cells)
    assert data["provenance"]["execution"] == exe
    text = md.read_text()
    assert _line(text, "- **Data provenance**: ") == f"- **Data provenance**: {exe['text']}"
    if not exe["off_host_requests"]:
        assert "off-host `klt sim`" not in text and "ran off-host" not in text
        cc = data["provenance"]["crosscheck"]
        assert cc["kind"] == "local-vs-local" and "LOCAL-vs-LOCAL" in cc["summary"]
        assert cc["summary"] in _line(text, "- Cross-check (klt-body path vs local harness path): ")
