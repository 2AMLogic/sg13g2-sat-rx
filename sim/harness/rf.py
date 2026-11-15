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

EXTENSION POINT -- noise- and dB-scale arithmetic that more than one bench
needs lands here; issue #257's later splits extend this module in place
(power/dB conversions, a single-bin reference DFT). Deliberately NOT here:

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
