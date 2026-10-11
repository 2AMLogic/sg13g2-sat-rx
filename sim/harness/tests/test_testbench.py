"""testbench.py: manifest validation, against every committed tb.json and
against deliberately broken synthetic ones."""

import json
from pathlib import Path

import pytest

from harness import testbench as T

SIM = Path(__file__).resolve().parents[2]
BENCHES = T.discover(SIM)


def test_all_three_committed_benches_are_discovered():
    assert {p.name for p in BENCHES} >= {"lna-sparam-nf", "mixer-conversion-iip3", "hbt-kaband-characterization"}


@pytest.mark.parametrize("bench", BENCHES, ids=lambda p: p.name)
def test_committed_manifest_loads_and_validates(bench):
    tb = T.load(bench)
    assert tb.experiment == bench.name
    assert tb.measure and tb.netlist.is_file()
    assert T.valid_netlist_provenance(tb.netlist_provenance)
    assert tb.corners == ("hbt",)
    assert len(tb.netlist_sha256) == 64 and len(tb.manifest_sha256) == 64
    for name in tb.checks:
        assert name in tb.measure


@pytest.mark.parametrize("bench", BENCHES, ids=lambda p: p.name)
def test_load_accepts_dir_testbench_dir_and_file(bench):
    a = T.load(bench)
    assert T.load(bench / "testbench").name == a.name
    assert T.load(bench / "testbench" / "tb.json").name == a.name


def make_bench(tmp_path, manifest_overrides=None, netlist="R1 a b 1k\n", drop=()):
    tbdir = tmp_path / "exp" / "testbench"
    tbdir.mkdir(parents=True)
    (tbdir / "dut.spice").write_text(netlist)
    manifest = {"name": "t", "netlist": "dut.spice", "measure": {"m1": "1"}}
    manifest.update(manifest_overrides or {})
    for key in drop:
        manifest.pop(key, None)
    (tbdir / "tb.json").write_text(json.dumps(manifest))
    return tmp_path / "exp"


def test_minimal_synthetic_bench_loads(tmp_path):
    tb = T.load(make_bench(tmp_path))
    assert tb.netlist_provenance == "schematic" and tb.experiment == "exp"


@pytest.mark.parametrize("key", ["netlist", "measure"])
def test_missing_required_key(tmp_path, key):
    with pytest.raises(ValueError, match=key):
        T.load(make_bench(tmp_path, drop=(key,)))


def test_missing_netlist_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        T.load(make_bench(tmp_path, {"netlist": "absent.spice"}))


def test_empty_measure_rejected(tmp_path):
    with pytest.raises(ValueError, match="at least one"):
        T.load(make_bench(tmp_path, {"measure": {}}))


def test_uppercase_or_punctuated_measure_names_rejected(tmp_path):
    with pytest.raises(ValueError, match="lower case"):
        T.load(make_bench(tmp_path, {"measure": {"Gain": "1"}}))
    with pytest.raises(ValueError, match="alphanumeric"):
        T.load(make_bench(tmp_path / "b", {"measure": {"a-b": "1"}}))


@pytest.mark.parametrize("bad", ["layout", "Schematic"])
def test_bad_netlist_provenance(tmp_path, bad):
    with pytest.raises(ValueError, match="netlist_provenance"):
        T.load(make_bench(tmp_path, {"netlist_provenance": bad}))


def test_provenance_forms():
    assert T.valid_netlist_provenance("schematic")
    assert T.valid_netlist_provenance("schematic (variant)")
    assert T.valid_netlist_provenance("extracted (post-layout)")
    assert not T.valid_netlist_provenance("schematics")


@pytest.mark.parametrize("directive", [".temp 27", ".include x", ".end", ".control", ".lib a b"])
def test_forbidden_netlist_directives(tmp_path, directive):
    with pytest.raises(ValueError, match="must not contain"):
        T.load(make_bench(tmp_path, netlist=f"R1 a b 1k\n{directive}\n"))


def test_check_must_name_a_measurement(tmp_path):
    with pytest.raises(ValueError, match="does not name a measurement"):
        T.load(make_bench(tmp_path, {"checks": {"nope": {"min": 0}}}))


def test_check_unknown_key_and_axis(tmp_path):
    with pytest.raises(ValueError, match="unknown key"):
        T.load(make_bench(tmp_path, {"checks": {"m1": {"minn": 0}}}))
    with pytest.raises(ValueError, match="unknown axis"):
        T.load(make_bench(tmp_path / "b", {"checks": {"m1": {"min_spread_pct_by_axis": {"humidity": 1}}}}))


