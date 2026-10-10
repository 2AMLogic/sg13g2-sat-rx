"""Pure logic for the pumped RF-port admittance probe (issue #111).

No simulator, no numpy: everything here is a function of numbers, so tests/ can
exercise the extraction, the known answers, the sabotages and the classification
without ngspice.

Conventions (shared with probe/admittance_probe.spice and controls/*.spice)
--------------------------------------------------------------------------
* Phasors are cosine-referenced: a waveform component at angular frequency w is
  ``y(t) = Re(X e^{j w t})``. Over a window of length T holding an integer number
  of periods of every analysed tone, ``C = int y cos(wt)``, ``S = int y sin(wt)``
  and ``X = (2/T) (C - j S)`` (``.meas tran ... INTEG``, trapezoid).
* Sidebands: ``f_u = f_LO + f_IF`` (wanted RF) and ``f_l = f_LO - f_IF`` (image).
* Port reference plane and current direction: the port voltage ``V`` is the
  port node to ground; the port current ``I`` is positive INTO the device
  under test (out of the source). For a fixture driven by a Norton perturbation
  current ``J`` in parallel with its own source resistor ``z0`` to a 0 V node,
  ``I = i(sense) + (v(term) - v(port)) / z0`` where ``i(sense)`` is the injected
  current through a 0 V ammeter (positive towards the port) and ``v(term)`` the
  far end of ``z0``. This is the same as driving the port from a Thevenin EMF
  ``J z0`` through ``z0``: the perturbation leaves the port termination unchanged.
* Baseline subtraction: every response is the run's phasor minus the phasor of
  the LO-only baseline run with the same time step, over the same window.
* Pumped (linear periodically time-varying) port model restricted to the two RF
  sidebands, with the image entering conjugated::

      I_u = Y_uu V_u + Y_ul conj(V_l)
      I_l = Y_lu conj(V_u) + Y_ll V_l

  An LTI port has ``Y_ul = Y_lu = 0`` and ``Y_uu = Y(f_u)``, ``Y_ll = Y(f_l)``:
  the scalar case. The matrix is conditional on the termination the fixture
  presents at every other mixing frequency (IF, 2 f_LO +- ..., 3 f_LO +- f_IF);
  it is an embedded, not an intrinsic, quantity.
* Two independent perturbation phases: run ``p1`` drives both sideband tones
  with phases (20, 70) deg, run ``p2`` with (20, 250) deg (the image tone
  inverted). Each phase gives one row of the 2x2 system per equation, so the
  four elements are solved from measured port voltages and currents. A scalar
  extraction ``I_u / V_u`` gives DIFFERENT answers for p1 and p2 when the
  conjugate term is present; that spread is reported as a model-free
  discriminator.
"""

from __future__ import annotations

import cmath
import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
THRESHOLDS_PATH = HERE / "thresholds.json"

# ---- probe constants (must match the .spice sources) ------------------------------
F_LO = 18.45e9
F_IF = 1.0e9
F_U = F_LO + F_IF          # 19.45 GHz, wanted RF sideband
F_L = F_LO - F_IF          # 17.45 GHz, image sideband
SIDEBANDS = {"u": F_U, "l": F_L}
T_STOP = 160e-9
T_STOP_REFINED = 120e-9
TMAX = 1e-12
TMAX_REFINED = 0.5e-12
WINDOWS = {"w": (80e-9, 120e-9),   # retained window: 40 ns = 778 f_u, 698 f_l, 738 f_LO periods
           "x": (80e-9, 160e-9)}   # extended window (retained-window extension), 80 ns
A_EMF = 2e-3               # perturbation EMF amplitude per tone [V] (Thevenin; J = A/z0)
PH_U_DEG = 20.0
PH_L_P1_DEG = 70.0
PH_L_P2_DEG = 250.0        # image tone inverted relative to p1

#: run -> (amplitude per tone, phase u, phase l, refined?)
RUNS = {
    "base":   (0.0,         PH_U_DEG, PH_L_P1_DEG, False),
    "p1":     (A_EMF,       PH_U_DEG, PH_L_P1_DEG, False),
    "p2":     (A_EMF,       PH_U_DEG, PH_L_P2_DEG, False),
    "p1h":    (A_EMF / 2,   PH_U_DEG, PH_L_P1_DEG, False),
    "p2h":    (A_EMF / 2,   PH_U_DEG, PH_L_P2_DEG, False),
    "base_r": (0.0,         PH_U_DEG, PH_L_P1_DEG, True),
    "p1_r":   (A_EMF,       PH_U_DEG, PH_L_P1_DEG, True),
    "p2_r":   (A_EMF,       PH_U_DEG, PH_L_P2_DEG, True),
}


