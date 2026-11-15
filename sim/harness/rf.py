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
- :func:`dft_bin` -- the single reference single-bin DFT of uniformly
  sampled data, normalised so a coherent sine reads its peak amplitude and
  carrying the kernel sign the generated ngspice decks actually emit
  (issue #264 unified the two bench-local copies, which disagreed on the
  imaginary sign while both docstrings claimed to state the same deck
  quantity).
- :func:`dft_bin_amplitude` -- the same bin's single-sided peak amplitude,
  computed from the same accumulators so the magnitude is bit-identical to
  the retired ``linearity.window_dft`` arithmetic.

EXTENSION POINT -- noise- and dB-scale arithmetic that more than one bench
needs lands here; issue #257's later splits extend this module in place
(power/dB conversions). Deliberately NOT here:

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


# ---------------------------------------------------------------------------
# Single-bin reference DFT
# ---------------------------------------------------------------------------


def _dft_bin_acc(samples: list[float], dt: float, freq_hz: float,
                 t0: float) -> tuple[int, float, float]:
    """Shared accumulator for :func:`dft_bin` and :func:`dft_bin_amplitude`.

    The accumulate-in-floats form (not ``cmath.exp``): it is the form the
    generated decks mirror -- ``2*mean(x*cos(w t))`` beside
    ``2*mean(x*sin(w t))`` -- and it avoids a complex-exponential call per
    sample. Raises :class:`ValueError` on empty input.
    """
    n = len(samples)
    if n == 0:
        raise ValueError("no samples")
    re_acc = im_acc = 0.0
    w = 2.0 * math.pi * freq_hz
    for k, x in enumerate(samples):
        ph = w * (k * dt + t0)
        re_acc += x * math.cos(ph)
        im_acc += x * math.sin(ph)
    return n, re_acc, im_acc


def dft_bin(samples: list[float], dt: float, freq_hz: float, t0: float = 0.0) -> complex:
    """Single-bin DFT of uniformly sampled data: the tree's one reference
    implementation (issue #264 unified ``mixfeas.dft_bin`` and
    ``linearity.window_dft``, which disagreed on the imaginary sign while
    both docstrings claimed to state the same deck quantity).

    KERNEL CONVENTION, stated against a worked example and verified against
    the generated deck text (not either retired docstring, which the deck
    check proved unreliable): for

        x[k] = a * sin(2 pi f (k dt + t0) + phi)

    on a coherent bin -- ``n`` samples spanning an integer number of periods
    of ``freq_hz`` -- the return is

        a * (sin(phi) + j * cos(phi))

    e.g. for ``a=0.37, phi=0.9`` on 200 samples at ``dt=0.005`` (samples
    built as ``0.37*sin(2 pi 5 k dt + 0.9)``) it reads
    ``(0.2898309565621686+0.22999568826014602j)``, asserted bit-for-bit in
    ``sim/harness/tests/test_rf.py`` (the last bits of the return track the
    bits of the samples themselves -- a script that builds ``t = k/200`` by
    division instead of ``k*dt`` differs in the last places; the signs and
    the magnitude convention do not move). ``abs()`` is
    the single-sided peak amplitude ``a``; ``atan2(im, re)`` is the phase in
    that (cos-reflected) frame. The kernel accumulates

        (2/n) * sum x[k] * exp(+j 2 pi f (k dt + t0))

    which is literally the ``re``/``im`` pair both campaigns' decks emit
    (``mixfeas.py`` ``mf_<name>_re``/``mf_<name>_im``, ``linearity.py``
    ``m_<rid>_<name>_c``/``m_<rid>_<name>_s``: ``2*mean(x*cos(w t))`` beside
    ``2*mean(x*sin(w t))``). ``linearity``'s retired kernel was the conjugate
    ``exp(-j w t)`` -- identical magnitudes, opposite imaginary sign, which is
    why every recorded magnitude survived the unification unchanged.

    Raises ``ValueError("no samples")`` on empty input (the deliberate guard
    ``mixfeas`` already had; ``linearity.window_dft`` previously divided by
    zero there instead).
    """
    n, re_acc, im_acc = _dft_bin_acc(samples, dt, freq_hz, t0)
    return complex(2.0 * re_acc / n, 2.0 * im_acc / n)


def dft_bin_amplitude(samples: list[float], dt: float, freq_hz: float,
                      t0: float = 0.0) -> float:
    """Single-sided peak amplitude at ``freq_hz``: the magnitude of
    :func:`dft_bin` for callers that do not consume the complex value.

    Computed from the same accumulators as ``2.0 * hypot(re, im) / n``
    rather than as ``abs(dft_bin(...))`` -- scaling before ``hypot`` rounds
    twice where this form rounds once, so this reproduces the retired
    ``linearity.window_dft`` arithmetic bit-for-bit and no recorded
    amplitude can move. Same empty-input ``ValueError("no samples")``.
    """
    n, re_acc, im_acc = _dft_bin_acc(samples, dt, freq_hz, t0)
    return 2.0 * math.hypot(re_acc, im_acc) / n
