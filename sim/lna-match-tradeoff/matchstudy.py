"""First-stage LNA input-match tradeoff study (issue #74): pure logic.

No simulator and no PDK are needed to import or test this module. It owns:

* the declared study (``testbench/study.json``): loading and validation;
* the ideal lossless input-network family (lowpass L-sections around the
  frozen ``design/lna_stage1`` cascode) and its closed-form synthesis from a
  target source impedance at the band centre;
* the DUT text: the frozen ``design/netlist/lna_stage1.spice`` with ONLY its
  two input-network lines (``Cshunt``, ``Lin``) parameterized and one
  device-side shunt capacitor ``Csh2`` added (``c_sh2 = 0`` is the
  baseline's own topology); every other byte is unchanged and checked;
* the ngspice ``.control`` text for one deck that simulates a list of
  candidates at one PVT point, and the parser for its printed tables;
* the extraction (S-parameters from port voltages, NF from the noiseless
  reference source, k / |Delta| / mu), per-cell validity, the joint screen,
  the declared shortlist rule, the acceptance gate and the conclusion.

Every number the study reports is computed here from printed port voltages
and noise densities, so the extraction is unit-tested against closed forms.

Nothing here claims a spec row. The input networks are IDEAL (no loss, no
Q, no parasitic): a candidate that passes the screen is an optimistic,
conditional feasibility point that still depends on real passives (#46),
the open band decision (row 1) and second-stage loading.
"""

from __future__ import annotations

import cmath
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parents[1]

K_BOLTZMANN = 1.380649e-23

#: The two lines of the frozen netlist this study is allowed to change, and
#: their replacements. ``Csh2`` is inserted directly after ``Lin``.
FROZEN_INPUT_LINES = {
    "Cshunt": "Cshunt in gnd 170f m=1",
    "Lin": "Lin in in2 1.41n m=1",
}
PARAM_INPUT_LINES = {
    "Cshunt": "Cshunt in gnd {c_sh1} m=1",
    "Lin": "Lin in in2 {l_in} m=1\nCsh2 in2 gnd {c_sh2} m=1",
}

#: Devices of the DUT (name, label, Nx), as in sim/lna-sparam-nf.
DEVICES = (("q1", "Q1 (CE)", 8, "xq1", "c1", "b1", "e1"),
           ("q2", "Q2 (CB)", 8, "xq2", "oc", "b2", "c1"),
           ("qr", "Qref (mirror)", 1, "xqr", "nr", "nr", "er"))

#: Cell statuses that may appear in a record.
CELL_STATUSES = ("ok", "rejected_invalid")


class StudyError(ValueError):
    """The declaration or a collection is malformed (never evidence)."""


# ---------------------------------------------------------------------------
# Declaration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    name: str
    role: str                 # "baseline" | "candidate"
    topology: str             # "shunt_first" | "series_first"
    c_sh1: float              # F, port-side shunt C
    l_in: float               # H, series L
    c_sh2: float              # F, device-side shunt C
    target: dict = field(default_factory=dict, hash=False, compare=False)

    def params(self) -> dict[str, float]:
        return {"c_sh1": self.c_sh1, "l_in": self.l_in, "c_sh2": self.c_sh2}


@dataclass(frozen=True)
class Grid:
    dense_n: int
    mid_n: int
    wide_start_hz: float
    wide_stop_hz: float
    wide_per_decade: int


@dataclass
class Study:
    raw: dict
    f0_hz: float
    band_hz: tuple[float, float]
    z0: float
    t0_k: float
    grid: Grid
    nominal: dict
    processes: tuple[str, ...]
    temps_c: tuple[float, ...]
    supplies_v: tuple[float, ...]
    rail_ceiling_v: float
    screen: dict
    tolerances: dict
    shortlist_rule: dict
    candidates: tuple[Candidate, ...]
    excluded_targets: tuple[dict, ...]

    def candidate(self, name: str) -> Candidate:
        for c in self.candidates:
            if c.name == name:
                return c
        raise KeyError(name)

    @property
    def baseline(self) -> Candidate:
        return next(c for c in self.candidates if c.role == "baseline")

    # frequency grids -----------------------------------------------------
    def dense_freqs(self) -> list[float]:
        lo, hi = self.band_hz
        n = self.grid.dense_n
        return [lo + i * (hi - lo) / (n - 1) for i in range(n)]

    def mid_freqs(self) -> list[float]:
        """Midpoints of the dense grid (the refined-grid control adds these)."""
        d = self.dense_freqs()
        return [(a + b) / 2 for a, b in zip(d, d[1:])]

    def mid_span(self) -> tuple[float, float]:
        m = self.mid_freqs()
        return m[0], m[-1]

    def wide_count(self) -> int:
        g = self.grid
        return int(round(math.log10(g.wide_stop_hz / g.wide_start_hz) * g.wide_per_decade)) + 1

    def pvt_points(self) -> list[tuple[str, float, float]]:
        return [(p, t, v) for p in self.processes for t in self.temps_c for v in self.supplies_v]


def load_study(path: Path | None = None) -> Study:
    path = path or BENCH_DIR / "testbench" / "study.json"
    return study_from_manifest(json.loads(Path(path).read_text()))


def _need(d: dict, key: str, where: str):
    if key not in d:
        raise StudyError(f"{where}: missing {key!r}")
    return d[key]


def study_from_manifest(m: dict, *, partial: bool = False) -> Study:
    """``partial`` loads a declaration whose candidate list is not yet
    expanded (used only by ``run.py derive`` / ``declare``)."""
    if partial:
        m = dict(m)
        m.setdefault("candidates", [])
    if not isinstance(m, dict):
        raise StudyError("study manifest is not an object")
    g = _need(m, "grid", "study")
    grid = Grid(dense_n=int(_need(g, "dense_points", "grid")), mid_n=int(_need(g, "dense_points", "grid")) - 1,
                wide_start_hz=float(_need(g, "wide_start_hz", "grid")),
                wide_stop_hz=float(_need(g, "wide_stop_hz", "grid")),
                wide_per_decade=int(_need(g, "wide_points_per_decade", "grid")))
    band = tuple(float(x) for x in _need(m, "band_hz", "study"))
    pvt = _need(m, "pvt", "study")
    cands = []
    for i, c in enumerate(_need(m, "candidates", "study")):
        cands.append(Candidate(name=str(c["name"]), role=str(c["role"]), topology=str(c["topology"]),
                               c_sh1=float(c["c_sh1"]), l_in=float(c["l_in"]), c_sh2=float(c["c_sh2"]),
                               target=dict(c.get("target") or {})))
    st = Study(
        raw=m, f0_hz=float(_need(m, "f0_hz", "study")), band_hz=(band[0], band[1]),
        z0=float(_need(m, "z0_ohm", "study")), t0_k=float(_need(m, "t0_k", "study")), grid=grid,
        nominal=dict(_need(m, "nominal", "study")),
        processes=tuple(_need(pvt, "processes", "pvt")),
        temps_c=tuple(float(x) for x in _need(pvt, "temperatures_c", "pvt")),
        supplies_v=tuple(float(x) for x in _need(pvt, "supplies_v", "pvt")),
        rail_ceiling_v=float(_need(pvt, "rail_ceiling_v", "pvt")),
        screen=dict(_need(m, "screen", "study")), tolerances=dict(_need(m, "tolerances", "study")),
        shortlist_rule=dict(_need(m, "shortlist_rule", "study")), candidates=tuple(cands),
        excluded_targets=tuple(m.get("excluded_targets") or ()))
    problems = [] if partial else validate_study(st)
    if problems:
        raise StudyError("; ".join(problems))
    return st