def run_windows(run: str) -> tuple[str, ...]:
    """Windows projected for a run: refined runs stop at 120 ns (retained window only)."""
    return ("w",) if RUNS[run][3] else ("w", "x")


#: extraction set -> (phase-1 run, phase-2 run, baseline run, window)
SETS = {
    "primary":  ("p1", "p2", "base", "w"),
    "halved":   ("p1h", "p2h", "base", "w"),
    "extended": ("p1", "p2", "base", "x"),
    "refined":  ("p1_r", "p2_r", "base_r", "w"),
}
CONVERGENCE = {"halving": "halved", "window": "extended", "timestep": "refined"}
CONVERGENCE_TOL_KEY = {"halving": "halving_rel_tol", "window": "window_rel_tol",
                       "timestep": "timestep_rel_tol"}

# ---- fixtures -----------------------------------------------------------------------
#: fixture -> (port node, sense source, termination node or None, z0 or None)
FIXTURES = {
    "rc":  ("kp", "vksense", "krs", 50.0),      # passive RC known answer, Norton drive
    "md":  ("mp", "vmsense", None, None),       # ideal periodically modulated, ideal V drive
    "dut": ("prf", "vpsense", "rfsrc", 50.0),   # placeholder RF port, its own Rrf = z0 = 50
}
CONTROL_FIXTURES = ("rc", "md")

# passive RC known answer: series R + C to ground (controls/rc_known_answer.spice)
RC_R = 25.0
RC_C = 1e-12
# ideal modulated known answer: G(t) = g0 + 2 g2 cos(2 w_LO t + th), shunt Cm, baseline
# current ib*sin(w_u t + phb) (controls/modulated_known_answer.spice)
MD_G0 = 0.02
MD_CM = 0.1e-12
MD_G2 = 0.006
MD_TH_DEG = 40.0
MD_IB = 1e-6
MD_PHB_DEG = 10.0

ELEMENTS = ("uu", "ul", "lu", "ll")

SABOTAGES = {
    # extraction-side faults; each must make the known-answer controls FAIL numerically
    "current_sign": "port current taken with the wrong sign (out of the DUT)",
    "omit_image": "scalar extraction I/V per sideband from phase p1 only; conjugate image coupling omitted",
    "no_baseline": "LO-only baseline not subtracted",
}
#: sabotage -> control checks at least one of which must fail
EXPECTED_FAILING = {
    "current_sign": {"rc.uu", "rc.ll", "md.uu", "md.ll"},
    "omit_image": {"md.ul", "md.lu", "md.uu", "md.ll"},
    "no_baseline": {"md.uu", "md.ul"},
}

S_SCALAR = "SCALAR_ADEQUATE"
S_MATRIX = "MATRIX_REQUIRED"
S_INCONCLUSIVE = "INCONCLUSIVE"
S_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
STATUSES = (S_SCALAR, S_MATRIX, S_INCONCLUSIVE, S_UNAVAILABLE)

SCOPE = ("method-feasibility evidence only; nominal single point; no row-5 compliance claim; "
         "no mixer or cascade NF claim; DR-0004 is neither ratified nor reversed")


class ProbeError(Exception):
    """Estimator/parse defect (not a finding about the DUT)."""


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict:
    data = json.loads(path.read_text())
    vals = data["values"]
    for k, v in vals.items():
        if not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            raise ProbeError(f"threshold {k} must be a positive finite number")
    return dict(vals)


# ---- phasors ---------------------------------------------------------------------------

def window_len(win: str) -> float:
    a, b = WINDOWS[win]
    return b - a


def phasor_from_integrals(c: float, s: float, t_window: float) -> complex:
    return complex(2 * c / t_window, -2 * s / t_window)


def integrals_from_phasor(x: complex, t_window: float) -> tuple[float, float]:
    return x.real * t_window / 2, -x.imag * t_window / 2


def sin_tone_phasor(a: float, phi_deg: float) -> complex:
    """Cosine-referenced phasor of ``a*sin(wt + phi)`` (= a e^{j(phi - 90 deg)})."""
    return a * cmath.exp(1j * math.radians(phi_deg - 90.0))


