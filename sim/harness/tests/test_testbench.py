"""testbench.py: manifest validation, against every committed tb.json and
against deliberately broken synthetic ones."""

import json
import math
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


# ---------------------------------------------------------------- issue #181: iip3 readout

# The committed mixer bench publishes iip3_dbm as the SLOPE-3-CONSTRAINED read
# at the top-of-fit drive (IIP3 = Pin + (Pfund - Pim3)/2, the classical
# slope-1/slope-3 extrapolation applied at the last fit-window point), with the
# free two-line intersection and the window-centroid mean demoted to published
# diagnostics. Record 20261012-061538-2bdb5be measured the free intersection's
# local-vs-batch bound at ~1.4 dB (it rotates with the fitted IM3 slope, which
# ngspice builds agree to only ~0.10) while the top-of-fit per-point reads
# agree to 0.0998 dB -- so the constrained headline's bound is ~0.05 dB.

MIXER = next(p for p in BENCHES if p.name == "mixer-conversion-iip3")


def mixer_manifest():
    return json.loads((MIXER / "testbench" / "tb.json").read_text())


def test_iip3_headline_is_topfit_slope3_read_with_published_diagnostics():
    raw = mixer_manifest()
    assert raw["measure"]["iip3_dbm"] == "iip3t"
    assert raw["measure"]["iip3_free_intersection_dbm"] == "iip3x"
    assert raw["measure"]["iip3_window_centroid_dbm"] == "iip3c"
    analyses = "\n".join(raw["analyses"])
    # the estimator definitions the synthetic-data mirror below computes
    assert "let iip3t = ($lopin) + ((($lopf) - ($lopim))/2)" in analyses
    assert "let iip3c = (($sx)/($n)) + (((($syf) - (($syi)))/($n))/2)" in analyses
    assert "let iip3x = (bfit_i - bfit_f) / (mfit_f - mfit_i)" in analyses
    # the headline read consumes the LAST fit-window point (lopin/lopf/lopim
    # accumulate inside the fit foreach), which must stay the top-of-fit drive
    # the floor control also runs at
    assert "foreach drv 0.014 0.02 0.028 0.04 0.056" in analyses
    assert "alterparam vrf = 0.056" in analyses


def test_issue181_slope_region_and_floor_gates_not_loosened():
    checks = mixer_manifest()["checks"]
    assert (checks["slope_fund_db_per_db"]["min"], checks["slope_fund_db_per_db"]["max"]) == (0.9, 1.1)
    assert (checks["slope_im3_db_per_db"]["min"], checks["slope_im3_db_per_db"]["max"]) == (2.7, 3.3)
    assert (checks["fit_n"]["min"], checks["fit_n"]["max"]) == (5, 5)
    assert checks["pim3_fit_margin_db"]["min"] == 20.0


def _deck_estimators(pin, pfund, pim3):
    """Python mirror of the tb.json in-deck estimators: the least-squares
    accumulators' free two-line intersection (iip3x), the window-centroid
    mean (iip3c) and the top-of-fit slope-3 read (iip3t)."""
    n = len(pin)
    sx = sum(pin)
    sxx = sum(p * p for p in pin)
    sxyf = sum(p * f for p, f in zip(pin, pfund))
    syf = sum(pfund)
    sxyi = sum(p * i for p, i in zip(pin, pim3))
    syi = sum(pim3)
    den = n * sxx - sx * sx
    mfit_f = (n * sxyf - sx * syf) / den
    mfit_i = (n * sxyi - sx * syi) / den
    bfit_f = (syf - mfit_f * sx) / n
    bfit_i = (syi - mfit_i * sx) / n
    return (
        (bfit_i - bfit_f) / (mfit_f - mfit_i),
        sx / n + ((syf - syi) / n) / 2,
        pin[-1] + (pfund[-1] - pim3[-1]) / 2,
    )


# the bench's stated fit window, DRIVELIST 0.014..0.056 V
_FIT_DRIVES = [0.014, 0.02, 0.028, 0.04, 0.056]


def _fit_pins_dbm():
    return [10 * math.log10(d * d / (8 * 50 * 1e-3)) for d in _FIT_DRIVES]


def test_iip3_estimators_recover_known_intercept_on_exact_two_line_data():
    # pfund = pin (slope 1), pim3 = 3*pin - 20 (slope 3): both lines meet at
    # IIP3 = +10 dBm, so every estimator must return exactly the intercept
    pin = _fit_pins_dbm()
    pfund, pim3 = pin, [3 * p - 20.0 for p in pin]
    free, centroid, topfit = _deck_estimators(pin, pfund, pim3)
    for got in (free, centroid, topfit):
        assert abs(got - 10.0) < 1e-9


def test_iip3_topfit_read_holds_while_free_intersection_swings():
    # two builds' IM3 reads per the cross-backend note of record
    # 20261012-061538-2bdb5be: per-point disagreement grows toward the window's
    # low end (0.0998 dB at top-of-fit up to 1.375 dB at 0.014 V); fundamentals
    # agree to 0.0014 dB (treated as identical here). The constrained top-of-fit
    # read inherits half the top-of-fit delta; the free intersection amplifies
    # the low-end scatter across the ~31 dB extrapolation.
    pin = _fit_pins_dbm()
    pfund = pin
    pim3_a = [3 * p - 20.0 for p in pin]
    pim3_b = [v + d for v, d in zip(pim3_a, [1.375, 0.685, 0.348, 0.187, 0.0998])]
    free_a, _, top_a = _deck_estimators(pin, pfund, pim3_a)
    free_b, cent_b, top_b = _deck_estimators(pin, pfund, pim3_b)
    assert abs(top_b - top_a) <= 0.05        # half the 0.0998 dB top-of-fit delta
    assert abs(free_b - free_a) > 1.0        # the free intersection swings ~dBs
    assert abs(cent_b - top_b) > 0.2         # the centroid keeps the low-drive scatter
