"""Ka-band npn13G2 device characterization: deck generation, log parsing,
and postprocessing (issue #17).

BENCH-LOCAL module, built on ``sim/harness`` rather than inside it: the
generic harness core runs one scalar ``measure`` set per PVT point; this
bench needs an independent Nx x VCE x VBE sweep *inside* every PVT point,
with several analyses per bias point (op, two Y-parameter ``.ac`` runs, an
``h21`` sweep, and one ``.noise`` run per source impedance per frequency).
So:

- :func:`build_control_lines` generates that sweep as an ngspice control
  loop. The same lines are used by ``run.py``'s local smoke/selftest path
  (appended by :func:`harness.runner.compose_deck` as the deck's
  ``.control`` block, one PVT point per ngspice process) and by its full-grid
  ``klt sim`` path (inlined into the request body).
- :func:`parse_log` turns one PVT point's ngspice log into per-bias-point raw
  rows, refusing stale or missing values.
- :func:`analyze_point` / :func:`analyze_frequency` do the physics: Y -> S,
  stability factor K / |Delta| and MAG-or-MSG, the h21 0 dB crossing (fT),
  and the two-port noise parameters (Fmin, Zopt, Rn) from several noiseless
  passive source impedances, validated against an independent simulation at
  the extracted optimum and against a direct 50 ohm simulation.
- :func:`cell_optima` / :func:`row3_screen` reduce full per-point rows to the
  per-corner summaries the record reports. The full per-point rows are always
  kept (written as record sidecars by run.py), so no aggregate can discard
  sweep data.

Everything here is pure Python (stdlib only) so ``tests/`` can exercise it
against synthetic data with known answers.
"""

from __future__ import annotations

import cmath
import math
import re
from dataclasses import dataclass, field

K_BOLTZMANN = 1.380649e-23  # J/K (exact, SI 2019)

#: Emitter area per emitter finger used for J_C, um^2. sg13g2_hbt_mod.lib's
#: header states "Emitter size (mask): Nx *(0.07 x 0.90) um^2", and the
#: process spec (SG13G2_os_process_spec.pdf section 3.1, quoted in
#: spec/target-spec.md) gives the same AE = 0.07 x 0.9 um^2 for npn13g2.
AE_UM2_PER_NX = 0.07 * 0.90
#: The alternative convention sg13g2-lna's hbt-characterization uses: the
#: npn13G2 subckt's own le*we default (0.96 um * 0.12 um). Neither parameter
#: enters the VBIC card's equations (only Nx does). Recorded as a second
#: column so numbers can be compared with that repo without re-deriving.
AE_ALT_UM2_PER_NX = 0.96 * 0.12

#: Model-card validity box, sg13g2_hbt_mod.lib header:
#: "ic: <(0.003*Nx) A  vbe :(0.65 - 0.96) V  vce :(0.4 - 2.0) V",
#: "Temp: -40 C - +125 C", "Valid numbers: NX = 1 - 10".
VALID_IC_A_PER_NX = 0.003
VALID_VBE_V = (0.65, 0.96)
VALID_VCE_V = (0.4, 2.0)
VALID_TEMP_C = (-40.0, 125.0)
VALID_NX = (1, 10)

#: Tolerance for the independent optimum check: NF simulated at the applied
#: optimum source impedance vs. the extracted NFmin.
NFMIN_CHECK_TOL_DB = 0.001
#: Tolerance for the direct 50 ohm simulation vs. the fitted noise
#: parameters' prediction at the same (exactly applied) impedance.
NF50_CHECK_TOL_DB = 0.001
#: Relative agreement required between the two DUT copies' collector current.
COPY_IC_RTOL = 1e-6

ROW3_LIMIT_DB = 2.5
T0_IEEE_K = 290.0
T0_REPO_K = 300.15

#: Gate on the noise-parameter least-squares fit. The model Sv(Zs) is exact
#: for a linear two-port, so a residual above this means the simulator's
#: noise numbers are not self-consistent (this is how the 1 H / 1 F
#: bias-tee conditioning problem documented in the fixture was found:
#: residual 1.3e-3 there, ~1e-10 with the committed element values at
#: 27 C). Each of the ten .noise runs re-solves the operating point, so at
#: 125 C, where ngspice needs gmin stepping, the separately converged
#: points scatter slightly: residuals up to 6e-6 were observed with the NF
#: checks still agreeing to 4e-6 dB. 1e-4 sits well above that scatter and
#: well below the known-bad case.
FIT_RESIDUAL_MAX = 1e-4

# L / C values used to realise a source reactance with no element removed
# from the deck: a "zero" inductor and a "short" capacitor (the same 1 nF as
# the fixture's DC blocks -- see its header for why not 1 F). Both are
# included exactly in applied_impedance(), so neither is an approximation.
L_ZERO_H = 1e-15
C_SHORT_F = 1e-9


# ---------------------------------------------------------------------------
# Sweep declaration
# ---------------------------------------------------------------------------


class SweepError(ValueError):
    """A sweep declaration is malformed."""


@dataclass(frozen=True)
class Sweep:
    nx: tuple[int, ...]
    vce_v: tuple[float, ...]
    vbe_v: tuple[float, ...]
    frequencies_hz: tuple[float, ...]
    source_impedances_ohm: tuple[tuple[float, float], ...]
    nf50_check_ohm: tuple[float, float]
    ft_sweep: str
    t0_k: tuple[float, ...]
    z0_ohm: float = 50.0

    @property
    def n_bias_points(self) -> int:
        return len(self.nx) * len(self.vce_v) * len(self.vbe_v)

    def closed_form_set(self) -> tuple[float, float, float]:
        """(R1, R2, X) of the first four declared impedances, which must be
        R1, R2, R1+jX, R1-jX (X > 0): the set the in-deck closed-form
        optimum (used only to choose the independent check point) needs."""
        z = self.source_impedances_ohm
        (r1, x1), (r2, x2), (r3, x3), (r4, x4) = z[:4]
        return r1, r2, x3


