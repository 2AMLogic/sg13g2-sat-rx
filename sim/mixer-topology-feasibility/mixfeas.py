"""Mixer-core topology feasibility study (issue #35): study declaration, deck
generation, log parsing, extraction, LO-drive selection, IIP3 fitting,
stress classification and evidence-acceptance gates.

BENCH-LOCAL module on top of ``sim/harness`` (same pattern as
``hbt-kaband-characterization/kaband.py``): the generic harness runs one
scalar ``measure`` set per PVT point, while this study runs several
transient analyses per PVT point (RF on at two powers, RF off, LO-drive
points, two-tone power steps) and reduces each with an in-deck single-bin
DFT. Everything here is pure Python (stdlib only) so ``tests/`` can exercise
it against synthetic data with known answers, without a PDK or simulator.

DEVICE-LEVEL TOPOLOGY STUDY. Candidates use ideal baluns, ideal R/C and
ideal bias sources (see ``testbench/*.spice``). Nothing computed here claims
any ``spec/target-spec.md`` row is met.

Conventions (``testbench/ports_common.spice`` is the circuit side):

- RF available power per tone ``P = vrf^2 / (8 * z0)`` (50 ohm Thevenin).
- LO: TOTAL available power of the differential 100 ohm port,
  ``P = vlo_open_diff_peak^2 / (8 * R_diff)``.
- Delivered power at a terminated node: ``|V_peak|^2 / (2 * z0)``.
- Conversion gain = IF fundamental power delivered into the 50 ohm IF
  termination / RF available power (per tone).
- Spectral extraction: uniform resampling (ngspice ``linearize``) of the
  retained window ``[settle, settle + window)``, rectangular window over an
  integer number of periods of every tone (checked: :func:`coherence_problems`),
  single-bin DFT ``A = (2/N) * sum x[k] * exp(-j 2 pi f t_k)`` so a sine of
  peak amplitude ``a`` on a bin reads ``|A| = a`` exactly.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

Z0_OHM = 50.0
LO_RDIFF_OHM = 100.0

#: Every value printed by a generated deck is named ``mf_<key>``.
_VALUE_RE = re.compile(
    r"^(mf_\w+)\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|[-+]?nan|[-+]?inf)\s*$",
    re.IGNORECASE,
)
_MESSAGE_RE = re.compile(r"^(warning|error|fatal|doanalyses|internal error|the temperature limiting)",
                         re.IGNORECASE)

STRESS_INTERVALS = ("dc", "startup", "retained")


class StudyError(ValueError):
    """The study declaration (tb.json ``study`` block) is malformed."""


# ---------------------------------------------------------------------------
# Power arithmetic
# ---------------------------------------------------------------------------


def dbm(watts: float) -> float:
    """Power in dBm; ``-inf`` for exactly zero, NaN propagates."""
    if watts != watts:  # NaN
        return float("nan")
    if watts <= 0.0:
        return float("-inf")
    return 10.0 * math.log10(watts / 1e-3)


def watts(dbm_value: float) -> float:
    return 1e-3 * 10.0 ** (dbm_value / 10.0)


def available_power_w(v_open_peak: float, r_source: float) -> float:
    """Available power of a Thevenin source (peak open-circuit voltage,
    real source resistance): ``V^2 / (8 R)``."""
    return v_open_peak * v_open_peak / (8.0 * r_source)


def v_open_peak_for(dbm_value: float, r_source: float) -> float:
    """Inverse of :func:`available_power_w` for a power in dBm."""
    return math.sqrt(8.0 * r_source * watts(dbm_value))


def delivered_power_w(v_peak: float, r_load: float) -> float:
    """Power delivered into a resistor by a sine of peak amplitude ``v_peak``."""
    return v_peak * v_peak / (2.0 * r_load)


def dft_bin(samples: list[float], dt: float, freq_hz: float, t0: float = 0.0) -> complex:
    """Single-bin DFT of uniformly sampled data, normalised so that
    ``a * sin(2 pi f t + phi)`` on a coherent bin returns
    ``a * (sin(phi) + j cos(phi))`` (``abs`` = peak amplitude ``a``).

    The same expression the generated deck evaluates in ngspice; this pure
    Python copy is what the analytic parser tests exercise."""
    n = len(samples)
    if n == 0:
        raise ValueError("no samples")
    re_acc = im_acc = 0.0
    w = 2.0 * math.pi * freq_hz
    for k, x in enumerate(samples):
        ph = w * (k * dt + t0)
        re_acc += x * math.cos(ph)
        im_acc += x * math.sin(ph)
    return complex(2.0 * re_acc / n, 2.0 * im_acc / n)


# ---------------------------------------------------------------------------
# Study declaration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Device:
    name: str
    c: str
    b: str
    e: str
    nx: int


@dataclass(frozen=True)
class Candidate:
    name: str
    role: str                  # "candidate" | "floor" | "control"
    fragment: str
    rf_dc_v: float
    lo_dc_v: float
    devices: tuple[Device, ...]
    summary: str = ""
    params: dict = field(default_factory=dict, compare=False, hash=False)
    #: Nodes carrying an IDEAL current sink to ground. Not a card device, so
    #: no limit is applied; the voltage across each sink (its compliance
    #: headroom, which a real sink would need) is reported.
    sink_nodes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Band:
    name: str
    rf_hz: float
    lo_hz: float
    two_tone_hz: tuple[float, float]
    two_tone_lo_hz: float


@dataclass(frozen=True)
class Timing:
    settle_s: float
    window_single_s: float
    window_two_tone_s: float
    tmax_s: float
    tstep_s: float


@dataclass(frozen=True)
class MatrixDecl:
    name: str
    corners: tuple[str, ...]
    temperatures_c: tuple[float, ...]
    supplies_v: tuple[float, ...]
    bands: tuple[str, ...]
    seed: int | None = None


@dataclass(frozen=True)
class StressLimits:
    vce_v: tuple[float, float]
    vbe_v: tuple[float, float]
    ic_a_per_nx: float
    reject_intervals: tuple[str, ...]


@dataclass(frozen=True)
class Study:
    if_hz: float
    rail_max_v: float
    band_hz: tuple[float, float]
    bands: tuple[Band, ...]
    candidates: tuple[Candidate, ...]
    control: Candidate
    rf_dbm: float
    rf_check_dbm: float
    small_signal_tol_db: float
    lo_sweep_dbm: tuple[float, ...]
    plateau_db: float
    plateau_run: int
    iip3_pin_dbm: tuple[float, ...]
    iip3_rules: dict
    timing: Timing
    convergence_tol_db: float
    floor_margin_db: float
    abs_floor_dbm: float
    stress: StressLimits
    matrices: dict
    smoke: dict

    def band(self, name: str) -> Band:
        for b in self.bands:
            if b.name == name:
                return b
        raise KeyError(f"unknown band {name!r}; known: {', '.join(b.name for b in self.bands)}")

    def candidate(self, name: str) -> Candidate:
        for c in self.candidates + (self.control,):
            if c.name == name:
                return c
        raise KeyError(f"unknown candidate {name!r}; known: "
                       f"{', '.join(c.name for c in self.candidates)}")


def _range(spec) -> tuple[float, ...]:
    if isinstance(spec, dict):
        start, stop, step = float(spec["start"]), float(spec["stop"]), float(spec["step"])
        if step <= 0 or stop < start:
            raise StudyError(f"bad range {spec!r}")
        n = int(round((stop - start) / step)) + 1
        out = tuple(round(start + i * step, 9) for i in range(n))
        if abs(out[-1] - stop) > 1e-9:
            raise StudyError(f"range {spec!r} does not land on its stop value")
        return out
    return tuple(float(v) for v in spec)


def _candidate(d: dict) -> Candidate:
    devices = tuple(Device(name=str(x["name"]), c=str(x["c"]), b=str(x["b"]), e=str(x["e"]),
                           nx=int(x["nx"])) for x in d.get("devices", []))
    names = [x.name for x in devices]
    if len(set(names)) != len(names):
        raise StudyError(f"candidate {d.get('name')!r}: duplicate device names {names}")
    for dev in devices:
        if not 1 <= dev.nx <= 10:
            raise StudyError(f"{d.get('name')}/{dev.name}: Nx={dev.nx} outside the card's 1..10")
    role = str(d.get("role", "candidate"))
    if role not in ("candidate", "floor", "control"):
        raise StudyError(f"candidate {d.get('name')!r}: unknown role {role!r}")
    return Candidate(name=str(d["name"]), role=role, fragment=str(d["fragment"]),
                     rf_dc_v=float(d.get("rf_dc_v", 0.0)), lo_dc_v=float(d.get("lo_dc_v", 0.0)),
                     devices=devices, summary=str(d.get("summary", "")),
                     params=dict(d.get("params", {})),
                     sink_nodes=tuple(str(n) for n in d.get("ideal_sink_nodes", ())))


def supply_axis(nominal_v: float, tolerance: float) -> tuple[float, ...]:
    """Nominal and +/- tolerance (same arithmetic as harness.corners.supply_points)."""
    return (round(nominal_v * (1 - tolerance), 6), round(nominal_v, 6),
            round(nominal_v * (1 + tolerance), 6))


def study_from_manifest(manifest: dict) -> Study:
    """Parse and validate tb.json's ``study`` block.

    Refuses (StudyError) rather than adjusts: a supply above the rail
    ceiling, an LO that is not RF - IF, a two-tone pair outside the band, a
    reduced matrix that silently differs from what the README states, etc."""
    s = manifest.get("study")
    if not isinstance(s, dict):
        raise StudyError("tb.json has no 'study' block")
    if_hz = float(s["if_hz"])
    band_lo, band_hi = (float(x) for x in s["rf_band_hz"])
    bands = []
    for b in s["bands"]:
        rf = float(b["rf_hz"])
        t1, t2 = (float(x) for x in b["two_tone_hz"])
        for f in (rf, t1, t2):
            if not band_lo - 1e-3 <= f <= band_hi + 1e-3:
                raise StudyError(f"band {b['name']}: {f:.6g} Hz outside the declared RF band")
        if not t1 < t2:
            raise StudyError(f"band {b['name']}: two-tone pair must be increasing")
        bands.append(Band(name=str(b["name"]), rf_hz=rf, lo_hz=rf - if_hz, two_tone_hz=(t1, t2),
                          two_tone_lo_hz=(t1 + t2) / 2.0 - if_hz))
    if len({b.name for b in bands}) != len(bands):
        raise StudyError("duplicate band names")
    t = s["timing"]
    timing = Timing(settle_s=float(t["settle_s"]), window_single_s=float(t["window_single_s"]),
                    window_two_tone_s=float(t["window_two_tone_s"]), tmax_s=float(t["tmax_s"]),
                    tstep_s=float(t["tstep_s"]))
    if timing.tstep_s > timing.tmax_s:
        raise StudyError("resampling step must not exceed the maximum simulator timestep")
    rail_max = float(s["rail_max_v"])
    nominal = float(manifest["nominal_supply_v"])
    tol = float(manifest["supply_tolerance"])
    main_supplies = supply_axis(nominal, tol)
    matrices = {}
    for name, m in s["matrices"].items():
        if name.startswith("_"):
            continue
        supplies = main_supplies if m.get("supplies_v") == "nominal_pm_tolerance" else \
            tuple(float(v) for v in m["supplies_v"])
        for v in supplies:
            if v > rail_max:
                raise StudyError(f"matrix {name}: supply {v} V exceeds the {rail_max} V rail ceiling "
                                 "(row 17); refusing rather than clipping")
        band_names = tuple(b.name for b in bands) if m.get("bands", "all") == "all" else \
            tuple(m["bands"])
        for bn in band_names:
            if bn not in {b.name for b in bands}:
                raise StudyError(f"matrix {name}: unknown band {bn!r}")
        matrices[name] = MatrixDecl(
            name=name, corners=tuple(m["corners"]),
            temperatures_c=tuple(float(x) for x in m["temperatures_c"]),
            supplies_v=tuple(supplies), bands=band_names,
            seed=int(m["seed"]) if m.get("seed") is not None else None)
    for required in ("main", "leakage", "lo_select", "iip3"):
        if required not in matrices:
            raise StudyError(f"study.matrices lacks {required!r}")
    if matrices["leakage"].seed is None:
        raise StudyError("leakage matrix must record a fixed mismatch seed")
    for c in matrices["leakage"].corners:
        if not c.endswith("_mismatch"):
            raise StudyError(f"leakage matrix corner {c!r} is not a mismatch card")
    candidates = tuple(_candidate(c) for c in s["candidates"])
    if len({c.name for c in candidates}) != len(candidates):
        raise StudyError("duplicate candidate names")
    if sum(1 for c in candidates if c.role == "floor") != 1:
        raise StudyError("exactly one candidate must have role 'floor'")
    control = _candidate(dict(s["analytic_control"], role="control"))
    st = s["stress"]
    stress = StressLimits(vce_v=tuple(float(x) for x in st["vce_v"]),
                          vbe_v=tuple(float(x) for x in st["vbe_v"]),
                          ic_a_per_nx=float(st["ic_a_per_nx"]),
                          reject_intervals=tuple(st["reject_intervals"]))
    for iv in stress.reject_intervals:
        if iv not in STRESS_INTERVALS:
            raise StudyError(f"unknown stress interval {iv!r}")
    iip3 = dict(s["iip3"])
    study = Study(
        if_hz=if_hz, rail_max_v=rail_max, band_hz=(band_lo, band_hi), bands=tuple(bands),
        candidates=candidates, control=control,
        rf_dbm=float(s["rf_small_signal_dbm"]), rf_check_dbm=float(s["rf_check_dbm"]),
        small_signal_tol_db=float(s["small_signal_tol_db"]),
        lo_sweep_dbm=_range(s["lo_sweep_dbm"]),
        plateau_db=float(s["lo_select"]["plateau_db"]), plateau_run=int(s["lo_select"]["run_length"]),
        iip3_pin_dbm=_range(iip3.pop("pin_dbm")), iip3_rules=iip3, timing=timing,
        convergence_tol_db=float(s["convergence"]["tol_db"]),
        floor_margin_db=float(s["convergence"]["floor_margin_db"]),
        abs_floor_dbm=float(s["convergence"]["absolute_floor_dbm"]),
        stress=stress, matrices=matrices, smoke=dict(s.get("smoke", {})),
    )
    for band in study.bands:
        for kind in ("single", "rfoff", "two_tone"):
            run = RunSpec(run_id="check", kind=kind, band=band, vlo_dbm=0.0,
                          rf_dbm=None if kind == "rfoff" else study.rf_dbm,
                          window_s=timing.window_two_tone_s if kind == "two_tone" else timing.window_single_s,
                          settle_s=timing.settle_s, tmax_s=timing.tmax_s, tstep_s=timing.tstep_s,
                          if_hz=if_hz)
            problems = coherence_problems(run)
            if problems:
                raise StudyError(f"band {band.name} {kind}: " + "; ".join(problems))
    return study


# ---------------------------------------------------------------------------
# Runs and their spectral bins
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunSpec:
    """One transient analysis inside a deck."""

    run_id: str
    kind: str                 # "single" | "rfoff" | "two_tone"
    band: Band
    vlo_dbm: float
    rf_dbm: float | None      # per tone; None when the RF source is off
    window_s: float
    settle_s: float
    tmax_s: float
    tstep_s: float
    if_hz: float = 1e9

    @property
    def tstop_s(self) -> float:
        return self.settle_s + self.window_s

    @property
    def n_samples(self) -> int:
        return int(round(self.window_s / self.tstep_s))

    @property
    def resolution_hz(self) -> float:
        return 1.0 / self.window_s

    @property
    def tones(self) -> tuple[float, float, float]:
        """(f1, f2, flo)."""
        if self.kind == "two_tone":
            f1, f2 = self.band.two_tone_hz
            return f1, f2, self.band.two_tone_lo_hz
        return self.band.rf_hz, self.band.rf_hz, self.band.lo_hz

    @property
    def vlo_open_peak(self) -> float:
        return v_open_peak_for(self.vlo_dbm, LO_RDIFF_OHM)

    @property
    def vrf_open_peak(self) -> tuple[float, float]:
        if self.rf_dbm is None:
            return 0.0, 0.0
        v = v_open_peak_for(self.rf_dbm, Z0_OHM)
        return (v, v) if self.kind == "two_tone" else (v, 0.0)

    def params(self) -> dict[str, float]:
        f1, f2, flo = self.tones
        vrf1, vrf2 = self.vrf_open_peak
        return {"f1": f1, "f2": f2, "flo": flo, "vrf1": vrf1, "vrf2": vrf2, "vlo": self.vlo_open_peak}

    def bins(self) -> dict[str, tuple[str, float]]:
        """Named spectral bins: name -> (ngspice expression, frequency)."""
        f1, f2, flo = self.tones
        res = self.resolution_hz
        lo_diff = "v(lo_p)-v(lo_n)"
        out: dict[str, tuple[str, float]] = {"lodiff": (lo_diff, flo)}
        if self.kind == "single":
            fif = f1 - flo
            out.update({
                "if": ("v(if_out)", fif),
                "loif": ("v(if_out)", flo),
                "lorf": ("v(rf_port)", flo),
                # Empty bins one resolution step either side of the IF: no
                # product of order < ~400 lands there (see README).
                "flifa": ("v(if_out)", fif - res),
                "flifb": ("v(if_out)", fif + res),
                "fllorf": ("v(rf_port)", flo + res),
                "flloif": ("v(if_out)", flo + res),
            })
        elif self.kind == "rfoff":
            out.update({
                "loif": ("v(if_out)", flo),
                "lorf": ("v(rf_port)", flo),
                "fllorf": ("v(rf_port)", flo + res),
                "flloif": ("v(if_out)", flo + res),
            })
        elif self.kind == "two_tone":
            if1, if2 = f1 - flo, f2 - flo
            spacing = f2 - f1
            centre = (if1 + if2) / 2.0
            out.update({
                "if1": ("v(if_out)", if1),
                "if2": ("v(if_out)", if2),
                "im3l": ("v(if_out)", 2 * f1 - f2 - flo),
                "im3h": ("v(if_out)", 2 * f2 - f1 - flo),
                # Midway between adjacent products (offset spacing/2 from
                # every n*spacing comb line around the IF): empty.
                "fl2a": ("v(if_out)", centre - spacing),
                "fl2b": ("v(if_out)", centre),
                "fl2c": ("v(if_out)", centre + spacing),
            })
        else:
            raise ValueError(f"unknown run kind {self.kind!r}")
        return out

    def floor_bins(self) -> dict[str, tuple[str, ...]]:
        """Which empty bins bound the extraction floor of which quantity."""
        if self.kind == "single":
            return {"if": ("flifa", "flifb"), "loif": ("flloif",), "lorf": ("fllorf",)}
        if self.kind == "rfoff":
            return {"loif": ("flloif",), "lorf": ("fllorf",)}
        return {"im3": ("fl2a", "fl2b", "fl2c")}


def coherence_problems(run: RunSpec, tol: float = 1e-6) -> list[str]:
    """Every bin frequency must be an integer number of cycles in the
    retained window, and the window an integer number of resampling steps."""
    problems = []
    steps = run.window_s / run.tstep_s
    if abs(steps - round(steps)) > tol:
        problems.append(f"window {run.window_s:g} s is not an integer number of {run.tstep_s:g} s steps")
    for name, (_, f) in run.bins().items():
        cycles = f * run.window_s
        if abs(cycles - round(cycles)) > tol * max(1.0, cycles):
            problems.append(f"bin {name} at {f:.9g} Hz is not coherent with the {run.window_s:g} s window "
                            f"({cycles:.6f} cycles)")
        if f <= 0 or f >= 0.5 / run.tstep_s:
            problems.append(f"bin {name} at {f:.6g} Hz is outside (0, Nyquist)")
    for f in run.tones:
        cycles = f * run.window_s
        if abs(cycles - round(cycles)) > tol * max(1.0, cycles):
            problems.append(f"tone {f:.9g} Hz is not coherent with the window")
    return problems


# ---------------------------------------------------------------------------
# Deck generation (ngspice control block)
# ---------------------------------------------------------------------------

STRESS_QTYS = ("vce", "vbe", "ic")


def _q_let(dev: Device, q: str) -> str:
    if q == "vce":
        return f"v({dev.c})-v({dev.e})"
    if q == "vbe":
        return f"v({dev.b})-v({dev.e})"
    return f"i(vic_{dev.name})"


def run_keys(run: RunSpec, devices: tuple[Device, ...], sink_nodes: tuple[str, ...] = ()) -> list[str]:
    """Every ``mf_`` value one run must print (the parser's completeness list)."""
    keys = ["mf_l", "mf_n", "mf_dcirail", "mf_prail"]
    for node in sink_nodes:
        keys += [f"mf_dc_sink_{node}", f"mf_su_sinkmin_{node}", f"mf_ss_sinkmin_{node}"]
    for dev in devices:
        for q in STRESS_QTYS:
            keys.append(f"mf_dc_{q}_{dev.name}")
            for iv in ("su", "ss"):
                keys += [f"mf_{iv}_{q}max_{dev.name}", f"mf_{iv}_{q}min_{dev.name}"]
    for name in run.bins():
        keys += [f"mf_{name}_re", f"mf_{name}_im"]
    return keys


def _fmt(x: float) -> str:
    return repr(float(x))


def build_run_lines(run: RunSpec, devices: tuple[Device, ...], *, sink_nodes: tuple[str, ...] = (),
                    drop_key: str | None = None) -> list[str]:
    """ngspice control lines for one transient run.

    ``drop_key`` deletes one required print (selftest's invalid-deck control:
    the parser must refuse the run)."""
    ts, te, dt = run.settle_s, run.tstop_s, run.tstep_s
    lines = [f'echo "MFRUN {run.run_id}"']
    for k, v in run.params().items():
        lines.append(f"alterparam {k} = {_fmt(v)}")
    lines += ["reset", "op", "let mf_dcirail = 0 - i(vdd)"]
    prints = ["mf_dcirail"]
    for dev in devices:
        for q in STRESS_QTYS:
            name = f"mf_dc_{q}_{dev.name}"
            lines.append(f"let {name} = {_q_let(dev, q)}")
            prints.append(name)
    for node in sink_nodes:
        lines.append(f"let mf_dc_sink_{node} = v({node})")
        prints.append(f"mf_dc_sink_{node}")
    lines += [f"print {p}" for p in prints if p != drop_key]
    lines.append(f"tran {_fmt(dt)} {_fmt(te)} 0 {_fmt(run.tmax_s)}")
    meas = []
    for dev in devices:
        for q in STRESS_QTYS:
            # control-mode `meas` rejects v(a,b); measure a named vector
            vec = f"mfq_{q}_{dev.name}"
            lines.append(f"let {vec} = {_q_let(dev, q)}")
            for iv, (a, b) in (("su", (0.0, ts)), ("ss", (ts, te))):
                for fn in ("max", "min"):
                    name = f"mf_{iv}_{q}{fn}_{dev.name}"
                    lines.append(f"meas tran {name} {fn.upper()} {vec} from={_fmt(a)} to={_fmt(b)}")
                    meas.append(name)
    for node in sink_nodes:
        for iv, (a, b) in (("su", (0.0, ts)), ("ss", (ts, te))):
            name = f"mf_{iv}_sinkmin_{node}"
            lines.append(f"meas tran {name} MIN v({node}) from={_fmt(a)} to={_fmt(b)}")
            meas.append(name)
    lines += [f"print {m}" for m in meas if m != drop_key]
    lines += [
        "linearize",
        "let mf_l = length(time)",
        f"let mfw = (time ge {_fmt(ts - dt / 2)}) * (time lt {_fmt(te - dt / 2)})",
        "let mf_n = mean(mfw) * mf_l",
        "let mfs = mf_l / mf_n",
        "let mf_prail = mean(v(vdd) * (0 - i(vdd)) * mfw) * mfs",
    ]
    prints = ["mf_l", "mf_n", "mf_prail"]
    for name, (expr, f) in run.bins().items():
        lines += [
            f"let mfph = 2 * pi * {_fmt(f)} * (time - {_fmt(ts)})",
            f"let mf_{name}_re = 2 * mean(({expr}) * mfw * cos(mfph)) * mfs",
            f"let mf_{name}_im = 2 * mean(({expr}) * mfw * sin(mfph)) * mfs",
        ]
        prints += [f"mf_{name}_re", f"mf_{name}_im"]
    lines += [f"print {p}" for p in prints if p != drop_key]
    lines += ["destroy all", f'echo "MFEND {run.run_id}"']
    return lines


def build_control_lines(runs: list[RunSpec], devices: tuple[Device, ...], *,
                        sink_nodes: tuple[str, ...] = (), drop_key: str | None = None) -> list[str]:
    ids = [r.run_id for r in runs]
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate run ids {ids}")
    lines = ['echo "MF_DECK_BEGIN"']
    for run in runs:
        lines += build_run_lines(run, devices, sink_nodes=sink_nodes, drop_key=drop_key)
    lines.append('echo "MF_DECK_END"')
    return lines


def deck_params(study: Study, cand: Candidate, run: RunSpec | None = None) -> dict[str, float]:
    """``.param`` defaults for a composed deck (overridden per run by alterparam)."""
    band = study.bands[0]
    p = {"f1": band.rf_hz, "f2": band.rf_hz, "flo": band.lo_hz, "vrf1": 0.0, "vrf2": 0.0,
         "vlo": 0.0, "rf_dc": cand.rf_dc_v, "lo_dc": cand.lo_dc_v}
    p.update(cand.params)
    if run is not None:
        p.update(run.params())
    return p


_DEVICE_RE = re.compile(r"^\s*x(\w+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+npn13g2\b(.*)$", re.IGNORECASE)
_SENSE_RE = re.compile(r"^\s*vic_(\w+)\s+(\S+)\s+(\S+)\s+0\s*$", re.IGNORECASE)


def check_fragment_devices(text: str, cand: Candidate) -> list[str]:
    """The fragment's npn13G2 instances must be exactly the declared devices,
    with the declared c/b/e nodes, Nx, and a collector sense source each."""
    problems = []
    found = {}
    senses = {}
    for line in text.splitlines():
        if line.lstrip().startswith("*"):
            continue
        m = _DEVICE_RE.match(line)
        if m:
            nx = re.search(r"nx\s*=\s*(\d+)", m.group(6), re.IGNORECASE)
            found[m.group(1).lower()] = (m.group(2).lower(), m.group(3).lower(), m.group(4).lower(),
                                         int(nx.group(1)) if nx else 1)
        m = _SENSE_RE.match(line)
        if m:
            senses[m.group(1).lower()] = (m.group(2).lower(), m.group(3).lower())
    declared = {d.name.lower(): d for d in cand.devices}
    for name in sorted(set(found) - set(declared)):
        problems.append(f"{cand.name}: undeclared npn13G2 instance x{name}")
    for name, dev in declared.items():
        if name not in found:
            problems.append(f"{cand.name}: declared device {name} not in fragment")
            continue
        c, b, e, nx = found[name]
        if (c, b, e) != (dev.c.lower(), dev.b.lower(), dev.e.lower()) or nx != dev.nx:
            problems.append(f"{cand.name}/{name}: fragment has c={c} b={b} e={e} Nx={nx}, declared "
                            f"c={dev.c} b={dev.b} e={dev.e} Nx={dev.nx}")
        if name not in senses or senses[name][1] != dev.c.lower():
            problems.append(f"{cand.name}/{name}: no collector sense source vic_{name} <net> {dev.c} 0")
    return problems


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------


@dataclass
class ParsedDeck:
    runs: dict[str, dict[str, float]]
    complete: bool
    problems: list[str]
    messages: dict[str, int]


def parse_log(text: str) -> ParsedDeck:
    """Split a deck log into per-run ``mf_`` values. Never guesses: a run
    without its MFEND marker, a value printed twice, or a value outside any
    run is a problem, not data."""
    runs: dict[str, dict[str, float]] = {}
    problems: list[str] = []
    messages: dict[str, int] = {}
    current = None
    began = complete = False
    ended: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "MF_DECK_BEGIN":
            began = True
            continue
        if line == "MF_DECK_END":
            complete = True
            continue
        if line.startswith("MFRUN "):
            rid = line.split(None, 1)[1]
            if rid in runs:
                problems.append(f"run {rid} appears twice in the log")
            if current is not None:
                problems.append(f"run {current} has no MFEND marker")
            runs[rid] = {}
            current = rid
            continue
        if line.startswith("MFEND "):
            rid = line.split(None, 1)[1]
            if rid != current:
                problems.append(f"MFEND {rid} does not close the open run {current}")
            else:
                ended.add(rid)
            current = None
            continue
        if _MESSAGE_RE.match(line):
            key = re.sub(r"[-+]?\d+(\.\d+)?(e[-+]?\d+)?", "#", line.lower())[:120]
            messages[key] = messages.get(key, 0) + 1
            continue
        m = _VALUE_RE.match(line)
        if m:
            name = m.group(1).lower()
            if current is None:
                problems.append(f"value {name} printed outside any run")
                continue
            if name in runs[current]:
                problems.append(f"run {current}: {name} printed twice")
            runs[current][name] = float(m.group(2))
    if current is not None:
        problems.append(f"run {current} has no MFEND marker (truncated log?)")
    if not began:
        problems.append("deck never started (no MF_DECK_BEGIN)")
    if not complete:
        problems.append("deck did not finish (no MF_DECK_END)")
    for rid in runs:
        if rid not in ended:
            problems.append(f"run {rid} incomplete")
    return ParsedDeck(runs=runs, complete=complete and began, problems=problems, messages=messages)


# ---------------------------------------------------------------------------
# Per-run analysis
# ---------------------------------------------------------------------------


def classify_stress(devices: tuple[Device, ...], values: dict[str, float],
                    limits: StressLimits) -> dict:
    """Per-device DC / startup / retained extrema and every limit violation.

    A violation in an interval listed in ``limits.reject_intervals`` makes the
    run a REJECTED outcome (``stress_ok`` False); violations in other
    intervals are recorded as flags. Nothing is averaged away."""
    table = []
    violations = []
    for dev in devices:
        ic_max = limits.ic_a_per_nx * dev.nx
        row = {"device": dev.name, "nx": dev.nx, "ic_limit_a": ic_max}
        for iv, prefix in (("dc", "dc"), ("startup", "su"), ("retained", "ss")):
            for q in STRESS_QTYS:
                if iv == "dc":
                    lo = hi = values.get(f"mf_dc_{q}_{dev.name}")
                else:
                    lo = values.get(f"mf_{prefix}_{q}min_{dev.name}")
                    hi = values.get(f"mf_{prefix}_{q}max_{dev.name}")
                row[f"{iv}_{q}_min"], row[f"{iv}_{q}_max"] = lo, hi
                if lo is None or hi is None or not (math.isfinite(lo) and math.isfinite(hi)):
                    violations.append({"device": dev.name, "interval": iv, "quantity": q,
                                       "kind": "missing", "value": None, "limit": None})
                    continue
                if q == "vce":
                    bounds = limits.vce_v
                elif q == "vbe":
                    bounds = limits.vbe_v
                else:
                    bounds = (None, ic_max)
                if bounds[0] is not None and lo < bounds[0]:
                    violations.append({"device": dev.name, "interval": iv, "quantity": q,
                                       "kind": "below", "value": lo, "limit": bounds[0]})
                if q == "ic" and hi >= bounds[1] or q != "ic" and hi > bounds[1]:
                    violations.append({"device": dev.name, "interval": iv, "quantity": q,
                                       "kind": "above", "value": hi, "limit": bounds[1]})
        table.append(row)
    rejecting = [v for v in violations if v["interval"] in limits.reject_intervals or v["kind"] == "missing"]
    return {"table": table, "violations": violations, "rejecting": rejecting,
            "stress_ok": not rejecting}


def analyze_run(run: RunSpec, values: dict[str, float], devices: tuple[Device, ...],
                limits: StressLimits, *, abs_floor_dbm: float = -140.0,
                floor_margin_db: float = 10.0, sink_nodes: tuple[str, ...] = ()) -> dict:
    """Turn one run's raw values into measured quantities.

    Returns a dict with ``status``: "ok" (all values present and finite,
    stress valid), "rejected_stress" (complete data, a device outside the
    limits in a rejecting interval -- an explicit scientific outcome), or
    "invalid" (missing / nonfinite / incoherent data -- never evidence)."""
    out: dict = {"run_id": run.run_id, "kind": run.kind, "band": run.band.name,
                 "vlo_dbm": run.vlo_dbm, "rf_dbm": run.rf_dbm, "problems": []}
    missing = [k for k in run_keys(run, devices, sink_nodes) if k not in values]
    nonfinite = [k for k, v in values.items() if not math.isfinite(v)]
    if missing:
        out["problems"].append("missing " + ",".join(missing[:8]) + (" ..." if len(missing) > 8 else ""))
    if nonfinite:
        out["problems"].append("nonfinite " + ",".join(sorted(nonfinite)[:8]))
    if not missing and "mf_n" not in nonfinite and int(round(values["mf_n"])) != run.n_samples:
        out["problems"].append(f"retained window holds {values['mf_n']:.0f} samples, expected {run.n_samples}")
    out["problems"] += coherence_problems(run)
    if out["problems"]:
        out["status"] = "invalid"
        return out
    amp = {name: math.hypot(values[f"mf_{name}_re"], values[f"mf_{name}_im"]) for name in run.bins()}

    def p_dbm(name):
        return dbm(delivered_power_w(amp[name], Z0_OHM))

    out.update({
        "f1_hz": run.tones[0], "f2_hz": run.tones[1], "flo_hz": run.tones[2],
        "window_s": run.window_s, "settle_s": run.settle_s, "tmax_s": run.tmax_s,
        "tstep_s": run.tstep_s, "n_samples": run.n_samples, "resolution_hz": run.resolution_hz,
        "bins_hz": {name: f for name, (_, f) in run.bins().items()},
        "lo_avail_dbm": run.vlo_dbm,
        "lo_vdiff_open_peak_v": run.vlo_open_peak,
        "lo_vdiff_loaded_peak_v": amp["lodiff"],
        "rail_power_mw": values["mf_prail"] * 1e3,
        "dc_rail_power_mw": None,
        "ideal_sink_v": {node: {"dc": values[f"mf_dc_sink_{node}"],
                                "startup_min": values[f"mf_su_sinkmin_{node}"],
                                "retained_min": values[f"mf_ss_sinkmin_{node}"]} for node in sink_nodes},
    })
    # Extraction floor of each quantity: the larger of the strongest nearby
    # empty bin (settling residue, numerical noise of THIS run) and the
    # declared absolute resolution floor.
    floors = {}
    for qty, names in run.floor_bins().items():
        floors[qty] = max([abs_floor_dbm] + [p_dbm(n) for n in names])
    out["floor_dbm"] = floors
    out["floor_margin_db"] = floor_margin_db
    if run.kind in ("single", "rfoff"):
        out["lo_if_dbm"] = p_dbm("loif")
        out["lo_rf_dbm"] = p_dbm("lorf")
        # "resolved" = clear of the floor by the margin; otherwise the value
        # is only an upper bound (report "<= floor + margin").
        out["resolved"] = {"loif": out["lo_if_dbm"] >= floors["loif"] + floor_margin_db,
                           "lorf": out["lo_rf_dbm"] >= floors["lorf"] + floor_margin_db}
    if run.kind == "single":
        out["p_if_dbm"] = p_dbm("if")
        out["gain_db"] = out["p_if_dbm"] - run.rf_dbm
        out["resolved"]["if"] = out["p_if_dbm"] >= floors["if"] + floor_margin_db
        if not out["resolved"]["if"]:
            out["problems"].append("IF fundamental not clear of the extraction floor")
            out["status"] = "invalid"
            return out
    if run.kind == "two_tone":
        out.update({"p_if1_dbm": p_dbm("if1"), "p_if2_dbm": p_dbm("if2"),
                    "p_im3l_dbm": p_dbm("im3l"), "p_im3h_dbm": p_dbm("im3h")})
    stress = classify_stress(devices, values, limits)
    out["stress"] = stress
    out["stress_ok"] = stress["stress_ok"]
    out["status"] = "ok" if stress["stress_ok"] else "rejected_stress"
    return out


def with_dc_power(result: dict, values: dict[str, float], vdd: float) -> dict:
    if "mf_dcirail" in values and math.isfinite(values["mf_dcirail"]):
        result["dc_rail_power_mw"] = vdd * values["mf_dcirail"] * 1e3
    return result


def small_signal_check(g_main_db: float | None, g_check_db: float | None, tol_db: float) -> dict:
    """RF -60 dBm vs -66 dBm gain agreement (issue #35: <= 0.2 dB)."""
    if g_main_db is None or g_check_db is None or not (math.isfinite(g_main_db) and math.isfinite(g_check_db)):
        return {"ok": None, "delta_db": None}
    d = g_main_db - g_check_db
    return {"ok": abs(d) <= tol_db, "delta_db": d}


# ---------------------------------------------------------------------------
# LO-drive selection
# ---------------------------------------------------------------------------


def select_lo_drive(points: list[dict], bands: list[str], drives: list[float], *,
                    plateau_db: float = 0.5, run_length: int = 3) -> dict:
    """Issue #35 selection rule.

    ``points``: one dict per (band, drive) with keys band, drive_dbm,
    status ("ok" | "rejected_stress" | anything else = missing/invalid),
    gain_db, ss_ok (small-signal check passed).

    A point QUALIFIES at its band if it is stress-valid, passes the
    small-signal check, and its gain is within ``plateau_db`` of that band's
    maximum stress-valid gain. The selected drive is the LOWEST drive that
    starts a run of ``run_length`` consecutive declared drives qualifying at
    EVERY band. Outcomes: ``selected`` / ``no acceptable drive in declared
    sweep`` / ``inconclusive`` (any missing or invalid point -- never a
    guessed optimum)."""
    by = {}
    for p in points:
        key = (p["band"], float(p["drive_dbm"]))
        if key in by:
            return {"status": "inconclusive", "reason": f"duplicate point {key}", "per_band": {}}
        by[key] = p
    missing = [(b, d) for b in bands for d in drives
               if (b, d) not in by or by[(b, d)].get("status") not in ("ok", "rejected_stress")
               or (by[(b, d)].get("status") == "ok" and not _finite(by[(b, d)].get("gain_db")))]
    if missing:
        return {"status": "inconclusive",
                "reason": "missing or invalid sweep points: " + ", ".join(f"{b}@{d:g}dBm" for b, d in missing[:10]),
                "per_band": {}}
    per_band = {}
    qualifies = {}
    for b in bands:
        valid = [by[(b, d)] for d in drives if by[(b, d)]["status"] == "ok"]
        if not valid:
            per_band[b] = {"max_valid_gain_db": None, "qualifying_dbm": [],
                           "reason": "no stress-valid point at this band"}
            for d in drives:
                qualifies[(b, d)] = False
            continue
        gmax = max(p["gain_db"] for p in valid)
        q = []
        for d in drives:
            p = by[(b, d)]
            ok = p["status"] == "ok" and bool(p.get("ss_ok")) and p["gain_db"] >= gmax - plateau_db
            qualifies[(b, d)] = ok
            if ok:
                q.append(d)
        per_band[b] = {"max_valid_gain_db": gmax, "qualifying_dbm": q}
    for i in range(len(drives) - run_length + 1):
        window = drives[i:i + run_length]
        if all(qualifies[(b, d)] for b in bands for d in window):
            return {"status": "selected", "drive_dbm": drives[i], "run_dbm": list(window),
                    "per_band": per_band}
    failing = [b for b in bands
               if not any(all(qualifies[(b, d)] for d in drives[i:i + run_length])
                          for i in range(len(drives) - run_length + 1))]
    reason = ("no common run of %d qualifying drives across bands" % run_length if not failing else
              "no run of %d qualifying drives at band(s) %s" % (run_length, ", ".join(failing)))
    return {"status": "no acceptable drive in declared sweep", "reason": reason, "per_band": per_band}


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


# ---------------------------------------------------------------------------
# IIP3 from a swept two-tone power sweep
# ---------------------------------------------------------------------------


def _linfit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Least squares y = a + s x; returns (a, s, max |residual|)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    s = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - s * mx
    res = max(abs(y - (a + s * x)) for x, y in zip(xs, ys))
    return a, s, res


def fit_iip3(points: list[dict], *, slope_fund=(0.9, 1.1), slope_im3=(2.7, 3.3), min_points=3,
             floor_margin_db=10.0, compression_db=1.0, max_residual_db=0.5) -> dict:
    """IIP3 only from a verified 1:3-slope region (spec/porting-plan.md 4.1).

    ``points``: per input power step (per-tone available power ``pin_dbm``):
    p_if1_dbm, p_if2_dbm, p_im3l_dbm, p_im3h_dbm, floor_dbm, status.
    Pairing: the low IM3 sideband (2f1-f2) with the f1 fundamental, the high
    sideband (2f2-f1) with f2. For each sideband the LONGEST contiguous run
    (ties: lowest power) of at least ``min_points`` steps is used in which:
    every step is status ok and finite, IM3 is at least ``floor_margin_db``
    above the extraction floor, the conversion gain is within
    ``compression_db`` of the lowest-power step's gain (below compression),
    and the least-squares slopes are 1 +/- 0.1 (fundamental) and 3 +/- 0.3
    (IM3) with residuals <= ``max_residual_db``. The intercept is the
    intersection of the two fitted lines; the reported (conservative) IIP3 is
    the lower of the two sidebands. Otherwise ``IIP3 unavailable`` with the
    reason -- never a single-point or below-floor extrapolation."""
    pts = sorted(points, key=lambda p: p["pin_dbm"])
    if len(pts) < min_points:
        return {"status": "IIP3 unavailable", "reason": f"only {len(pts)} power step(s); need >= {min_points}"}
    ref_gain = None
    for p in pts:
        if p.get("status") == "ok" and _finite(p.get("p_if1_dbm")):
            ref_gain = p["p_if1_dbm"] - p["pin_dbm"]
            break
    sidebands = {}
    for side, fund_key, im3_key in (("low", "p_if1_dbm", "p_im3l_dbm"), ("high", "p_if2_dbm", "p_im3h_dbm")):
        usable = []
        reasons = {}
        for p in pts:
            why = None
            if p.get("status") != "ok":
                why = f"status {p.get('status')}"
            elif not all(_finite(p.get(k)) for k in (fund_key, im3_key, "floor_dbm")):
                why = "nonfinite/missing value"
            elif p[im3_key] < p["floor_dbm"] + floor_margin_db:
                why = "IM3 below extraction floor + margin"
            elif ref_gain is not None and (p[fund_key] - p["pin_dbm"]) < ref_gain - compression_db:
                why = "compressed"
            usable.append(why is None)
            if why:
                reasons[p["pin_dbm"]] = why
        best = None
        n = len(pts)
        for i in range(n):
            for j in range(i + min_points, n + 1):
                if not all(usable[i:j]):
                    break
                seg = pts[i:j]
                xs = [p["pin_dbm"] for p in seg]
                a1, s1, r1 = _linfit(xs, [p[fund_key] for p in seg])
                a3, s3, r3 = _linfit(xs, [p[im3_key] for p in seg])
                if not (slope_fund[0] <= s1 <= slope_fund[1] and slope_im3[0] <= s3 <= slope_im3[1]):
                    continue
                if max(r1, r3) > max_residual_db:
                    continue
                cand = {"interval_dbm": [xs[0], xs[-1]], "n_points": len(seg), "slope_fund": s1,
                        "slope_im3": s3, "residual_fund_db": r1, "residual_im3_db": r3,
                        "iip3_dbm": (a1 - a3) / (s3 - s1),
                        "per_point_iip3_dbm": [x + (p[fund_key] - p[im3_key]) / 2 for x, p in zip(xs, seg)]}
                if best is None or cand["n_points"] > best["n_points"]:
                    best = cand
        if best is None:
            sidebands[side] = {"status": "IIP3 unavailable",
                               "reason": "no contiguous run of >= %d steps with slopes 1+/-0.1 and 3+/-0.3 "
                                         "above the floor and below compression" % min_points,
                               "excluded_steps": reasons}
        else:
            sidebands[side] = dict(best, status="ok", excluded_steps=reasons)
    ok = [s for s in sidebands.values() if s["status"] == "ok"]
    if len(ok) < 2:
        bad = [k for k, s in sidebands.items() if s["status"] != "ok"]
        return {"status": "IIP3 unavailable", "reason": f"no valid 1:3 region for the {', '.join(bad)} "
                f"IM3 sideband(s)", "sidebands": sidebands}
    return {"status": "ok", "iip3_dbm": min(s["iip3_dbm"] for s in ok), "sidebands": sidebands,
            "convention": "per-tone available input power at the 50 ohm RF port; lower of the two "
                          "sidebands' line intersections"}


# ---------------------------------------------------------------------------
# Convergence control
# ---------------------------------------------------------------------------


def compare_converged(name: str, base_dbm: float, other_dbm: float, floor_dbm: float, *,
                      tol_db: float, floor_margin_db: float) -> dict:
    """Agreement of one quantity between the baseline and a refined run.

    Above floor + margin in BOTH runs: |delta| <= tol_db. At or below the
    floor in BOTH runs: agreement is "both at floor" (the quantity is below
    what the extraction resolves; reported as an upper bound). Anything
    else (one above, one below) is a failure."""
    vals = (base_dbm, other_dbm, floor_dbm)
    if not all(isinstance(v, float) and not math.isnan(v) for v in vals):
        return {"quantity": name, "ok": False, "reason": "missing/NaN value"}
    above = [v >= floor_dbm + floor_margin_db for v in (base_dbm, other_dbm)]
    if all(above):
        d = other_dbm - base_dbm
        return {"quantity": name, "ok": abs(d) <= tol_db, "delta_db": d,
                "reason": "" if abs(d) <= tol_db else f"|delta| {abs(d):.3f} dB > {tol_db} dB"}
    if not any(above):
        return {"quantity": name, "ok": True, "delta_db": None, "reason": "both at extraction floor"}
    return {"quantity": name, "ok": False, "delta_db": other_dbm - base_dbm,
            "reason": "above floor in one run and not the other"}


# ---------------------------------------------------------------------------
# Analytic control expectations
# ---------------------------------------------------------------------------


def analytic_expectations(params: dict, run: RunSpec) -> dict[str, float]:
    """Closed forms for testbench/control_analytic_multiplier.spice (see its
    header): V(if_out) = 0.5 [k v_rf v_lo + k3 v_rf^3 v_lo + c v_lo] and
    V(rf_port) at flo = 50 g v_lo (RF source off)."""
    k, k3, c, g = (float(params[x]) for x in ("ac_k", "ac_k3", "ac_c", "ac_g"))
    vlo = run.vlo_open_peak
    out = {}
    if run.kind in ("single", "rfoff"):
        out["lo_if_dbm"] = dbm(delivered_power_w(0.5 * abs(c) * vlo, Z0_OHM))
    if run.kind == "rfoff":
        out["lo_rf_dbm"] = dbm(delivered_power_w(Z0_OHM * g * vlo, Z0_OHM))
        return out
    a, _ = run.vrf_open_peak
    if run.kind == "single":
        amp = 0.25 * vlo * abs(k * a + k3 * 0.75 * a ** 3)
        out["p_if_dbm"] = dbm(delivered_power_w(amp, Z0_OHM))
        out["gain_db"] = out["p_if_dbm"] - run.rf_dbm
        return out
    fund = 0.25 * vlo * abs(k * a + k3 * 2.25 * a ** 3)
    im3 = 0.25 * vlo * abs(k3) * 0.75 * a ** 3
    out.update({"p_if1_dbm": dbm(delivered_power_w(fund, Z0_OHM)),
                "p_if2_dbm": dbm(delivered_power_w(fund, Z0_OHM)),
                "p_im3l_dbm": dbm(delivered_power_w(im3, Z0_OHM)),
                "p_im3h_dbm": dbm(delivered_power_w(im3, Z0_OHM))})
    return out


def interp_bound_db(freq_hz: float, dt: float) -> float:
    """Worst-case power error (dB, positive) of a sine of frequency ``freq_hz``
    read through ngspice ``linearize``: the simulator's own time points are
    not on the resampling grid (breakpoints add points), so samples are
    LINEAR interpolations between points <= dt apart, which attenuates the
    amplitude by at most (2 pi f dt)^2 / 8. Negligible at the 1 GHz IF
    (4e-6 dB at 1 ps), ~0.015 dB at 18-21 GHz; bounded again, empirically,
    by the halved-timestep convergence control."""
    x = (2.0 * math.pi * freq_hz * dt) ** 2 / 8.0
    return -20.0 * math.log10(1.0 - x)


def quantity_freq_hz(run: RunSpec, key: str) -> float:
    """The frequency at which a reported quantity is extracted."""
    f1, f2, flo = run.tones
    return {"lo_if_dbm": flo, "lo_rf_dbm": flo, "p_if_dbm": f1 - flo, "gain_db": f1 - flo,
            "p_if1_dbm": f1 - flo, "p_if2_dbm": f2 - flo, "p_im3l_dbm": 2 * f1 - f2 - flo,
            "p_im3h_dbm": 2 * f2 - f1 - flo}[key]


def analytic_iip3_dbm(params: dict) -> float:
    """Small-signal intercept of the control: k a = |k3| (3/4) a^3."""
    k, k3 = float(params["ac_k"]), float(params["ac_k3"])
    a2 = 4.0 * k / (3.0 * abs(k3))
    return dbm(a2 / (8.0 * Z0_OHM))


# ---------------------------------------------------------------------------
# Declared cells, collection gate, conclusion
# ---------------------------------------------------------------------------


def cell_id(**kw) -> str:
    """Stable identity of one declared cell."""
    order = ("matrix", "candidate", "corner", "temp_c", "vdd_v", "band", "drive_dbm", "rf_dbm", "pin_dbm")
    parts = []
    for key in order:
        if key in kw and kw[key] is not None:
            v = kw[key]
            parts.append(f"{key}={v:g}" if isinstance(v, float) else f"{key}={v}")
    return "|".join(parts)


def expected_cells(study: Study) -> list[dict]:
    """Every cell the full study must account for (main gain/stress/power,
    mismatch leakage, LO-selection sweep, IIP3 sweep), per candidate."""
    cells = []
    for cand in study.candidates:
        m = study.matrices["main"]
        for corner in m.corners:
            for t in m.temperatures_c:
                for v in m.supplies_v:
                    for b in m.bands:
                        cells.append(dict(matrix="main", candidate=cand.name, corner=corner, temp_c=t,
                                          vdd_v=v, band=b))
        m = study.matrices["leakage"]
        for corner in m.corners:
            for t in m.temperatures_c:
                for v in m.supplies_v:
                    for b in m.bands:
                        cells.append(dict(matrix="leakage", candidate=cand.name, corner=corner, temp_c=t,
                                          vdd_v=v, band=b, seed=m.seed))
        m = study.matrices["lo_select"]
        for corner in m.corners:
            for t in m.temperatures_c:
                for v in m.supplies_v:
                    for b in m.bands:
                        for d in study.lo_sweep_dbm:
                            for rf in (study.rf_dbm, study.rf_check_dbm):
                                cells.append(dict(matrix="lo_select", candidate=cand.name, corner=corner,
                                                  temp_c=t, vdd_v=v, band=b, drive_dbm=d, rf_dbm=rf))
        m = study.matrices["iip3"]
        for corner in m.corners:
            for t in m.temperatures_c:
                for v in m.supplies_v:
                    for b in m.bands:
                        for p in study.iip3_pin_dbm:
                            cells.append(dict(matrix="iip3", candidate=cand.name, corner=corner, temp_c=t,
                                              vdd_v=v, band=b, pin_dbm=p))
    for c in cells:
        c["id"] = cell_id(**{k: v for k, v in c.items() if k != "seed"})
    return cells


#: Values an "ok" cell of each matrix must carry (finite).
REQUIRED_CELL_KEYS = {
    "main": ("gain_db", "rail_power_mw", "dc_rail_power_mw", "lo_vdiff_loaded_peak_v"),
    "leakage": ("lo_rf_dbm", "lo_if_dbm", "lo_vdiff_loaded_peak_v"),
    "lo_select": ("gain_db", "lo_vdiff_loaded_peak_v"),
    "iip3": ("p_if1_dbm", "p_if2_dbm", "p_im3l_dbm", "p_im3h_dbm"),
}

#: Scientific outcomes a cell may carry. Anything else is a corrupt run.
CELL_STATUSES = ("ok", "rejected_stress", "not_applicable_no_drive")


#: Matrices whose cells exist only at a selected LO drive.
DRIVE_DEPENDENT_MATRICES = ("main", "leakage", "iip3")


def selection_from_cells(study: Study, cells: list[dict], cand_name: str) -> dict:
    """Re-derive one candidate's LO-drive selection from its collected
    lo_select cells (rf main/check pairs per band and drive), exactly as the
    collector pairs them. Missing, duplicate or non-measured points make the
    selection ``inconclusive``."""
    by: dict = {}
    dup = False
    for c in cells:
        if c.get("matrix") == "lo_select" and c.get("candidate") == cand_name:
            key = (c.get("band"), c.get("drive_dbm"), c.get("rf_dbm"))
            dup = dup or key in by
            by[key] = c
    if dup:
        return {"status": "inconclusive", "reason": "duplicate lo_select cells"}
    points = []
    for b in study.matrices["lo_select"].bands:
        for d in study.lo_sweep_dbm:
            main, chk = by.get((b, d, study.rf_dbm)), by.get((b, d, study.rf_check_dbm))
            if main is None or chk is None:
                points.append({"band": b, "drive_dbm": d, "status": "missing"})
                continue
            ss = small_signal_check(main.get("gain_db"), chk.get("gain_db"), study.small_signal_tol_db)
            status = main.get("status")
            if status == "ok" and chk.get("status") != "ok":
                status = chk.get("status")
            points.append({"band": b, "drive_dbm": d, "status": status, "gain_db": main.get("gain_db"),
                           "ss_ok": ss["ok"]})
    return select_lo_drive(points, list(study.matrices["lo_select"].bands), list(study.lo_sweep_dbm),
                           plateau_db=study.plateau_db, run_length=study.plateau_run)


def validate_collection(study: Study, cells: list[dict]) -> list[str]:
    """Acceptance gate for a collected comparison: returns problems (empty =
    acceptable). A corrupt or incomplete collection must not become a record.

    Checks: every declared cell present exactly once and nothing undeclared;
    every cell a declared scientific status; "ok" cells carry every required
    value, finite; stress classification consistent with the recorded
    violations ("ok" with a rejecting violation, or "rejected_stress" with
    none, is a classification error); each cell's recorded model section is
    its own corner; leakage cells carry the declared seed; and the process
    axis actually moves the main-matrix gain (the sabotage control: corners
    forced to typical collapse it).

    ``not_applicable_no_drive`` is accepted only for drive-dependent matrices
    (main, leakage, iip3) and only for a candidate whose LO selection,
    re-derived from its own lo_select cells, is a definite "no acceptable
    drive"; lo_select cells must be measured or stress-rejected, and a
    candidate with a selected drive must have its dependent cells simulated.
    A missing/inconclusive selection never licenses a skip."""
    problems = []
    expected = {c["id"]: c for c in expected_cells(study)}
    seen: dict[str, int] = {}
    for cell in cells:
        cid = cell.get("id")
        seen[cid] = seen.get(cid, 0) + 1
    for cid, n in sorted(seen.items(), key=lambda x: str(x[0])):
        if n > 1:
            problems.append(f"duplicate cell {cid} ({n}x)")
        if cid not in expected:
            problems.append(f"undeclared cell {cid}")
    for cid in expected:
        if cid not in seen:
            problems.append(f"missing cell {cid}")
    selections: dict[str, dict] = {}
    for cell in cells:
        cid = cell.get("id")
        if cid not in expected:
            continue
        decl = expected[cid]
        status = cell.get("status")
        if status not in CELL_STATUSES:
            problems.append(f"{cid}: status {status!r} is not a scientific outcome (corrupt run)")
            continue
        cand_name = decl["candidate"]
        if decl["matrix"] == "lo_select":
            if status == "not_applicable_no_drive":
                problems.append(f"{cid}: lo_select cells establish whether a drive exists and must be "
                                "measured or rejected_stress, never not_applicable_no_drive")
        else:
            if cand_name not in selections:
                selections[cand_name] = selection_from_cells(study, cells, cand_name)
            sel = selections[cand_name]
            if status == "not_applicable_no_drive":
                if sel["status"] == "selected":
                    problems.append(f"{cid}: not_applicable_no_drive but {cand_name} has a selected drive "
                                    f"({sel['drive_dbm']:g} dBm)")
                elif sel["status"] == "inconclusive":
                    problems.append(f"{cid}: not_applicable_no_drive without a validated selection outcome "
                                    f"for {cand_name} ({sel.get('reason')})")
            elif sel["status"] != "selected":
                problems.append(f"{cid}: {cand_name} has no selected drive ({sel['status']}) but the cell "
                                f"carries status {status!r}")
        if cell.get("model_section") != decl["corner"]:
            problems.append(f"{cid}: simulated with model section {cell.get('model_section')!r}, "
                            f"declared {decl['corner']!r}")
        if decl["matrix"] == "leakage" and cell.get("seed") != decl.get("seed"):
            problems.append(f"{cid}: mismatch seed {cell.get('seed')!r}, declared {decl.get('seed')!r}")
        violations = (cell.get("stress") or {}).get("rejecting")
        if status in ("ok", "rejected_stress"):
            if violations is None:
                problems.append(f"{cid}: no stress classification recorded")
            elif status == "ok" and violations:
                problems.append(f"{cid}: status ok but {len(violations)} rejecting stress violation(s)")
            elif status == "rejected_stress" and not violations:
                problems.append(f"{cid}: rejected_stress without any recorded violation")
        if status == "ok":
            for key in REQUIRED_CELL_KEYS[decl["matrix"]]:
                v = cell.get(key)
                if not _finite(v):
                    problems.append(f"{cid}: required value {key} missing or nonfinite ({v!r})")
    # sabotage / wrong-corner detection on the process axis
    groups: dict[tuple, list[float]] = {}
    for cell in cells:
        if cell.get("matrix") == "main" and _finite(cell.get("gain_db")):
            key = (cell["candidate"], cell.get("temp_c"), cell.get("vdd_v"), cell.get("band"))
            groups.setdefault(key, []).append(cell["gain_db"])
    multi = [g for g in groups.values() if len(g) >= 2]
    if multi and all(max(g) - min(g) < 1e-9 for g in multi):
        problems.append("process corners do not move the main-matrix gain anywhere: corner switching "
                        "is not taking effect (typical forced?)")
    return problems


def main_cell_problems(study: Study, cand_name: str, main: list[dict]) -> list[str]:
    """Exact-identity and measurement check of one candidate's main cells:
    each declared main cell present exactly once, nothing foreign, status
    ok/rejected_stress, "ok" cells carry finite required values and no
    rejecting violation, rejected cells carry one."""
    expected = {c["id"] for c in expected_cells(study) if c["matrix"] == "main" and c["candidate"] == cand_name}
    problems = []
    seen: dict = {}
    for c in main:
        seen[c.get("id")] = seen.get(c.get("id"), 0) + 1
    for cid, n in sorted(seen.items(), key=lambda x: str(x[0])):
        if n > 1:
            problems.append(f"duplicate main cell {cid} ({n}x)")
        if cid not in expected:
            problems.append(f"foreign main cell {cid}")
    problems += [f"missing main cell {cid}" for cid in sorted(expected) if cid not in seen]
    for c in main:
        if c.get("id") not in expected:
            continue
        cid, status = c["id"], c.get("status")
        if status not in ("ok", "rejected_stress"):
            problems.append(f"{cid}: main cell status {status!r}")
            continue
        violations = (c.get("stress") or {}).get("rejecting")
        if violations is None:
            problems.append(f"{cid}: no stress classification recorded")
        elif status == "ok" and violations:
            problems.append(f"{cid}: status ok with rejecting violation(s)")
        elif status == "rejected_stress" and not violations:
            problems.append(f"{cid}: rejected_stress without violation")
        if status == "ok":
            for key in REQUIRED_CELL_KEYS["main"]:
                if not _finite(c.get(key)):
                    problems.append(f"{cid}: {key} missing or nonfinite ({c.get(key)!r})")
    return problems


def conclude(study: Study, per_candidate: dict) -> dict:
    """Per-candidate verdict and a CONDITIONAL recommendation.

    ``per_candidate[name]``: {"lo_selection": select_lo_drive result,
    "main_cells": [...], "leakage_cells": [...]}. A candidate is
    "feasible (device-level, conditional)" only with a selected drive and
    every main cell stress-valid ("ok"); any rejected cell makes it
    "infeasible at the declared sizing" (stress excursions cannot support a
    model-valid recommendation); missing data makes it "inconclusive". The
    floor is never recommended. Recommendation: the feasible candidate with
    the highest worst-case main-matrix gain, or none."""
    verdicts = {}
    for cand in study.candidates:
        info = per_candidate.get(cand.name)
        if info is None:
            verdicts[cand.name] = {"verdict": "inconclusive", "reason": "no data"}
            continue
        sel = info.get("lo_selection", {})
        if sel.get("status") == "inconclusive":
            verdicts[cand.name] = {"verdict": "inconclusive", "reason": sel.get("reason")}
            continue
        if sel.get("status") != "selected":
            verdicts[cand.name] = {"verdict": "infeasible at the declared sizing",
                                   "reason": sel.get("reason", "no acceptable drive")}
            continue
        main = info.get("main_cells", [])
        if not _finite(sel.get("drive_dbm")):
            verdicts[cand.name] = {"verdict": "inconclusive", "reason": "selected drive missing or nonfinite"}
            continue
        mp = main_cell_problems(study, cand.name, main)
        if mp:
            verdicts[cand.name] = {"verdict": "inconclusive",
                                   "reason": "main-matrix data incomplete or invalid: " + "; ".join(mp[:3])
                                             + (f" (+{len(mp) - 3} more)" if len(mp) > 3 else "")}
            continue
        rejected = [c for c in main if c["status"] == "rejected_stress"]
        if rejected:
            verdicts[cand.name] = {"verdict": "infeasible at the declared sizing",
                                   "reason": f"{len(rejected)}/{len(main)} main cells outside device limits "
                                             "at the selected drive"}
            continue
        worst = min(c["gain_db"] for c in main)
        verdicts[cand.name] = {"verdict": "feasible (device-level, conditional)", "worst_gain_db": worst,
                               "drive_dbm": sel["drive_dbm"]}
    feasible = [(v["worst_gain_db"], name) for name, v in verdicts.items()
                if v["verdict"].startswith("feasible") and study.candidate(name).role == "candidate"]
    if feasible:
        best = max(feasible)[1]
        rec = {"draw_first": best,
               "basis": "highest worst-case device-level conversion gain among candidates with a selected "
                        "drive and no device-limit excursion in any main cell; ideal baluns/passives; "
                        "no spec row claimed"}
    else:
        rec = {"draw_first": None,
               "basis": "no candidate is feasible at its declared sizing within the declared sweep; "
                        "no topology recommendation is forced (route a sizing follow-up or a DR proposal)"}
    return {"verdicts": verdicts, "recommendation": rec}
