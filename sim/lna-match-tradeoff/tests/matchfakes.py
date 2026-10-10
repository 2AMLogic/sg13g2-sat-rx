"""Closed-form stand-in for the simulator (tests only; no ngspice, no PDK).

A synthetic linear "core" with known S-parameters (50 ohm reference, at
node in2) and known noise parameters (Fmin, Rn, Zopt) is cascaded with each
candidate's ideal L-section analytically (ABCD), and the result is printed in
exactly the ngspice format the study's decks produce (``print`` tables
between LM_BEGIN/LM_END markers, ``m_op_*`` lines). ``FakeKlt`` replaces
``collect.submit`` and writes klt-shaped reports and per-unit logs.
"""

from __future__ import annotations

import cmath
import json
import math
from pathlib import Path

import matchstudy as ms

Z0 = 50.0


def core_s(f: float, process: str = "hbt_typ", temp_c: float = 27.0, vdd: float = 2.5) -> dict:
    """Smooth, stable, non-unilateral synthetic core (S at node in2)."""
    x = (f - 19.45e9) / 19.45e9
    g = {"hbt_typ": 1.0, "hbt_bcs": 1.08, "hbt_wcs": 0.9}[process] * (1 - 0.0005 * (temp_c - 27)) * (vdd / 2.5) ** 0.1
    s11 = 0.91 * cmath.exp(1j * math.radians(-74 - 40 * x))
    s21 = 5.4 * g * cmath.exp(1j * math.radians(100 - 120 * x))
    s12 = 0.004 * cmath.exp(1j * math.radians(60 + 30 * x))
    s22 = 0.35 * cmath.exp(1j * math.radians(-30 - 90 * x))
    return {"s11": s11, "s21": s21, "s12": s12, "s22": s22}


def core_noise(f: float, process: str = "hbt_typ", temp_c: float = 27.0) -> dict:
    x = (f - 19.45e9) / 19.45e9
    fmin = 10 ** ((1.47 + 0.6 * x + 0.004 * (temp_c - 27)) / 10)
    return {"fmin": fmin, "rn": 37.2, "zopt": complex(146 - 120 * x, 100.0)}


def s_to_abcd(s: dict) -> tuple:
    s11, s12, s21, s22 = s["s11"], s["s12"], s["s21"], s["s22"]
    d = 2 * s21
    a = ((1 + s11) * (1 - s22) + s12 * s21) / d
    b = Z0 * ((1 + s11) * (1 + s22) - s12 * s21) / d
    c = ((1 - s11) * (1 - s22) - s12 * s21) / (Z0 * d)
    dd = ((1 - s11) * (1 + s22) + s12 * s21) / d
    return a, b, c, dd


def abcd_to_s(m: tuple) -> dict:
    a, b, c, d = m
    den = a + b / Z0 + c * Z0 + d
    return {"s11": (a + b / Z0 - c * Z0 - d) / den, "s12": 2 * (a * d - b * c) / den,
            "s21": 2 / den, "s22": (-a + b / Z0 - c * Z0 + d) / den}


def mul(m1: tuple, m2: tuple) -> tuple:
    a1, b1, c1, d1 = m1
    a2, b2, c2, d2 = m2
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2, c1 * a2 + d1 * c2, c1 * b2 + d1 * d2)


def network_abcd(c1: float, l: float, c2: float, f: float) -> tuple:
    w = 2 * math.pi * f
    sh1 = (1, 0, 1j * w * c1, 1)
    se = (1, 1j * w * l, 0, 1)
    sh2 = (1, 0, 1j * w * c2, 1)
    return mul(mul(sh1, se), sh2)


def pad_s() -> dict:
    return {"s11": 0j, "s21": 0.5 + 0j, "s12": 0.5 + 0j, "s22": 0j}


def total(cand: ms.Candidate, f: float, process: str, temp_c: float, vdd: float) -> tuple[dict, float]:
    """(overall S, inoise V/rtHz) of network + core at one frequency."""
    s = abcd_to_s(mul(network_abcd(cand.c_sh1, cand.l_in, cand.c_sh2, f), s_to_abcd(core_s(f, process, temp_c, vdd))))
    npar = core_noise(f, process, temp_c)
    gs = ms.gamma(ms.source_impedance(cand, f, Z0), Z0)
    gopt = ms.gamma(npar["zopt"], Z0)
    fl = ms.nf_lin_at(gs, npar["fmin"], npar["rn"] / Z0, gopt)
    return s, math.sqrt((fl - 1) * 4 * ms.K_BOLTZMANN * 300.15 * Z0)


def fmt(x: float) -> str:
    return f"{x:.10e}"


def table(rows: list[list[float]]) -> list[str]:
    out = ["--------------------------------------------------------------------------------",
           "Index   frequency       col1 ...", "--------------------------------------------------------------------------------"]
    for i, r in enumerate(rows):
        out.append("\t".join([str(i)] + [fmt(v) for v in r]) + "\t")
    return out