def _vbe_list(spec) -> tuple[float, ...]:
    if isinstance(spec, dict):
        start, stop, step = float(spec["start"]), float(spec["stop"]), float(spec["step"])
        if step <= 0 or stop < start:
            raise SweepError(f"bad vbe range {spec!r}")
        n = int(round((stop - start) / step)) + 1
        return tuple(round(start + i * step, 6) for i in range(n))
    return tuple(float(v) for v in spec)


def sweep_from_manifest(manifest: dict, profile: str = "full") -> Sweep:
    """Build a :class:`Sweep` from ``tb.json``'s ``sweep`` block.

    ``profile`` selects ``sweep.full`` or ``sweep.reduced``; the reduced
    profile only overrides the bias axes (nx / vce_v / vbe_v) and inherits
    every RF definition from the full one, so smoke/selftest exercise the
    exact same frequencies, source impedances and fT sweep as the record.
    """
    block = manifest.get("sweep")
    if not isinstance(block, dict) or "full" not in block:
        raise SweepError("tb.json has no sweep.full block")
    merged = dict(block["full"])
    if profile != "full":
        if profile not in block:
            raise SweepError(f"tb.json has no sweep.{profile} block")
        merged.update(block[profile])
    sweep = Sweep(
        nx=tuple(int(n) for n in merged["nx"]),
        vce_v=tuple(float(v) for v in merged["vce_v"]),
        vbe_v=_vbe_list(merged["vbe_v"]),
        frequencies_hz=tuple(float(f) for f in merged["frequencies_hz"]),
        source_impedances_ohm=tuple(
            (float(r), float(x)) for r, x in merged["source_impedances_ohm"]
        ),
        nf50_check_ohm=tuple(float(v) for v in merged["nf50_check_ohm"]),
        ft_sweep=str(merged["ft_sweep"]),
        t0_k=tuple(float(t) for t in merged["t0_k"]),
        z0_ohm=float(merged.get("z0_ohm", 50.0)),
    )
    validate_sweep(sweep)
    return sweep


def validate_sweep(sweep: Sweep) -> None:
    problems: list[str] = []
    for nx in sweep.nx:
        if not VALID_NX[0] <= nx <= VALID_NX[1]:
            problems.append(f"Nx={nx} outside the model card's {VALID_NX} range")
    for vce in sweep.vce_v:
        if not VALID_VCE_V[0] <= vce <= VALID_VCE_V[1]:
            problems.append(f"VCE={vce} outside the model card's {VALID_VCE_V} V range")
    f = sweep.frequencies_hz
    if len(f) >= 2:
        steps = {round(f[i + 1] - f[i], 3) for i in range(len(f) - 1)}
        if len(steps) != 1:
            problems.append("frequencies_hz must be equally spaced (one `ac lin N` run)")
    z = sweep.source_impedances_ohm
    if len(z) < 5:
        problems.append("need at least 5 source impedances (4 unknowns + 1 redundancy)")
    else:
        (r1, x1), (r2, x2), (r3, x3), (r4, x4) = z[:4]
        if not (x1 == 0 and x2 == 0 and r3 == r1 and r4 == r1 and x3 > 0 and x4 == -x3
                and r2 != r1):
            problems.append(
                "the first four source impedances must be R1, R2, R1+jX, R1-jX (X > 0, R2 != R1)"
            )
    for r, _x in z:
        if r <= 0:
            problems.append(f"source resistance {r} must be > 0")
    if sweep.nf50_check_ohm in z:
        problems.append("nf50_check_ohm must NOT be one of the fitted impedances (it is the independent check)")
    if problems:
        raise SweepError("; ".join(problems))


# ---------------------------------------------------------------------------
# Deck (control-block) generation
# ---------------------------------------------------------------------------


def source_elements(r_ohm: float, x_ohm: float, f_hz: float) -> tuple[float, float, float]:
    """(R, L, C) realising Zs = R + jX at ``f_hz`` with the fixture's
    series rsz-lsz-csz chain (csz is also the DC block)."""
    w = 2.0 * math.pi * f_hz
    if x_ohm > 0:
        return r_ohm, x_ohm / w, C_SHORT_F
    if x_ohm < 0:
        return r_ohm, L_ZERO_H, -1.0 / (w * x_ohm)
    return r_ohm, L_ZERO_H, C_SHORT_F


def applied_impedance(r: float, l_h: float, c_f: float, f_hz: float) -> complex:
    """The exact series impedance of the realised chain at ``f_hz``."""
    w = 2.0 * math.pi * f_hz
    return complex(r, w * l_h - 1.0 / (w * c_f))


def _g(v: float) -> str:
    return f"{v:.10g}"


