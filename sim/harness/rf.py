"""Shared RF physics arithmetic: the Boltzmann constant and the
noiseless-source noise factor.

GENERIC CORE:

- :data:`K_BOLTZMANN` -- the SI-2019 exact Boltzmann constant, J/K. The
  single declaration in the tree: benches import it instead of re-declaring
  it, so a future edit cannot make one bench's arithmetic silently diverge
  from another's (issue #262 consolidated four identical copies).
- :func:`noise_factor_from_inoise` -- ``F = 1 + inoise^2 / (4 k T0 Z)`` for
  a noiseless reference source of resistance ``z_ohm`` held at ``t0_k``:
  the input-referred noise density, squared, over the source's own thermal
  noise power density.
- :func:`noise_factor_from_inoise_sq` -- the same division with the density
  already squared (V^2/Hz). This is the primitive every noise-factor site
  shares; the density form squares with ``inoise * inoise``, which is the
  correctly-rounded, platform-independent convention (matchstudy's and
  kaband's).

POWER / dB CONVERSIONS (issue #263, split B of #257):

- :data:`Z0_OHM` -- the reference system impedance (ohm). The single
  declaration in the tree: benches import it instead of re-declaring it
  (it consolidated three identical copies; the local ``Z0`` in a test
  fixture and a stdlib-only script stay local on purpose).
- :func:`db10` / :func:`db20` -- the power / amplitude dB scales, each
  carrying ONE stated zero convention (``db10`` guards nothing;
  ``db20`` floors non-positive magnitudes -- including NaN -- to -inf).
- :func:`dbm_strict` / :func:`dbm_floored` -- watts to dBm under the two
  live edge conventions, named so the choice is visible at the call site:
  ``dbm_strict`` (NaN propagates, -inf at zero) and ``dbm_floored`` (the
  caller's required ``floor`` swallows zero, negative and NaN). Which
  convention a record rests on is split E of #257's decision; until then
  every existing site keeps its own, and this module provides both
  without preferring either.
- :func:`watts`, :func:`available_power_w`, :func:`v_open_peak_for`,
  :func:`delivered_power_w` -- the power arithmetic both power benches
  shared bit-for-bit under two naming schemes (available power
  ``V^2/(8R)``, delivered ``V^2/(2R)``). The resistance is always an
  explicit argument: no default impedance is baked in here.

EXTENSION POINT -- remaining shared arithmetic lands here; issue #257's
later splits extend this module in place (a single-bin reference DFT).
Deliberately NOT here:

- **No default ``t0_k``.** Benches use different reference temperatures on
  purpose (290 K IEEE at ``sim/hbt-kaband-characterization`` vs 300.15 K
  elsewhere; that bench's run prints the two side by side), so ``t0_k`` is
  a required argument and a call that omits it is a TypeError rather than
  a silently chosen reference.
- **No input guard.** Whichever non-finite behaviour a bench has today
  stays at that bench: lna-sparam-nf raises at its own call sites,
  matchstudy and kaband propagate. This helper imposes neither, so the
  consolidated arithmetic cannot average the two behaviours away.
- **One squaring per caller.** lna-sparam-nf squares its density with
  ``** 2`` (libm ``pow``), which on some libms is not the correctly-rounded
  square and can differ from ``inoise * inoise`` in the last bit; its
  recorded numbers carry that convention, so it keeps its own squaring and
  passes ``inoise ** 2`` to :func:`noise_factor_from_inoise_sq`.
  ``sim/harness/tests/test_rf.py`` records this divergence with concrete
  inputs instead of smoothing it over.

Everything is pure Python (stdlib only) so ``tests/`` can exercise it
against known answers.
"""

from __future__ import annotations

import math

#: Boltzmann constant, J/K (exact, SI 2019).
K_BOLTZMANN = 1.380649e-23


def noise_factor_from_inoise(inoise: float, t0_k: float, z_ohm: float) -> float:
    """Noise factor ``F = 1 + inoise^2 / (4 k T0 Z)``.

    ``inoise`` is the input-referred noise density of a noiseless source
    (V/sqrt(Hz)); ``t0_k`` is the reference temperature the source's own
    thermal noise is evaluated at (K, REQUIRED -- no default); ``z_ohm``
    is the real source resistance (ohm -- a complex source impedance
    passes ``zs.real`` explicitly at the call site).

    Squares with ``inoise * inoise`` (correctly rounded on every platform).
    No finite-input guard: benches keep their own.
    """
    return noise_factor_from_inoise_sq(inoise * inoise, t0_k, z_ohm)