def validate_study(st: Study) -> list[str]:
    p: list[str] = []
    names = [c.name for c in st.candidates]
    if len(names) != len(set(names)):
        p.append("duplicate candidate names")
    roles = [c.role for c in st.candidates]
    if roles.count("baseline") != 1:
        p.append("exactly one baseline candidate is required")
    if "probe_thru" not in names or roles.count("probe") < 5:
        p.append("probe_thru plus at least four ring probes are required (noise-parameter fit)")
    for c in st.candidates:
        if c.role not in ("baseline", "candidate", "probe"):
            p.append(f"{c.name}: role {c.role!r}")
        if c.topology not in ("shunt_first", "series_first"):
            p.append(f"{c.name}: topology {c.topology!r}")
        if not (c.l_in > 0 and c.c_sh1 >= 0 and c.c_sh2 >= 0):
            p.append(f"{c.name}: element values must be L > 0, C >= 0")
        if c.topology == "shunt_first" and c.c_sh2 != 0:
            p.append(f"{c.name}: shunt_first must have c_sh2 = 0")
        if c.topology == "series_first" and c.c_sh1 != 0:
            p.append(f"{c.name}: series_first must have c_sh1 = 0")
        if not re.match(r"^[a-z0-9_]+$", c.name):
            p.append(f"{c.name}: name must be [a-z0-9_]")
    b = [c for c in st.candidates if c.role == "baseline"]
    if b and (b[0].c_sh1, b[0].l_in, b[0].c_sh2) != (170e-15, 1.41e-9, 0.0):
        p.append("baseline must be the frozen schematic's own network (Cshunt 170 fF, Lin 1.41 nH)")
    if st.grid.dense_n < 3 or (st.grid.dense_n - 1) % 2:
        p.append("dense grid needs an odd point count >= 3 (so the band centre is a grid point)")
    if st.rail_ceiling_v not in st.supplies_v:
        p.append("rail ceiling must be one of the supplies")
    for key in ("nf_max_db", "s11_max_db", "s21_min_db", "k_min", "delta_max"):
        if key not in st.screen:
            p.append(f"screen.{key} missing")
    for key in ("refine_db", "model_db", "baseline_db", "baseline_k", "crosscheck_db", "control_nf_db",
                "control_s_db", "control_return_loss_db"):
        if key not in st.tolerances:
            p.append(f"tolerances.{key} missing")
    return p


# ---------------------------------------------------------------------------
# The network family (closed form)
# ---------------------------------------------------------------------------


def source_impedance(cand: Candidate | dict, f_hz: float, z0: float = 50.0) -> complex:
    """Impedance seen from the device side of the input network (node in2)
    looking back toward a z0 source: z0 || C1, + jwL, || C2."""
    if isinstance(cand, Candidate):
        c1, l, c2 = cand.c_sh1, cand.l_in, cand.c_sh2
    else:
        c1, l, c2 = cand["c_sh1"], cand["l_in"], cand["c_sh2"]
    w = 2 * math.pi * f_hz
    z = 1 / (1 / z0 + 1j * w * c1)
    z = z + 1j * w * l
    return 1 / (1 / z + 1j * w * c2)


def gamma(z: complex, z0: float = 50.0) -> complex:
    return (z - z0) / (z + z0)


def z_from_gamma(g: complex, z0: float = 50.0) -> complex:
    return z0 * (1 + g) / (1 - g)


def synthesize(zs: complex, f_hz: float, z0: float = 50.0) -> dict[str, dict | str]:
    """Lowpass L-sections presenting ``zs`` at ``f_hz``.

    Returns ``{"shunt_first": {...} | reason, "series_first": {...} | reason}``;
    a value is a dict of element values when realizable with positive L and
    non-negative C, else a string saying why not."""
    w = 2 * math.pi * f_hz
    out: dict[str, dict | str] = {}
    rs, xs = zs.real, zs.imag
    # shunt C at the source, then series L: Rs < z0, X = wL - Rs q >= ...
    if not (0 < rs < z0):
        out["shunt_first"] = f"needs 0 < Rs < {z0:g} ohm (Rs = {rs:.4g})"
    else:
        q = math.sqrt(z0 / rs - 1)
        wl = xs + rs * q
        if wl <= 0:
            out["shunt_first"] = f"needs a series capacitor (Xs = {xs:.4g} < -Rs q = {-rs * q:.4g})"
        else:
            out["shunt_first"] = {"c_sh1": q / (w * z0), "l_in": wl / w, "c_sh2": 0.0}
    # series L from the source, then shunt C at the device: Gs < 1/z0
    ys = 1 / zs
    gs, bs = ys.real, ys.imag
    if not (0 < gs < 1 / z0):
        out["series_first"] = f"needs 0 < Gs < {1 / z0:g} S (Gs = {gs:.4g})"
    else:
        x = math.sqrt(z0 / gs - z0 * z0)
        bc = bs + x / (z0 * z0 + x * x)
        if bc < 0:
            out["series_first"] = f"needs a shunt inductor (B_C = {bc:.4g} < 0)"
        else:
            out["series_first"] = {"c_sh1": 0.0, "l_in": x / w, "c_sh2": bc / w}
    return out


def round_sig(x: float, sig: int = 4) -> float:
    """Element values are declared to 4 significant digits (well below any
    plausible component tolerance); the declared value is the one simulated."""
    if x == 0:
        return 0.0
    return float(f"{x:.{sig - 1}e}")


#: Largest |Gamma_s| a declared target may have (beyond it the L-section's
#: loaded Q, and its sensitivity to the ideal element values, explode).
GAMMA_MAX = 0.98


def _expand_targets(f0: float, z0: float, targets: list[dict], role: str, prefix: str
                    ) -> tuple[list[dict], list[dict]]:
    cands: list[dict] = []
    excluded: list[dict] = []
    for t in targets:
        g = t["gamma"]
        tag = prefix + t["tag"]
        meta = {k: v for k, v in t.items() if k not in ("gamma", "tag")}
        meta.update(gamma_re=round(g.real, 6), gamma_im=round(g.imag, 6))
        if abs(g) >= GAMMA_MAX:
            excluded.append(dict(meta, name=tag, role=role,
                                 reason=f"|Gamma_s| = {abs(g):.3f} >= {GAMMA_MAX} (outside the declared disk)"))
            continue
        zs = z_from_gamma(g, z0)
        meta.update(zs_re=round(zs.real, 4), zs_im=round(zs.imag, 4))
        syn = synthesize(zs, f0, z0)
        for topo, short in (("shunt_first", "a"), ("series_first", "b")):
            v = syn[topo]
            if isinstance(v, str):
                excluded.append(dict(meta, name=f"{tag}_{short}", role=role, topology=topo, reason=v))
                continue
            cands.append({"name": f"{tag}_{short}", "role": role, "topology": topo,
                          "c_sh1": round_sig(v["c_sh1"]), "l_in": round_sig(v["l_in"]),
                          "c_sh2": round_sig(v["c_sh2"]), "target": meta})
    return cands, excluded


def _ring_targets(center: complex, radii, angles, kind: str, ctag: str) -> list[dict]:
    out = []
    for r in radii:
        for a in angles:
            g = center + float(r) * cmath.exp(1j * math.radians(float(a)))
            out.append({"kind": kind, "r": float(r), "angle_deg": float(a), "gamma": g,
                        "tag": f"{ctag}r{int(round(float(r) * 100)):02d}a{int(round(float(a))) % 360:03d}"})
    return out


def generate_family(gen: dict) -> tuple[list[dict], list[dict]]:
    """Expand the declared generator (``study.json`` ``family``) into the
    candidate list and the list of excluded (unrealizable) targets.

    Targets are source reflection coefficients at f0 (reference z0, at the
    device side of the network, node in2): the points of the declared
    segment from the circuit's power-match point to its noise optimum, and
    declared rings around each end. Each realizable lowpass orientation
    becomes one candidate."""
    f0, z0 = float(gen["f0_hz"]), float(gen["z0_ohm"])
    g_pm = complex(*gen["gamma_power_match"])
    g_opt = complex(*gen["gamma_noise_opt"])
    targets = []
    for t in gen["segment_fractions"]:
        targets.append({"kind": "segment", "t": float(t), "gamma": g_pm + float(t) * (g_opt - g_pm),
                        "tag": f"seg{int(round(float(t) * 1000)):04d}"})
    targets += _ring_targets(g_opt, gen["opt_ring_radii"], gen["ring_angles_deg"], "ring_opt", "opt")
    targets += _ring_targets(g_pm, gen["pm_ring_radii"], gen["ring_angles_deg"], "ring_pm", "pm")
    return _expand_targets(f0, z0, targets, "candidate", "")