def build_control_lines(sweep: Sweep, *, sabotage_measurement: bool = False) -> list[str]:
    """The ngspice control-language sweep for ONE PVT point.

    Output protocol (parsed by :func:`parse_log`):

    - ``KA_DECK_BEGIN`` / ``KA_DECK_END`` bracket the whole sweep; a log
      without ``KA_DECK_END`` was truncated (timeout / crash).
    - ``KA_POINT nx=<n> vce=<v> vbe=<v>`` opens one bias point.
    - ``KA_BLOCK <tag>`` opens one analysis's output; the ``name = value``
      lines that follow belong to it.
    - ``destroy all`` precedes every analysis, so a failed analysis leaves
      no vector behind for a following ``let``/``print`` to pick up: a
      failure shows up as a MISSING value, never as a stale one carried
      over from a previous plot (the cross-plot hazard sg13g2-lna's
      hbt-characterization documents).

    ``sabotage_measurement`` replaces one required printed quantity with a
    vector that does not exist -- the selftest's deliberately invalid deck,
    which the parser/postprocessor must reject.
    """
    f = sweep.frequencies_hz
    r1, r2, xcf = sweep.closed_form_set()
    lines = [
        "set numdgt=10",
        "set noaskquit",
        'echo "KA_DECK_BEGIN"',
        "foreach ka_nx " + " ".join(str(n) for n in sweep.nx),
        "  alterparam nx_dut = $ka_nx",
        "  reset",
        "  foreach ka_vce " + " ".join(f"{v:.3f}" for v in sweep.vce_v),
        "    alter vce_src dc = $ka_vce",
        "    foreach ka_vbe " + " ".join(f"{v:.4f}" for v in sweep.vbe_v),
        "      alter vbe_src dc = $ka_vbe",
        '      echo "KA_POINT nx=$ka_nx vce=$ka_vce vbe=$ka_vbe"',
    ]
    body: list[str] = []

    # --- DC operating point (both copies) ---
    icn_expr = "@q.xqn.qnpn13g2[ic]" if not sabotage_measurement else "@q.xqn.qnpn13g2[nonexistent_field]"
    body += [
        "destroy all",
        "op",
        'echo "KA_BLOCK op"',
        f"let ka_icn = {icn_expr}",
        "print ka_icn",
        "let ka_ibn = @q.xqn.qnpn13g2[ib]",
        "print ka_ibn",
        "let ka_icy = @q.xqy.qnpn13g2[ic]",
        "print ka_icy",
        "let ka_iby = @q.xqy.qnpn13g2[ib]",
        "print ka_iby",
        "let ka_vb = v(bn)",
        "print ka_vb",
        "let ka_vc = v(cn)",
        "print ka_vc",
        "let ka_dtj = v(xqn.t)",
        "print ka_dtj",
        "let ka_vsup = v(vsupply)",
        "print ka_vsup",
    ]

    # --- Y-parameters at the band frequencies (forward, reverse) ---
    ac_band = f"ac lin {len(f)} {_g(f[0])} {_g(f[-1])}" if len(f) > 1 else f"ac lin 1 {_g(f[0])} {_g(f[0])}"
    for tag, m1, m2, names in (
        ("yfwd", 1, 0, ("y11", "y21")),
        ("yrev", 0, 1, ("y12", "y22")),
    ):
        body += [
            "destroy all",
            f"alter vy1 ac = {m1}",
            f"alter vy2 ac = {m2}",
            ac_band,
            f'echo "KA_BLOCK {tag}"',
            "print @q.xqy.qnpn13g2[ic]",
            "let ka_t1 = -i(vy1)",
            "let ka_t2 = -i(vy2)",
        ]
        for k in range(len(f)):
            for name, vec in zip(names, ("ka_t1", "ka_t2")):
                idx = f"[{k}]" if len(f) > 1 else ""
                body += [
                    f"let ka_{name}r_{k} = real({vec}{idx})",
                    f"print ka_{name}r_{k}",
                    f"let ka_{name}i_{k} = imag({vec}{idx})",
                    f"print ka_{name}i_{k}",
                ]

    # --- h21 sweep for fT (same operating point, short-circuit output) ---
    body += [
        "destroy all",
        "alter vy1 ac = 1",
        "alter vy2 ac = 0",
        f"ac {sweep.ft_sweep}",
        'echo "KA_BLOCK h21"',
        "print @q.xqy.qnpn13g2[ic]",
        "let ka_h21 = mag(i(vy2)/i(vy1))",
        "print ka_h21",
    ]

    # --- noise: every declared Zs at every frequency, plus checks ---
    for k, fk in enumerate(f):
        # The four closed-form inputs are copied, at full precision, into
        # the const plot (which survives `destroy all`); unlet first so a
        # failed analysis can never leave a previous point's value behind.
        body += ["setplot const", "unlet ka_h0 ka_h1 ka_h2 ka_h3 ka_ok ka_ro ka_lv ka_cv"]
        for j, (r, x) in enumerate(sweep.source_impedances_ohm):
            rv, lv, cv = source_elements(r, x, fk)
            body += [
                "destroy all",
                f"alter rsz = {_g(rv)}",
                f"alter lsz = {_g(lv)}",
                f"alter csz = {_g(cv)}",
                f"noise v(on) vsn lin 1 {_g(fk)} {_g(fk)}",
                f'echo "KA_BLOCK nz f={k} z={j}"',
                "print @q.xqn.qnpn13g2[ic]",
                "let ka_isp = inoise_spectrum",
                "print ka_isp",
            ]
            if j < 4:
                body += [
                    "set ka_pl = $curplot",
                    "setplot const",
                    f"let ka_h{j} = {{$ka_pl}}.inoise_spectrum",
                ]
            if j == 3:
                body += _zopt_check_lines(k, fk, r1, r2, xcf)
        rv, lv, cv = source_elements(*sweep.nf50_check_ohm, fk)
        body += [
            "destroy all",
            f"alter rsz = {_g(rv)}",
            f"alter lsz = {_g(lv)}",
            f"alter csz = {_g(cv)}",
            f"noise v(on) vsn lin 1 {_g(fk)} {_g(fk)}",
            f'echo "KA_BLOCK nf50 f={k}"',
            "print @q.xqn.qnpn13g2[ic]",
            "let ka_isp = inoise_spectrum",
            "print ka_isp",
        ]

    lines += ["      " + b for b in body]
    lines += [
        "    end",
        "  end",
        "end",
        'echo "KA_DECK_END"',
        # Leave the circuit at a benign bias (smallest Nx, the fixture's
        # default VBE/VCE): `reset` reverts every `alter`, and anything that
        # runs after this block (klt's own sentinel analysis) must not inherit
        # the sweep's last, most extreme point.
        f"alterparam nx_dut = {sweep.nx[0]}",
        "reset",
    ]
    return lines


