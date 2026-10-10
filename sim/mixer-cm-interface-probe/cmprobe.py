"""Pure logic for the conversion-matrix interface probe (issue #89).

No simulator, no numpy. Everything here is a function of numbers, so
tests/ can exercise it (including the sabotage failures) without ngspice.

Conventions (shared with controls/ideal_mixer.spice and probe/interface_probe.spice)
-----------------------------------------------------------------------------------
* Tones are written ``a*sin(w t + phi)``; the tone phasor is ``P = a e^{j phi}``.
* The LO is ``cA*sin(wLO t + th)`` in the control.
* An IF waveform is ``y = Re(X e^{j wIF t})``; the probe measures
  ``C = 2/T int y cos(wIF t)`` and ``S = 2/T int y sin(wIF t)`` so ``X = C - jS``.
* Wanted sideband (RF = fLO + fIF): ``X = Gw * P``.
* Image sideband (RF = fLO - fIF): ``X = Gi * conj(P)`` (the image arrives
  conjugated; treating it as non-conjugated is the "wrong sideband sign" fault).
* Ideal multiplying mixer ``v = k*v_lo*v_rf``: ``Gw = (k cA/2) e^{-j th}``,
  ``Gi = (k cA/2) e^{+j th}``.
"""

from __future__ import annotations

import cmath
import math
import re

# ---- probe constants (must match the .spice sources) -------------------------
F_LO = 18.45e9
F_IF = 1.0e9
F_WRONG = 1.025e9           # an off-grid-of-interest IF used as a bookkeeping null
T_STOP = 120e-9
WINDOW = (80e-9, 120e-9)    # transfer projection window [s]: 40 IF periods, 738 LO periods
TRAJ_WINDOWS = ((80e-9, 100e-9), (100e-9, 120e-9))
A_TONE = 2e-3               # perturbation EMF amplitude [V] (and 2x for linearity)
PH_U_DEG = 20.0
PH_L_DEG = 70.0
CTL_K = 1.0
CTL_A = 1.0
CTL_TH_DEG = 30.0

#: run name -> (apu, apl)
RUNS = {
    "base": (0.0, 0.0),
    "u": (A_TONE, 0.0),
    "u2": (2 * A_TONE, 0.0),
    "l": (0.0, A_TONE),
    "ul": (A_TONE, A_TONE),
}

# tolerances
CTL_MAG_TOL = 1e-3          # relative |G| error of the known-answer control
CTL_PHASE_TOL_DEG = 0.1
CTL_NULL_TOL = 1e-3         # wrong-IF projection / wanted projection
DUT_LINEARITY_TOL = 0.02    # |G(2a)/G(a) - 1|
DUT_SUPERPOSITION_TOL = 0.02
TRAJ_SETTLE_TOL = 1e-3      # window-to-window relative change

STATES = ("demonstrated", "unsupported", "unknown")
INTERFACES = ("lo_period_trajectory", "wanted_sideband_transfer", "image_sideband_transfer",
              "noise_intensity_per_mechanism", "noise_covariance_ib_ic")

SABOTAGES = {
    # name -> {control .param overrides}
    "gain": {"ck": 0.8},
    "drop_image": {"cimg": 0.0},
    "image_sign": {"cimg": -1.0},
    "wrong_lo": {"cflo": 18.55e9},
}

S_CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
S_DEMONSTRATED = "INTERFACES_DEMONSTRATED"
S_PARTIAL = "INTERFACES_PARTIAL"
S_BLOCKED = "INTERFACES_BLOCKED"
STATUSES = (S_DEMONSTRATED, S_PARTIAL, S_BLOCKED, S_CAPABILITY_UNAVAILABLE)


class ProbeError(Exception):
    """Estimator/parse defect (not a capability finding)."""


# ---- closed form ----------------------------------------------------------------

def tone_phasor(a: float, phi_deg: float) -> complex:
    return a * cmath.exp(1j * math.radians(phi_deg))


def ideal_transfers(k: float = CTL_K, a_lo: float = CTL_A, th_deg: float = CTL_TH_DEG) -> tuple[complex, complex]:
    """(Gw, Gi) of the ideal multiplying mixer."""
    th = math.radians(th_deg)
    return (k * a_lo / 2) * cmath.exp(-1j * th), (k * a_lo / 2) * cmath.exp(1j * th)


def phasor_from_integrals(xc: float, xs: float, t_window: float) -> complex:
    """X = C - jS from the cos/sin trapezoid integrals over ``t_window`` seconds."""
    return complex(2 * xc / t_window, -2 * xs / t_window)