def generate_probes(gen: dict) -> tuple[list[dict], list[dict]]:
    """The declared probe networks (``study.json`` ``probes``): a near-zero
    'thru' (the core seen directly from z0) and L-sections on a ring around
    Gamma = 0. They are diagnostic only (noise-parameter fit and the
    network-independent bound), never selectable."""
    f0, z0 = float(gen["f0_hz"]), float(gen["z0_ohm"])
    thru = {"name": "probe_thru", "role": "probe", "topology": "shunt_first", "c_sh1": 0.0,
            "l_in": float(gen["thru_l_h"]), "c_sh2": 0.0, "target": {"kind": "thru"}}
    targets = _ring_targets(0j, [gen["ring_radius"]], gen["ring_angles_deg"], "probe_ring", "")
    cands, excl = _expand_targets(f0, z0, targets, "probe", "probe_")
    return [thru] + cands, excl


# ---------------------------------------------------------------------------
# Deck text
# ---------------------------------------------------------------------------


BASELINE = {"name": "baseline", "role": "baseline", "topology": "shunt_first", "c_sh1": 1.7e-13,
            "l_in": 1.41e-9, "c_sh2": 0.0, "target": {"kind": "baseline",
                                                       "note": "design/lna_stage1 as drawn (Cshunt 170 fF, Lin 1.41 nH)"}}


def candidate_from_dict(d: dict) -> Candidate:
    return Candidate(name=d["name"], role=d["role"], topology=d["topology"], c_sh1=float(d["c_sh1"]),
                     l_in=float(d["l_in"]), c_sh2=float(d["c_sh2"]), target=dict(d.get("target") or {}))


def expand_declaration(m: dict) -> tuple[list[dict], list[dict]]:
    """The full frozen candidate list (baseline, family, probes) and the
    excluded targets, regenerated from the declared generators. A test pins
    the committed ``candidates`` to this."""
    fam, fam_x = generate_family(m["family"])
    pro, pro_x = generate_probes(m["probes"])
    return [dict(BASELINE)] + fam + pro, fam_x + pro_x


def literal_dut_text(frozen: str, cand: Candidate) -> str:
    """The frozen netlist with the candidate's values written literally (no
    parameters): the alterparam-independent cross-check deck."""
    t = dut_text(frozen)
    for k, v in cand.params().items():
        t = t.replace("{" + k + "}", repr(float(v)))
    return t


def dut_text(frozen: str) -> str:
    """The frozen netlist with only the two input-network lines replaced."""
    lines = frozen.splitlines()
    out = []
    seen = set()
    for ln in lines:
        name = ln.split(" ", 1)[0]
        if name in FROZEN_INPUT_LINES:
            if ln.strip() != FROZEN_INPUT_LINES[name]:
                raise StudyError(f"frozen netlist line for {name} changed: {ln!r} "
                                 f"(expected {FROZEN_INPUT_LINES[name]!r}); re-derive the study")
            out.append(PARAM_INPUT_LINES[name])
            seen.add(name)
        else:
            out.append(ln)
    if seen != set(FROZEN_INPUT_LINES):
        raise StudyError(f"frozen netlist lacks {sorted(set(FROZEN_INPUT_LINES) - seen)}")
    return "\n".join(out) + "\n"


def unparameterize(dut: str) -> str:
    """Inverse of :func:`dut_text` (used by a test to prove nothing else moved)."""
    t = dut.replace(PARAM_INPUT_LINES["Lin"], FROZEN_INPUT_LINES["Lin"])
    return t.replace(PARAM_INPUT_LINES["Cshunt"], FROZEN_INPUT_LINES["Cshunt"])


PORTS = """\
* ---- two-port test fixture (method of sim/lna-sparam-nf/testbench/lna_stage1.spice) ----
* Power-wave injection through a Thevenin z0 source per port; forward /
* reverse by alterparam mag1/mag2 + reset. Rs1 is NOISELESS: the source
* noise is added analytically at T0 (F = 1 + inoise^2 / (4 k T0 z0)).
.param z0=50
Vdd vdd 0 DC {vdd_val}
Xdut p1 p2 vdd 0 lna_stage1
Vs1 s1n 0 DC 0 AC {mag1}
Rs1 s1n p1 {z0} noisy=0
Vs2 s2n 0 DC 0 AC {mag2}
Rs2 s2n p2 {z0}
"""


def op_lets(devices: tuple = DEVICES) -> list[tuple[str, str]]:
    """``(name, expression)`` of the operating-point measurements; the same
    expressions as sim/lna-sparam-nf/testbench/tb.json (a test pins them).
    ``devices`` defaults to this DUT's :data:`DEVICES`; a core-variant study
    (issue #79) passes its own terminal nodes / Nx."""
    out: list[tuple[str, str]] = []
    for dev, _label, nx, inst, c, b, e in devices:
        q = f"@q.xdut.{inst}.qnpn13g2"
        ft = (f"{q}[gm]/(2*3.14159265358979*({q}[cbe]+{q}[cbex]+{q}[cbc]+{q}[cbcx]+{q}[cbep]+{q}[cbcp]))/1e9")
        out += [(f"{dev}_vce", f"v(xdut.{c}) - v(xdut.{e})"),
                (f"{dev}_vbe", f"v(xdut.{b}) - v(xdut.{e})"),
                (f"{dev}_ic", f"{q}[ic]"),
                (f"{dev}_icfrac", f"{q}[ic]/(3e-3*{nx})"),
                (f"{dev}_dtj", f"v(xdut.{inst}.t)"),
                (f"{dev}_ft", ft)]
    out += [("idd_ma", "-i(vdd)*1e3"), ("pdc_mw", "-i(vdd)*v(vdd)*1e3")]
    return out


def _num(x: float) -> str:
    return repr(float(x))


def control_lines(st: Study, cands: list[Candidate], *, with_op: bool = True,
                  network_alter: bool = True, devices: tuple = DEVICES) -> list[str]:
    """The ``.control`` body for one deck at one PVT point: the operating
    point once (the input network is DC-isolated by Cblk_in, which the smoke
    control verifies), then per candidate the forward dense / midpoint /
    wide AC, the dense and midpoint noise, and the reverse AC sweeps, each
    printed between LM_BEGIN/LM_END markers."""
    lo, hi = st.band_hz
    mlo, mhi = st.mid_span()
    g = st.grid
    sweeps = {
        "dense": f"lin {g.dense_n} {_num(lo)} {_num(hi)}",
        "mid": f"lin {g.mid_n} {_num(mlo)} {_num(mhi)}",
        "wide": f"dec {g.wide_per_decade} {_num(g.wide_start_hz)} {_num(g.wide_stop_hz)}",
    }
    out = ["set width = 250", "set height = 1000000", "set numdgt = 10"]
    first = cands[0]
    if with_op:
        if network_alter:
            out += [f"alterparam {k} = {_num(v)}" for k, v in first.params().items()]
        out += ["alterparam mag1 = 1", "alterparam mag2 = 0", "reset", "op"]
        for name, expr in op_lets(devices):
            out.append(f"let m_op_{name} = {expr}")
        out += [f"print m_op_{name}" for name, _ in op_lets(devices)]
        out.append("destroy all")
    ports = "real(v(p1)) imag(v(p1)) real(v(p2)) imag(v(p2))"
    for c in cands:
        sws = ("dense",) if c.role == "probe" else ("dense", "mid", "wide")
        if network_alter:
            out += [f"alterparam {k} = {_num(v)}" for k, v in c.params().items()]
        out += ["alterparam mag1 = 1", "alterparam mag2 = 0", "reset"]
        for sw in sws:
            out += [f"ac {sweeps[sw]}", f"echo LM_BEGIN {c.name} fwd_{sw}", f"print {ports}",
                    f"echo LM_END {c.name} fwd_{sw}"]
            if sw != "wide":
                out += [f"noise v(p2) vs1 {sweeps[sw]}", "setplot previous",
                        f"echo LM_BEGIN {c.name} noise_{sw}", "print inoise_spectrum",
                        f"echo LM_END {c.name} noise_{sw}"]
        out += ["destroy all", "alterparam mag1 = 0", "alterparam mag2 = 1", "reset"]
        for sw in sws:
            out += [f"ac {sweeps[sw]}", f"echo LM_BEGIN {c.name} rev_{sw}", f"print {ports}",
                    f"echo LM_END {c.name} rev_{sw}"]
        out += ["destroy all"]
    out.append("echo LM_DONE")
    return out


