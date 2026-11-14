from types import SimpleNamespace

import pytest

from harness import klt_driver as kd


def test_request_shape_and_options():
    r = kd.klt_request("b.spice", ["a", "b"], (27.0,), "batch", 60, sentinel_name="s_v",
                       sentinel_node="v(vdd)", runner_version_check="warn")
    assert r["measurements"][0]["spice"] == ".meas tran s_v FIND v(vdd) AT=2p"
    assert r["options"] == {"timeout_s": 60, "keep_artifacts": True, "stage_model_inputs": True}
    assert r["batch"] == {"runner_version_check": "warn"}
    assert r["corners"] == {"process": ["a", "b"], "temperature_c": [27.0]}


def test_request_local_has_no_batch_block_and_staging_off():
    r = kd.klt_request("b.spice", ["a"], [27.0], "local", 60, sentinel_name="s", sentinel_node="v(x)",
                       stage_models=False, runner_version_check="warn")
    assert "batch" not in r and "stage_model_inputs" not in r["options"]


def test_body_supply(tmp_path):
    p = tmp_path / "b.spice"
    p.write_text("* x\n.param vdd_val=2.25\n")
    assert kd.body_supply(p) == 2.25
    p.write_text("nothing\n")
    with pytest.raises(SystemExit):
        kd.body_supply(p)


def test_pdk_provenance(tmp_path):
    m = tmp_path / "models"
    m.mkdir()
    (m / "a.lib").write_text("a")
    pdk = SimpleNamespace(model_lib=m / "a.lib", path=tmp_path)
    prov = kd.pdk_provenance(pdk, ("a.lib", "missing.lib"))
    assert list(prov["model_sha256"]) == ["a.lib"] and prov["fetched_version_file"] is None
    (tmp_path / ".fetched-version").write_text("v1\n")
    assert kd.pdk_provenance(pdk, ("a.lib",))["fetched_version_file"] == "v1"


def _fake_run(monkeypatch, rc, stdout, stderr=""):
    calls = []

    def run(cmd, stdout=None, stderr=None, text=None, **kw):  # noqa: ARG001
        calls.append(cmd)
        stdout.write(_fake_run.out)
        return SimpleNamespace(returncode=rc, stderr=_fake_run.err)

    _fake_run.out, _fake_run.err = stdout, stderr
    monkeypatch.setattr(kd.subprocess, "run", run)
    return calls


def test_submit_request_reuses_report_with_corners(tmp_path, monkeypatch):
    report = tmp_path / "report_k.json"
    report.write_text('{"corners": []}')
    calls = _fake_run(monkeypatch, 0, "{}")
    assert kd.submit_request(tmp_path / "r.json", report, "k", "batch", "klt", tmp_path) == report
    assert calls == []


def test_submit_request_runs_and_logs_stderr(tmp_path, monkeypatch):
    report = tmp_path / "report_k.json"
    calls = _fake_run(monkeypatch, 0, '{"corners": []}', "warn")
    assert kd.submit_request(tmp_path / "r.json", report, "k", "batch", "klt --x", tmp_path) == report
    assert calls[0][:2] == ["klt", "--x"] and calls[0][calls[0].index("--backend") + 1] == "batch"
    assert (tmp_path / "stderr_k.log").read_text() == "warn"


def test_submit_request_failure_renames_report_and_raises(tmp_path, monkeypatch):
    report = tmp_path / "report_k.json"
    _fake_run(monkeypatch, 3, '{"corners": []}', "boom")
    with pytest.raises(kd.CollectionError, match="exit 3"):
        kd.submit_request(tmp_path / "r.json", report, "k", "batch", "klt", tmp_path)
    assert not report.exists() and (tmp_path / "report_k.failed.json").is_file()


def test_corner_log_path_resolves_relative_against_report_dir(tmp_path):
    report = tmp_path / "sub" / "report.json"
    assert kd.corner_log_path({"artifacts": {"log": "c.log"}}, report) == (tmp_path / "sub" / "c.log").resolve()


def test_corner_log_path_keeps_absolute_and_reports_missing(tmp_path):
    report = tmp_path / "report.json"
    absolute = tmp_path / "abs.log"
    assert kd.corner_log_path({"artifacts": {"log": str(absolute)}}, report) == absolute
    assert kd.corner_log_path({"artifacts": {}}, report) is None
    assert kd.corner_log_path({"artifacts": None}, report) is None
    assert kd.corner_log_path({}, report) is None