def mark_key(fx: str, sig: str, run: str, win: str, sb: str, cs: str) -> str:
    return f"{fx}_{sig}_{run}_{win}_{sb}_{cs}"


def fixture_signals(fx: str) -> tuple[str, ...]:
    return ("v", "i", "t") if FIXTURES[fx][2] else ("v", "i")


# ---- parsing --------------------------------------------------------------------------------

MARK_RE = re.compile(r"^MARK\s+(.*)$")
KV_RE = re.compile(r"(\w+)=(\S*)")


def _float(s: str | None) -> float | None:
    if s is None or s == "":
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def parse_log(stdout: str, stderr: str) -> dict:
    marks: dict[str, float | None] = {}
    for line in stdout.splitlines():
        m = MARK_RE.match(line.strip())
        if m:
            for k, v in KV_RE.findall(m.group(1)):
                marks[k] = _float(v)
    both = stdout + "\n" + stderr
    return {"marks": marks, "completed": "MARK done" in stdout,
            "has_dut": any(k.startswith("dut_") for k in marks),
            "errors": [ln.strip() for ln in both.splitlines()
                       if re.search(r"\b(error|Error|ERROR)\b", ln) and "MARK" not in ln][:20]}


def _need(marks: dict, key: str) -> float:
    v = marks.get(key)
    if v is None:
        raise ProbeError(f"probe mark {key} missing or non-numeric")
    return v


def raw_phasor(marks: dict, fx: str, sig: str, run: str, win: str, sb: str) -> complex:
    return phasor_from_integrals(_need(marks, mark_key(fx, sig, run, win, sb, "c")),
                                 _need(marks, mark_key(fx, sig, run, win, sb, "s")), window_len(win))


def port_vi(marks: dict, fx: str, run: str, win: str, sb: str, sign: float = 1.0) -> tuple[complex, complex]:
    """(V, I) raw phasors at the port, I positive into the DUT (times ``sign``)."""
    _, _, term, z0 = FIXTURES[fx]
    v = raw_phasor(marks, fx, "v", run, win, sb)
    i = raw_phasor(marks, fx, "i", run, win, sb)
    if term:
        i = i + (raw_phasor(marks, fx, "t", run, win, sb) - v) / z0
    return v, sign * i


# ---- extraction ----------------------------------------------------------------------------------

def solve2(a11: complex, a12: complex, a21: complex, a22: complex, b1: complex, b2: complex) -> tuple[complex, complex]:
    det = a11 * a22 - a12 * a21
    if det == 0:
        raise ProbeError("singular 2x2 port-voltage matrix (perturbation phases not independent)")
    return (b1 * a22 - a12 * b2) / det, (a11 * b2 - a21 * b1) / det


def cond2(a11: complex, a12: complex, a21: complex, a22: complex) -> float:
    """2-norm condition number of a complex 2x2 matrix."""
    fro2 = abs(a11) ** 2 + abs(a12) ** 2 + abs(a21) ** 2 + abs(a22) ** 2
    det = abs(a11 * a22 - a12 * a21)
    if det == 0:
        return float("inf")
    disc = max(fro2 * fro2 - 4 * det * det, 0.0)
    s1 = math.sqrt((fro2 + math.sqrt(disc)) / 2)
    s2 = det / s1
    return s1 / s2


def responses(marks: dict, fx: str, set_name: str, sabotage: str | None = None) -> dict:
    """Baseline-subtracted port phasors of the two perturbation phases of one set."""
    r1, r2, base, win = SETS[set_name]
    sign = -1.0 if sabotage == "current_sign" else 1.0
    out = {}
    for sb in SIDEBANDS:
        vb, ib = port_vi(marks, fx, base, win, sb, sign)
        if sabotage == "no_baseline":
            vb, ib = 0j, 0j
        for tag, run in (("1", r1), ("2", r2)):
            v, i = port_vi(marks, fx, run, win, sb, sign)
            out[f"V{sb}{tag}"], out[f"I{sb}{tag}"] = v - vb, i - ib
    return out


