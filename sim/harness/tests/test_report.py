"""report.py on synthetic results: statistics, checks, record rendering, the
append-only writers -- and a cross-check that a freshly rendered harness
record satisfies the repo's evidence-format checker."""

import importlib.util
import json
from pathlib import Path

import pytest

from harness import corners as C
from harness import report as R
from harness.pdk import Pdk
from harness.runner import PointResult
from harness import testbench as T

SIM = Path(__file__).resolve().parents[2]
CHECKER = SIM.parent / ".github" / "scripts" / "check_evidence_formats.py"


def grid(temps=(-40, 27, 125), supplies=(2.25, 2.5, 2.75), corners=("hbt",)):
    return C.build_grid(C.resolve_corners(list(corners)), list(temps), list(supplies))


def results_for(points, fn, status="ok"):
    return [PointResult(point=p, status=status, measurements={"gain": fn(p)}) for p in points]


def gain(p):
    return {"hbt_typ": 10.0, "hbt_bcs": 11.0, "hbt_wcs": 9.0}[p.corner.name] + p.temp_c / 100 + p.vdd


def test_record_id_format_and_append_only_allocation(tmp_path):
    import datetime as dt
    when = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc)
    git = {"short": "abc1234"}
    assert R.format_record_id("abc1234", when) == "20260102-030405-abc1234"
    assert R.allocate_record_id(tmp_path, tmp_path, when, git) == "20260102-030405-abc1234"
    (tmp_path / "20260102-030405-abc1234.md").write_text("x")
    assert R.allocate_record_id(tmp_path, tmp_path, when, git) == "20260102-030406-abc1234"


def test_summarize_min_max_mean_spread():
    pts = grid()
    res = results_for(pts, gain)
    s = R.summarize(res, ["gain", "absent"])
    assert s["gain"]["n"] == 27
    assert s["gain"]["min"] == min(gain(p) for p in pts)
    assert s["gain"]["min_at"].startswith("hbt_wcs_-40c_2.25v")
    assert s["gain"]["spread_pct"] == pytest.approx(
        (s["gain"]["max"] - s["gain"]["min"]) / abs(s["gain"]["mean"]) * 100)
    assert s["absent"] == {"n": 0}


def test_failed_points_are_excluded_from_summary():
    pts = grid()
    res = results_for(pts, gain)
    res[0] = PointResult(point=pts[0], status="failed")
    assert R.summarize(res, ["gain"])["gain"]["n"] == 26


def test_axis_sensitivity_sees_every_swept_axis_and_flags_unswept():
    sens = R.axis_sensitivity(results_for(grid(), gain), ["gain"])["gain"]
    assert all(sens[a]["levels"] >= 2 and sens[a]["min_pct"] > 0 for a in ("process", "temperature", "supply"))
    single = R.axis_sensitivity(results_for(grid(temps=(27,), supplies=(2.5,)), gain), ["gain"])["gain"]
    assert single["temperature"]["levels"] == 1 and single["supply"]["levels"] == 1


def test_sabotaged_corners_trip_the_process_sensitivity_floor():
    """The harness negative control, on synthetic data: a runner that simulates
    typical everywhere produces zero process spread, and the floor fails."""
    checks = {"gain": {"min_spread_pct_by_axis": {"process": 0.01}}}

    def run(corner_list):
        pts = C.build_grid(corner_list, [27], [2.5])
        # model result depends only on the *sections* actually simulated
        res = [PointResult(point=p, status="ok",
                           measurements={"gain": {"hbt_typ": 10.0, "hbt_bcs": 11.0, "hbt_wcs": 9.0}[p.corner.sections[0]]})
               for p in pts]
        summ = R.summarize(res, ["gain"])
        return R.evaluate_checks(checks, res, summ, R.axis_sensitivity(res, ["gain"]))

    real = C.resolve_corners(["hbt"])
    assert run(real) == []
    failures = run(C.sabotage(real))
    assert failures and failures[0]["kind"] == "min_spread_pct_by_axis" and failures[0]["axis"] == "process"


def test_evaluate_checks_limits():
    pts = grid()
    res = results_for(pts, gain)
    summ = R.summarize(res, ["gain"])
    ok = R.evaluate_checks({"gain": {"min": 0, "max": 100, "max_spread_pct": 1000}}, res, summ)
    assert ok == []
    bad = R.evaluate_checks({"gain": {"min": 11.5, "max": 12.0}}, res, summ)
    kinds = {f["kind"] for f in bad}
    assert kinds == {"min", "max"}
    assert all("gain" in R.describe_failure(f) for f in bad)


