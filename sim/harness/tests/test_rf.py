"""Characterization of the noiseless-source noise factor across its four
per-bench implementations, plus the shared ``harness.rf`` module (issue #262).

Issue #264 adds the second half: the single-bin DFT characterization that
pinned the two bench-local copies (``mixfeas.dft_bin``,
``linearity.window_dft``) against the shared survivor
``harness.rf.dft_bin`` BEFORE the wrappers were made to delegate -- the
magnitude agreement is asserted exact, so a recorded amplitude cannot move.

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
import platform
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
    SIM / "mixer-topology-feasibility",
    SIM / "lna-linearity",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import kaband  # noqa: E402
import linearity as lin  # noqa: E402
import lna_nf as nf  # noqa: E402
import linearity as L  # noqa: E402
import matchstudy as ms  # noqa: E402
import mixfeas as mf  # noqa: E402

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


#: The concrete density PR #275 recorded: zero-based draw index 1522 (the
#: 1523rd draw) of ``random.Random(262).uniform(1e-12, 1e-6)`` -- the first
#: draw of that stream whose pow-vs-multiply squaring divergence survives the
#: shared division and reaches the final ``F``. Tried first so a platform
#: where it still diverges exercises exactly this recorded evidence.
_RECORDED_PROBE = 8.202961983264469e-07

#: Fallback scan size, matching the companion scan above; the stream's first
#: F-diverging draw on the recording host is at index 1522, so the margin is
#: ~13x. A budget is counted in draws taken and must exceed index 1522 to
#: reach the recorded literal's position at all.
_SCAN_BUDGET = 20000


def _f_diverges(v) -> bool:
    """Does the pow-vs-multiply squaring divergence survive the shared
    division and reach the final ``F`` for this density? This -- not
    ``v ** 2 != v * v`` -- is the selection predicate: the shared division
    absorbs the last bit for ~6% of the densities whose squarings diverge,
    so a squaring-selected probe would flake the test's own ``F`` assert."""
    f_pow = nf.f_from_added_noise(v)  # lna_nf: v ** 2
    f_mul = kaband.measured_noise_factor(v, complex(50.0, 0.0), 300.15)  # v * v
    return _bits(f_pow) != _bits(f_mul)


def _find_f_diverging_density(predicate=_f_diverges):
    """Return a density whose pow-vs-multiply divergence reaches ``F``, or
    ``None`` if this platform's ``pow`` rounds the exponent-2 squaring
    correctly so no such density exists in the scanned stream. The recorded
    PR #275 probe is tried first; otherwise the same seeded stream the
    companion scan uses is searched within a bounded budget."""
    if predicate(_RECORDED_PROBE):
        return _RECORDED_PROBE
    rng = random.Random(262)
    for _ in range(_SCAN_BUDGET):
        v = rng.uniform(1e-12, 1e-6)
        if predicate(v):
            return v
    return None


def test_pow_vs_multiply_divergence_reaches_f_concrete():
    """The concrete companion to the scan above: on libms whose pow is not
    correctly rounded for exponent 2 there are realistic densities where the
    pow-squared and multiply-squared F differ in the last bit (the division
    does not always absorb the squaring). Recorded so the lna_nf ``** 2``
    preservation in its wrapper is understood as evidence-preservation, not
    style. The divergence is a property of the platform's pow, not of this
    repo's arithmetic: where no diverging probe exists the test skips with
    an explicit reason instead of asserting -- but wherever a probe is
    found, the claim that the divergence reaches F is hard-asserted."""
    v = _find_f_diverging_density()
    if v is None:
        pytest.skip(
            "no density in the seeded scan makes the pow-vs-multiply "
            "divergence reach F on this platform "
            f"({platform.platform()}, {sys.version})"
        )
    assert v ** 2 != v * v
    f_pow = nf.f_from_added_noise(v)
    f_mul = kaband.measured_noise_factor(v, complex(50.0, 0.0), 300.15)
    assert _bits(f_pow) != _bits(f_mul), (f_pow, f_mul, f"probe {v=!r}")