def _zopt_check_lines(k: int, fk: float, r1: float, r2: float, x: float) -> list[str]:
    """In-deck closed-form optimum from the first four impedances, used ONLY
    to pick the independent check point; the reported NFmin/Zopt come from
    the postprocessor's least-squares fit over every declared impedance."""
    w = 2.0 * math.pi * fk
    # Runs with the const plot current (see build_control_lines): ka_h0..3
    # are the full-precision inoise values of the four closed-form impedances.
    # Element values are applied with `alter <dev> = <vector>` (full
    # precision), never via `$&` string substitution, which ngspice-46
    # truncates to 6 significant digits.
    return [
        "setplot const",
        "let ka_q0 = ka_h0*ka_h0",
        "let ka_q1 = ka_h1*ka_h1",
        "let ka_q2 = ka_h2*ka_h2",
        "let ka_q3 = ka_h3*ka_h3",
        f"let ka_dd = (ka_q2 - ka_q3)/(2*{_g(x)})",
        f"let ka_bb = ((ka_q2 + ka_q3)/2 - ka_q0)/({_g(x * x)})",
        f"let ka_cc = ((ka_q1 - ka_q0) - ka_bb*({_g(r2 * r2 - r1 * r1)}))/({_g(r2 - r1)})",
        f"let ka_aa = ka_q0 - ka_bb*{_g(r1 * r1)} - ka_cc*{_g(r1)}",
        "let ka_xo = -ka_dd/(2*ka_bb)",
        "let ka_ap = ka_aa - ka_dd*ka_dd/(4*ka_bb)",
        "let ka_ok = 0",
        "if ka_bb > 0",
        "  if ka_ap > 0",
        "    let ka_ok = 1",
        "  end",
        "end",
        "if ka_ok > 0",
        "  let ka_ro = sqrt(ka_ap/ka_bb)",
        "  if ka_xo > 0",
        f"    let ka_lv = ka_xo/{_g(w)}",
        f"    let ka_cv = {_g(C_SHORT_F)}",
        "  else",
        f"    let ka_lv = {_g(L_ZERO_H)}",
        f"    let ka_cv = -1/({_g(w)}*ka_xo)",
        "  end",
        "  alter rsz = ka_ro",
        "  alter lsz = ka_lv",
        "  alter csz = ka_cv",
        "  destroy all",
        f"  noise v(on) vsn lin 1 {_g(fk)} {_g(fk)}",
        f'  echo "KA_BLOCK zopt f={k}"',
        "  print @q.xqn.qnpn13g2[ic]",
        "  let ka_isp = inoise_spectrum",
        "  print ka_isp",
        "  print @rsz[resistance]",
        "  print @lsz[inductance]",
        "  print @csz[capacitance]",
        "else",
        f'  echo "KA_BLOCK zopt_skip f={k}"',
        "end",
    ]


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

_POINT_RE = re.compile(r"^KA_POINT nx=(\S+) vce=(\S+) vbe=(\S+)\s*$")
_BLOCK_RE = re.compile(r"^KA_BLOCK (\S+)(?: f=(\d+))?(?: z=(\d+))?\s*$")
_VALUE_RE = re.compile(r"^(\S+) = ([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*$")
_TABLE_RE = re.compile(
    r"^(\d+)\s+([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s+([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*$"
)
#: Simulator message lines worth keeping as annotations. They are NOT
#: exclusion criteria: ngspice prints recovered conditions ("singular
#: matrix", "Dynamic gmin stepping failed", pivot warnings) as warnings and
#: carries on, and in a log written with `-o` its stderr and stdout
#: interleave, so a message can land next to the wrong point. Validity is
#: decided from VALUES instead (missing values; the per-analysis bias gate;
#: the noise-fit, 50 ohm and optimum checks) -- see analyze_point.
_MESSAGE_RE = re.compile(r"^(warning|error|fatal|doanalyses|internal error|the temperature limiting)",
                         re.IGNORECASE)
#: Relative agreement required between the Ic every analysis actually ran
#: at and the operating point the row reports. Observed scatter between
#: separately converged operating points: <= 2.6e-6 (125 C, gmin stepping);
#: an analysis that lands in a different electrothermal state differs at
#: the percent level. 1e-4 separates the two.
BIAS_RTOL = 1e-4
_IC_KEYS = ("@q.xqn.qnpn13g2[ic]", "@q.xqy.qnpn13g2[ic]")


def normalize_message(line: str) -> str:
    """A message line with numbers and node names folded, for tallying."""
    out = re.sub(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", "N", line.strip())
    out = re.sub(r"check nodes? .*", "check nodes ...", out)
    return out[:120]


def log_messages(text: str) -> dict[str, int]:
    """Tally of every simulator warning/error line in a log (normalized)."""
    counts: dict[str, int] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if _MESSAGE_RE.match(line):
            key = normalize_message(line)
            counts[key] = counts.get(key, 0) + 1
    return counts


@dataclass
class RawPoint:
    nx: int
    vce_set: float
    vbe_set: float
    blocks: dict[str, dict[str, float]] = field(default_factory=dict)
    tables: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)


@dataclass
class ParsedLog:
    points: list[RawPoint]
    complete: bool
    unattributed_errors: list[str]


def parse_log(text: str) -> ParsedLog:
    points: list[RawPoint] = []
    current: RawPoint | None = None
    block: str | None = None
    complete = False
    unattributed_errors: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "KA_DECK_END":
            complete = True
            current, block = None, None
            continue
        m = _POINT_RE.match(line)
        if m:
            current = RawPoint(nx=int(float(m.group(1))), vce_set=float(m.group(2)),
                               vbe_set=float(m.group(3)))
            points.append(current)
            block = None
            continue
        if current is None:
            if _MESSAGE_RE.match(line):
                unattributed_errors.append(line)
            continue
        m = _BLOCK_RE.match(line)
        if m:
            tag = m.group(1)
            if m.group(2) is not None:
                tag += f".f{m.group(2)}"
            if m.group(3) is not None:
                tag += f".z{m.group(3)}"
            block = tag
            current.blocks.setdefault(block, {})
            continue
        if _MESSAGE_RE.match(line):
            msg = normalize_message(line)
            if msg not in current.messages:
                current.messages.append(msg)
            continue
        if block is None:
            continue
        m = _VALUE_RE.match(line)
        if m:
            current.blocks[block][m.group(1).lower()] = float(m.group(2))
            continue
        m = _TABLE_RE.match(line)
        if m:
            current.tables.setdefault(block, []).append((float(m.group(2)), float(m.group(3))))
    return ParsedLog(points=points, complete=complete, unattributed_errors=unattributed_errors)


# ---------------------------------------------------------------------------
# Physics
# ---------------------------------------------------------------------------


def y_to_s(y11: complex, y12: complex, y21: complex, y22: complex, z0: float = 50.0):
    """Two-port Y -> S at a real reference impedance ``z0``."""
    a11, a12, a21, a22 = y11 * z0, y12 * z0, y21 * z0, y22 * z0
    d = (1 + a11) * (1 + a22) - a12 * a21
    s11 = ((1 - a11) * (1 + a22) + a12 * a21) / d
    s12 = -2 * a12 / d
    s21 = -2 * a21 / d
    s22 = ((1 + a11) * (1 - a22) + a12 * a21) / d
    return s11, s12, s21, s22