def body_text(st: Study, frozen_netlist: str, cands: list[Candidate], vdd: float, *, title: str,
              dut: str | None = None, network_alter: bool = True, with_op: bool = True,
              devices: tuple = DEVICES) -> str:
    """Circuit body without model/corner lines (klt adds those; the local
    runner prepends them). ``dut`` overrides the DUT text (controls only)."""
    first = cands[0]
    lines = [f"* lna-match-tradeoff: {title} -- GENERATED by matchstudy.py, do not edit",
             f".param vdd_val={vdd!r}", ".param mag1=1 mag2=0"]
    lines += [f".param {k}={_num(v)}" for k, v in first.params().items()]
    if dut is None:
        lines += ["", "* ==== BEGIN design/netlist/lna_stage1.spice, input network parameterized ====",
                  dut_text(frozen_netlist).rstrip("\n"), "* ==== END design/netlist/lna_stage1.spice ===="]
    else:
        lines += ["", dut.rstrip("\n")]
    lines += ["", PORTS.rstrip("\n"), "", ".control", "set noaskquit",
              *control_lines(st, cands, with_op=with_op, network_alter=network_alter, devices=devices), ".endc", ""]
    return "\n".join(lines)


def pad_dut(loss_ratio_v: float = 2.0, z0: float = 50.0) -> str:
    """Normalization control DUT: the parameterized input network followed by
    a matched resistive pi pad of voltage ratio K (power loss L = K^2). With
    the thru network and the pad at T: F = 1 + (L - 1) T / T0 exactly."""
    k = loss_ratio_v
    rsh = z0 * (k + 1) / (k - 1)
    rse = z0 * (k * k - 1) / (2 * k)
    return "\n".join([
        f"* matched pi pad, K = {k!r} (L = {10 * math.log10(k * k):.4f} dB); NOT the LNA",
        ".subckt lna_stage1 in out vdd gnd",
        "Cshunt in gnd {c_sh1} m=1", "Lin in in2 {l_in} m=1", "Csh2 in2 gnd {c_sh2} m=1",
        f"Rp1 in2 gnd {rsh!r}", f"Rser in2 out {rse!r}", f"Rp2 out gnd {rsh!r}", "Rbleed vdd gnd 1k",
        ".ends", ""])


def local_deck(body: str, model_lib: str, process: str, temp_c: float) -> str:
    """A complete deck for one local ngspice run (one PVT point)."""
    return "\n".join([f"* lna-match-tradeoff local deck {process} {temp_c:g} C", f'.lib "{model_lib}" {process}',
                      f".temp {temp_c!r}", body, ".end", ""])


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

_BEGIN_RE = re.compile(r"^LM_BEGIN (\S+) (\S+)\s*$")
_END_RE = re.compile(r"^LM_END (\S+) (\S+)\s*$")
_OP_RE = re.compile(r"^\s*m_op_(\w+)\s*=\s*(\S+)\s*$")
_ERR_RE = re.compile(r"^\s*(error|fatal|doanalyses|internal error)\b", re.I)
SECTIONS = ("fwd_dense", "noise_dense", "fwd_mid", "noise_mid", "fwd_wide", "rev_dense", "rev_mid", "rev_wide")
#: Probes are diagnostic (noise-parameter fit, bound): dense grid only.
PROBE_SECTIONS = ("fwd_dense", "noise_dense", "rev_dense")


def sections_for(cand: Candidate) -> tuple[str, ...]:
    return PROBE_SECTIONS if cand.role == "probe" else SECTIONS


def _float(tok: str) -> float:
    try:
        return float(tok)
    except ValueError:
        t = tok.lower().lstrip("+-")
        if t in ("nan", "-nan", "nan(ind)"):
            return float("nan")
        raise


@dataclass
class ParsedLog:
    op: dict[str, float]
    tables: dict[str, dict[str, list[list[float]]]]   # cand -> section -> rows (freq, values...)
    done: bool
    problems: list[str]


def parse_log(text: str) -> ParsedLog:
    op: dict[str, float] = {}
    tables: dict[str, dict[str, list[list[float]]]] = {}
    problems: list[str] = []
    cur: tuple[str, str] | None = None
    rows: list[list[float]] = []
    done = False
    for line in text.splitlines():
        s = line.strip()
        if s == "LM_DONE":
            done = True
            continue
        m = _OP_RE.match(line)
        if m and cur is None:
            try:
                op[m.group(1)] = _float(m.group(2))
            except ValueError:
                problems.append(f"unparseable op value {line.strip()!r}")
            continue
        m = _BEGIN_RE.match(s)
        if m:
            if cur is not None:
                problems.append(f"LM_BEGIN {m.group(1)} {m.group(2)} inside an open block {cur}")
            cur, rows = (m.group(1), m.group(2)), []
            continue
        m = _END_RE.match(s)
        if m:
            if cur != (m.group(1), m.group(2)):
                problems.append(f"LM_END {m.group(1)} {m.group(2)} does not close {cur}")
            else:
                sect = tables.setdefault(cur[0], {})
                if cur[1] in sect:
                    problems.append(f"duplicate block {cur}")
                sect[cur[1]] = rows
            cur = None
            continue
        if cur is not None:
            toks = s.split()
            if toks and toks[0].isdigit() and len(toks) >= 3:
                try:
                    vals = [_float(t) for t in toks[1:]]
                except ValueError:
                    problems.append(f"{cur}: unparseable row {s[:60]!r}")
                    continue
                if int(toks[0]) != len(rows):
                    problems.append(f"{cur}: row index {toks[0]} out of sequence")
                rows.append(vals)
            elif _ERR_RE.match(s):
                problems.append(f"{cur}: simulator message {s[:80]!r}")
        elif _ERR_RE.match(s):
            problems.append(f"simulator message {s[:80]!r}")
    if cur is not None:
        problems.append(f"unterminated block {cur}")
    return ParsedLog(op=op, tables=tables, done=done, problems=problems)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def nf_db_from_inoise(inoise: float, t0_k: float = 300.15, z0: float = 50.0) -> float:
    """F = 1 + inoise^2/(4 k T0 z0) (noiseless reference source, issue #22)."""
    return 10 * math.log10(1 + inoise * inoise / (4 * K_BOLTZMANN * t0_k * z0))


def db20(x: complex | float) -> float:
    a = abs(x)
    return 20 * math.log10(a) if a > 0 else float("-inf")


def two_port(fwd: list[list[float]], rev: list[list[float]]) -> list[dict]:
    """Per-frequency S-parameters and stability from printed port voltages
    (rows: freq, re v1, im v1, re v2, im v2)."""
    out = []
    for a, b in zip(fwd, rev):
        f = a[0]
        v1f, v2f = complex(a[1], a[2]), complex(a[3], a[4])
        v1r, v2r = complex(b[1], b[2]), complex(b[3], b[4])
        s11, s21 = 2 * v1f - 1, 2 * v2f
        s22, s12 = 2 * v2r - 1, 2 * v1r
        out.append(dict(f=f, freq_rev=b[0], s11=s11, s21=s21, s22=s22, s12=s12, **stability(s11, s21, s12, s22)))
    return out


def stability(s11: complex, s21: complex, s12: complex, s22: complex) -> dict[str, float]:
    delta = s11 * s22 - s12 * s21
    den = 2 * abs(s12 * s21)
    k = (1 - abs(s11) ** 2 - abs(s22) ** 2 + abs(delta) ** 2) / den if den > 0 else float("inf")
    mu_den = abs(s22 - delta * s11.conjugate()) + abs(s12 * s21)
    mu = (1 - abs(s11) ** 2) / mu_den if mu_den > 0 else float("inf")
    return {"k": k, "delta": abs(delta), "mu": mu}


def _finite_all(xs) -> bool:
    return all(math.isfinite(x) for x in xs)


def _grid_ok(got: list[float], want: list[float], rel: float = 1e-6) -> bool:
    return len(got) == len(want) and all(abs(g - w) <= rel * w for g, w in zip(got, want))