def test_probe_selector_returns_none_when_no_density_diverges():
    """The 'no diverging probe on this platform' branch, exercised without a
    second libc: a predicate that never diverges must exhaust the budget and
    return None (which the concrete test turns into a skip), never raise and
    never loop unboundedly."""
    calls = []

    def never(v):
        calls.append(v)
        return False

    assert _find_f_diverging_density(predicate=never) is None
    # the recorded probe was tried first, then the full seeded budget
    assert len(calls) == 1 + _SCAN_BUDGET
    assert calls[0] == _RECORDED_PROBE


def test_probe_selector_tries_the_recorded_probe_first():
    """A platform where the recorded literal still diverges must exercise
    exactly that number -- no silent renumbering of PR #275's evidence and
    no scan draws needed."""

    def only_recorded(v):
        return v == _RECORDED_PROBE

    assert _find_f_diverging_density(predicate=only_recorded) == _RECORDED_PROBE


def test_probe_selector_with_the_real_predicate_returns_the_recorded_probe():
    if not _f_diverges(_RECORDED_PROBE):
        pytest.skip(
            "the recorded probe does not diverge on this platform "
            f"({platform.platform()}, {sys.version})"
        )
    assert _find_f_diverging_density() == _RECORDED_PROBE


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


# ---------------------------------------------------------------------------
# Power / dB characterization (issue #263) -- written BEFORE the move, so a
# delegation that changes a number fails here instead of in a record.
# ---------------------------------------------------------------------------

#: Positive-finite power vectors (W) and dBm vectors shared by the power
#: tables; the edge probes are per-table below.
POWERS_W = (1e-15, 1e-12, 2.5e-9, 1e-6, 1e-3, 0.01, 1.0, 2.5, 100.0)
DBMS = (-30.0, -10.0, 0.0, 3.0, 10.0, 30.0)
#: Edge probes for watts->dBm: zero, negative, NaN, both infinities.
DBM_EDGES_W = (0.0, -1.0, float("nan"), float("inf"), float("-inf"))
#: Peak voltages and real resistances for the V^2/R tables.
VOLTS = (0.0, 1e-6, 0.025, 1.0, 3.0)
RS = (25.0, 50.0, 100.0)
#: dB-scale input probes: positive finite, zero, negative, NaN, +inf.
DB_INPUTS = (1e-6, 0.5, 2.0, 1e6, 0.0, -1.0, float("nan"), float("inf"))


def test_power_helpers_agree_on_the_positive_finite_domain():
    """Every former copy and the shared primitive are bit-identical on
    positive finite inputs -- the domain split B unifies."""
    for w in POWERS_W:
        assert_bits_equal(hrf.dbm_strict(w), mf.dbm(w), f"strict {w=}")
        assert_bits_equal(hrf.dbm_strict(w), lin.dbm_from_w(w), f"strict vs lin {w=}")
    for dbm_value in DBMS:
        assert_bits_equal(hrf.watts(dbm_value), mf.watts(dbm_value),
                          f"watts {dbm_value=}")
        assert_bits_equal(hrf.watts(dbm_value), lin.w_from_dbm(dbm_value),
                          f"watts vs lin {dbm_value=}")
    for v in VOLTS:
        for r in RS:
            assert_bits_equal(hrf.available_power_w(v, r), mf.available_power_w(v, r),
                              f"pav {v=} {r=}")
            assert_bits_equal(hrf.delivered_power_w(v, r), mf.delivered_power_w(v, r),
                              f"pdel {v=} {r=}")
    for p_dbm in DBMS:
        for r in RS:
            assert_bits_equal(hrf.v_open_peak_for(p_dbm, r), mf.v_open_peak_for(p_dbm, r),
                              f"vopen {p_dbm=} {r=}")
        assert_bits_equal(hrf.v_open_peak_for(p_dbm, hrf.Z0_OHM),
                          lin.vs_peak_from_pav_dbm(p_dbm), f"vopen vs lin {p_dbm=}")
    for vs in VOLTS:
        assert_bits_equal(
            hrf.dbm_strict(hrf.available_power_w(vs, hrf.Z0_OHM)),
            lin.pav_dbm_from_vs_peak(vs), f"pav_dbm vs lin {vs=}")
        assert_bits_equal(
            hrf.dbm_strict(hrf.delivered_power_w(vs, hrf.Z0_OHM)),
            lin.delivered_dbm(vs), f"delivered_dbm vs lin {vs=}")


