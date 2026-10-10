"""Tests for the lna_stage1 bench pieces (issue #28). No simulator needed.

    python3 -m pytest sim/lna-sparam-nf/tests -q
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
REPO = BENCH.parents[1]
sys.path.insert(0, str(BENCH))

import make_stage1_fixture as fx  # noqa: E402
import stage1_tables as st  # noqa: E402

TB = json.loads((BENCH / "testbench" / "tb.json").read_text())
FIXTURE = (BENCH / "testbench" / "lna_stage1.spice").read_text()
DESIGN_NET = (REPO / "design" / "netlist" / "lna_stage1.spice").read_text()


def test_fixture_embeds_design_netlist_verbatim():
    assert fx.embedded(FIXTURE) == DESIGN_NET.rstrip("\n") + "\n"
    assert FIXTURE == fx.build(), "run sim/lna-sparam-nf/make_stage1_fixture.py"


def test_tb_json_points_at_the_stage1_fixture():
    assert TB["netlist"] == "lna_stage1.spice"
    assert TB["claim"].startswith("ideal-matching feasibility record; no spec row is claimed met; "
                                  "row 6 (k > 1) is reported, not claimed")


def test_nf_expression_is_still_the_corrected_post_22_one():
    for s in ("lo", "mid", "hi"):
        e = TB["measure"][f"nf_db_{s}"]
        assert e.startswith("10*log10(1+") and "300.15" in e and "4*1.380649e-23" in e


def test_reference_source_stays_noiseless():
    rs1 = [ln for ln in FIXTURE.splitlines() if ln.startswith("Rs1 ")]
    assert len(rs1) == 1 and "noisy=0" in rs1[0] and "temp" not in rs1[0].lower()


def test_dut_has_expected_devices_and_no_inductor_model():
    xs = [ln for ln in DESIGN_NET.splitlines() if re.match(r"X", ln)]
    assert len(xs) == 3 and all("npn13G2" in ln for ln in xs)
    assert not re.search(r"^\.(include|lib)", DESIGN_NET, re.M)
    # ideal behavioral L only: no PDK inductor subckt anywhere
    body = "\n".join(ln for ln in DESIGN_NET.splitlines() if not ln.startswith("*"))
    assert not re.search(r"inductor|ind_|spiral", body, re.I)


def test_stability_sweep_reaches_past_row6_out_of_band_point():
    sweeps = [a for a in TB["analyses"] if a.startswith("ac dec")]
    assert len(sweeps) == 2 and len(set(sweeps)) == 1
    _, _, per_dec, lo, hi = sweeps[0].split()
    assert float(hi) >= 3 * 21.2e9 and float(per_dec) >= 100


def test_limits_are_row_17_and_the_card_box():
    assert st.VCE_MAX_V == 1.4 and st.VCE_WINDOW_V == (0.4, 2.0)
    assert st.VBE_WINDOW_V == (0.65, 0.96) and st.RAIL_CEILING_V == 2.5


def _m(vce=1.2, vbe=0.8, icfrac=0.06, ft=150.0):
    d = {}
    for dev in ("q1", "q2", "qr"):
        d.update({f"{dev}_vce": vce, f"{dev}_vbe": vbe, f"{dev}_icfrac": icfrac, f"{dev}_ft": ft})
    return d


def test_op_flags_pass_and_each_fail_mode():
    assert all(st.op_flags(_m(), "q1").values())
    assert not st.op_flags(_m(vce=1.5), "q1")["vce_le_1v4"]
    assert st.op_flags(_m(vce=1.5), "q1")["vce_in_window"]
    assert not st.op_flags(_m(vce=2.1), "q1")["vce_in_window"]
    assert not st.op_flags(_m(vce=0.3), "q1")["vce_in_window"]
    assert not st.op_flags(_m(vbe=0.97), "q1")["vbe_in_window"]
    assert not st.op_flags(_m(vbe=0.64), "q1")["vbe_in_window"]
    assert not st.op_flags(_m(icfrac=1.0), "q1")["ic_in_box"]
    assert not st.op_flags(_m(ft=20.0), "q1")["ft_above_band"]


def test_supply_class_labels_the_excursion():
    assert "EXCURSION" in st.supply_class(2.75)
    assert "EXCURSION" not in st.supply_class(2.5) and "EXCURSION" not in st.supply_class(2.25)


def _stab(k=5.0, d=0.9, sw_n=0):
    m = {"sw_nunst": float(sw_n)}
    for s, _ in st.BAND_SUFFIX:
        m[f"k_{s}"] = k
        m[f"d_{s}"] = d
    return m


@pytest.mark.parametrize("kw,flag", [
    (dict(), False), (dict(k=1.0), True), (dict(k=0.4), True), (dict(d=1.0), True), (dict(sw_n=3), True)])
def test_stability_flag(kw, flag):
    assert st.stability_flag(_stab(**kw))[0] is flag


def _sweep_text(ks, ds, mus):
    rows = ["SWEEP_BEGIN", "Index frequency wf wk wd wmu"]
    for i, (k, d, mu) in enumerate(zip(ks, ds, mus)):
        f = 1e9 * 10 ** (i / 100)
        rows.append(f"{i}\t{f:.10e}\t{f:.10e}\t{k:.10e}\t{d:.10e}\t{mu:.10e}\t")
    rows.append("SWEEP_END")
    return "\n".join(rows)


def test_parse_and_stats_find_the_minimum_and_unstable_points():
    ks = [5.0, 3.0, 0.8, 2.0]
    ds = [0.9, 0.95, 1.2, 0.5]
    mus = [1.1, 1.0, 0.7, 1.3]
    s = st.sweep_stats(st.parse_sweep(_sweep_text(ks, ds, mus)))
    assert s.n == 4 and s.kmin == pytest.approx(0.8) and s.dmax == pytest.approx(1.2)
    assert s.mumin == pytest.approx(0.7) and s.n_unstable == 1
    assert s.ratio_step == pytest.approx(10 ** 0.01)


def test_parse_sweep_requires_the_block():
    with pytest.raises(ValueError):
        st.parse_sweep("nothing here")
