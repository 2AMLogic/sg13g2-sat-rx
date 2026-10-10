"""Pure logic for the LNA nonlinear characterization (issue #57).

Everything here is simulator-free: power conventions, coherent-bin checks, the
ngspice deck text, log parsing, the two estimators (two-tone IIP3 and
single-tone input P1dB), convergence verdicts and the closed-form analytic
controls. ``run.py`` adds only the ``klt sim`` plumbing and the record writer.

Conventions (declared in testbench/plan.json, repeated here because they are
the part a wrong-normalization bug would hide in):

* The DUT sits between an ideal Thevenin source (open-circuit peak ``Vs``
  behind ``Z0``) and a ``Z0`` load to ground. The AVAILABLE power of one tone is
  ``Vs^2 / (8 Z0)``; this is the "input power" axis of every sweep, so the
  reported P1dB/IIP3 are referred to available source power, not to the power
  the (imperfectly matched) input port actually absorbs.
* A spectral component of peak voltage ``V`` across the load delivers
  ``V^2 / (2 Z0)``.
* Bin amplitudes are the single-sided peak amplitudes
  ``(2/N) |sum x_k exp(-j 2 pi f t_k)|`` over a window of exactly ``N`` samples
  spanning an integer number of periods of every analysed frequency
  (rectangular window; no window correction is applicable or applied).

The mixer feasibility bench (``sim/mixer-topology-feasibility/mixfeas.py``)
uses the same two ideas (coherent bins; a verified 1:3 region); this module
restates them for an amplifier whose products stay at RF and shares no numbers
with it.
"""

from __future__ import annotations

import cmath
import json
import math
import re
from pathlib import Path

Z0_OHM = 50.0
NEG_INF_DBM = -400.0

# ---------------------------------------------------------------------------
# power conventions
# ---------------------------------------------------------------------------


def dbm_from_w(p_w: float) -> float:
    return 10.0 * math.log10(p_w / 1e-3) if p_w > 0 else NEG_INF_DBM


def w_from_dbm(p_dbm: float) -> float:
    return 1e-3 * 10.0 ** (p_dbm / 10.0)


def vs_peak_from_pav_dbm(pav_dbm: float, z0: float = Z0_OHM) -> float:
    """Open-circuit peak amplitude of ONE tone with available power ``pav_dbm``."""
    return math.sqrt(8.0 * z0 * w_from_dbm(pav_dbm))


def pav_dbm_from_vs_peak(vs: float, z0: float = Z0_OHM) -> float:
    return dbm_from_w(vs * vs / (8.0 * z0))