def extract(marks: dict, fx: str, set_name: str, sabotage: str | None = None) -> dict:
    """The 2x2 sideband admittance of one fixture from one extraction set."""
    r = responses(marks, fx, set_name, sabotage)
    vu1, vl1, vu2, vl2 = r["Vu1"], r["Vl1"], r["Vu2"], r["Vl2"]
    iu1, il1, iu2, il2 = r["Iu1"], r["Il1"], r["Iu2"], r["Il2"]
    cond = cond2(vu1, vl1.conjugate(), vu2, vl2.conjugate())
    if vu1 == 0 or vu2 == 0 or vl1 == 0 or vl2 == 0:
        raise ProbeError(f"{fx}/{set_name}: zero port-voltage response")
    if sabotage == "omit_image":
        y = {"uu": iu1 / vu1, "ul": 0j, "lu": 0j, "ll": il1 / vl1}
    else:
        yuu, yul = solve2(vu1, vl1.conjugate(), vu2, vl2.conjugate(), iu1, iu2)
        ylu, yll = solve2(vu1.conjugate(), vl1, vu2.conjugate(), vl2, il1, il2)
        y = {"uu": yuu, "ul": yul, "lu": ylu, "ll": yll}
    su1, su2, sl1, sl2 = iu1 / vu1, iu2 / vu2, il1 / vl1, il2 / vl2
    spread = max(abs(su1 - su2) / max(abs(su1 + su2) / 2, 1e-300),
                 abs(sl1 - sl2) / max(abs(sl1 + sl2) / 2, 1e-300))
    return {"y": y, "cond": cond, "scalar_phase_spread": spread, "phasors": r}


def kappa(y: dict) -> float:
    return max(abs(y["ul"]) / max(abs(y["uu"]), 1e-300), abs(y["lu"]) / max(abs(y["ll"]), 1e-300))


def ynorm(y: dict) -> float:
    return max(abs(y["uu"]), abs(y["ll"]))


def rel_change(a: dict, b: dict) -> float:
    """max_e |a_e - b_e| / max(|a_uu|, |a_ll|)."""
    n = ynorm(a)
    if n == 0:
        return float("inf")
    return max(abs(a[e] - b[e]) for e in ELEMENTS) / n


def response_to_baseline(marks: dict, fx: str) -> float:
    """Smallest |response| / |baseline| over runs, sidebands, port V and port I."""
    worst = float("inf")
    for r1, r2, base, win in SETS.values():
        for run in (r1, r2):
            for sb in SIDEBANDS:
                vb, ib = port_vi(marks, fx, base, win, sb)
                v, i = port_vi(marks, fx, run, win, sb)
                for resp, bl in ((v - vb, vb), (i - ib, ib)):
                    worst = min(worst, abs(resp) / max(abs(bl), 1e-30))
    return worst


def analyse_fixture(marks: dict, fx: str, thr: dict, sabotage: str | None = None) -> dict:
    """Extraction, numerical checks and classification of one fixture."""
    sets = {s: extract(marks, fx, s, sabotage) for s in SETS}
    prim = sets["primary"]["y"]
    conv = {}
    for name, s in CONVERGENCE.items():
        d = rel_change(prim, sets[s]["y"])
        conv[name] = {"rel_change": d, "tol": thr[CONVERGENCE_TOL_KEY[name]],
                      "pass": d <= thr[CONVERGENCE_TOL_KEY[name]]}
    cond = max(v["cond"] for v in sets.values())
    rtb = response_to_baseline(marks, fx)
    checks = dict(conv)
    checks["conditioning"] = {"cond_max_over_sets": cond, "tol": thr["cond_max"], "pass": cond <= thr["cond_max"]}
    checks["response_to_baseline"] = {"min_ratio": rtb, "tol": thr["response_to_baseline_min"],
                                      "pass": rtb >= thr["response_to_baseline_min"]}
    k = kappa(prim)
    dmax = max(c["rel_change"] for c in conv.values())
    diag_min = min(abs(prim["uu"]), abs(prim["ll"]))
    u = dmax * ynorm(prim) / diag_min if diag_min > 0 else float("inf")
    status, reasons = classify(k, u, all(c["pass"] for c in checks.values()), thr,
                               failed=[n for n, c in checks.items() if not c["pass"]])
    return {"y": {e: cplx(v) for e, v in prim.items()},
            "y_sets": {s: {e: cplx(v) for e, v in d["y"].items()} for s, d in sets.items()},
            "kappa": k, "kappa_uncertainty": u, "scalar_phase_spread": sets["primary"]["scalar_phase_spread"],
            "checks": checks, "numerics_pass": all(c["pass"] for c in checks.values()),
            "classification": status, "classification_reasons": reasons,
            "phasors": {k2: cplx(v) for k2, v in sets["primary"]["phasors"].items()}}