def test_unswept_axis_is_a_failure_unless_allowed():
    pts = grid(temps=(27,))
    res = results_for(pts, gain)
    summ = R.summarize(res, ["gain"])
    sens = R.axis_sensitivity(res, ["gain"])
    chk = {"gain": {"min_spread_pct_by_axis": {"temperature": 0.1}}}
    assert R.evaluate_checks(chk, res, summ, sens)[0]["note"].startswith("axis was never swept")
    assert R.evaluate_checks(chk, res, summ, sens, allow_unswept_axes=True) == []


def make_tb(tmp_path, corners=("hbt",)):
    bench = tmp_path / "exp" / "testbench"
    bench.mkdir(parents=True)
    (bench / "d.spice").write_text("R1 a b 1\n")
    (bench / "tb.json").write_text(json.dumps(
        {"netlist": "d.spice", "measure": {"gain": "1"}, "nominal_supply_v": 2.5,
         "corners": list(corners)}))
    return T.load(tmp_path / "exp")


def pt(name, temp, vdd):
    return C.PvtPoint(C.CORNERS[name], temp, vdd)


def test_matrix_conformance(tmp_path):
    tb = make_tb(tmp_path)
    full = R.matrix_conformance(tb, grid())
    assert full["full"] and full["missing"] == [] and full["covered_points"] == 27
    thin = R.matrix_conformance(tb, grid(corners=("hbt_typ",), temps=(27,), supplies=(2.5,)))
    assert not thin["full"] and thin["covered_points"] == 1 and len(thin["missing_combinations"]) == 26


def test_diagonal_points_are_incomplete_and_list_missing_combos(tmp_path):
    tb = make_tb(tmp_path)
    diag = [pt("hbt_typ", -40, 2.25), pt("hbt_bcs", 27, 2.5), pt("hbt_wcs", 125, 2.75)]
    m = R.matrix_conformance(tb, diag)
    assert not m["full"]
    assert m["covered_points"] == 3 and m["required_points"] == 27
    assert len(m["missing_combinations"]) == 24
    assert ["hbt_typ", 27.0, 2.5] in m["missing_combinations"]
    assert "missing" in m["missing"][0] and "hbt_typ/27 C/2.50 V" in m["missing"][0]


def test_removing_one_combination_is_incomplete_though_axes_are_covered(tmp_path):
    tb = make_tb(tmp_path)
    pts = grid()
    dropped = pts[13]
    m = R.matrix_conformance(tb, pts[:13] + pts[14:])
    assert not m["full"]
    assert m["missing_combinations"] == [[dropped.corner.name, dropped.temp_c, dropped.vdd]]


def test_duplicates_do_not_fill_gaps(tmp_path):
    tb = make_tb(tmp_path)
    pts = grid()
    m = R.matrix_conformance(tb, pts[1:] + [pts[1]])
    assert not m["full"] and m["covered_points"] == 26


def test_unexpected_process_names_do_not_satisfy_declared_corners(tmp_path):
    tb = make_tb(tmp_path)
    # three arbitrary process names (the old len(process) >= 3 rule) in place of hbt_*
    pts = grid(corners=("tt", "ff", "ss"))
    m = R.matrix_conformance(tb, pts)
    assert not m["full"] and m["covered_points"] == 0
    assert len(m["unexpected_combinations"]) == 27
    assert any("unexpected" in x for x in m["missing"])
    # a full grid plus extras is still full coverage; the extras are reported
    extra = R.matrix_conformance(tb, grid() + grid(corners=("tt",)))
    assert extra["full"] and len(extra["unexpected_combinations"]) == 9


def test_explicit_required_override_is_recorded(tmp_path):
    tb = make_tb(tmp_path)
    req = [("hbt_typ", 27, 2.5)]
    m = R.matrix_conformance(tb, [pt("hbt_typ", 27, 2.5)], required=req)
    assert m["full"] and m["required_source"] == "override" and m["required_points"] == 1
    assert R.matrix_conformance(tb, grid())["required_source"] == "testbench"


class FakePdk(Pdk):
    """A Pdk with a stated revision: the real ``Pdk.version`` reads a SOURCES
    file that the synthetic tree does not have and would print 'unknown', which
    the evidence checker rejects for any non-grandfathered record (#85)."""

    @property
    def version(self) -> str:
        return "fake-rev-0"


ART = {
    "status": "verified", "upstream_repo": "https://example.invalid/pdk", "upstream_tag": "v0",
    "upstream_commit": "a" * 40, "manifest": "sim/pdk-artifact.json", "manifest_sha256": "b" * 64,
    "files_verified": 4, "method": "test",
}


