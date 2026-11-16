"""Shared two-tone IIP3 estimator: one gated 1:3-slope region fit, three
published intercept definitions.

GENERIC CORE:

- :func:`linfit` -- least squares ``y = a + s x`` returning ``(a, s, max
  |residual|)``, summed with ``math.fsum`` (correctly rounded: the builtin
  ``sum`` of floats changed to compensated summation in Python 3.12, so with
  it a re-derivation on another interpreter could differ in the last kept
  digit and a frozen record would not reproduce). The single declaration in
  the tree: both campaign fitters (``mixfeas._linfit``, ``linearity.linfit``)
  delegate here instead of restating the five lines (issue #276 consolidated
  them; the mixfeas copy used builtin ``sum`` and carried exactly the hazard
  the linearity copy's docstring documented).
- :func:`select_run` -- the run-selection and gate pipeline both campaign
  fitters share: the longest contiguous run (ties: lowest power) of at least
  ``min_points`` usable steps in which the least-squares slopes fall inside
  the ``slope_fund`` / ``slope_im3`` windows with residuals <=
  ``max_residual_db`` and every injected campaign gate passes. On the
  selected run it computes ALL THREE intercept definitions the tree has in
  play, mirroring what ``sim/mixer-conversion-iip3/testbench/tb.json``
  publishes for the in-deck bench:

  - ``iip3_free_slope_dbm`` -- the intersection of the two free-slope fitted
    lines, ``(a1 - a3) / (s3 - s1)`` (the deck's ``iip3x``; the headline
    ``mixfeas.fit_iip3`` publishes);
  - ``iip3_ideal_slope_dbm`` -- the ideal-slope intercept, the mean of
    ``pin + (P_fund - P_im3) / 2`` over the run (the deck's ``iip3c`` window
    centroid; the headline ``linearity.fit_iip3`` publishes, cross-checked
    against the free-slope value by its own gate);
  - ``iip3_topfit_dbm`` -- the slope-3-constrained read at the top-of-fit
    drive, ``pin + (P_fund - P_im3) / 2`` at the run's last point (the deck's
    ``iip3t``, the headline the #181 resolution chose for the in-deck bench
    on measured cross-backend reproducibility).

  On residual-free rows all three are exact and agree whenever ``s3 - s1 ==
  2`` -- which the slope gates (1+/-0.1 and 3+/-0.3) permit at many slope
  pairs other than exactly (1, 3) -- and the free-slope intersection is exact
  for any slopes; elsewhere the definitions genuinely differ and each
  campaign keeps publishing its own.

EXTENSION POINT -- campaign-only behaviour stays at the campaigns:

- **No usable-point classification.** Each campaign decides which steps are
  usable (status flags, floor margins, compression against its own baseline
  reference, operating limits) and passes ``usable`` flags; this module
  never sees a status vocabulary or a limit check.
- **No headline choice.** The returned candidate carries all three
  intercepts; each wrapper selects its own as ``iip3_dbm`` and keeps its own
  status strings ("IIP3 unavailable" in mixfeas, "unavailable" in linearity)
  and reason texts. The wrappers also keep their published dict shapes
  unchanged by default (frozen records pin them structurally) and surface
  the full three-intercept shape only behind their opt-in
  ``diagnostics=True`` -- a campaign that re-records after a shape change
  can adopt it permanently.
- **Campaign-only gates are injected** as ``extra_gate`` -- a callable
  receiving the candidate's per-point reads and intercepts, returning a
  rejection reason string or ``None`` (linearity injects its free-vs-fixed
  cross-check and per-point spread gate there; mixfeas injects nothing).

Which definition *should* be the single reference is deliberately NOT
decided here: the definitions agree only under the condition above, so
switching either headline moves published numbers, which under the
append-only evidence rule is a re-recording question for a
``spec/decision-records/`` entry, not a refactor's side effect.
``sim/mixer-conversion-iip3/README.md`` records the strongest existing input
to that decision -- the #181 measured cross-backend comparison (top-of-fit
0.0492 dB vs centroid ~0.27 dB vs free intersection ~1.4 dB across ngspice
builds) in which the free intersection ranked worst.

Everything is pure Python (stdlib only) so ``tests/`` can exercise it
against synthetic data with known answers, without a PDK or simulator.
"""

from __future__ import annotations

import math