def gain_metrics(s11: complex, s12: complex, s21: complex, s22: complex) -> dict:
    """Rollett K, |Delta|, and the maximum gain that exists.

    MAG (maximum available gain, simultaneous conjugate match) exists only
    when the two-port is unconditionally stable, K > 1 AND |Delta| < 1. Any
    other case reports MSG = |S21|/|S12| (maximum stable gain) with
    ``gmax_kind = "MSG"`` -- never a MAG where it is undefined.
    """
    delta = s11 * s22 - s12 * s21
    mag_s12, mag_s21 = abs(s12), abs(s21)
    if mag_s12 == 0 or mag_s21 == 0:
        return {"k": None, "delta_mag": abs(delta), "gmax_db": None, "gmax_kind": "undefined",
                "msg_db": None, "s21_db": None}
    k = (1 - abs(s11) ** 2 - abs(s22) ** 2 + abs(delta) ** 2) / (2 * mag_s12 * mag_s21)
    msg = mag_s21 / mag_s12
    unconditionally_stable = k > 1 and abs(delta) < 1
    if unconditionally_stable:
        g = msg * (k - math.sqrt(k * k - 1))
        kind = "MAG"
    else:
        g = msg
        kind = "MSG"
    return {
        "k": k,
        "delta_mag": abs(delta),
        "gmax_db": 10 * math.log10(g),
        "gmax_kind": kind,
        "msg_db": 10 * math.log10(msg),
        "s21_db": 20 * math.log10(mag_s21),
    }


def ft_from_h21(table: list[tuple[float, float]]) -> dict:
    """fT = the frequency where |h21| crosses 1 (0 dB), log-log interpolated
    between the two bracketing sweep points. Never extrapolates: a sweep that
    never crosses reports why, with ``ft_hz = None``."""
    if not table:
        return {"ft_hz": None, "ft_status": "no_h21_data"}
    pts = sorted(table)
    if any(not (h > 0 and math.isfinite(h)) for _, h in pts):
        return {"ft_hz": None, "ft_status": "h21_nonfinite"}
    if pts[0][1] < 1.0:
        return {"ft_hz": None, "ft_status": "below_sweep_start",
                "ft_bracket": f"|h21|={pts[0][1]:.4g}<1 at {pts[0][0]:.4g} Hz"}
    for (f_lo, h_lo), (f_hi, h_hi) in zip(pts, pts[1:]):
        if h_lo >= 1.0 > h_hi:
            frac = math.log(h_lo) / (math.log(h_lo) - math.log(h_hi))
            ft = math.exp(math.log(f_lo) + frac * (math.log(f_hi) - math.log(f_lo)))
            return {"ft_hz": ft, "ft_status": "bracketed",
                    "ft_bracket": f"[{f_lo:.6g} Hz |h21|={h_lo:.6g}, {f_hi:.6g} Hz |h21|={h_hi:.6g}]"}
    return {"ft_hz": None, "ft_status": "above_sweep_stop",
            "ft_bracket": f"|h21|={pts[-1][1]:.4g}>=1 at {pts[-1][0]:.4g} Hz"}


class NoiseFitError(ValueError):
    pass


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (small dense systems)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-300:
            raise NoiseFitError("singular normal equations (degenerate impedance set)")
        m[col], m[piv] = m[piv], m[col]
        for r in range(col + 1, n):
            fac = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= fac * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def fit_noise_parameters(samples: list[tuple[complex, float]]) -> dict:
    """Two-port noise parameters from (Zs, Sv) samples.

    ``Sv`` is the device's input-referred noise voltage density squared
    (V^2/Hz) in series with a NOISELESS source impedance ``Zs`` (ngspice's
    ``inoise_spectrum``^2 with the source resistor ``noisy=0``). For any
    linear noisy two-port, with en/in its input-referred voltage/current
    noise sources,

        Sv(Zs) = |en + Zs*in|^2 = a + b*|Zs|^2 + c*Rs + d*Xs

    exactly (a = |en|^2, b = |in|^2, c/d = 2 Re/Im of the correlation), so
    a weighted least-squares fit over >= 4 non-degenerate impedances
    recovers it (Lane's method in impedance form). Rows are weighted by
    1/Sv so every impedance counts by relative, not absolute, error.

    The noise temperature at the optimum is T0-independent:

        Xopt = -d/(2b),  a' = a - d^2/(4b),  Ropt = sqrt(a'/b),
        Tmin = (2*sqrt(a'*b) + c) / (4k),    Fmin(T0) = 1 + Tmin/T0.

    Requires b > 0 and a' > 0 (a physically meaningful, bounded optimum);
    otherwise raises :class:`NoiseFitError`.
    """
    if len(samples) < 4:
        raise NoiseFitError(f"need >= 4 source impedances, got {len(samples)}")
    # Columns are scaled by a reference impedance so the 4x4 normal
    # equations stay well conditioned for |Zs| of order 10..1000 ohm.
    zr = 50.0
    rows, rhs = [], []
    for z, sv in samples:
        if not (sv > 0 and math.isfinite(sv)):
            raise NoiseFitError(f"non-positive/non-finite noise density {sv!r} at Zs={z}")
        w = 1.0 / sv
        u = z / zr
        rows.append([w, w * abs(u) ** 2, w * u.real, w * u.imag])
        rhs.append(1.0)  # (w * sv)
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(4)] for i in range(4)]
    atb = [sum(r[i] * y for r, y in zip(rows, rhs)) for i in range(4)]
    a, bs, cs, ds = _solve(ata, atb)
    b, c, d = bs / zr ** 2, cs / zr, ds / zr
    pred = [a + b * abs(z) ** 2 + c * z.real + d * z.imag for z, _ in samples]
    rel = [abs(p - sv) / sv for p, (_z, sv) in zip(pred, samples)]
    if b <= 0:
        raise NoiseFitError(f"fit gives b = |in|^2 = {b:.4g} <= 0 (no bounded optimum)")
    xopt = -d / (2 * b)
    ap = a - d * d / (4 * b)
    if ap <= 0:
        raise NoiseFitError(f"fit gives a' = {ap:.4g} <= 0 (no positive optimum resistance)")
    ropt = math.sqrt(ap / b)
    tmin = (2 * math.sqrt(ap * b) + c) / (4 * K_BOLTZMANN)
    return {
        "a": a, "b": b, "c": c, "d": d,
        "ropt_ohm": ropt,
        "xopt_ohm": xopt,
        "tmin_k": tmin,
        "fit_max_rel_residual": max(rel),
        "fit_n": len(samples),
    }