def build_synthetic_record(tmp_path, record_id="20260101-000000-abc1234", status_points=None):
    exp = tmp_path / "sim" / "synthetic-bench"
    tbdir = exp / "testbench"
    tbdir.mkdir(parents=True)
    # A bench with records/ must carry a cold-start README (check_bench_readmes, #85).
    (exp / "README.md").write_text("# synthetic-bench\n\n## Cold start\n\n```\ntrue\n```\n")
    (tbdir / "d.spice").write_text("R1 a b 1k\n")
    (tbdir / "tb.json").write_text(json.dumps({
        "name": "synthetic", "netlist": "d.spice", "measure": {"gain": "1"},
        "nominal_supply_v": 2.5, "corners": ["hbt"], "claim": "synthetic claim",
        "checks": {"gain": {"min_spread_pct_by_axis": {"process": 0.01, "temperature": 0.01, "supply": 0.01}}},
        "evidence": {"data_provenance": "simulated", "notes": ["a note"]},
    }))
    tb = T.load(exp)
    pts = grid()
    res = results_for(pts, gain)
    pdk = FakePdk(name="fake", path=tmp_path, variant="v", source="test", model_lib_rel="m.lib")
    rec = R.build_record(tb, pdk, pts, res, "ngspice-0", tmp_path, record_id,
                         "2026-01-01T00:00:00+00:00", 1.234,
                         git={"short": "abc1234", "branch": "b", "dirty": False}, pdk_artifact=ART)
    return exp, tb, pts, rec


def test_build_and_render_record(tmp_path):
    exp, tb, pts, rec = build_synthetic_record(tmp_path)
    assert rec["status"] == "pass" and rec["matrix"]["full"]
    assert rec["grid"]["points"] == rec["grid"]["points_ok"] == 27
    md = R.render_markdown(rec)
    for needle in ("# 20260101-000000-abc1234", "**Status**: pass", "**Experiment**: synthetic-bench",
                   "27 point full-factorial grid", "Full PVT matrix.", "- **Data provenance**: simulated",
                   "- **Note**: a note", "**PASS**", "`gain`: min", "## Environment"):
        assert needle in md


def test_record_is_error_when_a_point_failed(tmp_path):
    exp, tb, pts, rec = build_synthetic_record(tmp_path)
    res = results_for(pts, gain)
    res[3] = PointResult(point=pts[3], status="failed")
    rec2 = R.build_record(tb, FakePdk("f", tmp_path, "v", "t", "m"), pts, res, "n", tmp_path, "id", "t", 1.0,
                          git={"short": "x", "branch": "b", "dirty": False}, pdk_artifact=ART)
    assert rec2["status"] == "error" and rec2["grid"]["points_ok"] == 26


def test_subset_run_states_gaps_and_justification(tmp_path):
    exp, tb, _, _ = build_synthetic_record(tmp_path)
    pts = grid(corners=("hbt_typ",), temps=(27,), supplies=(2.5,))
    rec = R.build_record(tb, FakePdk("f", tmp_path, "v", "t", "m"), pts, results_for(pts, gain), "n", tmp_path,
                         "id", "t", 1.0, subset_reason="because", git={"short": "x", "branch": "b", "dirty": False}, pdk_artifact=ART)
    md = R.render_markdown(rec)
    assert "Subset of the mandated PVT matrix" in md and "Justification: because" in md
    assert "full-factorial" not in md and "Full PVT matrix." not in md
    assert "1 point grid (subset" in md


def test_diagonal_record_renders_as_subset_and_failed_points_stay_error(tmp_path):
    exp, tb, _, _ = build_synthetic_record(tmp_path)
    pts = [pt("hbt_typ", -40, 2.25), pt("hbt_bcs", 27, 2.5), pt("hbt_wcs", 125, 2.75)]
    res = results_for(pts, gain)
    res[0] = PointResult(point=pts[0], status="failed")
    rec = R.build_record(tb, FakePdk("f", tmp_path, "v", "t", "m"), pts, res, "n", tmp_path,
                         "id", "t", 1.0, git={"short": "x", "branch": "b", "dirty": False}, pdk_artifact=ART)
    assert rec["status"] == "error" and rec["grid"]["points_ok"] == 2
    assert not rec["matrix"]["full"]
    md = R.render_markdown(rec)
    assert "full-factorial" not in md and "Subset of the mandated PVT matrix" in md


def test_writers_are_append_only(tmp_path):
    exp, tb, pts, rec = build_synthetic_record(tmp_path)
    md = R.write_record(rec, exp)
    snap = R.write_netlist_snapshot(tb, exp, rec["record_id"])
    assert md.read_text().startswith("# 20260101-000000-abc1234")
    assert f"sha256     : {tb.netlist_sha256}" in snap.read_text()
    before = md.read_bytes()
    with pytest.raises(R.RecordExists):
        R.write_record(rec, exp)
    with pytest.raises(R.RecordExists):
        R.write_netlist_snapshot(tb, exp, rec["record_id"])
    assert md.read_bytes() == before