def integrals_from_phasor(x: complex, t_window: float) -> tuple[float, float]:
    """Inverse of :func:`phasor_from_integrals` (used to fabricate marks)."""
    return x.real * t_window / 2, -x.imag * t_window / 2


# ---- parsing -----------------------------------------------------------------------

MARK_RE = re.compile(r"^MARK\s+(.*)$")
KV_RE = re.compile(r"(\w+)=(\S*)")
NOISE_RE = re.compile(r"^(onoise_total\S*)\s*=\s*(\S+)\s*$")


def _float(s: str | None) -> float | None:
    if s is None or s == "":
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def parse_log(stdout: str, stderr: str) -> dict:
    """MARK key=value pairs, per-bias .noise vectors, pss reply."""
    marks: dict[str, float | None] = {}
    noise: dict[str, dict[str, float]] = {}
    section: str | None = None
    for line in stdout.splitlines():
        s = line.strip()
        m = MARK_RE.match(s)
        if m:
            body = m.group(1)
            kv = dict(KV_RE.findall(body))
            if "N_section_begin" in kv:
                section = kv["N_section_begin"]
                noise.setdefault(section, {})
            elif "N_section_end" in kv:
                section = None
            else:
                for k, v in kv.items():
                    marks[k] = _float(v)
            continue
        n = NOISE_RE.match(s)
        if n and section is not None:
            val = _float(n.group(2))
            if val is not None:
                noise[section][n.group(1)] = val
    both = stdout + "\n" + stderr
    missing = "pss: no such command" in both
    return {"marks": marks, "noise_totals_v_rms": noise,
            "pss_command_missing": missing,
            "pnoise_command_missing": "pnoise: no such command" in both,
            "pac_command_missing": "pac: no such command" in both,
            "pss_started": "Periodic Steady State Analysis Started" in both,
            "pss_convergence_not_reached": "Convergence not reached" in both,
            "completed": "MARK done" in stdout}


# ---- projections from marks ---------------------------------------------------------

def _need(marks: dict, key: str) -> float:
    v = marks.get(key)
    if v is None:
        raise ProbeError(f"probe mark {key} missing or non-numeric")
    return v


def run_phasor(marks: dict, ckt: str, run: str, tag: str = "x") -> complex:
    t = WINDOW[1] - WINDOW[0]
    return phasor_from_integrals(_need(marks, f"{tag}_{ckt}_{run}_c"), _need(marks, f"{tag}_{ckt}_{run}_s"), t)


def response(marks: dict, ckt: str, run: str) -> complex:
    """Perturbation response: IF phasor minus the LO-only baseline's."""
    return run_phasor(marks, ckt, run) - run_phasor(marks, ckt, "base")


def transfers(marks: dict, ckt: str) -> dict:
    """Wanted/image transfers from runs u, u2, l, plus the superposition residual."""
    pu, pl = tone_phasor(A_TONE, PH_U_DEG), tone_phasor(A_TONE, PH_L_DEG)
    xu, xu2, xl, xul = (response(marks, ckt, r) for r in ("u", "u2", "l", "ul"))
    gw = xu / pu
    gw2 = xu2 / (2 * pu)
    gi = xl / pl.conjugate()
    scale = max(abs(xu), abs(xl)) or float("nan")
    return {"gw": gw, "gw_2x": gw2, "gi": gi,
            "linearity_err": abs(gw2 / gw - 1) if gw != 0 else float("inf"),
            "superposition_err": abs(xul - xu - xl) / scale if scale == scale else float("inf"),
            "x_u": xu, "x_l": xl}


# ---- known-answer control --------------------------------------------------------------

def _phase_err_deg(a: complex, b: complex) -> float:
    if a == 0 or b == 0:
        return 180.0
    d = math.degrees(cmath.phase(a / b))
    return abs((d + 180.0) % 360.0 - 180.0)