def noise_factor(fit: dict, zs: complex, t0_k: float) -> float:
    """F at source impedance ``zs`` predicted by a fit (source noise at T0)."""
    sv = fit["a"] + fit["b"] * abs(zs) ** 2 + fit["c"] * zs.real + fit["d"] * zs.imag
    return 1.0 + sv / (4 * K_BOLTZMANN * t0_k * zs.real)


def measured_noise_factor(isp: float, zs: complex, t0_k: float) -> float:
    """F from one simulated ``inoise_spectrum`` with a noiseless source:
    the source's own thermal noise is added analytically at ``t0_k``."""
    return 1.0 + isp * isp / (4 * K_BOLTZMANN * t0_k * zs.real)


def db10(x: float) -> float:
    return 10.0 * math.log10(x)


# ---------------------------------------------------------------------------
# Per-point analysis
# ---------------------------------------------------------------------------

#: Quantities that must be present for a point to be usable at all.
_OP_KEYS = ("ka_icn", "ka_ibn", "ka_icy", "ka_iby", "ka_vb", "ka_vc", "ka_dtj", "ka_vsup")


def validity_flags(nx: int, ic_a: float, vbe_v: float, vce_v: float, temp_c: float) -> list[str]:
    flags = []
    if ic_a >= VALID_IC_A_PER_NX * nx:
        flags.append("ic_high")
    if vbe_v < VALID_VBE_V[0]:
        flags.append("vbe_low")
    if vbe_v > VALID_VBE_V[1]:
        flags.append("vbe_high")
    if vce_v < VALID_VCE_V[0]:
        flags.append("vce_low")
    if vce_v > VALID_VCE_V[1]:
        flags.append("vce_high")
    if not VALID_TEMP_C[0] <= temp_c <= VALID_TEMP_C[1]:
        flags.append("temp_out")
    if not VALID_NX[0] <= nx <= VALID_NX[1]:
        flags.append("nx_out")
    return flags


def analyze_point(raw: RawPoint, sweep: Sweep, temp_c: float) -> list[dict]:
    """One bias point -> one row per frequency (DC quantities repeated).

    Every row carries ``status`` ("ok" or "excluded") and, when excluded,
    an explicit ``reason``; nothing is silently dropped.
    """
    base = {
        "nx": raw.nx,
        "vce_set_v": raw.vce_set,
        "vbe_set_v": raw.vbe_set,
    }
    op = raw.blocks.get("op", {})
    missing_op = [k for k in _OP_KEYS if k not in op]

    def excluded(reason: str, extra: dict | None = None) -> list[dict]:
        rows = []
        for k, fk in enumerate(sweep.frequencies_hz):
            row = dict(base, freq_index=k, freq_hz=fk, status="excluded", reason=reason)
            if extra:
                row.update(extra)
            rows.append(row)
        return rows

    note = {"sim_messages": " | ".join(raw.messages)} if raw.messages else {}
    if missing_op:
        return excluded("missing op value(s): " + ",".join(missing_op), note)
    ic, ib = op["ka_icn"], op["ka_ibn"]
    if not all(math.isfinite(v) for v in (ic, ib, op["ka_icy"], op["ka_vb"], op["ka_vc"])):
        return excluded("non-finite operating point")
    if ic <= 0:
        return excluded(f"non-positive Ic={ic!r}")
    if abs(op["ka_icy"] - ic) > COPY_IC_RTOL * abs(ic):
        return excluded(f"DUT copies disagree: Ic_noise={ic!r} Ic_y={op['ka_icy']!r}", note)
    # Bias-consistency gate: every analysis re-solves the operating point;
    # each prints the Ic it actually ran at. A point is only usable if every
    # analysis ran at the bias this row reports (this is what catches an
    # analysis that silently converged to a different electrothermal state).
    worst_dev, missing_ic = 0.0, []
    for name, vals in raw.blocks.items():
        if name == "op" or name.startswith("zopt_skip"):
            continue
        key = next((k for k in _IC_KEYS if k in vals), None)
        if key is None:
            missing_ic.append(name)
            continue
        worst_dev = max(worst_dev, abs(vals[key] - ic) / abs(ic))
    if missing_ic:
        return excluded("missing per-analysis bias value in " + ",".join(missing_ic[:4]), note)
    if worst_dev > BIAS_RTOL:
        return excluded(f"bias differs between analyses (max |dIc|/Ic = {worst_dev:.3g})", note)
    vbe, vce = op["ka_vb"], op["ka_vc"]
    dc = {
        "ic_a": ic,
        "ib_a": ib,
        "vbe_v": vbe,
        "vce_v": vce,
        "jc_ma_um2": ic * 1e3 / (raw.nx * AE_UM2_PER_NX),
        "jc_alt_ma_um2": ic * 1e3 / (raw.nx * AE_ALT_UM2_PER_NX),
        "pdc_mw": (ic * vce + ib * vbe) * 1e3,
        "dtj_k": op["ka_dtj"],
        "vsupply_v": op["ka_vsup"],
        "validity_flags": ";".join(validity_flags(raw.nx, ic, vbe, vce, temp_c)),
        "bias_max_rel_dev": worst_dev,
        **note,
    }
    # Out-of-model points are computed and kept (status "ok"), but carry
    # in_box = False and are excluded from every reported optimum.
    dc["in_box"] = not dc["validity_flags"]
    ft = ft_from_h21(raw.tables.get("h21", []))
    rows = []
    for k, fk in enumerate(sweep.frequencies_hz):
        row = dict(base, freq_index=k, freq_hz=fk, **dc, **ft)
        row.update(analyze_frequency(raw, sweep, k, fk))
        row["active"] = is_active(row)
        rows.append(row)
    return rows


