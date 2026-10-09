"""Tests for the lna-sparam-nf noise-figure normalization (issue #22).

No simulator needed. Run from the repo root:

    python3 -m pytest sim/lna-sparam-nf/tests -q
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))

import lna_nf as nf  # noqa: E402

MANIFEST = json.loads((BENCH / "testbench" / "tb.json").read_text())
FIXTURE = (BENCH / "testbench" / "lna_ce_placeholder.spice").read_text()
NF_EXPR = {s: MANIFEST["measure"][f"nf_db_{s}"] for s in nf.FREQ_SUFFIXES}
REF = nf.noise_ref_w_per_hz()


def spectrum_for_f(f_true: float) -> float:
    return math.sqrt((f_true - 1.0) * REF)


def test_reference_density_is_4kT0Z0():
    assert REF == pytest.approx(4 * 1.380649e-23 * 300.15 * 50.0)


@pytest.mark.parametrize("suffix,idx", [("lo", 0), ("mid", 1), ("hi", 2)])
def test_zero_added_noise_is_unity_factor_and_zero_db(suffix, idx):
    """Negative control: a noiseless DUT must read F=1, NF=0 dB. The old
    formula (no +1) would read -inf dB here."""
    spec = [0.0, 0.0, 0.0]
    assert nf.eval_manifest_nf(NF_EXPR[suffix], spec) == pytest.approx(0.0, abs=1e-12)
    assert nf.f_from_added_noise(0.0) == 1.0
    with pytest.raises(ValueError):  # the former expression diverges
        nf.eval_manifest_nf(f"10*log10(noise2.inoise_spectrum[{idx}]*noise2.inoise_spectrum[{idx}]/(4*1.380649e-23*300.15*50))", spec)


@pytest.mark.parametrize("suffix,idx", [("lo", 0), ("mid", 1), ("hi", 2)])
def test_known_density_gives_analytic_factor(suffix, idx):
    for f_true in (1.5, 2.5, 10.0):
        spec = [0.0, 0.0, 0.0]
        spec[idx] = spectrum_for_f(f_true)
        got = nf.eval_manifest_nf(NF_EXPR[suffix], spec)
        assert got == pytest.approx(10 * math.log10(f_true), abs=1e-9)


def test_each_expression_reads_only_its_own_frequency_point():
    spec = [spectrum_for_f(1.5), spectrum_for_f(2.5), spectrum_for_f(4.0)]
    got = [nf.eval_manifest_nf(NF_EXPR[s], spec) for s in nf.FREQ_SUFFIXES]
    assert got == pytest.approx([10 * math.log10(x) for x in (1.5, 2.5, 4.0)], abs=1e-9)


def test_former_temp27_method_disagrees_by_27_over_300_15_in_linear_f():
    """The superseded method (source at 327.15 K, plain inoise^2/4kT0Z0) on
    the SAME circuit reads high by exactly 27/300.15 in F -- and that is NOT
    a constant dB offset."""
    assert nf.LEGACY_F_BIAS == pytest.approx(27.0 / 300.15)
    diffs_db = []
    for f_true in (1.2, 2.0, 3.0):
        added = spectrum_for_f(f_true)  # DUT-only noise, noiseless source
        # What the noisy 327.15 K source would have produced for the same DUT:
        inoise_legacy = math.sqrt(added ** 2 + 4 * nf.K_BOLTZMANN * nf.LEGACY_SOURCE_K * 50.0)
        f_old = nf.legacy_f(inoise_legacy)
        assert f_old - f_true == pytest.approx(27.0 / 300.15, rel=1e-12)
        assert f_old - nf.f_from_added_noise(added) == pytest.approx(0.0899550, abs=1e-6)
        diffs_db.append(10 * math.log10(f_old) - 10 * math.log10(f_true))
    assert max(diffs_db) - min(diffs_db) > 0.05  # not a constant dB offset


def test_correction_from_recorded_db_is_linear_in_f():
    f_true = 2.5
    nf_old_db = 10 * math.log10(nf.legacy_f_from_true_f(f_true))
    assert nf.true_f_from_legacy_db(nf_old_db) == pytest.approx(f_true, abs=1e-12)
    # a constant-dB subtraction would be wrong:
    const_db = 10 * math.log10(1 + 27 / 300.15)
    assert 10 ** ((nf_old_db - const_db) / 10) != pytest.approx(f_true, abs=1e-3)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_inputs_are_rejected(bad):
    with pytest.raises(ValueError):
        nf.f_from_added_noise(bad)
    for s in nf.FREQ_SUFFIXES:
        with pytest.raises(ValueError):
            nf.eval_manifest_nf(NF_EXPR[s], [bad, 1e-9, 1e-9])
    with pytest.raises(ValueError):
        nf.true_f_from_legacy_db(bad)


def test_evaluator_rejects_unknown_tokens():
    with pytest.raises(ValueError):
        nf.eval_manifest_nf("__import__('os')", [1.0, 1.0, 1.0])


# ---- manifest / fixture text ----------------------------------------------


def test_manifest_has_all_three_expressions_in_corrected_form():
    for s in nf.FREQ_SUFFIXES:
        expr = NF_EXPR[s]
        assert expr.startswith("10*log10(1+(noise2.inoise_spectrum[")
        assert "4*1.380649e-23*300.15*50" in expr


def test_fixture_source_is_noiseless_with_no_instance_temperature():
    rs1 = [ln for ln in FIXTURE.splitlines() if ln.startswith("Rs1 ")]
    assert len(rs1) == 1
    assert "noisy=0" in rs1[0]
    assert "temp" not in rs1[0].lower()
    rs2 = [ln for ln in FIXTURE.splitlines() if ln.startswith("Rs2 ")]
    assert len(rs2) == 1 and "noisy" not in rs2[0]  # output load keeps its noise


def test_notes_do_not_claim_the_override_pins_300_15():
    text = json.dumps(MANIFEST["evidence"]["notes"]) + FIXTURE
    assert "always at exactly 300.15 K" not in text
    assert "noise is always at exactly" not in text
    assert "Rs1 carries an explicit TEMP=27 override" not in text


# ---- comparison with the superseded record ---------------------------------


def _write_old(tmp_path, cid, nf_old_db, s21=8.0, k=0.3):
    (tmp_path / f"{cid}.log").write_text(
        f"m_s21_db_mid = {s21:.10e}\nm_k_mid = {k:.10e}\n"
        + "".join(f"m_nf_db_{s} = {nf_old_db:.10e}\n" for s in nf.FREQ_SUFFIXES))


def _new(f_true, s21=8.0, k=0.3):
    d = {"s21_db_mid": s21, "k_mid": k}
    d.update({f"nf_db_{s}": 10 * math.log10(f_true) for s in nf.FREQ_SUFFIXES})
    return d


def test_compare_accepts_a_consistent_correction(tmp_path):
    f_true = 2.58
    _write_old(tmp_path, "c1", 10 * math.log10(f_true + 27 / 300.15))
    res = nf.compare_to_superseded({"c1": _new(f_true)}, tmp_path)
    assert res["problems"] == [] and res["compared"] == 5
    assert res["worst"]["nf_f"] < 1e-8


def test_compare_flags_constant_db_shift_instead_of_linear_f(tmp_path):
    """Negative control: a result that merely shifts NF by a constant dB (or
    leaves the old value) must be flagged."""
    f_true = 2.58
    old_db = 10 * math.log10(f_true + 27 / 300.15)
    _write_old(tmp_path, "c1", old_db)
    wrong = _new(f_true)
    for s in nf.FREQ_SUFFIXES:
        wrong[f"nf_db_{s}"] = old_db - 10 * math.log10(1 + 27 / 300.15)
    assert nf.compare_to_superseded({"c1": wrong}, tmp_path)["problems"]
    unchanged = _new(f_true)
    for s in nf.FREQ_SUFFIXES:
        unchanged[f"nf_db_{s}"] = old_db
    assert nf.compare_to_superseded({"c1": unchanged}, tmp_path)["problems"]


def test_compare_flags_changed_sparams_and_missing_logs(tmp_path):
    f_true = 2.58
    _write_old(tmp_path, "c1", 10 * math.log10(f_true + 27 / 300.15))
    assert nf.compare_to_superseded({"c1": _new(f_true, s21=8.01)}, tmp_path)["problems"]
    assert nf.compare_to_superseded({"c2": _new(f_true)}, tmp_path)["problems"]