def evaluate_control(marks: dict) -> dict:
    """Compare the measured control transfers with the closed form."""
    tr = transfers(marks, "ctl")
    gw_x, gi_x = ideal_transfers()
    checks = {}
    for name, got, exp in (("wanted", tr["gw"], gw_x), ("image", tr["gi"], gi_x)):
        mag_err = abs(abs(got) / abs(exp) - 1)
        ph_err = _phase_err_deg(got, exp)
        checks[name] = {"measured": [abs(got), math.degrees(cmath.phase(got)) if got else 0.0],
                        "expected": [abs(exp), math.degrees(cmath.phase(exp))],
                        "mag_rel_err": mag_err, "phase_err_deg": ph_err,
                        "pass": mag_err <= CTL_MAG_TOL and ph_err <= CTL_PHASE_TOL_DEG}
    # frequency bookkeeping: the wanted run must leave nothing at a wrong IF
    t = WINDOW[1] - WINDOW[0]
    xw = phasor_from_integrals(_need(marks, "w_ctl_u_c"), _need(marks, "w_ctl_u_s"), t)
    null = abs(xw) / abs(tr["x_u"]) if abs(tr["x_u"]) > 0 else float("inf")
    checks["frequency_null"] = {"wrong_if_hz": F_WRONG, "relative_projection": null,
                                "pass": null <= CTL_NULL_TOL}
    checks["linearity"] = {"err": tr["linearity_err"], "pass": tr["linearity_err"] <= DUT_LINEARITY_TOL}
    checks["superposition"] = {"err": tr["superposition_err"],
                               "pass": tr["superposition_err"] <= DUT_SUPERPOSITION_TOL}
    return {"pass": all(c["pass"] for c in checks.values()), "checks": checks}


# ---- fabricating marks from closed form (tests; also documents the mark schema) -------------

def synth_control_marks(sabotage: str | None = None) -> dict:
    """Marks an ideal (or sabotaged) multiplying mixer would print, from closed form."""
    ov = SABOTAGES.get(sabotage, {}) if sabotage else {}
    k = ov.get("ck", CTL_K)
    img = ov.get("cimg", 1.0)
    flo = ov.get("cflo", F_LO)
    t = WINDOW[1] - WINDOW[0]
    gw, gi = ideal_transfers(k)
    th = math.radians(CTL_TH_DEG)
    # A shifted LO moves the product tones off the IF grid: nothing lands at F_IF
    # (the shifted IF, |F_RF - flo|, is orthogonal to the F_IF projection).
    on_grid = abs(flo - F_LO) < 1.0
    marks: dict[str, float] = {}
    for run, (apu, apl) in RUNS.items():
        pu, pl = tone_phasor(apu, PH_U_DEG), tone_phasor(apl, PH_L_DEG)
        x = (gw * pu + img * gi * pl.conjugate()) if on_grid else 0j
        c, s = integrals_from_phasor(x, t)
        marks[f"x_ctl_{run}_c"], marks[f"x_ctl_{run}_s"] = c, s
        xw = 0j
        if not on_grid:  # product tone at F_IF + 100 MHz: orthogonal to both projections
            xw = 0j
        cw, sw = integrals_from_phasor(xw, t)
        marks[f"w_ctl_{run}_c"], marks[f"w_ctl_{run}_s"] = cw, sw
    del th
    return marks


# ---- DUT interface derivation ----------------------------------------------------------------------

def trajectory_metrics(marks: dict) -> dict:
    """Window-to-window change of the LO-only baseline's harmonics and mean."""
    out = {}
    worst = 0.0
    for h in ("f1", "f2"):
        ph = []
        for i, (a, b) in enumerate(TRAJ_WINDOWS, 1):
            ph.append(phasor_from_integrals(_need(marks, f"t_dut_base_w{i}_{h}_c"),
                                            _need(marks, f"t_dut_base_w{i}_{h}_s"), b - a))
        out[f"{h}_amplitude_v"] = [abs(p) for p in ph]
        ref = max(abs(ph[0]), abs(ph[1]), 1e-30)
        out[f"{h}_relative_change"] = abs(ph[1] - ph[0]) / ref
        worst = max(worst, out[f"{h}_relative_change"])
    avg = [_need(marks, f"t_dut_base_w{i}_avg") for i in (1, 2)]
    out["mean_v"] = avg
    out["mean_relative_change"] = abs(avg[1] - avg[0]) / max(abs(avg[0]), abs(avg[1]), 1e-30)
    out["worst_relative_change"] = max(worst, out["mean_relative_change"])
    return out