def is_active(row: dict) -> bool:
    """Is the device an amplifier at this frequency and bias?

    NFmin alone is not a usable optimization target at very low current:
    with fT below the measurement frequency the bare device is a nearly
    lossless reactive network with no current gain, and its two-port NFmin
    falls again (a second, spurious low-current branch of NFmin(J_C) -- seen
    in this bench's own data, e.g. ~0.9 dB at fT ~ 1 GHz). Reported optima
    are therefore restricted to points where |h21| > 1 at the frequency
    (bracketed fT above it) AND the maximum gain (MAG or MSG) exceeds 0 dB.
    """
    ft = row.get("ft_hz")
    g = row.get("gmax_db")
    return bool(ft and ft > row["freq_hz"] and g is not None and g > 0)


def analyze_frequency(raw: RawPoint, sweep: Sweep, k: int, fk: float) -> dict:
    out: dict = {"status": "ok", "reason": ""}
    yf, yr = raw.blocks.get("yfwd", {}), raw.blocks.get("yrev", {})
    try:
        y11 = complex(yf[f"ka_y11r_{k}"], yf[f"ka_y11i_{k}"])
        y21 = complex(yf[f"ka_y21r_{k}"], yf[f"ka_y21i_{k}"])
        y12 = complex(yr[f"ka_y12r_{k}"], yr[f"ka_y12i_{k}"])
        y22 = complex(yr[f"ka_y22r_{k}"], yr[f"ka_y22i_{k}"])
    except KeyError as exc:
        return {"status": "excluded", "reason": f"missing Y-parameter value {exc.args[0]}"}
    s11, s12, s21, s22 = y_to_s(y11, y12, y21, y22, sweep.z0_ohm)
    out.update(gain_metrics(s11, s12, s21, s22))
    out["s11_db"] = 20 * math.log10(abs(s11)) if abs(s11) > 0 else None

    samples = []
    for j, (r, x) in enumerate(sweep.source_impedances_ohm):
        blk = raw.blocks.get(f"nz.f{k}.z{j}", {})
        if "ka_isp" not in blk:
            return dict(out, status="excluded", reason=f"missing noise value (f={k}, Zs #{j})")
        rv, lv, cv = source_elements(r, x, fk)
        samples.append((applied_impedance(rv, lv, cv, fk), blk["ka_isp"] ** 2))
    try:
        fit = fit_noise_parameters(samples)
    except NoiseFitError as exc:
        return dict(out, status="excluded", reason=f"noise fit: {exc}")
    zopt = complex(fit["ropt_ohm"], fit["xopt_ohm"])
    z0 = sweep.z0_ohm
    out.update({
        "ropt_ohm": fit["ropt_ohm"],
        "xopt_ohm": fit["xopt_ohm"],
        "gamma_opt_mag": abs((zopt - z0) / (zopt + z0)),
        "gamma_opt_deg": math.degrees(cmath.phase((zopt - z0) / (zopt + z0))),
        "tmin_k": fit["tmin_k"],
        "rn_ohm": fit["a"] / (4 * K_BOLTZMANN * T0_IEEE_K),
        "fit_max_rel_residual": fit["fit_max_rel_residual"],
    })
    if fit["fit_max_rel_residual"] > FIT_RESIDUAL_MAX:
        return dict(out, status="excluded",
                    reason=f"noise fit residual {fit['fit_max_rel_residual']:.3g} > {FIT_RESIDUAL_MAX:g}")
    if fit["tmin_k"] <= 0:
        return dict(out, status="excluded", reason=f"unphysical Tmin={fit['tmin_k']:.4g} K")
    for t0 in sweep.t0_k:
        out[f"nfmin_db_t{t0:g}"] = db10(1 + fit["tmin_k"] / t0)

    # Independent check 1: direct simulation at 50 ohm vs. the fit.
    blk50 = raw.blocks.get(f"nf50.f{k}", {})
    if "ka_isp" not in blk50:
        return dict(out, status="excluded", reason=f"missing NF50 check value (f={k})")
    z50 = applied_impedance(*source_elements(*sweep.nf50_check_ohm, fk), fk)
    for t0 in sweep.t0_k:
        nf50 = db10(measured_noise_factor(blk50["ka_isp"], z50, t0))
        out[f"nf50_db_t{t0:g}"] = nf50
    t0c = sweep.t0_k[0]
    out["nf50_fit_delta_db"] = out[f"nf50_db_t{t0c:g}"] - db10(noise_factor(fit, z50, t0c))
    if abs(out["nf50_fit_delta_db"]) > NF50_CHECK_TOL_DB:
        return dict(out, status="excluded",
                    reason=f"50-ohm check disagrees with fit by {out['nf50_fit_delta_db']:.4g} dB")

    # Independent check 2: a separate simulation at the (in-deck) optimum.
    blkz = raw.blocks.get(f"zopt.f{k}", {})
    if f"zopt_skip.f{k}" in raw.blocks or "ka_isp" not in blkz:
        out["nfmin_check"] = "not_run"
        return dict(out, status="excluded",
                    reason=f"independent optimum check did not run (f={k})")
    try:
        zchk = applied_impedance(blkz["@rsz[resistance]"], blkz["@lsz[inductance]"],
                                 blkz["@csz[capacitance]"], fk)
    except KeyError as exc:
        return dict(out, status="excluded", reason=f"missing applied check impedance {exc.args[0]}")
    nf_chk = db10(measured_noise_factor(blkz["ka_isp"], zchk, t0c))
    out["nfmin_check_zs_ohm"] = f"{zchk.real:.6g}{zchk.imag:+.6g}j"
    out["nfmin_check_db"] = nf_chk
    out["nfmin_check_delta_db"] = nf_chk - out[f"nfmin_db_t{t0c:g}"]
    out["nfmin_check_fit_delta_db"] = nf_chk - db10(noise_factor(fit, zchk, t0c))
    if abs(out["nfmin_check_delta_db"]) > NFMIN_CHECK_TOL_DB:
        out["nfmin_check"] = "fail"
        return dict(out, status="excluded",
                    reason=f"independent optimum check off by {out['nfmin_check_delta_db']:.4g} dB")
    out["nfmin_check"] = "pass"
    return out


