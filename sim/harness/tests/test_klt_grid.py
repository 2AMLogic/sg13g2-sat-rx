"""Issue #134: `harness.cli run` routes a multi-point grid through `klt sim`.

No ngspice, no PDK, no network: every `klt sim` submission is a stub that
writes a synthetic report + per-corner logs (conftest.py additionally makes
any real submission fail the test). Covered: backend resolution, the local
--jobs guard, request/body generation, report grading (complete, missing,
errored and failed points), the no-fallback failure path, the off-host model
gate, and the execution provenance in the record's Environment section.
"""

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness import cli, klt_driver as kd, report as R
from harness import corners as C
from harness import testbench as T
from harness.runner import PointResult, compose_deck

SIM = Path(__file__).resolve().parents[2]
REAL_SUBMIT = kd.submit  # captured before conftest's autouse guard patches it
COMMIT = "a" * 40
IDENTITY = {"status": "verified", "verified_scope": "offhost-job-model-inputs",
            "upstream_repo": "r", "upstream_tag": "t", "upstream_commit": COMMIT,
            "manifest": "sim/pdk-artifact.json", "manifest_sha256": "b" * 64,
            "files_verified": 4, "jobs": [{"job_id": "job-2.25"}]}


@pytest.fixture
def bench(tmp_path):
    """A copy of the mixer bench's testbench/ in a scratch experiment dir."""
    exp = tmp_path / "mixer-conversion-iip3"
    shutil.copytree(SIM / "mixer-conversion-iip3" / "testbench", exp / "testbench")
    return T.load(exp)


@pytest.fixture
def pdk(tmp_path):
    root = tmp_path / "pdk" / "ihp-sg13g2"
    return SimpleNamespace(path=root, model_lib=root / "libs.tech/ngspice/models/cornerHBT.lib",
                           design_include=None, version="0.3.0", variant="ihp-sg13g2",
                           provenance=lambda: {"name": "sg13g2", "version": "0.3.0"})


def _grid(tb, corner_names=("hbt",)):
    return C.build_grid(C.resolve_corners(list(corner_names)), tb.temperatures_c,
                        C.supply_points(tb.nominal_supply_v, tb.supply_tolerance))


def _value(tb, name, process, temp, vdd):
    return 1.0 + list(tb.measure).index(name) + {"hbt_typ": 0.0, "hbt_bcs": 0.1, "hbt_wcs": 0.2}[process] \
        + temp / 100.0 + vdd


def fake_submit(tb, *, drop=(), errored=(), nolog=(), nomeas=(), job_env=None):
    """Stub for klt_driver.submit: one synthetic corner per (process, temp)."""
    def go(job, backend, klt_cmd="klt"):
        req = json.loads(job.request.read_text())
        assert backend == "batch" and req["backend"] == "batch"
        out = job.request.parent / f"out_{job.key}"
        out.mkdir(parents=True, exist_ok=True)
        corners = []
        for process in req["corners"]["process"]:
            for temp in req["corners"]["temperature_c"]:
                cid = f"{process}_{temp:g}c_{job.supply_v:.2f}v"
                if cid in drop:
                    continue
                corner = {"process": process, "temperature_c": temp, "runtime_s": 1.5,
                          "status": "error" if cid in errored else "pass", "artifacts": {}}
                if cid not in nolog:
                    lines = [f"m_{n} = {_value(tb, n, process, temp, job.supply_v):.10e}"
                             for n in tb.measure if not (cid in nomeas and n == next(iter(tb.measure)))]
                    log = out / f"{cid}.log"
                    log.write_text("ngspice banner\n" + "\n".join(lines) + "\n")
                    corner["artifacts"]["log"] = str(log)
                else:
                    corner["diagnostics"] = [{"code": "batch_job_failed"}]
                corners.append(corner)
        env = {"engine": "ngspice", "engine_version": "46",
               "remote": {"job_id": f"job-{job.supply_v:.2f}", "provider": "aws-batch",
                          "runner_klt_version": "0.7.0", "client_klt_version": "0.7.0",
                          "runner_compatibility": "match"},
               "staged_model_inputs": [{"name": "cornerHBT.lib", "sha256": "c" * 64}]}
        env.update(job_env or {})
        job.report = {"status": "pass", "corners": corners, "environment": env}
        job.report_path.write_text(json.dumps(job.report))
        job.exit_code = 0
        return job
    return go


# ---------------------------------------------------------------------------
# backend resolution and the local --jobs guard
# ---------------------------------------------------------------------------

def test_backend_defaults_multi_point_to_batch_single_point_to_local():
    assert cli.resolve_backend(None, 27) == "batch"
    assert cli.resolve_backend(None, 1) == "local"
    assert cli.resolve_backend("local", 27) == "local"
    assert cli.resolve_backend("batch", 1) == "batch"