def build_matrix(parsed: dict, references: dict) -> dict:
    """The five-interface matrix. Pure function of the parsed log + reference text.

    A transfer interface is ``demonstrated`` ONLY when the known-answer control
    passes AND the DUT response is linear/superposable AND the LO orbit is settled; a failing control leaves
    it ``unknown`` (never ``unsupported``: a broken probe is not an absent
    capability).
    """
    if not parsed.get("completed"):
        raise ProbeError("probe log incomplete (no 'MARK done')")
    mk = parsed["marks"]
    ctl = evaluate_control(mk)
    dut = transfers(mk, "dut")
    traj = trajectory_metrics(mk)
    ctl_ok = ctl["pass"]

    traj_ok = traj["worst_relative_change"] <= TRAJ_SETTLE_TOL
    matrix: dict[str, dict] = {}
    matrix["lo_period_trajectory"] = {
        "state": "demonstrated" if traj_ok else "unknown",
        "basis": "probe",
        "reference": references["manual_tran"],
        "probe_marks": traj,
        "note": ("transient-settled LO orbit read from .tran (no periodic steady-state solver); "
                 f"window-to-window change <= {TRAJ_SETTLE_TOL:g}" if traj_ok else
                 "orbit not settled to tolerance in the probe window"),
    }
    lin_ok = dut["linearity_err"] <= DUT_LINEARITY_TOL and dut["superposition_err"] <= DUT_SUPERPOSITION_TOL
    for key, g in (("wanted_sideband_transfer", dut["gw"]), ("image_sideband_transfer", dut["gi"])):
        ok = ctl_ok and lin_ok and traj_ok
        why = ("control failed" if not ctl_ok else
               "DUT response not linear/superposable at the probe amplitude" if not lin_ok else
               "LO orbit not settled: finite-window linearity does not establish transfer "
               "about a settled periodic operating trajectory")
        matrix[key] = {
            "state": "demonstrated" if ok else "unknown",
            "basis": "probe",
            "reference": references["manual_tran"],
            "probe_marks": {"gain_magnitude": abs(g), "gain_phase_deg": math.degrees(cmath.phase(g)) if g else 0.0,
                            "linearity_err": dut["linearity_err"],
                            "superposition_err": dut["superposition_err"],
                            "control_pass": ctl_ok},
            "note": ("perturbation (u/l tone) response minus LO-only baseline, "
                     "IF projection over an integer number of IF periods; control passed"
                     if ok else why),
        }
    pss_missing = bool(parsed.get("pss_command_missing"))
    pnoise_missing = bool(parsed.get("pnoise_command_missing"))
    noise = parsed.get("noise_totals_v_rms", {})
    ic_key = "onoise_total_q.xq1.qnpn13g2_ic"
    dc = {b: {"onoise_total": v.get("onoise_total"), "ic_shot": v.get(ic_key)} for b, v in noise.items()}
    matrix["noise_intensity_per_mechanism"] = {
        "state": "unsupported" if (pss_missing or pnoise_missing) else "unknown",
        "basis": "probe+source",
        "reference": references["manual_pss"] + " | " + references["source_noise"],
        "probe_marks": {"dc_noise_per_generator_available": bool(noise),
                        "dc_noise_by_bias": dc, "pss_command_missing": pss_missing,
                        "pnoise_command_missing": pnoise_missing,
                        "pac_command_missing": bool(parsed.get("pac_command_missing")),
                        "pss_started": bool(parsed.get("pss_started")),
                        "pss_convergence_not_reached": bool(parsed.get("pss_convergence_not_reached"))},
        "note": ("per-mechanism intensities are reachable only as DC .noise totals at a fixed operating "
                 "point; no analysis evaluates them along a periodic trajectory (no pnoise"
                 + (", no pss" if pss_missing else "") + " command in this build)"
                 if (pss_missing or pnoise_missing) else
                 "a periodic-noise command appears to exist in this build: access is unresolved, not absent"),
    }
    matrix["noise_covariance_ib_ic"] = {
        "state": "unsupported",
        "basis": "source",
        "reference": references["source_noise"],
        "probe_marks": {},
        "note": ("VBICnoise() evaluates every generator independently: the model defines no ib/ic "
                 "covariance and no analysis exposes one"),
    }
    return matrix


def decide_status(tool_ok: bool, matrix: dict | None) -> tuple[str, list[str]]:
    """(status, reasons). No input can yield a METHOD_VALIDATION-like verdict."""
    if not tool_ok or matrix is None:
        return S_CAPABILITY_UNAVAILABLE, ["pinned simulator not available on this host; "
                                          "this status never establishes absence"]
    states = {k: matrix[k]["state"] for k in INTERFACES}
    uns = [k for k, s in states.items() if s == "unsupported"]
    unk = [k for k, s in states.items() if s == "unknown"]
    if uns:
        return S_BLOCKED, [f"{k}: unsupported" for k in uns] + [f"{k}: unresolved" for k in unk]
    if unk:
        return S_PARTIAL, [f"{k}: unresolved" for k in unk]
    return S_DEMONSTRATED, ["all five required interfaces demonstrated (interface feasibility only)"]