def load_noise_share(s21: complex, s22: complex, temp_c: float, t0_k: float) -> float:
    """Linear-F share of the 50 ohm output load's own thermal noise (at the
    circuit temperature) in the bench-convention F: (T/T0) |1 + S22|^2 / |S21|^2.
    (The load noise voltage reaches p2 through (1 + S22)/2 and is referred to
    the source through S21/2.)"""
    return (temp_c + 273.15) / t0_k * abs(1 + s22) ** 2 / abs(s21) ** 2


def analyze_candidate(st: Study, cand: Candidate, tables: dict[str, list[list[float]]],
                      temp_c: float | None = None) -> dict:
    """One candidate at one PVT point -> per-frequency arrays, band and wide
    summaries, the refined-grid control and validity problems. With
    ``temp_c`` the per-frequency NF without the output load's share
    (``nf_excl_load_db``) is reported beside the bench-convention NF."""
    problems: list[str] = []
    sects = sections_for(cand)
    probe = cand.role == "probe"
    for s in sects:
        if s not in tables:
            problems.append(f"missing printed block {s}")
    extra = sorted(set(tables) - set(sects))
    if extra:
        problems.append(f"unexpected printed blocks {extra}")
    if problems:
        return {"valid": False, "problems": problems}
    want = {"dense": st.dense_freqs(), "mid": st.mid_freqs()}
    wide_n = st.wide_count()
    for s in sects:
        rows = tables[s]
        ncol = 2 if s.startswith("noise") else 5
        if any(len(r) != ncol for r in rows):
            problems.append(f"{s}: rows do not have {ncol} columns")
            return {"valid": False, "problems": problems}
        f = [r[0] for r in rows]
        sw = s.split("_")[1]
        if sw == "wide":
            if len(f) != wide_n or abs(f[0] - st.grid.wide_start_hz) > 1 or abs(f[-1] - st.grid.wide_stop_hz) > 1e3:
                problems.append(f"{s}: wide sweep has {len(f)} points from {f[:1]} to {f[-1:]} (declared {wide_n})")
        elif not _grid_ok(f, want[sw]):
            problems.append(f"{s}: frequency grid differs from the declared {sw} grid ({len(f)} points)")
    if problems:
        return {"valid": False, "problems": problems}

    res: dict = {"valid": True, "problems": problems}
    band: dict[str, dict] = {}
    for sw in (("dense",) if probe else ("dense", "mid")):
        tp = two_port(tables[f"fwd_{sw}"], tables[f"rev_{sw}"])
        nf = [nf_db_from_inoise(r[1], st.t0_k, st.z0) if math.isfinite(r[1]) else float("nan")
              for r in tables[f"noise_{sw}"]]
        if temp_c is not None:
            excl = []
            for p, x in zip(tp, nf):
                f_lin = 10 ** (x / 10) - load_noise_share(p["s21"], p["s22"], temp_c, st.t0_k)
                excl.append(10 * math.log10(f_lin) if f_lin > 0 else float("nan"))
        band[sw] = {
            "f_hz": [p["f"] for p in tp],
            "s11_db": [db20(p["s11"]) for p in tp],
            "s21_db": [db20(p["s21"]) for p in tp],
            "s22_db": [db20(p["s22"]) for p in tp],
            "s12_db": [db20(p["s12"]) for p in tp],
            "nf_db": nf,
            "k": [p["k"] for p in tp],
            "delta": [p["delta"] for p in tp],
            "mu": [p["mu"] for p in tp],
        }
        if temp_c is not None:
            band[sw]["nf_excl_load_db"] = excl
    wide = [] if probe else two_port(tables["fwd_wide"], tables["rev_wide"])
    w = {"f_hz": [p["f"] for p in wide], "k": [p["k"] for p in wide], "delta": [p["delta"] for p in wide],
         "mu": [p["mu"] for p in wide]}
    for name, arr in [(f"{sw}.{k}", v) for sw in band for k, v in band[sw].items()] + \
                     [(f"wide.{k}", v) for k, v in w.items()]:
        if not _finite_all(arr):
            problems.append(f"non-finite value(s) in {name}")
    res["band"] = band["dense"]
    if not probe:
        res["mid"] = band["mid"]
        res["wide"] = w
    if problems:
        res["valid"] = False
        return res

    def summ(b: dict) -> dict:
        extra = {"nf_max_excl_load_db": max(b["nf_excl_load_db"])} if "nf_excl_load_db" in b else {}
        return {**extra, "nf_max_db": max(b["nf_db"]), "nf_min_db": min(b["nf_db"]),
                "s11_max_db": max(b["s11_db"]), "s21_min_db": min(b["s21_db"]),
                "s21_max_db": max(b["s21_db"]), "s22_max_db": max(b["s22_db"]),
                "k_min": min(b["k"]), "delta_max": max(b["delta"])}

    dense = summ(band["dense"])
    i0 = band["dense"]["f_hz"].index(min(band["dense"]["f_hz"], key=lambda x: abs(x - st.f0_hz)))
    dense.update(nf_f0_db=band["dense"]["nf_db"][i0], s11_f0_db=band["dense"]["s11_db"][i0],
                 s21_f0_db=band["dense"]["s21_db"][i0])
    if probe:
        res["summary"] = dense
        return res
    union = {k: band["dense"][k] + band["mid"][k] for k in band["dense"]}
    refined = summ(union)
    unst = sum(1 for k, d in zip(w["k"], w["delta"]) if k <= 1 or d >= 1)
    iw = min(range(len(w["k"])), key=lambda j: w["k"][j])
    dense.update(wide_k_min=w["k"][iw], wide_f_kmin_hz=w["f_hz"][iw], wide_delta_max=max(w["delta"]),
                 wide_mu_min=min(w["mu"]), wide_n_unstable=unst)
    deltas = {k: refined[k] - dense[k] for k in ("nf_max_db", "s11_max_db", "s21_min_db")}
    tol = float(st.tolerances["refine_db"])
    res["summary"] = dense
    res["refined"] = {"summary": refined, "delta": deltas, "tol_db": tol,
                      "ok": all(abs(v) <= tol for v in deltas.values())}
    if not res["refined"]["ok"]:
        res["valid"] = False
        problems.append("refined-grid control failed: " + ", ".join(
            f"{k} moved {v:+.4f} dB" for k, v in deltas.items() if abs(v) > tol) + f" (tolerance {tol} dB)")
    return res


# ---------------------------------------------------------------------------
# Operating point checks (row 17 and the model card box)
# ---------------------------------------------------------------------------

VCE_MAX_V = 1.4
VCE_WINDOW_V = (0.4, 2.0)
VBE_WINDOW_V = (0.65, 0.96)


def op_checks(op: dict[str, float], vdd: float, st: Study, devices: tuple = DEVICES) -> dict:
    """Per-device pass/fail against row 17 and the card box; 2.75 V-class
    supplies above the rail ceiling are labelled an excursion, not merged."""
    devs = {}
    fails = []
    for dev, label, _nx, *_ in devices:
        need = [f"{dev}_{q}" for q in ("vce", "vbe", "icfrac", "ft")]
        if any(n not in op or not math.isfinite(op[n]) for n in need):
            return {"valid": False, "problems": [f"op values missing/non-finite for {dev}"]}
        vce, vbe = op[f"{dev}_vce"], op[f"{dev}_vbe"]
        flags = {
            "vce_le_1v4": vce <= VCE_MAX_V,
            "vce_in_window": VCE_WINDOW_V[0] <= vce <= VCE_WINDOW_V[1],
            "vbe_in_window": VBE_WINDOW_V[0] <= vbe <= VBE_WINDOW_V[1],
            "ic_in_box": op[f"{dev}_icfrac"] < 1.0,
            "ft_above_band": op[f"{dev}_ft"] > st.band_hz[1] / 1e9,
        }
        devs[dev] = {"label": label, "vce": vce, "vbe": vbe, "icfrac": op[f"{dev}_icfrac"],
                     "ft_ghz": op[f"{dev}_ft"], "dtj_k": op.get(f"{dev}_dtj"), "flags": flags}
        fails += [f"{dev}:{k}" for k, v in flags.items() if not v]
    excursion = vdd > st.rail_ceiling_v + 1e-9
    return {"valid": True, "devices": devs, "pass": not fails, "failures": fails,
            "supply_class": "excursion" if excursion else "in_rail",
            "idd_ma": op.get("idd_ma"), "pdc_mw": op.get("pdc_mw")}