def test_watts_to_dbm_edge_convention_is_repo_wide():
    """Issue #268 settled the watts->dBm edge convention split E left open:
    strict everywhere -- positive finite converts, zero and negative give
    ``-inf``, NaN propagates -- so ``mf.dbm`` and ``lin.dbm_from_w`` agree on
    every input, edges included, and linearity's former finite -400.0 floor
    (``linearity.NEG_INF_DBM``) is gone with the site. The canonical
    statement is ``sim/README.md`` -> "Watts-to-dBm edge convention"."""
    nan = float("nan")
    inf, minf = float("inf"), float("-inf")
    # Both former sites now agree with the shared primitive on every edge.
    for w in (*DBM_EDGES_W, -0.0, -1e-30):
        assert_bits_equal(hrf.dbm_strict(w), mf.dbm(w), f"strict edge {w=}")
        assert_bits_equal(hrf.dbm_strict(w), lin.dbm_from_w(w),
                          f"strict edge vs lin {w=}")
    assert mf.dbm(0.0) == minf
    assert mf.dbm(-1.0) == minf
    assert math.isnan(mf.dbm(nan))
    assert mf.dbm(inf) == inf
    assert mf.dbm(minf) == minf
    assert not hasattr(lin, "NEG_INF_DBM")
    # The floor primitive stays available as a named entry point for any
    # future site that needs one: the caller's floor is honoured verbatim
    # for every non-positive/NaN input, and no default floor exists.
    for floor in (-400.0, -300.0, 0.0):
        for w in (0.0, -1.0, nan, minf):
            assert hrf.dbm_floored(w, floor) == floor, (floor, w)
    with pytest.raises(TypeError):
        hrf.dbm_floored(0.5)  # no default floor: the caller must name it


def test_watts_edges_and_round_trips():
    inf, minf = float("inf"), float("-inf")
    assert hrf.watts(minf) == 0.0
    assert math.isnan(hrf.watts(float("nan")))
    assert hrf.watts(inf) == inf
    for w in POWERS_W:
        # log10/10** is not a bit-exact round trip at every mantissa; the
        # characterization claim is agreement between copies, and the
        # round trip to ~1 ulp.
        rt = hrf.watts(hrf.dbm_strict(w))
        assert rt == pytest.approx(w, rel=1e-14), (w, rt)
    for dbm_value in DBMS:
        rt = hrf.dbm_strict(hrf.watts(dbm_value))
        assert rt == pytest.approx(dbm_value, rel=1e-12, abs=1e-12), (dbm_value, rt)
        # The composed voltage round trip through the shared primitives.
        vs = hrf.v_open_peak_for(dbm_value, hrf.Z0_OHM)
        pav = hrf.dbm_floored(hrf.available_power_w(vs, hrf.Z0_OHM), -400.0)
        assert pav == pytest.approx(dbm_value, rel=1e-12, abs=1e-12), (dbm_value, pav)


def test_available_vs_delivered_gap_is_exactly_10log10_4():
    for v in (0.025, 1.0, 3.0):
        for r in RS:
            pav = hrf.dbm_floored(hrf.available_power_w(v, r), -400.0)
            pdel = hrf.dbm_floored(hrf.delivered_power_w(v, r), -400.0)
            assert pdel - pav == pytest.approx(10.0 * math.log10(4.0), rel=1e-9), (v, r)
    # The issue's concrete probe: 1 V peak into 50 ohm delivers exactly 10 dBm.
    assert lin.delivered_dbm(1.0) == 10.0
    assert hrf.dbm_floored(hrf.delivered_power_w(1.0, hrf.Z0_OHM), -400.0) == 10.0