def test_rendered_harness_record_satisfies_the_evidence_format_checker(tmp_path):
    """Renderer and checker must agree: a record freshly produced by the
    harness, with its snapshot and one log per grid point, passes."""
    spec = importlib.util.spec_from_file_location("check_evidence_formats", CHECKER)
    chk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(chk)

    exp, tb, pts, rec = build_synthetic_record(tmp_path)
    R.write_record(rec, exp)
    R.write_netlist_snapshot(tb, exp, rec["record_id"])
    logs = exp / "corners" / rec["record_id"]
    logs.mkdir(parents=True)
    for p in pts:
        (logs / f"{p.corner_id}.log").write_text("log\n")
    assert chk.check_format(tmp_path).items == []

    (logs / f"{pts[0].corner_id}.log").unlink()          # negative control
    assert any("missing declared corner identity" in m for m in chk.check_format(tmp_path).items)


def test_rendered_subset_record_satisfies_the_evidence_format_checker(tmp_path):
    """The subset wording ('N point grid (subset of ...)') must parse too, or
    the first committed subset record fails the evidence-formats CI job."""
    spec = importlib.util.spec_from_file_location("check_evidence_formats", CHECKER)
    chk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(chk)

    exp, tb, _, _ = build_synthetic_record(tmp_path)
    pts = grid(corners=("hbt_typ",), temps=(27,), supplies=(2.5,))
    rec = R.build_record(tb, FakePdk("f", tmp_path, "v", "t", "m"), pts, results_for(pts, gain), "n", tmp_path,
                         "20260101-000000-abc1234", "2026-01-01T00:00:00+00:00", 1.0, subset_reason="because",
                         git={"short": "abc1234", "branch": "b", "dirty": False}, pdk_artifact=ART)
    assert not rec["matrix"]["full"]
    assert chk.declared_native_matrix(R.render_markdown(rec)) == (["hbt_typ"], [27.0], [2.5], 1, 1)
    R.write_record(rec, exp)
    R.write_netlist_snapshot(tb, exp, rec["record_id"])
    logs = exp / "corners" / rec["record_id"]
    logs.mkdir(parents=True)
    (logs / f"{pts[0].corner_id}.log").write_text("log\n")
    assert chk.check_format(tmp_path).items == []


def test_record_carries_verified_identity_separate_from_install_marker(tmp_path):
    exp, tb, pts, rec = build_synthetic_record(tmp_path)
    env = rec["environment"]
    assert env["pdk_artifact"]["upstream_commit"] == "a" * 40 and env["pdk"]["version"] == "fake-rev-0"
    md = R.render_markdown(rec)
    assert "(install marker: fake-rev-0, via test)" in md
    assert "- PDK artifact: **verified**" in md and "a" * 40 in md and "b" * 64 in md
    assert json.loads(json.dumps(rec))["environment"]["pdk_artifact"] == ART  # JSON form round-trips


@pytest.mark.parametrize("bad", [
    None, {}, {**ART, "status": "unverified"}, {**ART, "upstream_commit": "a" * 7},
    {**ART, "manifest_sha256": "zz"}, "verified",
])
def test_record_refused_without_verified_identity(tmp_path, bad):
    from harness.pdkartifact import ArtifactNotVerified
    exp, tb, pts, rec = build_synthetic_record(tmp_path)
    with pytest.raises(ArtifactNotVerified):
        R.build_record(tb, FakePdk("f", tmp_path, "v", "t", "m"), pts, results_for(pts, gain), "n", tmp_path,
                       "id", "t", 1.0, git={"short": "x", "branch": "b", "dirty": False}, pdk_artifact=bad)


def test_markerless_unknown_install_still_passes_checker_with_verified_identity(tmp_path):
    """Markerless install -> 'install marker: unknown', yet the record passes
    because it carries the hash-verified commit (the case #85 left open)."""
    spec = importlib.util.spec_from_file_location("check_evidence_formats", CHECKER)
    chk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(chk)
    exp, tb, pts, rec = build_synthetic_record(tmp_path)
    rec["environment"]["pdk"]["version"] = "unknown"
    R.write_record(rec, exp)
    R.write_netlist_snapshot(tb, exp, rec["record_id"])
    logs = exp / "corners" / rec["record_id"]
    logs.mkdir(parents=True)
    for p in pts:
        (logs / f"{p.corner_id}.log").write_text("log\n")
    assert "install marker: unknown" in (exp / "records" / f"{rec['record_id']}.md").read_text()
    assert chk.check_format(tmp_path).items == []