# ---------------------------------------------------------------------------
# Cells, screen, shortlist, gate, conclusion
# ---------------------------------------------------------------------------


def corner_id(process: str, temp_c: float, vdd: float) -> str:
    return f"{process}_{temp_c:g}c_{vdd:.2f}v"


def cell_id(phase: str, cand: str, process: str, temp_c: float, vdd: float) -> str:
    return f"{phase}__{cand}__{corner_id(process, temp_c, vdd)}"


def screen_cell(st: Study, cell: dict) -> dict:
    """The joint screen for one valid cell. Thresholds are declared in
    study.json and each one names the spec row it is traceable to."""
    s = st.screen
    sm = cell["summary"]
    reasons = []
    if sm["nf_max_db"] > s["nf_max_db"]:
        reasons.append(f"NF max {sm['nf_max_db']:.2f} dB > {s['nf_max_db']} dB")
    if sm["s11_max_db"] > s["s11_max_db"]:
        reasons.append(f"S11 max {sm['s11_max_db']:.2f} dB > {s['s11_max_db']} dB")
    if sm["s21_min_db"] < s["s21_min_db"]:
        reasons.append(f"S21 min {sm['s21_min_db']:.2f} dB < {s['s21_min_db']} dB")
    if sm["k_min"] <= s["k_min"] or sm["wide_k_min"] <= s["k_min"]:
        reasons.append(f"k min {min(sm['k_min'], sm['wide_k_min']):.3f} <= {s['k_min']}")
    if sm["delta_max"] >= s["delta_max"] or sm["wide_delta_max"] >= s["delta_max"]:
        reasons.append(f"|Delta| max {max(sm['delta_max'], sm['wide_delta_max']):.3f} >= {s['delta_max']}")
    op = cell.get("op") or {}
    if op and not op.get("pass", False):
        reasons.append("operating point outside row 17 / card box: " + ", ".join(op.get("failures", [])))
    margin = min(s["nf_max_db"] - sm["nf_max_db"], s["s11_max_db"] - sm["s11_max_db"],
                 sm["s21_min_db"] - s["s21_min_db"])
    return {"pass": not reasons, "reasons": reasons, "joint_margin_db": margin}


def make_cell(st: Study, phase: str, cand: Candidate, process: str, temp_c: float, vdd: float,
              tables: dict, op: dict, devices: tuple = DEVICES) -> dict:
    an = analyze_candidate(st, cand, tables, temp_c)
    cell = {"id": cell_id(phase, cand.name, process, temp_c, vdd), "phase": phase, "candidate": cand.name,
            "role": cand.role, "process": process, "model_section": process, "temp_c": temp_c, "vdd_v": vdd,
            "corner_id": corner_id(process, temp_c, vdd),
            "supply_class": "excursion" if vdd > st.rail_ceiling_v + 1e-9 else "in_rail",
            "op": op_checks(op, vdd, st, devices)}
    problems = list(an.get("problems", []))
    if not cell["op"].get("valid"):
        problems += cell["op"].get("problems", [])
    for k in ("band", "mid", "wide", "summary", "refined"):
        if k in an:
            cell[k] = an[k]
    if an.get("valid") and not problems:
        cell["status"] = "ok"
        cell["screen"] = (screen_cell(st, cell) if cand.role != "probe" else
                          {"pass": False, "reasons": ["probe: diagnostic network, never selectable"],
                           "joint_margin_db": None})
    else:
        cell["status"] = "rejected_invalid"
        cell["reason"] = "; ".join(problems)
        cell["screen"] = {"pass": False, "reasons": ["invalid: " + cell["reason"]], "joint_margin_db": None}
    return cell


def shortlist(st: Study, screen_cells: list[dict]) -> dict:
    """The declared shortlist rule (study.json ``shortlist_rule``), applied to
    the nominal-screen cells. Only ``ok`` cells enter; the baseline is always
    retained. Returns ``{"names": [...], "why": {name: [reasons]}}``."""
    rule = st.shortlist_rule
    ok = [c for c in screen_cells if c["status"] == "ok" and c.get("role") == "candidate"]
    stable = [c for c in ok if c["summary"]["wide_k_min"] > st.screen["k_min"]
              and c["summary"]["k_min"] > st.screen["k_min"]
              and c["summary"]["wide_delta_max"] < st.screen["delta_max"]
              and c["summary"]["delta_max"] < st.screen["delta_max"]]
    why: dict[str, list[str]] = {st.baseline.name: ["baseline (always retained)"]}

    def add(c: dict | None, reason: str) -> None:
        if c is not None:
            why.setdefault(c["candidate"], []).append(reason)

    passing = sorted([c for c in stable if c["screen"]["pass"]],
                     key=lambda c: (-c["screen"]["joint_margin_db"], c["candidate"]))
    for c in passing[: int(rule["max_passing"])]:
        add(c, "passes the joint nominal screen")
    key_nf = lambda c: (c["summary"]["nf_max_db"], c["candidate"])  # noqa: E731
    key_s11 = lambda c: (c["summary"]["s11_max_db"], c["candidate"])  # noqa: E731
    if stable:
        add(max(stable, key=lambda c: (c["screen"]["joint_margin_db"], c["candidate"])), "best joint margin")
        add(min(stable, key=key_nf), "lowest in-band NF max")
        add(min(stable, key=key_s11), "lowest in-band S11 max")
        rl = [c for c in stable if c["summary"]["s11_max_db"] <= st.screen["s11_max_db"]]
        if rl:
            add(min(rl, key=key_nf), f"lowest NF max with S11 max <= {st.screen['s11_max_db']} dB")
        nfok = [c for c in stable if c["summary"]["nf_max_db"] <= st.screen["nf_max_db"]]
        if nfok:
            add(min(nfok, key=key_s11), f"lowest S11 max with NF max <= {st.screen['nf_max_db']} dB")
    names = [st.baseline.name] + sorted(n for n in why if n != st.baseline.name)
    return {"names": names, "why": why}


def corner_deck_names(st: Study, shortlist_names: list[str]) -> list[str]:
    """Networks simulated at every PVT point: the shortlist (baseline first)
    plus every probe (for the per-point noise parameters and bound)."""
    return list(shortlist_names) + [c.name for c in st.candidates if c.role == "probe"]


def expected_cells(st: Study, shortlist_names: list[str]) -> list[str]:
    n = st.nominal
    ids = [cell_id("screen", c.name, n["process"], float(n["temp_c"]), float(n["vdd"])) for c in st.candidates]
    ids += [cell_id("corners", name, p, t, v) for name in corner_deck_names(st, shortlist_names)
            for p, t, v in st.pvt_points()]
    return ids


def validate_collection(st: Study, cells: list[dict], shortlist_names: list[str]) -> list[str]:
    """Acceptance gate: every declared cell exactly once, nothing undeclared,
    scientific statuses, finite values in ok cells, model section = declared
    corner, and the process sabotage control (corners must move S21)."""
    p: list[str] = []
    ids = [c.get("id") for c in cells]
    want = expected_cells(st, shortlist_names)
    seen = set()
    for i in ids:
        if i in seen:
            p.append(f"duplicate cell {i}")
        seen.add(i)
    for i in sorted(set(want) - seen):
        p.append(f"missing declared cell {i}")
    for i in sorted(seen - set(want)):
        p.append(f"undeclared cell {i}")
    for c in cells:
        if c.get("status") not in CELL_STATUSES:
            p.append(f"{c.get('id')}: status {c.get('status')!r}")
            continue
        if c.get("model_section") != c.get("process"):
            p.append(f"{c.get('id')}: model section {c.get('model_section')!r} != {c.get('process')!r}")
        if c["status"] == "ok":
            sm = c.get("summary") or {}
            if not sm or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in sm.values()):
                p.append(f"{c['id']}: ok cell with missing or non-finite summary")
            if c.get("role") != "probe" and not (c.get("refined") or {}).get("ok"):
                p.append(f"{c['id']}: ok cell without a passing refined-grid control")
        elif not c.get("reason"):
            p.append(f"{c['id']}: rejected cell without a reason")
    # sabotage control: across the corner campaign, process must move S21 at f0
    by = {}
    for c in cells:
        if c.get("phase") == "corners" and c.get("status") == "ok" and c["candidate"] == st.baseline.name:
            by.setdefault((c["temp_c"], c["vdd_v"]), {})[c["process"]] = c["summary"]["s21_f0_db"]
    if shortlist_names and by:
        moved = any(len(set(round(v, 9) for v in d.values())) > 1 for d in by.values() if len(d) > 1)
        if not moved:
            p.append("process corners do not move the baseline S21 (corner sections not applied?)")
    return p


