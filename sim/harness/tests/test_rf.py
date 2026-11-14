"""Characterization of the noiseless-source noise factor across its four
per-bench implementations, plus the shared ``harness.rf`` module (issue #262).

The characterization half was written against the four pre-existing
implementations BEFORE the consolidation and is kept as the regression guard
after it: it proves the move was behaviour-preserving bit-for-bit, and it
pins the two divergences the move must NOT average away --

* lna-sparam-nf raises on a non-finite input; matchstudy and kaband
  propagate (NaN in, NaN out);
* T0 is passed explicitly everywhere -- kaband's 290 K IEEE reference and
  the other benches' 300.15 K both appear, and ``harness.rf`` takes ``t0_k``
  with no default (a call that omits it is a TypeError).

kaband's fitted noise numerator ``sv`` is a variance (V^2/Hz), not a
density, so it shares the arithmetic through
:func:`harness.rf.noise_factor_from_inoise_sq` rather than losing bits to a
``sqrt`` round-trip (pinned below with a concrete counterexample).

No simulator, no numpy needed for the characterization itself (the one
nfmethod test skips if numpy is missing). From the repo root:

    python3 -m pytest sim/harness/tests/test_rf.py -q
"""

import math
import random
import re
import struct
import sys
from pathlib import Path

import pytest