def classify(k: float, u: float, numerics_ok: bool, thr: dict, failed: list | None = None,
             controls_ok: bool = True) -> tuple[str, list[str]]:
    """Scalar adequate / matrix required / inconclusive. Never a compliance verdict."""
    ks = thr["kappa_scalar_max"]
    if not controls_ok:
        return S_INCONCLUSIVE, ["known-answer controls failed: the extraction is not qualified"]
    if not numerics_ok:
        return S_INCONCLUSIVE, [f"numerical check failed: {', '.join(failed or [])}"]
    if k + u < ks:
        return S_SCALAR, [f"kappa {k:.4g} + uncertainty {u:.3g} < {ks:g}: a scalar sideband admittance "
                          "describes the port at this point"]
    if k - u > ks:
        return S_MATRIX, [f"kappa {k:.4g} - uncertainty {u:.3g} > {ks:g}: conjugate image coupling is "
                          "significant; a sideband-coupled 2x2 admittance is required"]
    return S_INCONCLUSIVE, [f"kappa {k:.4g} +- {u:.3g} straddles the {ks:g} scalar bound"]


def cplx(z: complex) -> list[float]:
    return [z.real, z.imag]


def from_cplx(v) -> complex:
    return complex(v[0], v[1])


# ---- known answers ------------------------------------------------------------------------------

def rc_expected() -> dict:
    def y(f):
        return 1 / (RC_R + 1 / (1j * 2 * math.pi * f * RC_C))
    return {"uu": y(F_U), "ul": 0j, "lu": 0j, "ll": y(F_L)}


def md_expected() -> dict:
    g2 = MD_G2 * cmath.exp(1j * math.radians(MD_TH_DEG))
    return {"uu": MD_G0 + 1j * 2 * math.pi * F_U * MD_CM, "ul": g2, "lu": g2,
            "ll": MD_G0 + 1j * 2 * math.pi * F_L * MD_CM}


EXPECTED = {"rc": rc_expected, "md": md_expected}
EXPECTED_CLASS = {"rc": S_SCALAR, "md": S_MATRIX}


def phase_err_deg(a: complex, b: complex) -> float:
    if a == 0 or b == 0:
        return 180.0
    d = math.degrees(cmath.phase(a / b))
    return abs((d + 180.0) % 360.0 - 180.0)


def evaluate_controls(marks: dict, thr: dict, sabotage: str | None = None) -> dict:
    """Known-answer checks on both control fixtures (flat check names ``<fx>.<check>``)."""
    checks: dict[str, dict] = {}
    fixtures = {}
    for fx in CONTROL_FIXTURES:
        an = analyse_fixture(marks, fx, thr, sabotage)
        fixtures[fx] = an
        exp = EXPECTED[fx]()
        got = {e: from_cplx(v) for e, v in an["y"].items()}
        for e in ELEMENTS:
            if exp[e] == 0:
                diag = abs(got["uu"]) if e == "ul" else abs(got["ll"])
                null = abs(got[e]) / max(diag, 1e-300)
                checks[f"{fx}.{e}"] = {"expected": [0.0, 0.0], "measured": cplx(got[e]),
                                       "relative_to_diagonal": null, "tol": thr["control_null_rel_tol"],
                                       "pass": null <= thr["control_null_rel_tol"]}
            else:
                mag = abs(abs(got[e]) / abs(exp[e]) - 1)
                ph = phase_err_deg(got[e], exp[e])
                checks[f"{fx}.{e}"] = {"expected": cplx(exp[e]), "measured": cplx(got[e]),
                                       "mag_rel_err": mag, "phase_err_deg": ph,
                                       "pass": mag <= thr["control_mag_rel_tol"] and ph <= thr["control_phase_tol_deg"]}
        checks[f"{fx}.numerics"] = {"failed": [n for n, c in an["checks"].items() if not c["pass"]],
                                    "pass": an["numerics_pass"]}
        checks[f"{fx}.classification"] = {"expected": EXPECTED_CLASS[fx], "got": an["classification"],
                                          "pass": an["classification"] == EXPECTED_CLASS[fx]}
    return {"pass": all(c["pass"] for c in checks.values()), "checks": checks, "fixtures": fixtures}


