"""Fabricate ngspice stdout for the interface probe from closed form (no simulator).

The fabricated log has exactly the MARK schema ``run_probe.run_block`` makes
ngspice print, so ``cmprobe.parse_log`` / ``build_matrix`` are exercised on the
same text shape a real run produces.
"""

from __future__ import annotations

import cmath
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import cmprobe as C  # noqa: E402

DUT_GW = 0.0576 * cmath.exp(1j * math.radians(177.0))
DUT_GI = 0.0583 * cmath.exp(1j * math.radians(177.0))


def marks(sabotage=None, dut_nonlinear=0.0, settled=True, dut_gw=DUT_GW, dut_gi=DUT_GI) -> dict:
    mk = C.synth_control_marks(sabotage)
    t = C.WINDOW[1] - C.WINDOW[0]
    base_x = 0.3 + 0.1j  # LO-only baseline IF content (not zero: must be subtracted)
    for run, (apu, apl) in C.RUNS.items():
        pu, pl = C.tone_phasor(apu, C.PH_U_DEG), C.tone_phasor(apl, C.PH_L_DEG)
        x = base_x + dut_gw * pu + dut_gi * pl.conjugate()
        if apu == 2 * C.A_TONE:  # compress the 2x run to mimic a nonlinear device
            x = base_x + (dut_gw * pu) * (1 - dut_nonlinear)
        c, s = C.integrals_from_phasor(x, t)
        mk[f"x_dut_{run}_c"], mk[f"x_dut_{run}_s"] = c, s
    for i, (a, b) in enumerate(C.TRAJ_WINDOWS, 1):
        for h, amp in (("f1", 0.145), ("f2", 0.00135)):
            drift = 0.0 if settled else 0.01 * amp * (i - 1)
            c, s = C.integrals_from_phasor(complex(amp + drift, 0.0), b - a)
            mk[f"t_dut_base_w{i}_{h}_c"], mk[f"t_dut_base_w{i}_{h}_s"] = c, s
        mk[f"t_dut_base_w{i}_avg"] = 1.577 + (0.0 if settled else 0.05 * (i - 1))
    return mk


def stdout(mk: dict, pss_missing=True, pnoise_missing=True, done=True) -> str:
    lines = ["MARK ngspice_banner_follows"]
    for k, v in mk.items():
        lines.append(f"MARK {k}={v:.12g}")
    for bias, ic in (("bias_a", 1.0236e-3), ("bias_b", 9.864e-4)):
        lines += [f"MARK N_section_begin={bias}", f"onoise_total = {2.5e-3:.6e}",
                  f"onoise_total_q.xq1.qnpn13g2_ic = {ic:.6e}", f"MARK N_section_end={bias}"]
    lines.append("MARK E_pss_attempt_begin")
    lines.append("pss: no such command available in ngspice" if pss_missing else
                 "Periodic Steady State Analysis Started")
    lines.append("MARK E_pnoise_attempt_begin")
    lines.append("pnoise: no such command available in ngspice" if pnoise_missing else "pnoise started")
    if done:
        lines.append("MARK done")
    return "\n".join(lines) + "\n"
