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
