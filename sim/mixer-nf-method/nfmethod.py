"""Mixer SSB noise-figure method: estimator, accounting and status gates (issue #27).

This module is the *definition* of the method in README.md, written so that
each convention is enforced by code and exercised by tests on analytic
fixtures (``tests/test_nfmethod.py``). It never runs a simulator; the
capability probe (``run_probe.py``) does that once and feeds its findings into
:func:`decide_status`.

Conventions (README.md "Definitions" derives each one):

* One-sided PSD, W/Hz (or V^2/Hz into a stated resistance), from a windowed
  periodogram normalised by the window power ``sum(w^2)`` so that the integral
  over 0..fs/2 equals the sample variance (Parseval). DC and Nyquist bins are
  not doubled. Equivalent noise bandwidth is reported in bins and in Hz.
* SSB noise factor (IEEE): ``F_SSB = N_out / (k T0 B G_w)`` where ``N_out`` is
  the delivered IF noise power in bandwidth ``B`` with the source termination
  at T0 in BOTH the wanted and the image sideband, and ``G_w`` is the available
  power gain from the wanted RF sideband to the IF load. Image noise is part of
  ``N_out``; it is never dropped, and a DSB figure is never substituted.
* T0 = 300.15 K (same reference as the corrected LNA bench, issue #22).

Statuses (exactly one per record):

* ``METHOD_VALIDATION``      every coverage gate, control and convergence gate
                             passed. Methodology evidence only, never a row-10 or
                             row-12 compliance number.
* ``MODEL_ABSENT``           a noise mechanism the method needs is not generated
                             by the simulator in LO-driven transient operation
                             (or its coverage cannot be established).
* ``UNCONVERGED``            coverage and controls pass but the seed / duration /
                             timestep gates do not, within the permitted
                             duration doublings.
* ``CAPABILITY_UNAVAILABLE`` the simulator executable / runner could not be run;
                             this can never establish model absence.

Accounting errors (omitted image term, invalid PSD normalisation, a failed
analytic known-answer control) are *defects in the estimator*, not outcomes:
they raise and no record is written.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Iterable, Mapping, Sequence

import numpy as np

K_B = 1.380649e-23  # J/K (exact, SI 2019)
T0_K = 300.15       # reference temperature, K (27 C)

METHOD_VALIDATION = "METHOD_VALIDATION"
MODEL_ABSENT = "MODEL_ABSENT"
UNCONVERGED = "UNCONVERGED"
CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
STATUSES = (METHOD_VALIDATION, MODEL_ABSENT, UNCONVERGED, CAPABILITY_UNAVAILABLE)

SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
UNKNOWN = "unknown"

# Methodology qualification limits (issue #27 step 4/5). Not row-10 limits.
CONTROL_TOL_DB = 0.25
CI_HALFWIDTH_MAX_DB = 0.25
DELTA_DURATION_MAX_DB = 0.25
DELTA_TIMESTEP_MAX_DB = 0.25
MIN_SEEDS = 8
MAX_DURATION_DOUBLINGS = 3

# Transient-domain mechanisms an active-mixer SSB NF needs. Every one must be
# SUPPORTED (generated during LO-driven .tran) for METHOD_VALIDATION.
REQUIRED_TRAN_MECHANISMS = (
    "hbt_shot_collector",        # VBIC _ic
    "hbt_shot_base",             # VBIC _ib (and _ibep)
    "hbt_terminal_resistor_thermal",  # VBIC _rb/_rbi/_rbp/_rc/_rci/_re/_rs
    "hbt_flicker",               # VBIC _1overfbe/_1overfbep
    "resistor_thermal",          # bias / load / source-termination resistors
)


class MethodError(ValueError):
    """An estimator/accounting defect: never converted into a record status."""


class NormalizationError(MethodError):
    pass


class ImageAccountingError(MethodError):
    pass


# --------------------------------------------------------------------------
# PSD estimation and bandwidth normalisation
# --------------------------------------------------------------------------

def window(name: str, n: int) -> np.ndarray:
    if name == "rect":
        return np.ones(n)
    if name == "hann":
        # periodic Hann (DFT-even), the usual choice for spectral estimation
        return 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)
    raise NormalizationError(f"unknown window {name!r}")


def enbw_bins(w: np.ndarray) -> float:
    """Equivalent noise bandwidth of window ``w`` in DFT bins: N sum(w^2)/sum(w)^2."""
    return len(w) * float(np.sum(w * w)) / float(np.sum(w)) ** 2


def one_sided_psd(x: Sequence[float], fs: float, win: str = "hann",
                  detrend: bool = True) -> tuple[np.ndarray, np.ndarray, dict]:
    """One-sided periodogram PSD of a uniformly sampled record.

    Returns ``(f, psd, meta)``. Normalisation: ``psd = c |X_k|^2 / (fs sum w^2)``
    with ``c = 2`` for 0 < k < N/2 and ``c = 1`` for DC and Nyquist, so that
    ``sum(psd) * df`` equals the mean-square of the (windowed-power-corrected)
    record. ``meta`` carries ``df``, ``enbw_bins`` and ``enbw_hz``.
    """
    x = np.asarray(x, dtype=float)
    n = x.size
    if n < 16:
        raise NormalizationError("record too short for a PSD estimate")
    if not (fs > 0 and math.isfinite(fs)):
        raise NormalizationError("sample rate must be positive and finite")
    if detrend:
        x = x - x.mean()
    w = window(win, n)
    spec = np.fft.rfft(x * w)
    psd = (np.abs(spec) ** 2) / (fs * float(np.sum(w * w)))
    scale = np.full(psd.shape, 2.0)
    scale[0] = 1.0
    if n % 2 == 0:
        scale[-1] = 1.0
    psd = psd * scale
    f = np.fft.rfftfreq(n, d=1.0 / fs)
    df = fs / n
    eb = enbw_bins(w)
    return f, psd, {"df_hz": df, "enbw_bins": eb, "enbw_hz": eb * df, "n": n,
                    "fs_hz": fs, "window": win, "one_sided": True}


def check_parseval(x: Sequence[float], psd: np.ndarray, meta: Mapping, rtol: float = 0.05) -> float:
    """Reject a PSD whose integral does not reproduce the record's variance.

    A two-sided PSD, a missing window-power correction or a wrong ``df`` all
    fail this check. Returns the ratio integral/variance.
    """
    x = np.asarray(x, dtype=float)
    var = float(np.var(x))
    if var <= 0:
        raise NormalizationError("zero-variance record: nothing to normalise")
    if not meta.get("one_sided"):
        raise NormalizationError("PSD is not declared one-sided")
    integral = float(np.sum(psd) * meta["df_hz"])
    ratio = integral / var
    if abs(ratio - 1.0) > rtol:
        raise NormalizationError(
            f"PSD integral / variance = {ratio:.4f} (expected 1 within {rtol}); "
            "two-sided, window-uncorrected or mis-scaled PSD")
    return ratio


def band_power(f: np.ndarray, psd: np.ndarray, meta: Mapping, f_lo: float, f_hi: float,
               min_enbw_multiple: float = 4.0) -> tuple[float, float]:
    """Integrate a one-sided PSD over [f_lo, f_hi]; returns (power, bandwidth_hz).

    The band must lie strictly inside (0, fs/2) and span at least
    ``min_enbw_multiple`` window ENBWs, otherwise window leakage, not the
    noise, sets the answer and the estimate is rejected.
    """
    if not meta.get("one_sided"):
        raise NormalizationError("band_power needs a one-sided PSD")
    nyq = meta["fs_hz"] / 2.0
    if not (0.0 < f_lo < f_hi < nyq):
        raise NormalizationError(f"band [{f_lo}, {f_hi}] Hz not inside (0, fs/2={nyq})")
    if (f_hi - f_lo) < min_enbw_multiple * meta["enbw_hz"]:
        raise NormalizationError(
            f"band {f_hi - f_lo:.4g} Hz narrower than {min_enbw_multiple} x ENBW "
            f"({meta['enbw_hz']:.4g} Hz)")
    sel = (f >= f_lo) & (f <= f_hi)
    nb = int(np.count_nonzero(sel))
    bw = nb * meta["df_hz"]
    return float(np.sum(psd[sel]) * meta["df_hz"]), bw


# --------------------------------------------------------------------------
# SSB / image accounting
# --------------------------------------------------------------------------

@dataclasses.dataclass
class NoiseBudget:
    """Delivered IF noise in bandwidth ``bandwidth_hz`` and its declared parts.

    ``gain_wanted``/``gain_image``: available-power gain (linear) from the
    wanted / image RF sideband to the IF load. ``gain_image`` must be declared
    (0.0 for an image-rejecting front end); ``None`` is an omission and is
    rejected. ``contributions``: W in band, keys ``source_wanted``,
    ``source_image``, ``dut``, ``load`` (others allowed). ``t_source_*_k``: the
    physical temperatures of the source termination in each sideband during
    the run; the estimator re-references them to T0.
    """

    bandwidth_hz: float
    gain_wanted: float
    gain_image: float | None
    n_out_w: float
    contributions: Mapping[str, float]
    t_source_wanted_k: float = T0_K
    t_source_image_k: float = T0_K
    accounting_rtol: float = 1e-3


def _validate_budget(b: NoiseBudget) -> None:
    if not (b.bandwidth_hz > 0 and math.isfinite(b.bandwidth_hz)):
        raise NormalizationError("bandwidth must be positive and finite")
    if not (b.gain_wanted > 0):
        raise MethodError("wanted-sideband gain must be positive")
    if b.gain_image is None:
        raise ImageAccountingError(
            "image-sideband gain not declared: SSB F needs the image term "
            "(declare 0.0 explicitly for an image-rejecting front end)")
    if b.gain_image < 0:
        raise ImageAccountingError("image-sideband gain must be >= 0")
    for key in ("source_wanted", "dut", "load"):
        if key not in b.contributions:
            raise MethodError(f"noise contribution {key!r} not accounted")
    if b.gain_image > 0 and "source_image" not in b.contributions:
        raise ImageAccountingError(
            "image sideband has gain but its source-noise contribution is missing")
    total = float(sum(b.contributions.values()))
    if not math.isclose(total, b.n_out_w, rel_tol=b.accounting_rtol):
        raise MethodError(
            f"contributions sum {total:.6g} W != measured N_out {b.n_out_w:.6g} W")


def n_out_at_t0(b: NoiseBudget, t0: float = T0_K) -> float:
    """N_out re-referenced to a source termination at T0 in both sidebands."""
    _validate_budget(b)
    kb = K_B * b.bandwidth_hz
    return (b.n_out_w
            - kb * (b.t_source_wanted_k - t0) * b.gain_wanted
            - kb * (b.t_source_image_k - t0) * b.gain_image)


def ssb_noise_factor(b: NoiseBudget, t0: float = T0_K) -> float:
    """IEEE SSB noise factor (wanted-sideband gain, image noise included)."""
    return n_out_at_t0(b, t0) / (K_B * t0 * b.bandwidth_hz * b.gain_wanted)


def dsb_noise_factor(b: NoiseBudget, t0: float = T0_K) -> float:
    """DSB noise factor (signal in both sidebands). Reported only beside, and
    labelled as, DSB; never substituted for the SSB figure."""
    return n_out_at_t0(b, t0) / (K_B * t0 * b.bandwidth_hz * (b.gain_wanted + b.gain_image))


def db(x: float) -> float:
    return 10.0 * math.log10(x)


def attenuator_ideal_mixer_f_ssb(loss: float, t_att_k: float, gain_wanted: float,
                                 gain_image: float, t0: float = T0_K) -> float:
    """Known answer: matched attenuator (loss L >= 1, physical temperature
    T_att) ahead of a noiseless mixer with sideband gains G_w, G_i; source at T0.

    F_SSB = (1 + G_i/G_w) * (1 + (L - 1) T_att / T0)
    (equal sidebands, T_att = T0: F_SSB = 2L, i.e. 3.01 dB + L_dB).
    """
    if loss < 1:
        raise MethodError("attenuator loss must be >= 1")
    return (1.0 + gain_image / gain_wanted) * (1.0 + (loss - 1.0) * t_att_k / t0)


def y_factor_f_ssb(y: float, t_hot_k: float, t_cold_k: float, gain_wanted: float,
                   gain_image: float | None, t0: float = T0_K) -> float:
    """SSB F from a Y-factor whose hot/cold source temperature is applied in
    BOTH sidebands (a broadband termination). The measured equivalent
    temperature is DSB-referred, ``Te = (T_hot - Y T_cold)/(Y - 1)``, and is
    converted to the SSB reference with the declared sideband gain ratio:
    ``F_SSB = (1 + G_i/G_w)(1 + Te/T0)``.
    """
    if gain_image is None:
        raise ImageAccountingError("Y-factor conversion to SSB needs the image gain")
    if not y > 1:
        raise MethodError("Y must exceed 1")
    te = (t_hot_k - y * t_cold_k) / (y - 1.0)
    return (1.0 + gain_image / gain_wanted) * (1.0 + te / t0)


# --------------------------------------------------------------------------
# Statistics / convergence
# --------------------------------------------------------------------------

# two-sided 95 % Student-t quantiles, df = 1..30
_T975 = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
         2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
         2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042)


def t975(dof: int) -> float:
    if dof < 1:
        raise MethodError("need at least two seeds for an interval")
    return _T975[dof - 1] if dof <= 30 else 1.960


def nf_interval(f_lin_per_seed: Iterable[float]) -> dict:
    """95 % interval on the mean noise factor across independent seeds.

    Construction: Student-t on the per-seed linear F (seeds are independent
    records of equal length and bandwidth), half-width h = t * s / sqrt(n);
    the dB half-width is the larger of 10log10((m+h)/m) and 10log10(m/(m-h))
    (infinite if m - h <= 0).
    """
    vals = [float(v) for v in f_lin_per_seed]
    n = len(vals)
    if n < 2:
        raise MethodError("need at least two seeds for an interval")
    m = sum(vals) / n
    s = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))
    h = t975(n - 1) * s / math.sqrt(n)
    up = db((m + h) / m)
    dn = math.inf if m - h <= 0 else db(m / (m - h))
    return {"n_seeds": n, "mean_f": m, "nf_db": db(m), "halfwidth_lin": h,
            "halfwidth_db": max(up, dn), "construction": "student-t 95% on per-seed linear F"}


@dataclasses.dataclass
class Convergence:
    n_seeds: int
    ci_halfwidth_db: float
    delta_duration_db: float | None   # |NF(2T) - NF(T)|, timestep fixed
    delta_timestep_db: float | None   # |NF(dt/2) - NF(dt)|, duration fixed
    duration_doublings: int
    bandwidth_hz: float


def convergence_failures(c: Convergence | None) -> list[str]:
    if c is None:
        return ["no convergence evidence"]
    out = []
    if c.n_seeds < MIN_SEEDS:
        out.append(f"{c.n_seeds} seeds < {MIN_SEEDS}")
    if not (c.ci_halfwidth_db <= CI_HALFWIDTH_MAX_DB):
        out.append(f"95% half-width {c.ci_halfwidth_db:.3g} dB > {CI_HALFWIDTH_MAX_DB}")
    if c.delta_duration_db is None or not (abs(c.delta_duration_db) <= DELTA_DURATION_MAX_DB):
        out.append(f"duration-doubling change {c.delta_duration_db} dB not <= {DELTA_DURATION_MAX_DB}")
    if c.delta_timestep_db is None or not (abs(c.delta_timestep_db) <= DELTA_TIMESTEP_MAX_DB):
        out.append(f"timestep-halving change {c.delta_timestep_db} dB not <= {DELTA_TIMESTEP_MAX_DB}")
    if c.duration_doublings > MAX_DURATION_DOUBLINGS:
        out.append(f"{c.duration_doublings} duration doublings > {MAX_DURATION_DOUBLINGS}")
    if not (c.bandwidth_hz > 0):
        out.append("bandwidth not recorded")
    return out


# --------------------------------------------------------------------------
# Controls and status decision
# --------------------------------------------------------------------------

@dataclasses.dataclass
class Controls:
    """Outcomes of the step-4 controls; ``None`` = not executed.

    analytic_error_db        |NF_est - NF_analytic| for the attenuator +
                             ideal-mixer known answer (image included).
    lo_off_hbt_error_db      |NF_tran - NF_.noise| for the LO-off HBT control
                             in the same finite bandwidth.
    omission_detected        True when removing the intrinsic contribution
                             makes the LO-off control FAIL (required).
    periodic_coverage        True when an independent LO-driven internal-noise
                             control / model-level evidence passed.
    """

    analytic_error_db: float | None = None
    lo_off_hbt_error_db: float | None = None
    omission_detected: bool | None = None
    periodic_coverage: bool | None = None


def coverage_failures(inventory: Mapping[str, Mapping]) -> list[str]:
    out = []
    for mech in REQUIRED_TRAN_MECHANISMS:
        st = inventory.get(mech, {}).get("tran")
        if st != SUPPORTED:
            out.append(f"{mech}: transient generation {st or 'not inventoried'}")
    return out


def control_failures(c: Controls | None) -> list[str]:
    if c is None:
        return ["controls not executed"]
    out = []
    if c.lo_off_hbt_error_db is None or not (c.lo_off_hbt_error_db <= CONTROL_TOL_DB):
        out.append(f"LO-off HBT control vs .noise: {c.lo_off_hbt_error_db} dB (limit {CONTROL_TOL_DB})")
    if c.omission_detected is not True:
        out.append("intrinsic-noise omission control did not demonstrate a failure")
    if c.periodic_coverage is not True:
        out.append("no LO-driven internal-noise coverage evidence")
    return out


def decide_status(runner_available: bool, inventory: Mapping[str, Mapping] | None,
                  controls: Controls | None = None,
                  convergence: Convergence | None = None) -> tuple[str, list[str]]:
    """Return (status, reasons). Raises MethodError for estimator defects."""
    if not runner_available:
        return CAPABILITY_UNAVAILABLE, ["simulator executable / runner unavailable"]
    if inventory is None:
        raise MethodError("runner ran but produced no inventory")
    cov = coverage_failures(inventory)
    if cov:
        return MODEL_ABSENT, cov
    if controls is not None and controls.analytic_error_db is not None \
            and not (controls.analytic_error_db <= CONTROL_TOL_DB):
        raise MethodError(
            f"analytic known-answer control off by {controls.analytic_error_db} dB: "
            "estimator defect, fix before recording")
    if controls is None or controls.analytic_error_db is None:
        raise MethodError("analytic known-answer control not executed")
    ctl = control_failures(controls)
    if ctl:
        return MODEL_ABSENT, ctl
    conv = convergence_failures(convergence)
    if conv:
        return UNCONVERGED, conv
    return METHOD_VALIDATION, []