#: The three intercept keys :func:`select_run` adds to every candidate, named
#: after the definitions the in-deck bench publishes (``iip3x``/``iip3c``/
#: ``iip3t``). Campaign wrappers strip the keys their pre-#276 shape lacked
#: (mixfeas: all three; linearity: the two it did not already publish) from
#: their returned dicts by default: a committed record's verify re-derives
#: every placement from the frozen logs and compares structurally, so the
#: pre-#276 key set stays the published shape and the full three-intercept
#: shape surfaces behind each wrapper's opt-in ``diagnostics=True``.
INTERCEPT_KEYS = ("iip3_free_slope_dbm", "iip3_ideal_slope_dbm", "iip3_topfit_dbm")


def linfit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Least squares y = a + s x; returns (a, s, max |residual|).

    Sums use ``math.fsum`` (correctly rounded); see the module docstring for
    why the builtin ``sum`` is not used.
    """
    n = len(xs)
    mx, my = math.fsum(xs) / n, math.fsum(ys) / n
    sxx = math.fsum((x - mx) ** 2 for x in xs)
    s = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - s * mx
    return a, s, max(abs(y - (a + s * x)) for x, y in zip(xs, ys))


def select_run(*, xs: list[float], fund_ys: list, im3_ys: list, usable: list[bool],
               min_points: int, slope_fund: tuple[float, float], slope_im3: tuple[float, float],
               max_residual_db: float, extra_gate=None) -> tuple[dict | None, list[dict]]:
    """Longest contiguous qualifying run for one IM3 sideband, with all three
    intercepts computed on it.

    ``xs`` / ``fund_ys`` / ``im3_ys`` are the full sorted sweep (one entry per
    swept ``pin_dbm``; a point lacking a value may carry ``None`` there --
    only usable windows are ever fitted), ``usable`` the per-point flags the
    campaign's own classification produced. Every contiguous window of at
    least ``min_points`` usable steps is fitted: slopes must fall inside the
    ``slope_fund`` / ``slope_im3`` windows, residuals stay <=
    ``max_residual_db``, and ``extra_gate`` (when given) may reject with a
    reason. The longest qualifying run wins; ties keep the first encountered,
    which is the lowest-power one because the sweep is sorted. Returns
    ``(best, rejected)``: best is ``None`` or a dict with ``interval_dbm``,
    ``n_points``, ``slope_fund``, ``slope_im3``, ``residual_fund_db``,
    ``residual_im3_dbm`` residuals, ``per_point_iip3_dbm`` and the three
    intercepts ``iip3_free_slope_dbm`` / ``iip3_ideal_slope_dbm`` /
    ``iip3_topfit_dbm``; ``rejected`` lists one ``{"interval_dbm", "reason"}``
    entry per failing window in scan order (the campaign's rejection log,
    empty for campaigns that do not record one).
    """
    best: dict | None = None
    rejected: list[dict] = []
    n = len(xs)
    for i in range(n):
        for j in range(i + min_points, n + 1):
            if not all(usable[i:j]):
                break
            a1, s1, r1 = linfit(xs[i:j], fund_ys[i:j])
            a3, s3, r3 = linfit(xs[i:j], im3_ys[i:j])
            interval = [xs[i], xs[j - 1]]
            if not (slope_fund[0] <= s1 <= slope_fund[1] and slope_im3[0] <= s3 <= slope_im3[1]):
                rejected.append({"interval_dbm": interval, "reason": f"slopes {s1:.3f}/{s3:.3f} out of tolerance"})
                continue
            if max(r1, r3) > max_residual_db:
                rejected.append({"interval_dbm": interval, "reason": f"residual {max(r1, r3):.3f} dB too large"})
                continue
            per_pt = [x + (f - im) / 2.0 for x, f, im in zip(xs[i:j], fund_ys[i:j], im3_ys[i:j])]
            fixed = math.fsum(per_pt) / len(per_pt)
            free = (a1 - a3) / (s3 - s1)
            topfit = xs[j - 1] + (fund_ys[j - 1] - im3_ys[j - 1]) / 2.0
            if extra_gate is not None:
                why = extra_gate(per_pt=per_pt, fixed=fixed, free=free, interval_dbm=interval)
                if why:
                    rejected.append({"interval_dbm": interval, "reason": why})
                    continue
            cand = {"interval_dbm": interval, "n_points": j - i, "slope_fund": s1, "slope_im3": s3,
                    "residual_fund_db": r1, "residual_im3_db": r3, "per_point_iip3_dbm": per_pt,
                    "iip3_free_slope_dbm": free, "iip3_ideal_slope_dbm": fixed, "iip3_topfit_dbm": topfit}
            if best is None or cand["n_points"] > best["n_points"]:
                best = cand
    return best, rejected