def test_bad_evidence_block_rejected(tmp_path):
    with pytest.raises(Exception, match="bogus"):
        T.load(make_bench(tmp_path, {"evidence": {"bogus": 1}}))


def test_discover_ignores_dirs_without_a_testbench(tmp_path):
    make_bench(tmp_path)
    (tmp_path / "other").mkdir()
    assert [p.name for p in T.discover(tmp_path)] == ["exp"]


# ---------------------------------------------------------------- frozen inputs (issue #141)


def test_digests_describe_load_time_bytes_not_a_later_edit(tmp_path):
    exp = make_bench(tmp_path)
    tb = T.load(exp)
    netlist_sha, manifest_sha = tb.netlist_sha256, tb.manifest_sha256
    (exp / "testbench" / "tb.json").write_text(json.dumps(
        {"name": "t", "netlist": "dut.spice", "measure": {"m1": "999"}}))
    (exp / "testbench" / "dut.spice").write_text("R1 a b 2k\n")
    assert tb.manifest_sha256 == manifest_sha
    assert tb.netlist_sha256 == netlist_sha
    assert json.loads(tb.manifest_data)["measure"] == {"m1": "1"}
    assert tb.netlist_data == b"R1 a b 1k\n"


def test_working_input_drift_detects_manifest_and_fragment_changes(tmp_path):
    exp = make_bench(tmp_path)
    tb = T.load(exp)
    assert tb.working_input_drift() == ""
    (exp / "testbench" / "tb.json").write_text('{"netlist": "dut.spice", "measure": {"m1": "2"}}')
    drift = tb.working_input_drift()
    assert "manifest" in drift and "changed" in drift
    (exp / "testbench" / "tb.json").write_text(json.dumps(
        {"name": "t", "netlist": "dut.spice", "measure": {"m1": "1"}}))
    assert tb.working_input_drift() == ""
    (exp / "testbench" / "dut.spice").write_text("R1 a b 3k\n")
    assert "netlist fragment" in tb.working_input_drift()


def test_working_input_drift_detects_vanished_inputs(tmp_path):
    exp = make_bench(tmp_path)
    tb = T.load(exp)
    (exp / "testbench" / "dut.spice").unlink()
    assert "no longer readable" in tb.working_input_drift()


def write_raw_manifest(tmp_path, checks_literal):
    tbdir = tmp_path / "exp" / "testbench"
    tbdir.mkdir(parents=True)
    (tbdir / "dut.spice").write_text("R1 a b 1k\n")
    (tbdir / "tb.json").write_text(
        '{"name": "t", "netlist": "dut.spice", "measure": {"m1": "1"}, "checks": ' + checks_literal + "}"
    )
    return tmp_path / "exp"


@pytest.mark.parametrize("literal", [
    '{"m1": {"min": NaN}}',
    '{"m1": {"max": Infinity}}',
    '{"m1": {"min": -Infinity}}',
    '{"m1": {"max": 1e999}}',
    '{"m1": {"max_spread_pct": 1e999}}',
    '{"m1": {"min": true}}',
    '{"m1": {"max": "5"}}',
    '{"m1": {"max_spread_pct": false}}',
    '{"m1": {"min": 5, "max": 1}}',
    '{"m1": {"max_spread_pct": -1}}',
    '{"m1": {"min_spread_pct": -0.5}}',
    '{"m1": {"max_spread_pct_by_axis": {"supply": NaN}}}',
    '{"m1": {"min_spread_pct_by_axis": {"process": "1"}}}',
    '{"m1": {"max_spread_pct_by_axis": {"temperature": 1e999}}}',
    '{"m1": {"min_spread_pct_by_axis": {"supply": true}}}',
    '{"m1": {"max_spread_pct_by_axis": {"supply": -2}}}',
])
def test_bad_numeric_limits_rejected_at_load(tmp_path, literal):
    with pytest.raises(ValueError, match="m1"):
        T.load(write_raw_manifest(tmp_path, literal))


def test_valid_numeric_limits_still_load(tmp_path):
    tb = T.load(write_raw_manifest(
        tmp_path, '{"m1": {"min": -1, "max": 2.5, "max_spread_pct": 0, "min_spread_pct_by_axis": {"supply": 1}}}'
    ))
    assert tb.checks["m1"]["max"] == 2.5
    T.load(make_bench(tmp_path / "x", {"checks": {"m1": {"min": 3, "max": 3}}}))