def analyze_log(text: str, sweep: Sweep, temp_c: float) -> tuple[list[dict], list[str]]:
    """All rows for one PVT point's log, plus log-level problems.

    Problems are structural only (truncated log, wrong number of bias
    points): those make the whole PVT point unusable. Simulator messages are
    never problems by themselves (see _MESSAGE_RE); a message that matters
    shows up as a missing or inconsistent value in some row, which is then
    excluded with its reason. The full message tally is in log_messages()."""
    parsed = parse_log(text)
    problems = []
    if not parsed.complete:
        problems.append("log has no KA_DECK_END (truncated: timeout, crash or deck error)")
    expected = sweep.n_bias_points
    if len(parsed.points) != expected:
        problems.append(f"expected {expected} bias points, log has {len(parsed.points)}")
    rows: list[dict] = []
    for raw in parsed.points:
        rows.extend(analyze_point(raw, sweep, temp_c))
    return rows, problems


# ---------------------------------------------------------------------------
# Reductions
# ---------------------------------------------------------------------------


def _in_box(row: dict) -> bool:
    return row.get("status") == "ok" and not row.get("validity_flags")


def _eligible(row: dict) -> bool:
    return _in_box(row) and bool(row.get("active"))


def _why_ineligible(row: dict) -> str:
    reasons = [f for f in (row.get("validity_flags") or "").split(";") if f]
    if not row.get("active"):
        reasons.append("inactive(fT<=f or Gmax<=0dB)")
    return ";".join(reasons) or "?"


def cell_optima(rows: list[dict], t0_k: float) -> dict:
    """Noise optimum and fT peak over the bias (VBE / J_C) sweep of one cell
    (one PVT point x Nx x VCE x frequency).

    - ``opt_row``: the grid-sampled NFmin optimum over ELIGIBLE points --
      inside the model card's validity box AND active (see
      :func:`is_active`). Out-of-model, inactive, excluded (nonconvergent,
      failed-check) points never enter it. If the optimum sits on the edge
      of the eligible J_C range it is a CONSTRAINED optimum, and
      ``opt_constrained_by`` names the side and why the next grid point is
      not eligible (e.g. ``upper: ic_high`` or ``lower: inactive(...)``);
      otherwise it is empty (an interior, bracketed optimum).
    - ``ftpk_row``: the fT peak over in-box points with a bracketed fT.
    - ``eligible_jc_decades``: the J_C span the optimum was searched over.
    """
    key = f"nfmin_db_t{t0_k:g}"
    ok = sorted((r for r in rows if r.get("status") == "ok" and key in r),
                key=lambda r: r["jc_ma_um2"])
    elig = [r for r in ok if _eligible(r)]
    out: dict = {
        "n_points": len(rows), "n_ok": len(ok),
        "n_in_box": sum(1 for r in ok if _in_box(r)), "n_eligible": len(elig),
        "n_excluded": sum(1 for r in rows if r.get("status") != "ok"),
    }
    if elig:
        out["eligible_jc_min"] = elig[0]["jc_ma_um2"]
        out["eligible_jc_max"] = elig[-1]["jc_ma_um2"]
        out["eligible_jc_decades"] = math.log10(elig[-1]["jc_ma_um2"] / elig[0]["jc_ma_um2"])
        best = min(elig, key=lambda r: r[key])
        i = elig.index(best)
        out["opt_row"] = best
        constrained = []
        if i == len(elig) - 1:
            above = [r for r in ok if r["jc_ma_um2"] > best["jc_ma_um2"]]
            constrained.append("upper: " + (_why_ineligible(above[0]) if above else "end of sweep"))
        if i == 0:
            below = [r for r in ok if r["jc_ma_um2"] < best["jc_ma_um2"]]
            constrained.append("lower: " + (_why_ineligible(below[-1]) if below else "start of sweep"))
        out["opt_constrained_by"] = "; ".join(constrained)
    ft_rows = [r for r in ok if _in_box(r) and r.get("ft_hz")]
    if ft_rows:
        out["ftpk_row"] = max(ft_rows, key=lambda r: r["ft_hz"])
        edge = []
        if out["ftpk_row"] is ft_rows[-1]:
            edge.append("upper")
        if out["ftpk_row"] is ft_rows[0]:
            edge.append("lower")
        # A peak on the edge of the in-box range is a constrained maximum.
        out["ftpk_at_inbox_edge"] = "/".join(edge)
    if "opt_row" in out and "ftpk_row" in out:
        out["opt_over_ftpk_jc"] = out["opt_row"]["jc_ma_um2"] / out["ftpk_row"]["jc_ma_um2"]
    return out


def row3_screen(best_by_corner_freq: dict[tuple, dict], t0_k: float,
                limit_db: float = ROW3_LIMIT_DB) -> dict:
    """Device-level feasibility screen for target-spec row 3.

    ``best_by_corner_freq`` maps (corner_id, freq_hz) -> the in-box noise
    optimum row with the lowest NFmin over every Nx/VCE at that PVT point and
    frequency. Margin = limit - NFmin (positive = headroom for matching loss
    and circuit noise; NOT proof the row is achievable).
    """
    key = f"nfmin_db_t{t0_k:g}"
    margins = {}
    missing = []
    for cf, row in best_by_corner_freq.items():
        if row is None or key not in row:
            missing.append(cf)
            continue
        margins[cf] = limit_db - row[key]
    if not margins:
        return {"verdict": "no_data", "missing": missing}
    worst_cf = min(margins, key=lambda cf: margins[cf])
    worst = margins[worst_cf]
    if missing:
        verdict = "incomplete"
    elif worst > 0:
        verdict = "below_limit_everywhere"
    else:
        verdict = "exceeds_limit_somewhere"
    return {
        "verdict": verdict,
        "t0_k": t0_k,
        "limit_db": limit_db,
        "worst_corner_freq": worst_cf,
        "worst_margin_db": worst,
        "worst_nfmin_db": limit_db - worst,
        "best_margin_db": max(margins.values()),
        "n_cells": len(margins),
        "n_exceeding": sum(1 for m in margins.values() if m <= 0),
        "missing": missing,
        "margins": margins,
    }