def evaluate(parsed: dict, thr: dict, sabotage: str | None = None) -> dict:
    """Controls + (if present) DUT + overall status. Pure function of the parsed log."""
    if not parsed.get("completed"):
        raise ProbeError("probe log incomplete (no 'MARK done')")
    mk = parsed["marks"]
    ctl = evaluate_controls(mk, thr, sabotage)
    out = {"controls": ctl, "dut": None, "status": None, "reasons": []}
    if not parsed.get("has_dut"):
        return out
    dut = analyse_fixture(mk, "dut", thr, sabotage)
    failed = [n for n, c in dut["checks"].items() if not c["pass"]]
    status, reasons = classify(dut["kappa"], dut["kappa_uncertainty"], dut["numerics_pass"], thr,
                               failed=failed, controls_ok=ctl["pass"])
    out.update(dut=dut, status=status, reasons=reasons)
    return out


# ---- fabricating marks from closed form (tests; also documents the mark schema) -----------------

def _port_solution(y: dict, z0: float | None, a: float, phu: float, phl: float) -> dict:
    """Port (V, I) per sideband for a pumped 2x2 port driven by tones of EMF ``a``."""
    eu, el = sin_tone_phasor(a, phu), sin_tone_phasor(a, phl)
    if z0 is None:  # ideal voltage drive
        vu, vl = eu, el
    else:           # Norton J = E/z0 in parallel with z0
        ju, jl = eu / z0, el / z0
        g = 1 / z0
        # (Yuu+g) Vu + Yul conj(Vl) = Ju ; conj(Ylu) Vu + conj(Yll+g) conj(Vl) = conj(Jl)
        vu, cvl = solve2(y["uu"] + g, y["ul"], y["lu"].conjugate(), (y["ll"] + g).conjugate(),
                         ju, jl.conjugate()) if a else (0j, 0j)
        vl = cvl.conjugate()
    iu = y["uu"] * vu + y["ul"] * vl.conjugate()
    il = y["lu"] * vu.conjugate() + y["ll"] * vl
    return {"u": (vu, iu), "l": (vl, il)}


def synth_marks(dut_y: dict | None = None, perturb: dict | None = None, baseline: dict | None = None,
                rc_y: dict | None = None, md_y: dict | None = None) -> dict:
    """Marks the deck would print for fixtures with the given (or known-answer) admittances.

    ``perturb`` maps an extraction set ("halved", "extended", "refined") to a complex
    additive change of every DUT element in that set's runs (mimicking amplitude
    dependence, unsettled windows or integration error). ``baseline`` maps a fixture to
    {sideband: (V, I)} added to every run (the LO-only content); md defaults to its
    known ``ib`` term.
    """
    perturb = perturb or {}
    models = {"rc": (rc_y or rc_expected(), 50.0), "md": (md_y or md_expected(), None)}
    if dut_y is not None:
        models["dut"] = (dut_y, 50.0)
    base = {"md": {"u": (0j, sin_tone_phasor(MD_IB, MD_PHB_DEG)), "l": (0j, 0j)}}
    base.update(baseline or {})
    mk: dict[str, float] = {}
    for fx, (y, z0) in models.items():
        _, _, term, _ = FIXTURES[fx]
        for run, (a, phu, phl, refined) in RUNS.items():
            for win in run_windows(run):
                yy = dict(y)
                if fx == "dut":
                    for s, (r1, r2, _b, w) in SETS.items():
                        if s in perturb and run in (r1, r2) and win == w:
                            yy = {e: y[e] + perturb[s] for e in ELEMENTS}
                sol = _port_solution(yy, z0, a, phu, phl)
                t = window_len(win)
                for sb in SIDEBANDS:
                    v, i = sol[sb]
                    bv, bi = base.get(fx, {}).get(sb, (0j, 0j))
                    v, i = v + bv, i + bi
                    # raw sense current: I = i_sense + (t - v)/z0 with t = 0  ->  i_sense = I + v/z0
                    isense = i + v / z0 if term else i
                    sigs = {"v": v, "i": isense}
                    if term:
                        sigs["t"] = 0j
                    for sig, x in sigs.items():
                        c, s = integrals_from_phasor(x, t)
                        mk[mark_key(fx, sig, run, win, sb, "c")] = c
                        mk[mark_key(fx, sig, run, win, sb, "s")] = s
    return mk


def synth_stdout(mk: dict, done: bool = True) -> str:
    lines = ["MARK ngspice_banner_follows"] + [f"MARK {k}={v:.15g}" for k, v in mk.items()]
    if done:
        lines.append("MARK done")
    return "\n".join(lines) + "\n"