def _set_env(tmp_path, keys, *, statuses=None, missing=()):
    """An aggregate --batch-set envelope with one member report per key."""
    statuses = statuses or {}
    entries = []
    for i, key in enumerate(keys):
        member = tmp_path / "set" / f"request_{key}" / "report.json"
        entry = {"index": i, "request": str((tmp_path / f"request_{key}.json").resolve()),
                 "status": statuses.get(key, "pass"), "exit_code": 0,
                 "job_id": f"klt-sim-{i}", "job_ids": [f"klt-sim-{i}"],
                 "report": str(member), "error": None}
        if key in missing:
            entry.update(report=None, status="error", exit_code=1,
                         error={"code": "batch_no_capacity", "message": "no capacity"})
        else:
            member.parent.mkdir(parents=True, exist_ok=True)
            member.write_text('{"corners": [{"process": "%s"}]}' % key)
        entries.append(entry)
    return {"schema_version": 1, "status": "pass", "request_count": len(keys),
            "refused_codes": [], "requests": entries}


def _set_requests(tmp_path, keys):
    out = []
    for key in keys:
        req = tmp_path / f"request_{key}.json"
        req.write_text("{}")
        out.append((key, req))
    return out


def test_submit_set_copies_every_member_report_into_the_workdir(tmp_path, monkeypatch):
    import json
    keys = ["a__2.250v", "b__2.500v"]
    calls = _fake_run(monkeypatch, 0, json.dumps(_set_env(tmp_path, keys)))
    done = kd.submit_set(_set_requests(tmp_path, keys), tmp_path, klt_cmd="klt",
                         max_in_flight=2, capacity_retries=3, wait_for_capacity=600)
    assert sorted(done) == keys
    for key in keys:
        assert done[key] == tmp_path / f"report_{key}.json"
        assert kd.report_has_corners(done[key])
    cmd = calls[0]
    assert cmd[:3] == ["klt", "sim", "--batch-set"]
    assert cmd[cmd.index("--backend") + 1] == "batch"
    assert cmd[cmd.index("--max-in-flight") + 1] == "2"
    assert cmd[cmd.index("--capacity-retries") + 1] == "3"
    assert cmd[cmd.index("--wait-for-capacity") + 1] == "600"


def test_submit_set_skips_requests_whose_report_is_already_complete(tmp_path, monkeypatch):
    import json
    keys = ["a__2.250v", "b__2.500v"]
    (tmp_path / "report_a__2.250v.json").write_text('{"corners": []}')
    calls = _fake_run(monkeypatch, 0, json.dumps(_set_env(tmp_path, ["b__2.500v"])))
    done = kd.submit_set(_set_requests(tmp_path, keys), tmp_path, max_in_flight=4)
    assert sorted(done) == keys
    submitted = [c for c in calls[0] if c.endswith(".json")]
    assert submitted == [str((tmp_path / "request_b__2.500v.json").resolve())]


def test_submit_set_submits_nothing_when_every_report_is_complete(tmp_path, monkeypatch):
    for key in ("a", "b"):
        (tmp_path / f"report_{key}.json").write_text('{"corners": []}')
    calls = _fake_run(monkeypatch, 0, "{}")
    assert sorted(kd.submit_set(_set_requests(tmp_path, ["a", "b"]), tmp_path)) == ["a", "b"]
    assert calls == []


def test_submit_set_refused_member_raises_and_keeps_the_finished_ones(tmp_path, monkeypatch):
    import json
    keys = ["a__2.250v", "b__2.500v"]
    env = _set_env(tmp_path, keys, missing=("b__2.500v",))
    env["refused_codes"] = ["batch_no_capacity"]
    _fake_run(monkeypatch, 4, json.dumps(env), "refused")
    with pytest.raises(kd.CollectionError, match="batch_no_capacity"):
        kd.submit_set(_set_requests(tmp_path, keys), tmp_path, max_in_flight=2, capacity_retries=3)
    # the member that finished is kept on disk, so --workdir resumes it
    assert kd.report_has_corners(tmp_path / "report_a__2.250v.json")
    assert not (tmp_path / "report_b__2.500v.json").exists()
    assert (tmp_path / "stderr_set.log").read_text() == "refused"


def test_submit_set_missing_envelope_entry_is_a_failure(tmp_path, monkeypatch):
    import json
    keys = ["a", "b"]
    env = _set_env(tmp_path, ["a"])
    _fake_run(monkeypatch, 0, json.dumps(env))
    with pytest.raises(kd.CollectionError, match="no envelope entry for b"):
        kd.submit_set(_set_requests(tmp_path, keys), tmp_path, max_in_flight=2)


def test_submit_set_unusable_envelope_raises(tmp_path, monkeypatch):
    _fake_run(monkeypatch, 1, "not json", "usage error")
    with pytest.raises(kd.CollectionError, match="no usable envelope"):
        kd.submit_set(_set_requests(tmp_path, ["a"]), tmp_path)


def test_submit_set_rejects_a_non_positive_in_flight_bound(tmp_path):
    with pytest.raises(kd.CollectionError, match="max_in_flight"):
        kd.submit_set(_set_requests(tmp_path, ["a"]), tmp_path, max_in_flight=0)