def test_db10_db20_delegation_preserves_each_guard():
    inf = float("inf")
    # db10 family: no guard -- zero/negative raise, NaN propagates as NaN.
    for x in DB_INPUTS:
        if math.isnan(x):
            assert math.isnan(kaband.db10(x)) and math.isnan(hrf.db10(x)), x
            continue
        try:
            want = hrf.db10(x)
        except ValueError:
            with pytest.raises(ValueError):
                kaband.db10(x)
            continue
        assert_bits_equal(kaband.db10(x), want, f"kaband db10 {x=}")
    with pytest.raises(ValueError):
        kaband.db10(0.0)
    with pytest.raises(ValueError):
        kaband.db10(-1.0)
    pytest.importorskip("numpy")
    import nfmethod

    assert_bits_equal(nfmethod.db(2.0), hrf.db10(2.0), "nfmethod db")
    with pytest.raises(ValueError):
        nfmethod.db(0.0)
    assert math.isnan(nfmethod.db(float("nan")))
    # db20 family: non-positive magnitude (including NaN) floors to -inf.
    for x in DB_INPUTS:
        assert_bits_equal(ms.db20(x), hrf.db20(x), f"matchstudy db20 {x=}")
    assert ms.db20(0.0) == float("-inf")
    # Negative amplitudes are legitimate inputs: db20 takes abs first, so
    # |x| > 0 converts normally; the -inf floor is for zero/NaN magnitude.
    assert ms.db20(-1.0) == 0.0
    assert ms.db20(complex(0.0, 0.0)) == float("-inf")
    assert ms.db20(float("nan")) == float("-inf")  # nan > 0 is False
    assert ms.db20(inf) == inf
    assert_bits_equal(ms.db20(complex(3.0, 4.0)), hrf.db20(5.0), "db20 complex")


def test_z0_is_declared_exactly_once_and_shared_by_identity():
    hits = []
    for path in sorted(SIM.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"Z0_OHM\s*=", line):
                hits.append(f"{path.relative_to(SIM)}:{lineno}")
    assert len(hits) == 1, hits
    assert hits[0].startswith(str(Path("harness") / "rf.py") + ":"), hits
    # Every bench's public name binds the same object -- no re-declaration
    # hiding behind an import.
    assert mf.Z0_OHM is hrf.Z0_OHM
    assert lin.Z0_OHM is hrf.Z0_OHM
    assert nf.Z0_OHM is hrf.Z0_OHM

# Single-bin DFT characterization (issue #264): the two bench-local copies
# vs the shared survivor. The magnitude-agreement vectors were run GREEN
# before either wrapper was made to delegate; they stay as the regression
# guard after.
# ---------------------------------------------------------------------------

#: Issue #264's own waveform: ``0.37 * sin(2 pi 5 t + 0.9)``, 200 samples at
#: dt = 0.005 s (a 1 s window -- 5 periods, coherent). The deck-verified
#: survivor convention reads it as a*(sin(phi) + j cos(phi)).
_A, _F, _PHI, _N, _DT = 0.37, 5.0, 0.9, 200, 0.005
COHERENT = [_A * math.sin(2 * math.pi * _F * k * _DT + _PHI) for k in range(_N)]


def test_dft_bin_pins_the_deck_kernel_convention_on_a_known_wave():
    z = hrf.dft_bin(COHERENT, _DT, _F)
    # The exact bits this stated construction yields (the issue's scratch
    # script built its samples with k/200 division and so reported the same
    # convention in slightly different last bits); the survivor adopts
    # mixfeas's kernel, which the agreement test pins bit-for-bit on
    # identical inputs.
    assert_bits_equal(z.real, 0.2898309565621686, "issue-wave re (cos-referenced)")
    assert_bits_equal(z.imag, 0.22999568826014602, "issue-wave im (+sine member)")
    # The docstring's worked example, independent of the pinned bits: the
    # conjugate kernel would flip the imaginary sign and fail hard.
    assert z.real == pytest.approx(_A * math.sin(_PHI), rel=1e-12)
    assert z.imag == pytest.approx(_A * math.cos(_PHI), rel=1e-12)
    assert abs(z) == pytest.approx(_A, rel=1e-12)
    assert hrf.dft_bin_amplitude(COHERENT, _DT, _F) == pytest.approx(_A, rel=1e-12)