def test_local_jobs_guard():
    assert cli.local_jobs_problem(3, 9) is not None
    assert cli.local_jobs_problem(2, 9) is None
    assert cli.local_jobs_problem(1, 27) is None
    assert cli.local_jobs_problem(8, 1) is None  # one point: one process whatever --jobs says


# ---------------------------------------------------------------------------
# request / body generation
# ---------------------------------------------------------------------------

def test_one_request_per_supply_with_every_process_and_temperature(bench, pdk, tmp_path):
    jobs = kd.build_jobs(bench, pdk, _grid(bench), tmp_path / "w", "batch", 900)
    assert [j.key for j in jobs] == ["2.25v", "2.50v", "2.75v"]
    req = json.loads(jobs[1].request.read_text())
    assert req["backend"] == "batch" and req["netlist"] == "body_2.50v.spice"
    assert req["corners"] == {"process": ["hbt_typ", "hbt_bcs", "hbt_wcs"],
                              "temperature_c": [-40.0, 27.0, 125.0]}
    assert req["models"] == {"pdk": "ihp-sg13g2", "lib": "libs.tech/ngspice/models/cornerHBT.lib"}
    assert req["options"]["stage_model_inputs"] is True and req["options"]["timeout_s"] == 900
    assert req["measurements"][0]["name"] == kd.HARNESS_SENTINEL_NAME
    # valid inside a bench's own `tran ... tstart` window too (no AT=2p)
    assert req["measurements"][0]["spice"] == ".meas tran harness_rail_v AVG v(vdd)"


def test_body_carries_the_same_control_block_as_the_local_deck(bench, pdk, tmp_path):
    point = _grid(bench)[0]
    body = kd.harness_body(bench, point.vdd)
    deck = compose_deck(bench, SimpleNamespace(design_include=None, model_lib=pdk.model_lib,
                                               name="sg13g2", variant="v", version="x"), point)
    tail = lambda text: text[text.index(".control"):].replace(".end\n", "")  # noqa: E731
    assert tail(body) == tail(deck)
    assert f".param vdd_val={point.vdd!r}" in body
    for forbidden in (".lib", ".temp", ".end\n"):
        assert forbidden not in body.replace(".endc", "")


def test_deck_reading_temp_c_gets_one_request_per_supply_and_temperature(bench, pdk, tmp_path):
    bench.params["rt"] = "{1k*(1+temp_c/1000)}"
    assert kd.deck_reads_temp_c(bench)
    jobs = kd.build_jobs(bench, pdk, _grid(bench), tmp_path / "w", "batch", 900)
    assert len(jobs) == 9 and jobs[0].key == "2.25v_-40c"
    assert ".param temp_c=-40.0" in jobs[0].body.read_text()
    assert json.loads(jobs[0].request.read_text())["corners"]["temperature_c"] == [-40.0]


def test_unexpressible_corner_sets_are_refused():
    multi = C.Corner("mix", ("tt", "res_typ"), "two sections")
    with pytest.raises(kd.KltGridError, match="exactly one"):
        kd.klt_process_names([C.PvtPoint(corner=multi, temp_c=27.0, vdd=1.0)])
    pts = [C.PvtPoint(corner=c, temp_c=27.0, vdd=1.0)
           for c in C.sabotage(C.resolve_corners(["hbt"]))]
    with pytest.raises(kd.KltGridError, match="told apart"):
        kd.klt_process_names(pts)


# ---------------------------------------------------------------------------
# grading the returned reports
# ---------------------------------------------------------------------------

def test_complete_grid_parses_into_ok_point_results(bench, pdk, tmp_path):
    points = _grid(bench)
    grid = kd.run_grid_klt(bench, pdk, points, tmp_path / "w", submit_fn=fake_submit(bench))
    assert [r.point.corner_id for r in grid.results] == [p.corner_id for p in points]
    assert all(r.status == "ok" for r in grid.results)
    r = grid.results[0]
    name = next(iter(bench.measure))
    assert r.measurements[name] == pytest.approx(_value(bench, name, r.point.corner.name,
                                                        r.point.temp_c, r.point.vdd))
    assert set(grid.logs) == {p.corner_id for p in points}
    ex = grid.execution("batch", "klt 0.7.0")
    assert [j["job_id"] for j in ex["jobs"]] == ["job-2.25", "job-2.50", "job-2.75"]
    assert ex["backend"] == "batch" and ex["via"] == "klt sim"
    assert grid.engine_versions() == ["46"]