def noise_factor_from_inoise_sq(inoise_sq: float, t0_k: float, z_ohm: float) -> float:
    """The shared division with the density already squared (V^2/Hz).

    Two callers need this form rather than :func:`noise_factor_from_inoise`:
    kaband's fit-derived numerator ``sv`` is a variance, not a density
    (routing it through ``sqrt`` would be a lossy round-trip that moves
    recorded fit deltas -- test_rf.py records a concrete case), and
    lna-sparam-nf preserves its own ``** 2`` squaring (see the module
    docstring). ``t0_k`` is REQUIRED -- no default.
    """
    return 1.0 + inoise_sq / (4.0 * K_BOLTZMANN * t0_k * z_ohm)


#: Reference system impedance, ohm -- the single declaration in the tree
#: (issue #263 consolidated three identical copies). Benches import this;
#: the local ``Z0`` in a test fixture and a stdlib-only script stays local
#: on purpose.
Z0_OHM = 50.0


# ---------------------------------------------------------------------------
# dB scale
# ---------------------------------------------------------------------------


def db10(x: float) -> float:
    """Power ratio in dB: ``10 log10(x)``.

    Zero convention (kaband's and nfmethod's, shared verbatim): NO guard.
    Zero or negative raises ValueError (math domain error); NaN propagates
    as NaN (``math.log10`` passes NaN through); +inf propagates as +inf.
    """
    return 10.0 * math.log10(x)


def db20(x: complex | float) -> float:
    """Amplitude ratio in dB: ``20 log10(|x|)``.

    Zero convention (matchstudy's, shared verbatim): ``|x| <= 0`` returns
    -inf -- and NaN floors to -inf too, because ``nan > 0`` is false;
    +inf propagates as +inf. Accepts complex amplitudes (``abs`` first).
    """
    a = abs(x)
    return 20.0 * math.log10(a) if a > 0 else float("-inf")


# ---------------------------------------------------------------------------
# Power / dBm conversions
# ---------------------------------------------------------------------------


def dbm_strict(power_w: float) -> float:
    """Power in dBm, strict edge convention (mixfeas's, shared verbatim).

    Exactly zero or negative returns -inf; NaN PROPAGATES (the explicit
    ``power_w != power_w`` branch); +inf propagates. The strict sibling of
    :func:`dbm_floored` -- which convention a record rests on is chosen by
    the name at the call site, never by a policy default here.
    """
    if power_w != power_w:  # NaN
        return float("nan")
    if power_w <= 0.0:
        return float("-inf")
    return 10.0 * math.log10(power_w / 1e-3)


def dbm_floored(power_w: float, floor: float) -> float:
    """Power in dBm with the caller's floor (linearity's convention).

    Zero, negative AND NaN all return ``floor`` -- the NaN case because
    ``power_w > 0`` is false for NaN; +inf propagates. ``floor`` is
    REQUIRED with no default: which floor a bench pins (linearity passes
    its ``NEG_INF_DBM``) is split E of #257's decision, not something this
    helper chooses.
    """
    if power_w > 0.0:
        return 10.0 * math.log10(power_w / 1e-3)
    return floor


def watts(dbm_value: float) -> float:
    """dBm to watts: ``1e-3 * 10 ** (dbm/10)``. No guard: -inf gives 0.0,
    NaN propagates, +inf propagates (both former copies agreed)."""
    return 1e-3 * 10.0 ** (dbm_value / 10.0)


def available_power_w(v_open_peak: float, r_source: float) -> float:
    """Available power of a Thevenin source (peak open-circuit voltage,
    real source resistance): ``V^2 / (8 R)``. No guard: NaN propagates."""
    return v_open_peak * v_open_peak / (8.0 * r_source)


def v_open_peak_for(dbm_value: float, r_source: float) -> float:
    """Inverse of :func:`available_power_w` for a power in dBm:
    ``sqrt(8 R watts(dbm))``."""
    return math.sqrt(8.0 * r_source * watts(dbm_value))


def delivered_power_w(v_peak: float, r_load: float) -> float:
    """Power delivered into a resistor by a sine of peak amplitude
    ``v_peak``: ``V^2 / (2 R)`` -- exactly ``10 log10(4)`` dB (6.02 dB)
    more than the available power of the same peak voltage behind the same
    resistance. No guard: NaN propagates."""
    return v_peak * v_peak / (2.0 * r_load)