def conclude(st: Study, cells: list[dict], sl: dict) -> dict:
    """Per shortlisted candidate: does it pass the joint screen at every
    in-rail corner? Excursion (above the rail ceiling) cells are reported
    separately and never merged into the verdict. No winner is forced."""
    per: dict[str, dict] = {}
    for name in sl["names"]:
        cs = [c for c in cells if c.get("phase") == "corners" and c["candidate"] == name]
        inr = [c for c in cs if c["supply_class"] == "in_rail"]
        exc = [c for c in cs if c["supply_class"] == "excursion"]
        invalid = [c["corner_id"] for c in cs if c["status"] != "ok"]
        fails = [c["corner_id"] for c in inr if not c["screen"]["pass"]]
        okc = [c for c in inr if c["status"] == "ok"]
        worst = {}
        if okc:
            worst = {"nf_max_db": max(c["summary"]["nf_max_db"] for c in okc),
                     "s11_max_db": max(c["summary"]["s11_max_db"] for c in okc),
                     "s21_min_db": min(c["summary"]["s21_min_db"] for c in okc),
                     "k_min": min(min(c["summary"]["k_min"], c["summary"]["wide_k_min"]) for c in okc)}
        per[name] = {
            "in_rail_cells": len(inr), "in_rail_fail": fails, "invalid": invalid,
            "excursion_fail": [c["corner_id"] for c in exc if not c["screen"]["pass"]],
            "worst_in_rail": worst,
            "verdict": ("inconclusive (invalid cells)" if invalid else
                        "passes the joint screen at every in-rail corner" if not fails else
                        f"fails the joint screen at {len(fails)}/{len(inr)} in-rail corners"),
        }
    viable = [n for n, v in per.items() if n != st.baseline.name and not v["in_rail_fail"] and not v["invalid"]]
    return {"per_candidate": per, "viable": viable,
            "outcome": ("conditional candidate(s) for passive qualification: " + ", ".join(viable)) if viable else
                       "no tested input match meets the joint screen at every in-rail corner"}


# ---------------------------------------------------------------------------
# Baseline reproduction against the lna-sparam-nf record
# ---------------------------------------------------------------------------

BASELINE_POINTS = (("lo", 0), ("mid", None), ("hi", -1))


def compare_baseline(st: Study, cell: dict, old: dict[str, float]) -> dict:
    """Baseline candidate at a shared corner vs the lna-sparam-nf record's
    m_* values at 17.7 / 19.45 / 21.2 GHz (the dense grid's first, centre and
    last points). Returns worst deltas and problems."""
    b = cell["band"]
    n = len(b["f_hz"])
    worst = {"s_db": 0.0, "nf_db": 0.0, "k": 0.0}
    problems = []
    for suf, idx in BASELINE_POINTS:
        i = (n - 1) // 2 if idx is None else idx % n
        for q in ("s11", "s21", "s22", "s12"):
            key = f"{q}_db_{suf}"
            if key not in old:
                problems.append(f"record has no m_{key}")
                continue
            worst["s_db"] = max(worst["s_db"], abs(b[f"{q}_db"][i] - old[key]))
        if f"nf_db_{suf}" in old:
            worst["nf_db"] = max(worst["nf_db"], abs(b["nf_db"][i] - old[f"nf_db_{suf}"]))
        if f"k_{suf}" in old:
            worst["k"] = max(worst["k"], abs(b["k"][i] - old[f"k_{suf}"]))
    tol_db, tol_k = float(st.tolerances["baseline_db"]), float(st.tolerances["baseline_k"])
    for key, tol in (("s_db", tol_db), ("nf_db", tol_db), ("k", tol_k)):
        if worst[key] > tol:
            problems.append(f"baseline {key} differs by {worst[key]:.3g} > {tol:g}")
    return {"worst": worst, "problems": problems, "tolerances": {"db": tol_db, "k": tol_k}}


# ---------------------------------------------------------------------------
# Noise-parameter fit (derivation of the declared range)
# ---------------------------------------------------------------------------


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    # column scaling, then a relative pivot test: an ill-posed probe set
    # (e.g. every source on one circle) must fail loudly, not fit garbage
    scale = [max(abs(a[r][c]) for r in range(n)) or 1.0 for c in range(n)]
    m = [[row[c] / scale[c] for c in range(n)] + [bb] for row, bb in zip(a, b)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-10:
            raise StudyError("singular noise-parameter fit (probe source impedances are degenerate)")
        m[c], m[piv] = m[piv], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] / scale[i] for i in range(n)]


def fit_noise_params(points: list[tuple[complex, float]]) -> dict:
    """Least-squares fit of F(Ys) = Fmin + Rn/Gs |Ys - Yopt|^2 to
    ``[(Zs, F_linear), ...]``. Linear in (Rn, Fmin - 2 Rn Gopt, -2 Rn Bopt,
    Rn |Yopt|^2) after multiplying by Gs. Returns Fmin, Rn, Yopt, Zopt and
    the rms residual in dB."""
    if len(points) < 4:
        raise StudyError("need at least 4 source impedances")
    rows, rhs = [], []
    for zs, f in points:
        ys = 1 / zs
        g, b = ys.real, ys.imag
        rows.append([g * g + b * b, g, b, 1.0])
        rhs.append(f * g)
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(4)] for i in range(4)]
    atb = [sum(r[i] * y for r, y in zip(rows, rhs)) for i in range(4)]
    a, b1, c, d = _solve(ata, atb)
    rn = a
    bopt = -c / (2 * a)
    gsq = d / a - bopt * bopt
    if gsq <= 0:
        raise StudyError("noise-parameter fit gave a non-physical Gopt")
    gopt = math.sqrt(gsq)
    fmin = b1 + 2 * a * gopt
    yopt = complex(gopt, bopt)
    res = []
    for zs, f in points:
        ys = 1 / zs
        fm = fmin + rn / ys.real * abs(ys - yopt) ** 2
        res.append(10 * math.log10(fm) - 10 * math.log10(f))
    return {"fmin_db": 10 * math.log10(fmin), "fmin": fmin, "rn_ohm": rn, "yopt": yopt, "zopt": 1 / yopt,
            "rms_residual_db": math.sqrt(sum(r * r for r in res) / len(res))}


# ---------------------------------------------------------------------------
# Network-independent bound (any lossless input network)
# ---------------------------------------------------------------------------
#
# Behind a lossless reciprocal input network the port noise factor and the
# port return loss depend ONLY on the source reflection Gamma_s the network
# presents to the core at each frequency (F = F_core(Z_s); |S11_port| is the
# power mismatch between Gamma_s and Gamma_in of the core). So at each
# frequency the joint (NF, S11) question has a network-independent answer:
# the smallest NF any lossless network could give with |S11| <= rho, and the
# smallest |S11| with NF <= the screen. Both sublevel families are circles
# in the Gamma_s plane, so each bound is a minimum over a circle.


def nf_lin_at(gs: complex, fmin: float, rn_norm: float, gopt: complex) -> float:
    """F(Gamma_s) = Fmin + 4 rn |Gs - Gopt|^2 / ((1 - |Gs|^2) |1 + Gopt|^2)."""
    den = (1 - abs(gs) ** 2) * abs(1 + gopt) ** 2
    if den <= 0:
        return float("inf")
    return fmin + 4 * rn_norm * abs(gs - gopt) ** 2 / den


def mismatch(gs: complex, gin: complex) -> float:
    """|Gamma_port| behind a lossless network presenting Gamma_s to a core of
    input reflection Gamma_in: |(Gamma_in - Gs*) / (1 - Gamma_in Gs)|."""
    return abs((gin - gs.conjugate()) / (1 - gin * gs))