def test_incomplete_or_failed_remote_points_are_explicit(bench, pdk, tmp_path):
    points = _grid(bench)
    ids = [p.corner_id for p in points]
    stub = fake_submit(bench, drop={ids[0]}, errored={ids[1]}, nolog={ids[2]}, nomeas={ids[3]})
    grid = kd.run_grid_klt(bench, pdk, points, tmp_path / "w", submit_fn=stub)
    by = {r.point.corner_id: r for r in grid.results}
    assert len(grid.results) == len(points)
    assert by[ids[0]].status == "error" and "no result" in by[ids[0]].message
    assert by[ids[1]].status == "error" and "'error'" in by[ids[1]].message
    assert by[ids[2]].status == "error" and "no log" in by[ids[2]].message
    assert by[ids[3]].status == "failed" and by[ids[3]].missing == [next(iter(bench.measure))]
    assert all(by[i].status == "ok" for i in ids[4:])
    assert grid.logs[ids[0]].startswith("KLT SIM:")  # every point still gets a log


def test_a_request_without_a_report_raises_and_never_falls_back(bench, pdk, tmp_path, monkeypatch):
    def broken(job, backend, klt_cmd="klt"):
        raise kd.KltGridError(f"klt sim returned no usable report for {job.key} (exit 1)")

    monkeypatch.setattr(cli, "run_grid", lambda *a, **k: pytest.fail("local fallback"))
    with pytest.raises(kd.KltGridError, match="no usable report"):
        kd.run_grid_klt(bench, pdk, _grid(bench), tmp_path / "w", submit_fn=broken)


def _fake_klt(tmp_path, stdout: str, code: int) -> str:
    script = tmp_path / "fake_klt.py"
    script.write_text(f"import sys\nsys.stdout.write({stdout!r})\nsys.stderr.write('boom')\nsys.exit({code})\n")
    return f"{sys.executable} {script}"


def test_submit_raises_on_klt_failure_and_accepts_exit_4_reports(tmp_path):
    req = tmp_path / "request_x.json"
    req.write_text("{}")
    job = kd.KltJob(key="x", supply_v=2.5, temp_c=None, request=req, body=tmp_path / "b.spice",
                    report_path=tmp_path / "report_x.json")
    with pytest.raises(kd.KltGridError, match="boom"):
        REAL_SUBMIT(job, "batch", _fake_klt(tmp_path, "", 1))
    payload = json.dumps({"status": "error", "corners": [], "environment": {}})
    REAL_SUBMIT(job, "batch", _fake_klt(tmp_path, payload, 4))
    assert job.exit_code == 4 and job.report["status"] == "error"


# ---------------------------------------------------------------------------
# cli run: routing, provenance, refusals
# ---------------------------------------------------------------------------

@pytest.fixture
def run(monkeypatch, bench, pdk, capsys):
    monkeypatch.setattr(cli, "load", lambda _e: bench)
    monkeypatch.setattr(cli, "_resolve_pdk", lambda: pdk)
    monkeypatch.setattr(cli, "ngspice_version", lambda: "ngspice-46")
    monkeypatch.setattr(cli.toolchain_mod, "load_pins", lambda sim: {})
    monkeypatch.setattr(cli.pdkartifact, "verified_identity", lambda p, s: dict(IDENTITY, jobs=None,
                                                                                  verified_scope=None))
    monkeypatch.setattr(cli.klt_driver, "klt_client_version", lambda cmd: "klt 0.7.0")
    calls = SimpleNamespace(local=0, klt=[])

    def local(*a, **k):
        calls.local += 1
        return [PointResult(point=p, status="ok", measurements={n: 1.0 for n in bench.measure})
                for p in a[2]]

    monkeypatch.setattr(cli, "run_grid", local)

    real = kd.run_grid_klt

    def go(*argv, stub=None):
        def klt(*a, **k):
            calls.klt.append(k.get("backend"))
            return real(*a, submit_fn=stub or fake_submit(bench), **k)

        monkeypatch.setattr(cli.klt_driver, "run_grid_klt", klt)
        rc = cli.main(["run", "mixer-conversion-iip3", *argv])
        return rc, calls, capsys.readouterr()

    return go


def test_multi_point_run_defaults_to_klt_batch(run, bench):
    rc, calls, out = run("--corners", "hbt", "--no-write")
    assert calls.klt == ["batch"] and calls.local == 0
    assert "backend: batch (27 point(s))" in out.out
    scratch = bench.experiment_dir / "corners" / "_scratch"
    assert len(list(scratch.glob("*.log"))) == 27
    assert not (bench.experiment_dir / "records").exists()


def test_backend_local_forces_the_local_path(run):
    rc, calls, out = run("--corners", "hbt", "--no-write", "--backend", "local")
    assert calls.local == 1 and calls.klt == []


def test_single_point_stays_local(run, bench):
    bench.temperatures_c = (27.0,)
    bench.supply_tolerance = 0.0
    rc, calls, out = run("--corners", "hbt_typ", "--no-write", "--smoke-subset")
    assert calls.local == 1 and calls.klt == [] and "backend: local (1 point(s))" in out.out


