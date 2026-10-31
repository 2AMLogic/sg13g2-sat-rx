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