def mismatch_circle(gin: complex, rho: float) -> tuple[complex, float]:
    """Gamma_s locus with |Gamma_port| <= rho: (centre, radius)."""
    a = abs(gin) ** 2
    d = 1 - rho * rho * a
    return gin.conjugate() * (1 - rho * rho) / d, rho * (1 - a) / d


def noise_circle(f_lin: float, fmin: float, rn_norm: float, gopt: complex) -> tuple[complex, float] | None:
    """Gamma_s locus with F <= f_lin: (centre, radius), or None if f_lin < Fmin."""
    if f_lin < fmin:
        return None
    n = (f_lin - fmin) * abs(1 + gopt) ** 2 / (4 * rn_norm)
    return gopt / (1 + n), math.sqrt(n * n + n * (1 - abs(gopt) ** 2)) / (1 + n)


def _min_on_circle(fun, centre: complex, radius: float, n: int = 720, zooms: int = 4) -> tuple[float, complex]:
    """Minimum of ``fun`` on a circle: n uniform samples, then ``zooms``
    rounds of 41 samples over +-2 of the previous step around the best one
    (final angular resolution 2 pi / n / 10^zooms)."""
    best = (float("inf"), centre, 0.0)
    step = 2 * math.pi / n
    for i in range(n):
        g = centre + radius * cmath.exp(1j * i * step)
        v = fun(g)
        if v < best[0]:
            best = (v, g, i * step)
    for _ in range(zooms):
        a0, span = best[2], 2 * step
        step = span / 20
        for j in range(-20, 21):
            a = a0 + j * step
            g = centre + radius * cmath.exp(1j * a)
            v = fun(g)
            if v < best[0]:
                best = (v, g, a)
    return best[0], best[1]


def gt_db(gs: complex, s: dict) -> float:
    """Transducer gain into the declared z0 load for source Gamma_s."""
    g = abs(s["s21"]) ** 2 * (1 - abs(gs) ** 2) / abs(1 - s["s11"] * gs) ** 2
    return 10 * math.log10(g) if g > 0 else float("-inf")


def frequency_bound(s: dict, npar: dict, z0: float, nf_max_db: float, s11_max_db: float) -> dict:
    """Both bounds at one frequency. ``s`` holds the core's complex S11/S21
    at node in2 (z0 reference, z0 load); ``npar`` the fitted noise parameters."""
    gin = s["s11"]
    fmin, rn = npar["fmin"], npar["rn_ohm"] / z0
    gopt = gamma(npar["zopt"], z0)
    rho = 10 ** (s11_max_db / 20)
    c, r = mismatch_circle(gin, rho)
    if abs(gopt - c) <= r:
        f_best, g_best = fmin, gopt
    else:
        f_best, g_best = _min_on_circle(lambda g: nf_lin_at(g, fmin, rn, gopt), c, r)
    out = {"nf_bound_db": 10 * math.log10(f_best), "gamma_at_nf_bound": [g_best.real, g_best.imag],
           "gt_at_nf_bound_db": gt_db(g_best, s)}
    circ = noise_circle(10 ** (nf_max_db / 10), fmin, rn, gopt)
    if circ is None:
        out.update(s11_bound_db=None, s11_bound_note="Fmin above the NF screen")
    else:
        cc, rr = circ
        if abs(gin.conjugate() - cc) <= rr:
            out.update(s11_bound_db=float("-inf"))
        else:
            m, g = _min_on_circle(lambda g: mismatch(g, gin), cc, rr)
            out.update(s11_bound_db=db20(m), gamma_at_s11_bound=[g.real, g.imag], gt_at_s11_bound_db=gt_db(g, s))
    return out


def point_bound(st: Study, tables: dict[str, dict], cands: list[Candidate]) -> dict:
    """Noise-parameter fit from the probe networks, the core's S-parameters
    from the thru probe, the network-independent bounds on the dense grid,
    and the model-consistency check: every non-probe candidate's simulated
    NF and S11 must equal the prediction from (noise parameters, S_core,
    its closed-form Z_s(f)) within ``tolerances.model_db``."""
    probes = [c for c in cands if c.role == "probe"]
    thru = next((c for c in probes if c.name == "probe_thru"), None)
    problems = []
    if thru is None or thru.name not in tables:
        return {"valid": False, "problems": ["no probe_thru data"]}
    an = {c.name: analyze_candidate(st, c, tables[c.name]) for c in cands if c.name in tables}
    usable = [c for c in probes if c.name in an and an[c.name].get("band") is not None
              and all(math.isfinite(x) for x in an[c.name]["band"]["nf_db"])]
    if len(usable) < 5:
        return {"valid": False, "problems": [f"only {len(usable)} usable probes (need 5)"]}
    core = two_port(tables[thru.name]["fwd_dense"], tables[thru.name]["rev_dense"])
    freqs = st.dense_freqs()
    rows = []
    for i, f in enumerate(freqs):
        pts = [(source_impedance(c, f, st.z0), 10 ** (an[c.name]["band"]["nf_db"][i] / 10)) for c in usable]
        try:
            npar = fit_noise_params(pts)
        except StudyError as exc:
            problems.append(f"{f / 1e9:.3f} GHz: {exc}")
            continue
        s = {"s11": core[i]["s11"], "s21": core[i]["s21"]}
        b = frequency_bound(s, npar, st.z0, float(st.screen["nf_max_db"]), float(st.screen["s11_max_db"]))
        zin = z_from_gamma(s["s11"], st.z0)
        rows.append(dict(f_hz=f, fmin_db=npar["fmin_db"], rn_ohm=npar["rn_ohm"], zopt=[npar["zopt"].real,
                         npar["zopt"].imag], zin_core=[zin.real, zin.imag], fit_rms_db=npar["rms_residual_db"],
                         _npar=npar, _s=s, **b))
    if problems:
        return {"valid": False, "problems": problems}
    # model-consistency check on the selectable candidates
    tol = float(st.tolerances["model_db"])
    checks = {}
    worst = 0.0
    for c in cands:
        if c.role == "probe" or not an.get(c.name, {}).get("valid"):
            continue
        e_nf = e_s11 = 0.0
        for i, row in enumerate(rows):
            gs = gamma(source_impedance(c, row["f_hz"], st.z0), st.z0)
            npar, s = row["_npar"], row["_s"]
            nf_p = 10 * math.log10(nf_lin_at(gs, npar["fmin"], npar["rn_ohm"] / st.z0, gamma(npar["zopt"], st.z0)))
            s11_p = db20(mismatch(gs, s["s11"]))
            e_nf = max(e_nf, abs(nf_p - an[c.name]["band"]["nf_db"][i]))
            if an[c.name]["band"]["s11_db"][i] > -60:
                e_s11 = max(e_s11, abs(s11_p - an[c.name]["band"]["s11_db"][i]))
        checks[c.name] = {"nf_err_db": e_nf, "s11_err_db": e_s11}
        worst = max(worst, e_nf, e_s11)
    for row in rows:
        row.pop("_npar")
        row.pop("_s")
    nfb = [r["nf_bound_db"] for r in rows]
    s11b = [r["s11_bound_db"] for r in rows]
    imax = max(range(len(nfb)), key=lambda j: nfb[j])
    infeasible = [r["f_hz"] for r in rows if r["nf_bound_db"] > float(st.screen["nf_max_db"])]
    summary = {
        "nf_bound_max_db": nfb[imax], "f_at_nf_bound_max_hz": rows[imax]["f_hz"],
        "nf_bound_min_db": min(nfb),
        "s11_bound_max_db": (None if any(x is None for x in s11b) else max(s11b)),
        "fmin_max_db": max(r["fmin_db"] for r in rows), "fmin_min_db": min(r["fmin_db"] for r in rows),
        "fit_rms_max_db": max(r["fit_rms_db"] for r in rows),
        "n_freq_jointly_infeasible": len(infeasible), "n_freq": len(rows),
        "model_check_worst_db": worst, "model_check_tol_db": tol,
    }
    valid = worst <= tol and summary["fit_rms_max_db"] <= tol
    if not valid:
        problems.append(f"model check worst {worst:.3g} dB / fit rms {summary['fit_rms_max_db']:.3g} dB "
                        f"exceeds {tol} dB: the bound is not used at this point")
    return {"valid": valid, "problems": problems, "rows": rows, "summary": summary, "model_check": checks,
            "probes_used": [c.name for c in usable]}