def test_local_multi_point_rejects_jobs_above_two(run):
    rc, calls, out = run("--corners", "hbt", "--no-write", "--backend", "local", "--jobs", "4")
    assert rc == 2 and calls.local == 0 and "--jobs" in out.err


def test_sabotage_cannot_go_to_batch(run):
    rc, calls, out = run("--corners", "hbt", "--sabotage")
    assert rc == 2 and calls.klt == [] and calls.local == 0 and "--backend local" in out.err


def test_batch_write_records_backend_job_ids_and_logs(run, bench, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.pdkartifact, "offhost_identity",
                        lambda jobs, sim: seen.setdefault("jobs", jobs) and IDENTITY)
    rc, calls, out = run("--corners", "hbt")
    assert rc == 0, out.err
    assert [label for label, _ in seen["jobs"]] == ["report_2.25v.json", "report_2.50v.json",
                                                   "report_2.75v.json"]
    (record,) = (bench.experiment_dir / "records").glob("*.md")
    rid = record.stem
    logs = sorted(p.name for p in (bench.experiment_dir / "corners" / rid).iterdir())
    assert len(logs) == 27 and all(n.endswith(".log") for n in logs)
    text = record.read_text()
    assert "**Status**: pass" in text
    assert "- Execution: backend `batch` via klt sim (client `klt 0.7.0`), 3 request(s)" in text
    assert "job `job-2.25`" in text and "job `job-2.75`" in text
    assert "- ngspice: ngspice-46 via klt sim batch (recording host: ngspice-46)" in text
    assert f"- PDK artifact: **verified** -- upstream r t commit `{COMMIT}`" in text
    assert "as the model inputs staged to off-host klt job(s)" in text


def test_batch_write_refused_when_offhost_models_unverified(run, bench, monkeypatch):
    def refuse(jobs, sim):
        raise cli.pdkartifact.ArtifactNotVerified("runner_compatibility is 'skew'")

    monkeypatch.setattr(cli.pdkartifact, "offhost_identity", refuse)
    rc, calls, out = run("--corners", "hbt")
    assert rc == 3 and "skew" in out.err
    assert not (bench.experiment_dir / "records").exists()
    assert not (bench.experiment_dir / "corners").exists()


def test_batch_submit_failure_records_nothing(run, bench):
    def broken(job, backend, klt_cmd="klt"):
        raise kd.KltGridError("klt sim returned no usable report for 2.25v (exit 1, backend batch): "
                              "no batch credentials")

    rc, calls, out = run("--corners", "hbt", stub=broken)
    assert rc == 1 and calls.local == 0
    assert "no batch credentials" in out.err and "no local fallback" in out.err
    assert not (bench.experiment_dir / "records").exists()
    assert not (bench.experiment_dir / "corners").exists()


def test_incomplete_batch_grid_is_an_error_record_not_a_pass(run, bench, monkeypatch):
    monkeypatch.setattr(cli.pdkartifact, "offhost_identity", lambda jobs, sim: IDENTITY)
    cid = _grid(bench)[0].corner_id
    rc, calls, out = run("--corners", "hbt", stub=fake_submit(bench, drop={cid}))
    assert rc == 1 and f"POINT ERROR: {cid}" in out.err
    (record,) = (bench.experiment_dir / "records").glob("*.md")
    assert "**Status**: error" in record.read_text()


def test_local_records_name_their_backend(bench, pdk, tmp_path):
    env = R.environment(pdk, "ngspice-46", SIM.parent, git={"short": "x"},
                        pdk_artifact=dict(IDENTITY, verified_scope=None))
    assert env["execution"] == {"backend": "local"}
    assert R._execution_line(env["execution"]).startswith("- Execution: backend `local`")


def test_runner_version_check_is_passed_through(bench, pdk, tmp_path):
    (job, *_) = kd.build_jobs(bench, pdk, _grid(bench), tmp_path / "w", "batch", 900, "warn")
    assert json.loads(job.request.read_text())["batch"] == {"runner_version_check": "warn"}
    (job, *_) = kd.build_jobs(bench, pdk, _grid(bench), tmp_path / "v", "batch", 900)
    assert "batch" not in json.loads(job.request.read_text())


def test_no_stage_models_is_refused_for_a_record(run, bench):
    rc, calls, out = run("--corners", "hbt", "--no-stage-models")
    assert rc == 3 and calls.klt == [] and "--no-write" in out.err
    rc, calls, out = run("--corners", "hbt", "--no-stage-models", "--no-write")
    assert calls.klt == ["batch"]
    req = json.loads(next((bench.experiment_dir / "_build").glob("klt-*/request_2.50v.json")).read_text())
    assert "stage_model_inputs" not in req["options"]