def delivered_dbm(v_peak: float, z0: float = Z0_OHM) -> float:
    """Power delivered to a ``z0`` load by a component of peak ``v_peak``."""
    return dbm_from_w(v_peak * v_peak / (2.0 * z0))


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def load_plan(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def sweep_pins(plan: dict, kind: str) -> list[float]:
    s = plan["sweep"][kind]
    n = int(round((s["stop_dbm"] - s["start_dbm"]) / s["step_db"])) + 1
    return [round(s["start_dbm"] + i * s["step_db"], 6) for i in range(n)]


def variant_timing(plan: dict, variant: str) -> dict:
    """Step / discard / window of one declared variant (base, half_step, double_window)."""
    t, c = plan["time"], plan["convergence"]
    step, disc, win = t["step_s"], t["settle_discard_s"], t["window_s"]
    if variant == "base":
        pass
    elif variant == "half_step":
        step = step * c["timestep_factor"]
    elif variant == "double_window":
        win = win * c["duration_factor"]
    else:
        raise ValueError(f"unknown variant {variant!r}")
    return {"step_s": step, "settle_discard_s": disc, "window_s": win, "ramp_s": t["ramp_s"]}


VARIANTS = ("base", "half_step", "double_window")
VARIANT_CODE = {"base": "b", "half_step": "h", "double_window": "d"}


def placement_freqs(pl: dict) -> dict:
    f1, f2 = float(pl["f_tone1_hz"]), float(pl["f_tone2_hz"])
    return {"f1": f1, "f2": f2, "im3l": 2 * f1 - f2, "im3h": 2 * f2 - f1, "f0": 0.5 * (f1 + f2),
            "spacing": f2 - f1}


def band_problems(plan: dict, pl: dict) -> list[str]:
    """Both tones, both IM3 products and the single tone must lie in the DRAFT band."""
    lo, hi = plan["band_hz"]
    fr = placement_freqs(pl)
    out = []
    for k in ("f1", "f2", "im3l", "im3h", "f0"):
        if not (lo - 1e-3 <= fr[k] <= hi + 1e-3):
            out.append(f"placement {pl['name']}: {k} = {fr[k]:.6g} Hz is outside the draft band {lo:.6g}-{hi:.6g} Hz")
    return out


def coherence_problems(freqs: dict[str, float], window_s: float, step_s: float,
                       settle_discard_s: float = 0.0, tol: float = 1e-9) -> list[str]:
    """Why a set of analysed frequencies is NOT coherent with the window.

    Every frequency must complete an integer number of periods in the window,
    the window must be an integer number of samples, the settling discard must
    land on a sample, and the highest analysed frequency must be well below
    Nyquist (>= 8 samples per period). Returns [] when coherent."""
    out = []
    n = window_s / step_s
    if abs(n - round(n)) > tol * max(1.0, n):
        out.append(f"window {window_s:g} s is not an integer number of {step_s:g} s samples ({n:.6f})")
    d = settle_discard_s / step_s
    if abs(d - round(d)) > tol * max(1.0, d):
        out.append(f"settling discard {settle_discard_s:g} s does not land on a sample ({d:.6f})")
    for name, f in sorted(freqs.items()):
        cyc = f * window_s
        if abs(cyc - round(cyc)) > tol * max(1.0, cyc):
            out.append(f"{name} = {f:.9g} Hz completes {cyc:.6f} periods in the window: not coherent")
        if f * step_s > 1.0 / 8.0:
            out.append(f"{name} = {f:.9g} Hz has fewer than 8 samples per period at step {step_s:g} s")
    return out


def analysis_bins(plan: dict, pl: dict, kind: str) -> dict[str, float]:
    """Named analysis frequencies of one run kind ('two' or 'one')."""
    fr = placement_freqs(pl)
    off = float(plan["extraction"]["floor_probe_offset_hz"])
    if kind == "two":
        return {"f1": fr["f1"], "f2": fr["f2"], "im3l": fr["im3l"], "im3h": fr["im3h"],
                "fl_lo": fr["im3l"] - off, "fl_hi": fr["im3h"] + off}
    if kind == "one":
        return {"f0": fr["f0"], "fl_lo": fr["f0"] - off, "fl_hi": fr["f0"] + off}
    raise ValueError(kind)


def placement_coherence(plan: dict, pl: dict, variant: str) -> list[str]:
    tm = variant_timing(plan, variant)
    out = []
    for kind in ("two", "one"):
        out += coherence_problems(analysis_bins(plan, pl, kind), tm["window_s"], tm["step_s"], tm["settle_discard_s"])
    return out


# ---------------------------------------------------------------------------
# reference coherent-bin extraction (used by tests and the control harness)
# ---------------------------------------------------------------------------


def window_dft(samples: list[float], step_s: float, f_hz: float, t0_s: float = 0.0) -> float:
    """Single-sided peak amplitude at ``f_hz`` of ``samples`` (reference implementation).

    The ngspice decks compute the same quantity as ``2*mean(x*cos)``/``2*mean(x*sin)``;
    this routine is the pure-Python statement of it and is what the tests use to
    qualify the normalization on known waveforms."""
    n = len(samples)
    acc = 0j
    for k, x in enumerate(samples):
        acc += x * cmath.exp(-2j * math.pi * f_hz * (t0_s + k * step_s))
    return 2.0 * abs(acc) / n


def amp(c: float, s: float) -> float:
    return math.hypot(c, s)


# ---------------------------------------------------------------------------
# ngspice deck text
# ---------------------------------------------------------------------------

DEVICE_MONITORS = (
    # name, expression over the (linearized) window vectors, subckt-local nodes
    ("vce_q1", "v(xdut.c1) - v(xdut.e1)"),
    ("vce_q2", "v(xdut.oc) - v(xdut.c1)"),
    ("vbe_q1", "v(xdut.b1) - v(xdut.e1)"),
    ("vbe_q2", "v(xdut.b2) - v(xdut.c1)"),
)
DEVICE_NODES = ("xdut.c1", "xdut.e1", "xdut.oc", "xdut.b1", "xdut.b2")


def run_ids(kind: str, n: int) -> list[str]:
    return [f"{kind}{i:02d}" for i in range(n)]


def _g(x: float) -> str:
    return repr(float(f"{float(x):.15g}"))


def dut_circuit(dut_text: str, vdd_v: float) -> str:
    return "\n".join([
        ".param z0=50", ".param va1=0 va2=0", "",
        dut_text.rstrip("\n"), "",
        f".param vdd_val={_g(vdd_v)}",
        "Vdd vdd 0 DC {vdd_val}",
        "Xdut p1 p2 vdd 0 lna_stage1",
    ])


def control_circuit(a1: float, a3: float) -> str:
    """Memoryless cubic amplifier between the same 50 ohm terminations.

    v(in) = Vs/2 (matched 50 ohm shunt load behind the 50 ohm source);
    y = a1 v + a3 v^3 drives a 50 ohm series resistor into the 50 ohm load,
    so the load sees y/2 (see :func:`cubic_expectations`)."""
    return "\n".join([
        ".param z0=50", ".param va1=0 va2=0", "",
        "Rin p1 0 {z0}",
        f"Bamp ya 0 V = {_g(a1)}*v(p1) + {_g(a3)}*v(p1)*v(p1)*v(p1)",
        "Rout ya p2 {z0}",
    ])


def run_block(rid: str, *, va1: float, va2: float, bins: dict[str, float], step_s: float,
              discard_s: float, window_s: float, monitors: bool) -> list[str]:
    """One transient + the coherent-bin sums of its retained window.

    ``tran`` starts at 0 (so klt's trailing sentinel measurement stays valid);
    the retained window is samples [i0, i1] of the uniform ``linearize`` grid,
    exactly ``N`` samples long, endpoint excluded."""
    i0 = int(round(discard_s / step_s))
    n = int(round(window_s / step_s))
    i1 = i0 + n - 1
    stop = discard_s + window_s
    vecs = "v(p2)" + (" " + " ".join(f"v({x})" for x in DEVICE_NODES) if monitors else "")
    lines = [
        f"  alterparam va1 = {_g(va1)}",
        f"  alterparam va2 = {_g(va2)}",
        "  reset",
        f"  tran {_g(step_s)} {_g(stop)} 0 {_g(step_s)}",
        f"  linearize {vecs}",
        f"  let tt = time[{i0},{i1}]",
        f"  let xo = v(p2)[{i0},{i1}]",
        f"  let m_{rid}_n = length(xo)",
        f"  let m_{rid}_t0 = tt[0]",
        f"  let m_{rid}_t1 = tt[{n - 1}]",
    ]
    for name, f in bins.items():
        lines += [
            f"  let m_{rid}_{name}_c = 2*mean(xo*cos(2*pi*{_g(f)}*tt))",
            f"  let m_{rid}_{name}_s = 2*mean(xo*sin(2*pi*{_g(f)}*tt))",
        ]
    if monitors:
        for name, expr in DEVICE_MONITORS:
            e = re.sub(r"v\(([^)]*)\)", lambda m: f"v({m.group(1)})[{i0},{i1}]", expr)
            lines += [f"  let m_{rid}_{name}_max = maximum({e})", f"  let m_{rid}_{name}_min = minimum({e})"]
    names = [f"m_{rid}_n", f"m_{rid}_t0", f"m_{rid}_t1"]
    names += [f"m_{rid}_{b}_{q}" for b in bins for q in ("c", "s")]
    if monitors:
        names += [f"m_{rid}_{m}_{q}" for m, _ in DEVICE_MONITORS for q in ("max", "min")]
    for i in range(0, len(names), 6):
        lines.append("  print " + " ".join(names[i:i + 6]))
    return lines


def sweep_runs(plan: dict, pl: dict, kind: str, *, monitors: bool, variants=VARIANTS) -> list[dict]:
    """The declared runs of one (placement, kind): every sweep power, for each requested variant."""
    fr = placement_freqs(pl)
    out = []
    bins = analysis_bins(plan, pl, kind)
    pins = sweep_pins(plan, kind)
    for variant in variants:
        tm = variant_timing(plan, variant)
        for i, pin in enumerate(pins):
            vs = vs_peak_from_pav_dbm(pin)
            out.append({"id": f"{VARIANT_CODE[variant]}_{kind}{i:02d}", "variant": variant, "kind": kind, "pin_dbm": pin,
                        "vs_peak_v": vs, "va1": vs, "va2": vs if kind == "two" else 0.0,
                        "f1": fr["f1"] if kind == "two" else fr["f0"],
                        "f2": fr["f2"] if kind == "two" else fr["f0"],
                        "bins": bins, "monitors": monitors, **tm})
    return out


def body_for_runs(title: str, circuit: str, runs: list[dict]) -> str:
    """One body for a list of runs. Runs of different kinds use different source
    frequencies, so the frequencies are parameters set per run with alterparam."""
    ramp = runs[0]["ramp_s"]
    env = f"(time<{_g(ramp)} ? 0.5*(1-cos(pi*time/{_g(ramp)})) : 1)"
    lines = [
        f"* {title} -- GENERATED by sim/lna-linearity/run.py, do not edit",
        circuit,
        ".param fq1=1e10 fq2=1e10",
        f"Bs n2 0 V = {env}*({{va1}}*sin(2*pi*{{fq1}}*time) + {{va2}}*sin(2*pi*{{fq2}}*time))",
        "Rs n2 p1 {z0}",
        "RL p2 0 {z0}",
        "",
        ".control",
        "set numdgt=12",
        "set noaskquit",
    ]
    for r in runs:
        lines.append(f"  * run {r['id']}: {r['kind']}-tone, available power {r['pin_dbm']:g} dBm per tone")
        lines.append(f"  alterparam fq1 = {_g(r['f1'])}")
        lines.append(f"  alterparam fq2 = {_g(r['f2'])}")
        lines += run_block(r["id"], va1=r["va1"], va2=r["va2"], bins=r["bins"], step_s=r["step_s"],
                           discard_s=r["settle_discard_s"], window_s=r["window_s"], monitors=r["monitors"])
    lines += ["  echo LNLIN_DONE", ".endc", ""]
    return "\n".join(lines)


def options_line(plan: dict, kind: str) -> str:
    n = plan["numerics"][kind]
    return ".options " + " ".join(f"{k}={_g(n[k])}" for k in ("reltol", "trtol", "vntol", "abstol") if k in n)


# ---------------------------------------------------------------------------
# log parsing
# ---------------------------------------------------------------------------

_MEAS_RE = re.compile(r"(m_[A-Za-z0-9_]+)\s*=\s*([-+0-9.eE]+|nan|inf|-inf)\b")


def parse_log(text: str) -> tuple[dict[str, float], bool]:
    """(m_* values, saw LNLIN_DONE). Last value wins for a repeated name."""
    vals: dict[str, float] = {}
    for m in _MEAS_RE.finditer(text):
        try:
            vals[m.group(1)] = float(m.group(2))
        except ValueError:
            pass
    return vals, "LNLIN_DONE" in text


ABORT_MARKERS = ("Timestep too small", "timestep too small", "no convergence", "Singular matrix")


def run_summary(vals: dict[str, float], run: dict, *, log_has_abort: bool = False) -> dict | None:
    """Per-run bin powers (dBm delivered to the load) and device excursions.

    Returns None when the run's values are missing or corrupt (a log-integrity
    problem). A run whose transient the simulator ABORTED (every analysed amplitude
    zero or absent, and the log carries a solver-abort message) is a scientific
    outcome of that sweep point: it is returned with ``status`` 'sim_failed', is
    published, and is excluded from every fit."""
    rid = run["id"]
    base = {"id": rid, "variant": run["variant"], "kind": run["kind"], "pin_dbm": run["pin_dbm"], "vs_peak_v": run["vs_peak_v"]}
    need = [f"m_{rid}_{b}_{q}" for b in run["bins"] for q in ("c", "s")]
    n = int(round(run["window_s"] / run["step_s"]))
    present = [vals.get(k) for k in need]
    dead = all((v is None) or (isinstance(v, float) and v == 0.0) for v in present)
    if dead and log_has_abort:
        return dict(base, status="sim_failed", reason="simulator aborted the transient (solver timestep too small / no convergence)",
                    amp_v={}, p_dbm={}, floor_dbm=None)
    if any(v is None or not math.isfinite(v) for v in present) or vals.get(f"m_{rid}_n") != n:
        return None
    amps = {b: amp(vals[f"m_{rid}_{b}_c"], vals[f"m_{rid}_{b}_s"]) for b in run["bins"]}
    out = dict(base, status="ok", amp_v=amps, p_dbm={b: delivered_dbm(a) for b, a in amps.items()})
    out["floor_dbm"] = max(out["p_dbm"]["fl_lo"], out["p_dbm"]["fl_hi"])
    if run["monitors"]:
        lim = {}
        for name, _ in DEVICE_MONITORS:
            for q in ("max", "min"):
                v = vals.get(f"m_{rid}_{name}_{q}")
                if v is None or not math.isfinite(v):
                    return None
                lim[f"{name}_{q}"] = v
        out["excursion_v"] = lim
    return out


def points_from_summaries(summaries: list[dict], kind: str) -> list[dict]:
    """Estimator input rows for one kind, sorted by power (failed runs carry no values)."""
    rows = []
    for s in sorted((x for x in summaries if x["kind"] == kind), key=lambda x: x["pin_dbm"]):
        row = {"id": s["id"], "pin_dbm": s["pin_dbm"], "floor_dbm": s["floor_dbm"],
               "excursion_v": s.get("excursion_v")}
        if s["status"] != "ok":
            row["sim_failed"] = s["reason"]
            for k in (("p_f1_dbm", "p_f2_dbm", "p_im3l_dbm", "p_im3h_dbm") if kind == "two" else ("p_f0_dbm",)):
                row[k] = None
            rows.append(row)
            continue
        p = s["p_dbm"]
        if kind == "two":
            row.update(p_f1_dbm=p["f1"], p_f2_dbm=p["f2"], p_im3l_dbm=p["im3l"], p_im3h_dbm=p["im3h"])
        else:
            row.update(p_f0_dbm=p["f0"])
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# operating limits (spec row 17 + model-card box)
# ---------------------------------------------------------------------------


def limit_violations(exc: dict | None, limits: dict) -> list[str]:
    """Which declared operating limits a point's window excursions break.
    ``exc`` is None when the run did not monitor devices: that is reported as a
    violation of 'monitored' (an unmonitored DUT point is never fitted through)."""
    if exc is None:
        return ["device excursions not monitored"]
    out = []
    for q in ("q1", "q2"):
        if exc[f"vce_{q}_max"] > limits["vce_max_v"]:
            out.append(f"{q} V_CE peak {exc[f'vce_{q}_max']:.4f} V > {limits['vce_max_v']} V (row 17)")
        if exc[f"vce_{q}_min"] < limits["vce_window_v"][0]:
            out.append(f"{q} V_CE minimum {exc[f'vce_{q}_min']:.4f} V < {limits['vce_window_v'][0]} V (card window)")
        if exc[f"vbe_{q}_max"] > limits["vbe_window_v"][1]:
            out.append(f"{q} V_BE peak {exc[f'vbe_{q}_max']:.4f} V > {limits['vbe_window_v'][1]} V (card box)")
        if exc[f"vbe_{q}_min"] < limits["vbe_window_v"][0]:
            out.append(f"{q} V_BE minimum {exc[f'vbe_{q}_min']:.4f} V < {limits['vbe_window_v'][0]} V (card box)")
    return out


# ---------------------------------------------------------------------------
# estimators
# ---------------------------------------------------------------------------


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def linfit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Least squares y = a + s x; returns (a, s, max |residual|)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    s = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - s * mx
    return a, s, max(abs(y - (a + s * x)) for x, y in zip(xs, ys))


def _baseline(rows: list[dict], gain_key: str, usable: list[bool], n: int, flat_db: float) -> dict | None:
    """First run of ``n`` consecutive usable points whose gain spread <= ``flat_db``."""
    for i in range(0, len(rows) - n + 1):
        if not all(usable[i:i + n]):
            continue
        g = [rows[j][gain_key] for j in range(i, i + n)]
        if max(g) - min(g) <= flat_db:
            return {"first_index": i, "n_points": n, "pin_dbm": [rows[j]["pin_dbm"] for j in range(i, i + n)],
                    "gain_db": sum(g) / n, "spread_db": max(g) - min(g)}
    return None


def _gain_rows(rows: list[dict], fund_key: str) -> None:
    for r in rows:
        r["gain_" + fund_key] = r[fund_key] - r["pin_dbm"] if _finite(r.get(fund_key)) else None


def point_status(r: dict, *, fund_key: str, im3_key: str | None, margin_db: float, limits: dict | None,
                 enforce_limits: bool = True) -> str | None:
    """Reason a point is not usable by an estimator, or None."""
    if r.get("sim_failed"):
        return "simulation failed: " + str(r["sim_failed"])
    need = [fund_key, "floor_dbm"] + ([im3_key] if im3_key else [])
    if not all(_finite(r.get(k)) for k in need):
        return "nonfinite or missing value"
    if r[fund_key] < r["floor_dbm"] + margin_db:
        return "fundamental below numerical floor + margin"
    if enforce_limits and limits is not None:
        v = limit_violations(r.get("excursion_v"), limits)
        if v:
            return "outside DUT operating limits: " + "; ".join(v)
    return None


def fit_iip3(rows: list[dict], params: dict, limits: dict | None, *, enforce_limits: bool = True) -> dict:
    """Two-tone IIP3 from a verified contiguous 1:3-slope region, per IM3 sideband.

    ``rows``: per swept per-tone available power ``pin_dbm``: p_f1_dbm, p_f2_dbm,
    p_im3l_dbm, p_im3h_dbm (dBm delivered to the load), floor_dbm, excursion_v.
    The low sideband (2 f1 - f2) pairs with the f1 fundamental, the high one
    (2 f2 - f1) with f2. For each sideband every contiguous run of at least
    ``min_points`` swept steps is considered in which each step is finite,
    inside the operating limits, has its fundamental and its IM3 at least
    ``floor_margin_db`` above the run's numerical floor, and is below
    compression (conversion gain within ``compression_db`` of the small-signal
    baseline). A run qualifies only if the least-squares slopes are
    ``slope_fund`` (1) and ``slope_im3`` (3) within tolerance with residuals
    <= ``max_residual_db``. The longest qualifying run (ties: lowest power) is
    selected. IIP3 is the intercept at the IDEAL slopes (mean of
    pin + (P_fund - P_im3)/2 over the run), cross-checked against the
    intersection of the two free-slope lines (``free_fixed_tol_db``); the
    reported value is the lower of the two sidebands. Anything else is
    'unavailable' with a reason: never a single-point or below-floor
    extrapolation."""
    rows = sorted((dict(r) for r in rows), key=lambda r: r["pin_dbm"])
    p = params
    if len(rows) < p["min_points"]:
        return {"status": "unavailable", "reason": f"only {len(rows)} sweep point(s); need >= {p['min_points']}"}
    sides = {}
    for side, fund, im3 in (("low", "p_f1_dbm", "p_im3l_dbm"), ("high", "p_f2_dbm", "p_im3h_dbm")):
        why = [point_status(r, fund_key=fund, im3_key=im3, margin_db=0.0, limits=limits,
                            enforce_limits=enforce_limits) for r in rows]
        _gain_rows(rows, fund)
        gk = "gain_" + fund
        usable0 = [w is None for w in why]
        base = _baseline(rows, gk, usable0, p["baseline_points"], p["baseline_flat_db"])
        usable = []
        excluded = {}
        for i, r in enumerate(rows):
            w = why[i]
            if w is None and r[im3] < r["floor_dbm"] + p["floor_margin_db"]:
                w = "IM3 below numerical floor + margin"
            if w is None and base is not None and r[gk] < base["gain_db"] - p["compression_db"]:
                w = "compressed (gain more than compression_db below the small-signal baseline)"
            if w is None and base is None:
                w = "no small-signal gain baseline established"
            usable.append(w is None)
            if w:
                excluded[f"{r['pin_dbm']:g}"] = w
        best, rejected = None, []
        n = len(rows)
        for i in range(n):
            for j in range(i + p["min_points"], n + 1):
                if not all(usable[i:j]):
                    break
                seg = rows[i:j]
                xs = [r["pin_dbm"] for r in seg]
                a1, s1, r1 = linfit(xs, [r[fund] for r in seg])
                a3, s3, r3 = linfit(xs, [r[im3] for r in seg])
                per_pt = [r["pin_dbm"] + (r[fund] - r[im3]) / 2.0 for r in seg]
                if not (p["slope_fund"][0] <= s1 <= p["slope_fund"][1] and p["slope_im3"][0] <= s3 <= p["slope_im3"][1]):
                    rejected.append({"interval_dbm": [xs[0], xs[-1]], "reason": f"slopes {s1:.3f}/{s3:.3f} out of tolerance"})
                    continue
                if max(r1, r3) > p["max_residual_db"]:
                    rejected.append({"interval_dbm": [xs[0], xs[-1]], "reason": f"residual {max(r1, r3):.3f} dB too large"})
                    continue
                fixed = sum(per_pt) / len(per_pt)
                free = (a1 - a3) / (s3 - s1)
                if abs(fixed - free) > p["free_fixed_tol_db"]:
                    rejected.append({"interval_dbm": [xs[0], xs[-1]],
                                     "reason": f"fixed-slope IIP3 {fixed:.2f} and free-slope intersection {free:.2f} dBm disagree"})
                    continue
                if max(per_pt) - min(per_pt) > p["max_point_spread_db"]:
                    rejected.append({"interval_dbm": [xs[0], xs[-1]], "reason": "per-point IIP3 spread too large"})
                    continue
                cand = {"interval_dbm": [xs[0], xs[-1]], "n_points": len(seg), "slope_fund": s1, "slope_im3": s3,
                        "residual_fund_db": r1, "residual_im3_db": r3, "iip3_dbm": fixed,
                        "iip3_free_slope_dbm": free, "per_point_iip3_dbm": per_pt,
                        "extrapolation_db": fixed - xs[-1]}
                if best is None or cand["n_points"] > best["n_points"]:
                    best = cand
        entry = {"baseline": base, "excluded_points": excluded, "rejected_intervals": rejected}
        if best is None:
            entry.update(status="unavailable",
                         reason=f"no contiguous run of >= {p['min_points']} usable steps with slopes "
                                f"1+/-{p['slope_fund'][1] - 1:.2g} and 3+/-{p['slope_im3'][1] - 3:.2g} above the "
                                "numerical floor, below compression and inside the operating limits")
        else:
            entry.update(best, status="ok")
        sides[side] = entry
    ok = [s for s in sides.values() if s["status"] == "ok"]
    if len(ok) < 2:
        bad = [k for k, s in sides.items() if s["status"] != "ok"]
        return {"status": "unavailable", "reason": "no valid 1:3 region for the " + ", ".join(bad) + " IM3 sideband(s)",
                "sidebands": sides}
    return {"status": "ok", "iip3_dbm": min(s["iip3_dbm"] for s in ok), "sidebands": sides,
            "sideband_spread_db": abs(sides["low"]["iip3_dbm"] - sides["high"]["iip3_dbm"]),
            "convention": "per-tone available input power at the 50 ohm source; lower of the two sidebands"}


def fit_p1db(rows: list[dict], params: dict, limits: dict | None, *, enforce_limits: bool = True) -> dict:
    """Single-tone input P1dB (available-power referred) from a bracketed crossing.

    ``rows``: per swept available power ``pin_dbm``: p_f0_dbm (delivered), floor_dbm,
    excursion_v. Gain is delivered/available. The small-signal baseline is the
    first run of ``baseline_points`` consecutive usable steps whose gain spread
    is <= ``baseline_flat_db``. The crossing is the first pair of consecutive
    usable sweep steps with gain drop below ``drop_db`` then at or above it;
    P1dB is the interpolation of the amplitude compression against linear power between them.
    A sweep that never crosses (or whose next step after the last good one is
    rejected) yields 'bounded' (a one-sided bound), never a number; with no
    baseline the result is 'unavailable'."""
    rows = sorted((dict(r) for r in rows), key=lambda r: r["pin_dbm"])
    p = params
    why = [point_status(r, fund_key="p_f0_dbm", im3_key=None, margin_db=p["floor_margin_db"], limits=limits,
                        enforce_limits=enforce_limits) for r in rows]
    _gain_rows(rows, "p_f0_dbm")
    gk = "gain_p_f0_dbm"
    usable = [w is None for w in why]
    excluded = {f"{r['pin_dbm']:g}": w for r, w in zip(rows, why) if w}
    base = _baseline(rows, gk, usable, p["baseline_points"], p["baseline_flat_db"])
    if base is None:
        return {"status": "unavailable", "reason": "no small-signal gain baseline: no run of "
                f"{p['baseline_points']} usable steps within {p['baseline_flat_db']} dB", "excluded_points": excluded}
    g0 = base["gain_db"]
    drops = [(g0 - r[gk]) if _finite(r.get(gk)) else None for r in rows]
    start = base["first_index"] + base["n_points"] - 1
    out = {"baseline": base, "excluded_points": excluded, "drop_db": p["drop_db"],
           "gain_drop_db": {f"{r['pin_dbm']:g}": d for r, d in zip(rows, drops)}}
    last_good = rows[start]["pin_dbm"]
    if drops[start] is not None and drops[start] >= p["drop_db"]:
        return dict(out, status="unavailable", reason="gain is already compressed at the end of the baseline")
    for i in range(start, len(rows) - 1):
        if not (usable[i] and usable[i + 1]):
            nxt = rows[i + 1]["pin_dbm"] if not usable[i + 1] else rows[i]["pin_dbm"]
            return dict(out, status="bounded", bound="lower", p1db_in_dbm_gt=last_good,
                        reason=f"sweep step at {nxt:g} dBm is rejected ({why[i + 1] or why[i]}); "
                               "the 1 dB crossing is not bracketed by usable points")
        d0, d1 = drops[i], drops[i + 1]
        last_good = rows[i + 1]["pin_dbm"]
        if d0 < p["drop_db"] <= d1:
            x0, x1 = rows[i]["pin_dbm"], rows[i + 1]["pin_dbm"]
            # amplitude compression 1 - 10^(-drop/20) grows ~linearly with LINEAR input power
            # (exactly so for a cubic nonlinearity): interpolate there, not in dB
            c0, c1, ct = (1.0 - 10.0 ** (-d / 20.0) for d in (d0, d1, p["drop_db"]))
            w0, w1 = w_from_dbm(x0), w_from_dbm(x1)
            pin = dbm_from_w(w0 + (ct - c0) / (c1 - c0) * (w1 - w0))
            return dict(out, status="ok", p1db_in_dbm=pin, p1db_out_dbm=pin + g0 - p["drop_db"],
                        bracket={"pin_dbm": [x0, x1], "drop_db": [d0, d1]},
                        method="linear interpolation of the amplitude compression 1-10^(-drop/20) against LINEAR "
                               "available input power between the two bracketing usable sweep steps")
    return dict(out, status="bounded", bound="lower", p1db_in_dbm_gt=last_good,
                reason=f"the sweep never reaches a {p['drop_db']} dB gain drop (highest usable step {last_good:g} dBm)")


# ---------------------------------------------------------------------------
# convergence
# ---------------------------------------------------------------------------


def compare_estimates(kind: str, base: dict, other: dict, tol_db: float, step_db: float) -> dict:
    """Agreement of one estimator between a baseline sweep and a refined sweep."""
    key = "iip3_dbm" if kind == "iip3" else "p1db_in_dbm"
    bkey = None if kind == "iip3" else "p1db_in_dbm_gt"
    res = {"estimator": kind, "tol_db": tol_db, "base_status": base["status"], "other_status": other["status"]}
    if base["status"] != other["status"]:
        return dict(res, ok=False, reason=f"status differs: {base['status']} vs {other['status']}")
    if base["status"] == "ok":
        d = other[key] - base[key]
        return dict(res, ok=abs(d) <= tol_db, delta_db=d,
                    reason="" if abs(d) <= tol_db else f"|delta| {abs(d):.3f} dB > {tol_db} dB")
    if base["status"] == "bounded" and bkey:
        d = other[bkey] - base[bkey]
        return dict(res, ok=abs(d) <= step_db, delta_db=d, reason="" if abs(d) <= step_db else
                    f"bound moved {abs(d):.3f} dB (> one sweep step {step_db} dB)")
    return dict(res, ok=True, delta_db=None, reason=f"both {base['status']}")


def used_pins(kind: str, result: dict) -> set[float]:
    """Sweep powers the estimator actually relied on (fit intervals / baseline + bracket)."""
    pins: set[float] = set()
    if kind == "iip3":
        for s in (result.get("sidebands") or {}).values():
            if s.get("status") == "ok":
                lo, hi = s["interval_dbm"]
                pins |= {lo, hi}
    else:
        if result.get("baseline"):
            pins |= set(result["baseline"]["pin_dbm"])
        if result.get("bracket"):
            pins |= set(result["bracket"]["pin_dbm"])
    return pins


def pointwise_deltas(base_rows: list[dict], other_rows: list[dict], keys: list[str], pins: set[float] | None = None,
                     *, margin_db: float) -> dict:
    """Largest dB change of each quantity between two sweeps over their shared powers
    (restricted to ``pins`` when given). A quantity that is at the floor in both runs
    is skipped (it is below what the extraction resolves); above the floor in only one
    of them is a failure."""
    o = {r["pin_dbm"]: r for r in other_rows}
    out = {}
    for k in keys:
        worst, fails, n = 0.0, 0, 0
        for r in base_rows:
            if pins is not None and r["pin_dbm"] not in pins:
                continue
            q = o.get(r["pin_dbm"])
            if q is None:
                continue
            a, b = r.get(k), q.get(k)
            if not (_finite(a) and _finite(b)):
                fails += 1
                continue
            above = [a >= r["floor_dbm"] + margin_db, b >= q["floor_dbm"] + margin_db]
            if not any(above):
                continue
            if not all(above):
                fails += 1
                continue
            n += 1
            worst = max(worst, abs(b - a))
        out[k] = {"max_abs_delta_db": worst, "n_compared": n, "n_inconsistent": fails}
    return out


def used_interval_pins(rows: list[dict], result: dict) -> set[float]:
    """All sweep powers inside each selected IIP3 interval (not only its ends)."""
    pins: set[float] = set()
    for s in (result.get("sidebands") or {}).values():
        if s.get("status") == "ok":
            lo, hi = s["interval_dbm"]
            pins |= {r["pin_dbm"] for r in rows if lo <= r["pin_dbm"] <= hi}
    return pins


def convergence_verdict(plan: dict, kind: str, base_rows: list[dict], base_res: dict,
                        other_rows: list[dict], other_res: dict, label: str) -> dict:
    """Estimator-level and point-level agreement of one refined variant with the baseline."""
    c = plan["convergence"]
    step = plan["sweep"]["two" if kind == "iip3" else "one"]["step_db"]
    tol = c["iip3_tol_db"] if kind == "iip3" else c["p1db_tol_db"]
    est = compare_estimates(kind, base_res, other_res, tol, step)
    if kind == "iip3":
        pins = used_interval_pins(base_rows, base_res) | used_interval_pins(other_rows, other_res)
        keys_f = ["p_f1_dbm", "p_f2_dbm"]
        keys_i = ["p_im3l_dbm", "p_im3h_dbm"]
        pw_f = pointwise_deltas(base_rows, other_rows, keys_f, pins or None, margin_db=0.0)
        pw_i = pointwise_deltas(base_rows, other_rows, keys_i, pins or None, margin_db=plan["extraction"]["iip3"]["floor_margin_db"])
    else:
        pins = used_pins("p1db", base_res) | used_pins("p1db", other_res)
        pw_f = pointwise_deltas(base_rows, other_rows, ["p_f0_dbm"], pins or None, margin_db=0.0)
        pw_i = {}
    pt_ok = all(v["n_inconsistent"] == 0 and v["max_abs_delta_db"] <= c["point_fund_tol_db"] for v in pw_f.values())
    pt_ok = pt_ok and all(v["n_inconsistent"] == 0 and v["max_abs_delta_db"] <= c["point_im3_tol_db"] for v in pw_i.values())
    return {"variant": label, "estimator": est, "pointwise_fundamental": pw_f, "pointwise_im3": pw_i,
            "pointwise_ok": pt_ok, "ok": bool(est["ok"] and pt_ok)}


# ---------------------------------------------------------------------------
# analytic controls (closed forms)
# ---------------------------------------------------------------------------


def cubic_expectations(a1: float, a3: float, drop_db: float = 1.0,
                       z0: float = Z0_OHM) -> dict:
    """Closed forms for the memoryless y = a1 x + a3 x^3 amplifier of :func:`control_circuit`.

    x = Vs/2 per tone (matched input), load voltage = y/2.
      single tone, input peak A : fundamental a1 A + (3/4) a3 A^3
      two tones, each peak A    : fundamental a1 A + (9/4) a3 A^3,
                                  IM3 (2f1-f2, 2f2-f1) (3/4)|a3| A^3
    Hence (input-referred to AVAILABLE power, Pav = Vs^2/(8 z0)):
      IIP3 : A^2 = (4/3) |a1/a3|
      P1dB : 1 + (3/4)(a3/a1) A^2 = 10^(-drop/20)   (a3 < 0)
      small-signal transducer gain Pload/Pav = a1^2 / 4 (Vs/2 at the input, half of y at the load)."""
    if a3 >= 0:
        raise ValueError("compressive control requires a3 < 0")
    a2_iip3 = 4.0 / 3.0 * abs(a1 / a3)
    a2_p1 = (10.0 ** (-drop_db / 20.0) - 1.0) / (0.75 * a3 / a1)
    pav = lambda a_in: pav_dbm_from_vs_peak(2.0 * a_in, z0)
    return {"iip3_dbm": pav(math.sqrt(a2_iip3)), "p1db_in_dbm": pav(math.sqrt(a2_p1)),
            "gain_db": 10.0 * math.log10(a1 * a1 / 4.0)}


def cubic_tone_amps(a1: float, a3: float, vs_per_tone: float, two_tone: bool) -> dict:
    """Load-referred peak amplitudes the control produces at one swept power."""
    a_in = vs_per_tone / 2.0
    if two_tone:
        fund = a1 * a_in + 2.25 * a3 * a_in ** 3
        im3 = 0.75 * abs(a3) * a_in ** 3
        return {"f1": abs(fund) / 2.0, "f2": abs(fund) / 2.0, "im3l": im3 / 2.0, "im3h": im3 / 2.0}
    return {"f0": abs(a1 * a_in + 0.75 * a3 * a_in ** 3) / 2.0}


def synthetic_rows(plan: dict, a1: float, a3: float, floor_v: float, *, kind: str,
                   scale: float = 1.0, shift_db: float = 0.0) -> list[dict]:
    """Analytic sweep rows (what a perfect extractor would report) with an additive amplitude floor.
    ``scale`` multiplies every extracted amplitude and ``shift_db`` the swept power axis: the
    deliberate normalization faults used as negative controls."""
    rows = []
    for pin in sweep_pins(plan, kind):
        vs = vs_peak_from_pav_dbm(pin + shift_db)
        am = cubic_tone_amps(a1, a3, vs, kind == "two")
        fl = floor_v
        row = {"id": f"{kind}{len(rows):02d}", "pin_dbm": pin, "excursion_v": None,
               "floor_dbm": delivered_dbm(fl)}
        if kind == "two":
            f = {k: delivered_dbm(math.hypot(scale * v, fl)) for k, v in am.items()}
            row.update(p_f1_dbm=f["f1"], p_f2_dbm=f["f2"], p_im3l_dbm=f["im3l"], p_im3h_dbm=f["im3h"])
        else:
            row.update(p_f0_dbm=delivered_dbm(math.hypot(scale * am["f0"], fl)))
        rows.append(row)
    return rows


def evaluate_control(plan: dict, kind: str, rows: list[dict], a1: float, a3: float) -> dict:
    """Estimator result on control rows judged against the closed form.

    Three quantities are judged: the input-referred IIP3 (two-tone) or P1dB
    (single tone), and the small-signal transducer gain. IIP3 and P1dB are
    insensitive to a common output-amplitude scale (only differences enter), so
    the gain is what catches a wrong DFT/amplitude normalization; the swept-power
    axis (available-power convention) is what shifts IIP3 and P1dB."""
    ctl = plan["controls"]
    exp = cubic_expectations(a1, a3, drop_db=plan["extraction"]["p1db"]["drop_db"])
    if kind == "two":
        res = fit_iip3(rows, plan["extraction"]["iip3"], None, enforce_limits=False)
        err = (res["iip3_dbm"] - exp["iip3_dbm"]) if res["status"] == "ok" else None
        tol = ctl["iip3_tol_db"]
        want = exp["iip3_dbm"]
        base = (res.get("sidebands") or {}).get("low", {}).get("baseline")
    else:
        res = fit_p1db(rows, plan["extraction"]["p1db"], None, enforce_limits=False)
        err = (res["p1db_in_dbm"] - exp["p1db_in_dbm"]) if res["status"] == "ok" else None
        tol = ctl["p1db_tol_db"]
        want = exp["p1db_in_dbm"]
        base = res.get("baseline")
    gerr = (base["gain_db"] - exp["gain_db"]) if base else None
    ok = err is not None and abs(err) <= tol and gerr is not None and abs(gerr) <= ctl["gain_tol_db"]
    return {"kind": kind, "expected_dbm": want, "expected_gain_db": exp["gain_db"], "result": res,
            "error_db": err, "gain_error_db": gerr, "tol_db": tol, "gain_tol_db": ctl["gain_tol_db"], "pass": bool(ok)}


def _slope2_rows(plan: dict) -> list[dict]:
    """Rows whose IM3 rises 2 dB/dB (a square-law product, not third order)."""
    rows = []
    for k, pin in enumerate(sweep_pins(plan, "two")):
        f = 10.0 + pin
        rows.append({"id": f"two{k:02d}", "pin_dbm": pin, "excursion_v": None, "floor_dbm": -150.0,
                     "p_f1_dbm": f, "p_f2_dbm": f, "p_im3l_dbm": -20.0 + 2.0 * (pin + 40.0),
                     "p_im3h_dbm": -20.0 + 2.0 * (pin + 40.0)})
    return rows


def negative_controls(plan: dict) -> list[dict]:
    """Deliberately faulty inputs that the qualification MUST reject. Each entry:
    name, what was broken, the observed outcome and ``rejected`` (True = the
    qualification caught it, which is the passing result of a negative control)."""
    c = plan["controls"]
    a1, a3 = c["a1"], c["a3"]
    out = []

    def add(name, fault, observed, rejected):
        out.append({"name": name, "fault": fault, "observed": observed, "rejected": bool(rejected)})

    for scale in c["negative_scale_factors"]:
        for kind in ("two", "one"):
            r = evaluate_control(plan, kind, synthetic_rows(plan, a1, a3, 1e-6, kind=kind, scale=scale), a1, a3)
            add(f"wrong_amplitude_normalization_x{scale:.4g}_{kind}", f"extracted amplitudes scaled by {scale:.6g}",
                f"gain error {r['gain_error_db']:.3f} dB (tol {r['gain_tol_db']})", not r["pass"])
    for shift in c["negative_shift_db"]:
        for kind in ("two", "one"):
            r = evaluate_control(plan, kind, synthetic_rows(plan, a1, a3, 1e-6, kind=kind, shift_db=shift), a1, a3)
            add(f"wrong_power_axis_{shift:g}dB_{kind}", f"swept available-power axis off by {shift:g} dB (e.g. rms/peak or Vs^2/(2Z0) confusion)",
                f"error {r['error_db']:.3f} dB (tol {r['tol_db']})" if r["error_db"] is not None else r["result"]["status"],
                not r["pass"])
    pl = next(p for p in plan["placements"] if p["name"] == c["placement"])
    tm = variant_timing(plan, "base")
    bins = analysis_bins(plan, pl, "two")
    bad = dict(bins)
    bad["f1"] = bins["f1"] + 0.3 / tm["window_s"]
    probs = coherence_problems(bad, tm["window_s"], tm["step_s"], tm["settle_discard_s"])
    add("noncoherent_tone_placement", "tone moved 0.3 bin off the coherent grid", "; ".join(probs) or "accepted", bool(probs))
    probs = coherence_problems(bins, tm["window_s"] * 1.0003, tm["step_s"], tm["settle_discard_s"])
    add("noninteger_window", "window length 0.03 % off an integer sample count", "; ".join(probs) or "accepted", bool(probs))
    # below-floor IM3: a floor high enough to bury every IM3 product
    r = fit_iip3(synthetic_rows(plan, a1, a3, 3e-2, kind="two"), plan["extraction"]["iip3"], None, enforce_limits=False)
    add("below_floor_im3", "numerical floor above every IM3 product", f"{r['status']}: {r.get('reason', '')}", r["status"] != "ok")
    r = fit_iip3(_slope2_rows(plan), plan["extraction"]["iip3"], None, enforce_limits=False)
    add("missing_1_to_3_slope_region", "IM3 rising 2 dB/dB (square law)", f"{r['status']}: {r.get('reason', '')}", r["status"] != "ok")
    short = [x for x in synthetic_rows(plan, a1, a3, 1e-6, kind="one") if x["pin_dbm"] <= -34.0]
    r = fit_p1db(short, plan["extraction"]["p1db"], None, enforce_limits=False)
    add("unbracketed_p1db", "sweep stopped below the 1 dB crossing",
        f"{r['status']}" + (f" (> {r['p1db_in_dbm_gt']:g} dBm)" if r["status"] == "bounded" else ""), r["status"] == "bounded")
    nobase = [dict(x, p_f0_dbm=x["p_f0_dbm"] + (0.5 if i % 2 else 0.0)) for i, x in
              enumerate(synthetic_rows(plan, a1, a3, 1e-6, kind="one"))]
    r = fit_p1db(nobase, plan["extraction"]["p1db"], None, enforce_limits=False)
    add("no_small_signal_baseline", "gain jittering 0.5 dB between steps", f"{r['status']}: {r.get('reason', '')}",
        r["status"] == "unavailable")
    lim = plan["extraction"]["operating_limits"]
    rows = synthetic_rows(plan, a1, a3, 1e-6, kind="one")
    for x in rows:
        x["excursion_v"] = {f"{n}_{q}": v for n, q, v in (("vce_q1", "max", 1.2), ("vce_q1", "min", 1.2), ("vce_q2", "max", 1.2),
                                                         ("vce_q2", "min", 1.2), ("vbe_q1", "max", 0.8), ("vbe_q1", "min", 0.8),
                                                         ("vbe_q2", "max", 0.8), ("vbe_q2", "min", 0.8))}
        if x["pin_dbm"] >= -30.0:
            x["excursion_v"]["vce_q2_max"] = 1.6
    r = fit_p1db(rows, plan["extraction"]["p1db"], lim, enforce_limits=True)
    add("out_of_limit_points_not_fitted_through", "points at and above -30 dBm break the V_CE limit; the 1 dB crossing lies beyond them",
        f"{r['status']}: {r.get('reason', '')}", r["status"] == "bounded")
    return out