def op_values(process: str, temp_c: float, vdd: float) -> dict[str, float]:
    vce = 1.243 + 0.8 * (vdd - 2.5) + 0.001 * (temp_c - 27) / 100
    d = {}
    for dev, *_ in ms.DEVICES:
        d.update({f"{dev}_vce": vce if dev != "qr" else 0.81, f"{dev}_vbe": 0.81, f"{dev}_ic": 1.5e-3,
                  f"{dev}_icfrac": 0.065, f"{dev}_dtj": 3.4, f"{dev}_ft": 180.0})
    d.update(idd_ma=2.07 * vdd / 2.5, pdc_mw=5.17 * (vdd / 2.5) ** 2)
    return d


_CACHE: dict = {}


def fake_log(st: ms.Study, names: list[str], process: str, temp_c: float, vdd: float, *,
             nan_in: str | None = None, drop: tuple[str, str] | None = None) -> str:
    key = (id(st), tuple(names), process, temp_c, vdd, nan_in, drop)
    if key not in _CACHE:
        _CACHE[key] = _fake_log(st, names, process, temp_c, vdd, nan_in=nan_in, drop=drop)
    return _CACHE[key]


def _fake_log(st: ms.Study, names: list[str], process: str, temp_c: float, vdd: float, *,
              nan_in: str | None = None, drop: tuple[str, str] | None = None) -> str:
    L = ["Circuit: * klt sim -- fake", "Doing analysis at TEMP = 27"]
    L += [f"m_op_{k} = {fmt(v)}" for k, v in op_values(process, temp_c, vdd).items()]
    grids = {"dense": st.dense_freqs(), "mid": st.mid_freqs(),
             "wide": [st.grid.wide_start_hz * 10 ** (i / st.grid.wide_per_decade) for i in range(st.wide_count())]}
    for n in names:
        c = st.candidate(n)
        sws = ("dense",) if c.role == "probe" else ("dense", "mid", "wide")
        for direction in ("fwd", "rev"):
            for sw in sws:
                rows, nrows = [], []
                for f in grids[sw]:
                    s, inz = total(c, f, process, temp_c, vdd)
                    if direction == "fwd":
                        v1, v2 = (1 + s["s11"]) / 2, s["s21"] / 2
                    else:
                        v1, v2 = s["s12"] / 2, (1 + s["s22"]) / 2
                    rows.append([f, v1.real, v1.imag, v2.real, v2.imag])
                    nrows.append([f, inz])
                if nan_in == n and sw == "dense" and direction == "fwd":
                    rows[3][1] = float("nan")
                for tag, data in ((f"{direction}_{sw}", rows), (f"noise_{sw}", nrows)):
                    if tag.startswith("noise") and direction == "rev" or tag.startswith("noise") and sw == "wide":
                        continue
                    if drop == (n, tag):
                        continue
                    L.append(f"LM_BEGIN {n} {tag}")
                    L += table(data)
                    L.append(f"LM_END {n} {tag}")
    L.append("LM_DONE")
    return "\n".join(L) + "\n"


class FakeKlt:
    """Replacement for ``collect.submit``: writes a klt-shaped report and one
    log per unit, computed in closed form. ``fail_on`` raises like a failed
    batch submit; ``corrupt`` names (key, network) to drop a block."""

    def __init__(self, st: ms.Study, root: Path, *, fail_on: str | None = None, corrupt=None):
        self.st, self.root, self.fail_on, self.corrupt = st, root, fail_on, corrupt
        self.calls: list[dict] = []

    def __call__(self, spec, req: Path, work: Path, args) -> Path:
        import matchcollect as collect  # noqa: PLC0415
        backend = collect.backend_for(spec, args)
        self.calls.append({"key": spec.key, "backend": backend, "units": spec.units,
                           "request": json.loads(req.read_text())})
        if self.fail_on and spec.key.startswith(self.fail_on):
            raise collect.CollectionError(f"klt sim failed for {spec.key} (exit 3, backend {backend}): fake")
        corners = []
        for p in spec.processes:
            for t in spec.temps:
                d = self.root / spec.key / f"{p}_{t:g}C"
                d.mkdir(parents=True, exist_ok=True)
                drop = None
                if self.corrupt and self.corrupt[0] == spec.key:
                    drop = (self.corrupt[1], "fwd_dense")
                (d / "ngspice.log").write_text(fake_log(self.st, spec.networks, p, t, spec.vdd, drop=drop))
                corners.append({"process": p, "temperature_c": t, "status": "pass",
                                "artifacts": {"log": str(d / "ngspice.log")}})
        remote = None if backend.startswith("local") else {
            "provider": "fake-fleet", "job_id": f"klt-sim-fake-{spec.key}", "instance_type": "fake",
            "runner_klt_version": "0.0", "client_klt_version": "0.0", "runner_compatibility": "match"}
        report = work / f"report_{spec.key}.json"
        report.write_text(json.dumps({"status": "pass", "corners": corners,
                                      "environment": {"engine": "ngspice", "engine_version": "46",
                                                      "models_lib_sha256": "0" * 64, "remote": remote},
                                      "provenance": {"klt_version": "fake"}}))
        return report


class Args:
    klt_cmd = "klt"
    backend = "batch"
    screen_backend = "local"
    timeout_s = 60
    no_stage_models = False
    runner_version_check = ""
    workdir = ""
    dry_run = False
    screen_only = False