SIM = Path(__file__).resolve().parents[2]
for _p in (
    SIM / "lna-sparam-nf",
    SIM / "lna-match-tradeoff",
    SIM / "hbt-kaband-characterization",
    SIM / "mixer-nf-method",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import kaband  # noqa: E402
import lna_nf as nf  # noqa: E402
import matchstudy as ms  # noqa: E402

from harness import rf as hrf  # noqa: E402

#: The SI value restated here so the known-answer pins stay independent of
#: ``harness.rf`` (they would catch the constant itself being mistyped).
K_LITERAL = 1.380649e-23

#: Input vectors shared by every characterization table: zero, a tiny
#: density, a realistic one (nV/sqrt(Hz) at an LNA input), its negation, a
#: large one, and NaN (the guard-divergence probe).
INOISE = (0.0, 1e-12, 2.0e-9, -2.0e-9, 1e-6, float("nan"))

#: Both reference temperatures live in the tree on purpose (290 K IEEE at
#: kaband, 300.15 K elsewhere); neither may become a default.
T0S = (290.0, 300.15)
ZS_REAL = (25.0, 50.0, 100.0)
ZS_COMPLEX = (complex(25.0, 15.0), complex(30.0, -40.0))


def _bits(x) -> bytes:
    return struct.pack("<d", float(x))


def assert_bits_equal(got, want, label: str) -> None:
    """Bit-for-bit equality; every NaN counts as the same outcome."""
    if math.isnan(got) and math.isnan(want):
        return
    assert _bits(got) == _bits(want), f"{label}: {got!r} != {want!r}"


# ---------------------------------------------------------------------------
# Characterization of the four pre-existing implementations
# ---------------------------------------------------------------------------


def test_lna_nf_known_answer():
    # lna-sparam-nf hardcodes T0 = 300.15 K and Z0 = 50 ohm.
    want = 1.0 + 2.0e-9 * 2.0e-9 / (4 * K_LITERAL * 300.15 * 50.0)
    assert_bits_equal(nf.f_from_added_noise(2.0e-9), want, "lna_nf F")
    assert_bits_equal(nf.nf_db(2.0e-9), 10.0 * math.log10(want), "lna_nf NF dB")
    assert nf.f_from_added_noise(0.0) == 1.0


def test_matchstudy_and_kaband_known_answers_all_t0_all_z():
    for t0 in T0S:
        for z in ZS_REAL:
            for v in (0.0, 2.0e-9, -2.0e-9):
                want = 1.0 + v * v / (4 * K_LITERAL * t0 * z)
                assert_bits_equal(
                    ms.nf_db_from_inoise(v, t0, z),
                    10 * math.log10(want), f"matchstudy {v=} {t0=} {z=}")
                assert_bits_equal(
                    kaband.measured_noise_factor(v, complex(z, 0.0), t0),
                    want, f"kaband measured {v=} {t0=} {z=}")


def test_the_four_sites_agree_bit_for_bit_where_they_agree_today():
    for v in INOISE:
        if not math.isfinite(v):
            continue  # the guard divergence is pinned separately, not compared
        f_lna = nf.f_from_added_noise(v)
        db_lna = nf.nf_db(v)
        assert_bits_equal(
            ms.nf_db_from_inoise(v, 300.15, 50.0), db_lna,
            f"matchstudy dB vs lna_nf dB {v=}")
        assert_bits_equal(
            kaband.measured_noise_factor(v, complex(50.0, 0.0), 300.15), f_lna,
            f"kaband measured vs lna_nf {v=}")
        # kaband's fit-derived form with a fit constructed so sv == inoise^2
        fit = {"a": v * v, "b": 0.0, "c": 0.0, "d": 0.0}
        assert_bits_equal(
            kaband.noise_factor(fit, complex(50.0, 0.0), 300.15), f_lna,
            f"kaband fit vs lna_nf {v=}")
        # the two non-lna_nf forms across the full shared grid
        for t0 in T0S:
            for z in ZS_REAL:
                f = kaband.measured_noise_factor(v, complex(z, 0.0), t0)
                assert_bits_equal(
                    ms.nf_db_from_inoise(v, t0, z), 10 * math.log10(f),
                    f"matchstudy vs kaband {v=} {t0=} {z=}")


def test_kaband_takes_complex_zs_its_real_part_is_what_enters_f():
    for v in (0.0, 2.0e-9, -2.0e-9):
        for zs in ZS_COMPLEX:
            for t0 in T0S:
                want = 1.0 + v * v / (4 * K_LITERAL * t0 * zs.real)
                assert_bits_equal(
                    kaband.measured_noise_factor(v, zs, t0), want,
                    f"measured {v=} {zs=} {t0=}")
                fit = {"a": v * v, "b": 0.0, "c": 0.0, "d": 0.0}
                assert_bits_equal(
                    kaband.noise_factor(fit, zs, t0), want,
                    f"fit {v=} {zs=} {t0=}")


def test_lna_nf_raises_on_nonfinite_the_others_propagate():
    # The load-bearing divergence: lna_nf guards, matchstudy/kaband do not.
    # The move must keep each site's own behaviour, not average the two.
    with pytest.raises(ValueError):
        nf.f_from_added_noise(float("nan"))
    with pytest.raises(ValueError):
        nf.nf_db(float("nan"))
    assert math.isnan(ms.nf_db_from_inoise(float("nan"), 300.15, 50.0))
    assert math.isnan(
        kaband.measured_noise_factor(float("nan"), complex(50.0, 0.0), 300.15))
    assert math.isnan(kaband.noise_factor(
        {"a": float("nan"), "b": 0.0, "c": 0.0, "d": 0.0},
        complex(50.0, 0.0), 300.15))
    # +/-inf propagates silently where lna_nf raises
    assert math.isinf(
        kaband.measured_noise_factor(float("inf"), complex(50.0, 0.0), 300.15))
    assert math.isinf(ms.nf_db_from_inoise(float("inf"), 300.15, 50.0))
    with pytest.raises(ValueError):
        nf.f_from_added_noise(float("inf"))


def test_the_two_reference_temperatures_produce_different_answers():
    f290 = kaband.measured_noise_factor(2.0e-9, complex(50.0, 0.0), 290.0)
    f300 = kaband.measured_noise_factor(2.0e-9, complex(50.0, 0.0), 300.15)
    assert f290 > f300 > 1.0  # the colder reference reports the larger F


# ---------------------------------------------------------------------------
# The shared harness.rf module
# ---------------------------------------------------------------------------


def test_the_constant_is_declared_exactly_once():
    hits = []
    for path in sorted(SIM.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"(K_BOLTZMANN|K_B)\s*=", line):
                hits.append(f"{path.relative_to(SIM)}:{lineno}")
    assert len(hits) == 1, hits
    assert hits[0].startswith(str(Path("harness") / "rf.py")), hits


def test_helper_known_answer_independent_literal():
    assert hrf.K_BOLTZMANN == K_LITERAL
    for t0 in T0S:
        for z in ZS_REAL:
            v = 2.0e-9
            want = 1.0 + v * v / (4 * K_LITERAL * t0 * z)
            assert_bits_equal(
                hrf.noise_factor_from_inoise(v, t0, z), want,
                f"helper {t0=} {z=}")
            assert_bits_equal(
                hrf.noise_factor_from_inoise_sq(v * v, t0, z), want,
                f"sq helper {t0=} {z=}")


def test_helper_matches_each_former_site_bit_for_bit():
    for v in INOISE:
        if not math.isfinite(v):
            continue  # guard behaviour is per-site and pinned separately
        # lna_nf keeps its own ** 2 squaring (see the recorded divergence
        # below); it shares the division through the sq form.
        f_sq = hrf.noise_factor_from_inoise_sq(v ** 2, 300.15, 50.0)
        assert_bits_equal(f_sq, nf.f_from_added_noise(v), f"vs lna_nf {v=}")
        assert_bits_equal(10.0 * math.log10(f_sq), nf.nf_db(v), f"vs lna_nf dB {v=}")
        for t0 in T0S:
            for z in ZS_REAL:
                assert_bits_equal(
                    10 * math.log10(hrf.noise_factor_from_inoise(v, t0, z)),
                    ms.nf_db_from_inoise(v, t0, z), f"vs matchstudy {v=} {t0=} {z=}")
            for zs in ZS_COMPLEX:
                assert_bits_equal(
                    hrf.noise_factor_from_inoise(v, t0, zs.real),
                    kaband.measured_noise_factor(v, zs, t0),
                    f"vs kaband measured {v=} {t0=} {zs=}")
                fit = {"a": v * v, "b": 0.0, "c": 0.0, "d": 0.0}
                assert_bits_equal(
                    hrf.noise_factor_from_inoise_sq(v * v, t0, zs.real),
                    kaband.noise_factor(fit, zs, t0),
                    f"vs kaband fit {v=} {t0=} {zs=}")


def test_lna_nf_squaring_divergence_is_recorded_not_smoothed():
    """lna_nf squares with ``** 2`` (libm pow); matchstudy and kaband square
    with ``*``. On libms whose pow is not correctly rounded for exponent 2
    the two squarings differ in the last bit for a small fraction of
    densities, so the four implementations do NOT agree bit-for-bit on
    every input today. Recorded here, not smoothed over: the shared
    division serves both conventions, each site keeps its own squaring
    (each side below must equal its own formula exactly), and the two
    disagree only where the squarings disagree."""
    rng = random.Random(262)
    for _ in range(20000):
        v = rng.uniform(1e-12, 1e-6)
        den = 4 * K_LITERAL * 300.15 * 50.0
        f_pow = nf.f_from_added_noise(v)  # lna_nf: v ** 2
        f_mul = kaband.measured_noise_factor(v, complex(50.0, 0.0), 300.15)  # v * v
        # each implementation equals its own formula bit-for-bit, always
        assert_bits_equal(f_pow, 1.0 + v ** 2 / den, f"pow side {v=}")
        assert_bits_equal(f_mul, 1.0 + v * v / den, f"multiply side {v=}")
        if v ** 2 == v * v:
            assert_bits_equal(f_pow, f_mul, f"squarings agree, F must too {v=}")


def test_pow_vs_multiply_divergence_reaches_f_concrete():
    """The concrete companion to the scan above: on this libm there are
    realistic densities where the pow-squared and multiply-squared F differ
    in the last bit (the division does not always absorb the squaring).
    Recorded so the lna_nf ``** 2`` preservation in its wrapper is understood
    as evidence-preservation, not style."""
    v = 8.202961983264469e-07
    assert v ** 2 != v * v
    f_pow = nf.f_from_added_noise(v)
    f_mul = kaband.measured_noise_factor(v, complex(50.0, 0.0), 300.15)
    assert _bits(f_pow) != _bits(f_mul), (f_pow, f_mul)


def test_t0_k_is_required_no_default():
    # A call that omits t0_k must be a TypeError, never a silently chosen
    # reference temperature (290 K IEEE vs 300.15 K is a deliberate split).
    with pytest.raises(TypeError):
        hrf.noise_factor_from_inoise(2.0e-9, 50.0)
    with pytest.raises(TypeError):
        hrf.noise_factor_from_inoise(2.0e-9, z_ohm=50.0)
    with pytest.raises(TypeError):
        hrf.noise_factor_from_inoise_sq(4e-18, 50.0)


def test_helper_itself_imposes_no_guard():
    # Per-site guards stay at the sites: lna_nf raises (pinned above), the
    # shared helper propagates so matchstudy/kaband keep their behaviour.
    assert math.isnan(hrf.noise_factor_from_inoise(float("nan"), 300.15, 50.0))
    assert math.isinf(hrf.noise_factor_from_inoise(float("inf"), 300.15, 50.0))
    assert math.isnan(hrf.noise_factor_from_inoise_sq(float("nan"), 300.15, 50.0))


def test_lna_nf_noise_reference_uses_the_shared_constant():
    assert_bits_equal(
        nf.noise_ref_w_per_hz(),
        4.0 * hrf.K_BOLTZMANN * nf.T0_K * nf.Z0_OHM, "noise_ref_w_per_hz")


def test_matchstudy_wrapper_keeps_backward_compatible_default():
    # The wrapper may keep its (300.15, 50) default for old callers; the
    # shared helper must not have one.
    assert_bits_equal(
        ms.nf_db_from_inoise(2.0e-9),
        ms.nf_db_from_inoise(2.0e-9, 300.15, 50.0), "wrapper default")


def test_nfmethod_uses_the_shared_constant():
    pytest.importorskip("numpy")
    import nfmethod

    assert nfmethod.K_B is hrf.K_BOLTZMANN


def test_fit_numerators_route_through_the_sq_variant_not_sqrt():
    """kaband's fitted ``sv`` is a variance (V^2/Hz), not a density: routing
    it through the density helper would need ``inoise = sqrt(sv)``, and that
    round-trip is not bit-exact for arbitrary-mantissa variances (real fit
    outputs). This concrete, realistic-magnitude case (recorded, not smoothed
    over) changes the final F -- which is why ``noise_factor_from_inoise_sq``
    exists and why the kaband fit site calls it instead."""
    sv = 8.925409107045308e-18
    t0, z = 290.0, 25.0
    den = 4 * K_LITERAL * t0 * z
    assert math.sqrt(sv) * math.sqrt(sv) != sv
    want = 1.0 + sv / den
    assert_bits_equal(
        hrf.noise_factor_from_inoise_sq(sv, t0, z), want, "sq helper = formula")
    through_sqrt = hrf.noise_factor_from_inoise(math.sqrt(sv), t0, z)
    assert _bits(through_sqrt) != _bits(want), (through_sqrt, want)