def test_single_bin_dft_magnitude_agrees_across_all_three_implementations():
    """Exact magnitude agreement between mixfeas's copy, linearity's copy and
    the survivor over every characterization vector -- written before the
    wrappers delegated, kept after as the no-recorded-number-moved proof."""
    incoherent = [0.6 * math.sin(2 * math.pi * 5.37 * k * _DT + 0.2) for k in range(_N)]
    dc_offset = [0.25 + v for v in COHERENT]
    cases = [
        # (label, samples, dt, freq, t0) -- coherent known bin, deliberately
        # incoherent bin, DC offset on a tone, the DC bin itself, a non-zero
        # window start, and a single-sample "window".
        ("coherent", COHERENT, _DT, _F, 0.0),
        ("incoherent", incoherent, _DT, 5.37, 0.0),
        ("dc-offset tone", dc_offset, _DT, _F, 0.0),
        ("dc bin", dc_offset, _DT, 0.0, 0.0),
        ("nonzero t0", COHERENT, _DT, _F, 0.1),
        ("single sample", [0.8], 0.005, 5.0, 0.0),
    ]
    for label, samples, dt, f, t0 in cases:
        got_c = mf.dft_bin(samples, dt, f, t0)  # legacy complex reference
        got_m = L.window_dft(samples, dt, f, t0)  # legacy magnitude reference
        z = hrf.dft_bin(samples, dt, f, t0)
        amp = hrf.dft_bin_amplitude(samples, dt, f, t0)
        assert isinstance(got_c, complex) and isinstance(got_m, float), label
        assert isinstance(z, complex) and isinstance(amp, float), label
        # linearity's copy == the survivor's amplitude accessor, bit-for-bit
        # (same 2*hypot(re, im)/n scale-and-divide order its numbers carry).
        assert_bits_equal(got_m, amp, f"window_dft == dft_bin_amplitude ({label})")
        # mixfeas's copy == the survivor's complex bin, bit-for-bit.
        assert_bits_equal(got_c.real, z.real, f"dft_bin re ({label})")
        assert_bits_equal(got_c.imag, z.imag, f"dft_bin im ({label})")
        # three-way magnitude agreement (abs vs the accessor rounds once
        # vs twice, so approx here; the exact pins are the two above).
        assert abs(z) == pytest.approx(amp, rel=1e-12), label
        assert got_m == pytest.approx(abs(got_c), rel=1e-12), label


def test_single_bin_dft_empty_input_raises_the_shared_exception():
    for call in (
        lambda: hrf.dft_bin([], _DT, _F),
        lambda: hrf.dft_bin_amplitude([], _DT, _F),
        lambda: mf.dft_bin([], _DT, _F),
        lambda: L.window_dft([], _DT, _F),
    ):
        with pytest.raises(ValueError, match="no samples"):
            call()


def test_legacy_wrappers_delegate_with_unchanged_contracts():
    """Post-delegation guard: both bench entry points stay thin (same
    signatures and return types) and answer bit-identically to the survivor
    they now call."""
    z = mf.dft_bin(COHERENT, _DT, _F, 0.0)
    assert_bits_equal(z.real, hrf.dft_bin(COHERENT, _DT, _F, 0.0).real, "mixfeas re")
    assert_bits_equal(z.imag, hrf.dft_bin(COHERENT, _DT, _F, 0.0).imag, "mixfeas im")
    m = L.window_dft(COHERENT, _DT, _F, 0.0)
    assert_bits_equal(m, hrf.dft_bin_amplitude(COHERENT, _DT, _F, 0.0), "linearity amp")
    # the sign-sensitive consumer shape the parser tests use (fake-log
    # mf_<name>_re/_im pairs from z.real/z.imag) keeps mixfeas's convention:
    # the imaginary member is the deck's +sine term, positive here (phi=0.9).
    assert z.imag > 0.0 and z.real > 0.0
