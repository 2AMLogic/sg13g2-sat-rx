"""Closed-form fake of the ``klt sim`` logs of the lna-linearity bodies (no simulator).

The 'fake DUT' is the memoryless cubic of the analytic control; its device
excursions grow with the output amplitude so the operating-limit path is
exercised. Everything the real log would carry is emitted in the same
``m_<run>_<name> = value`` form, so parsing and analysis run unmodified."""

from __future__ import annotations

import math

import analysis as A
import linearity as L


def fake_log(plan: dict, key: str, *, a1: float, a3: float, floor_v: float = 1e-7, excursion_per_v: float | None = None,
             quiescent_vce2: float = 1.25, only_variant: str | None = None, im3_scale: float = 1.0) -> str:
    lines = ["ngspice fake log"]
    for run in A.runs_for_key(plan, key):
        rid = run["id"]
        n = int(round(run["window_s"] / run["step_s"]))
        am = L.cubic_tone_amps(a1, a3, run["vs_peak_v"], run["kind"] == "two")
        if "im3l" in am and (only_variant is None or run["variant"] == only_variant):
            am["im3l"] *= im3_scale
            am["im3h"] *= im3_scale
        vals = {f"m_{rid}_n": n, f"m_{rid}_t0": 0.0, f"m_{rid}_t1": 0.0}
        for b in run["bins"]:
            a = am.get(b, floor_v if b.startswith("fl") else 0.0)
            if b.startswith("fl"):
                a = floor_v
            vals[f"m_{rid}_{b}_c"] = a * 0.6
            vals[f"m_{rid}_{b}_s"] = a * 0.8
        if run["monitors"]:
            swing = 0.0 if excursion_per_v is None else excursion_per_v * max(v for k, v in am.items() if not k.startswith("fl"))
            for name, nom in (("vce_q1", 1.25), ("vce_q2", quiescent_vce2), ("vbe_q1", 0.8), ("vbe_q2", 0.8)):
                sw = swing if name.startswith("vce") else 0.0
                vals[f"m_{rid}_{name}_max"] = nom + sw
                vals[f"m_{rid}_{name}_min"] = nom - sw
        for k, v in vals.items():
            lines.append(f"{k} = {v:.12e}")
    lines.append("LNLIN_DONE")
    return "\n".join(lines) + "\n"


def fake_logs(plan: dict, *, a1: float = 10.0, a3: float = -2000.0, **kw) -> dict[str, str]:
    c = plan["controls"]
    out = {}
    for key in A.request_keys(plan):
        if A.split_key(key)[0] == A.CONTROL:
            out[key] = fake_log(plan, key, a1=c["a1"], a3=c["a3"], floor_v=1e-9)
        else:
            out[key] = fake_log(plan, key, a1=a1, a3=a3, **kw)
    return out
