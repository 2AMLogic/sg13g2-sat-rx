"""Local single-point ngspice execution for lna-match-tradeoff.

Used only for single-corner work that the host rules allow on this machine:
the nominal derivation probe and the smoke/control decks. Each call is ONE
``ngspice -b`` process at ONE PVT point. Every multi-corner run goes through
``klt sim`` (collect.py), never through this module.
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
SIM_DIR = BENCH_DIR.parent
sys.path.insert(0, str(SIM_DIR))

from harness import klt_driver  # noqa: E402
from harness.runner import ngspice_version  # noqa: E402

import matchstudy as ms  # noqa: E402

SCRATCH = BENCH_DIR / "_build"


def pdk():
    return klt_driver.find_pdk_or_exit(SIM_DIR)


def run_point(body: str, process: str, temp_c: float, tag: str, *, timeout_s: int = 1800) -> str:
    """Run one deck (one PVT point) locally; return the log text."""
    p = pdk()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    deck = SCRATCH / f"{tag}.cir"
    deck.write_text(ms.local_deck(body, str(p.model_lib), process, temp_c))
    proc = subprocess.run(["ngspice", "-b", str(deck)], capture_output=True, text=True, timeout=timeout_s)
    text = proc.stdout + "\n" + proc.stderr
    (SCRATCH / f"{tag}.out").write_text(text)
    if proc.returncode != 0:
        raise RuntimeError(f"ngspice exit {proc.returncode} for {deck}; see {SCRATCH / (tag + '.out')}")
    return text


def version() -> str:
    return ngspice_version()


def pad_control(st: ms.Study, temp_c: float) -> dict:
    """Matched 6.02 dB pad behind the thru network at ``temp_c``. In this
    bench's convention (sim/lna-sparam-nf: noiseless reference source, the
    50 ohm output load noisy at the circuit temperature) the closed form is
    F = 1 + (L - 1) T/T0 (pad) + L T/T0 (load referred through the pad)
    = 1 + (2L - 1) T/T0, with T = temp_c + 273.15 K. Also S21 = -L dB,
    S11 and S22 below the declared return-loss floor, on the dense grid, and
    the reported load share must remove exactly the L T/T0 term."""
    thru = st.candidate("probe_thru")
    body = ms.body_text(st, "", [thru], 2.5, title=f"pad control {temp_c:g} C", dut=ms.pad_dut(2.0, st.z0),
                        with_op=False)
    pl = ms.parse_log(run_point(body, st.nominal["process"], temp_c, f"control_pad_{temp_c:g}c"))
    an = ms.analyze_candidate(st, thru, pl.tables.get(thru.name, {}), temp_c)
    loss = 4.0
    t_k = temp_c + 273.15
    nf_exp = 10 * math.log10(1 + (2 * loss - 1) * t_k / st.t0_k)
    nf_excl_exp = 10 * math.log10(1 + (loss - 1) * t_k / st.t0_k)
    s21_exp = -10 * math.log10(loss)
    tol = st.tolerances
    if not an.get("band"):
        return {"ok": False, "problems": an.get("problems") or pl.problems}
    b = an["band"]
    e_nf = max(max(abs(x - nf_exp) for x in b["nf_db"]),
               max(abs(x - nf_excl_exp) for x in b["nf_excl_load_db"]))
    e_s21 = max(abs(x - s21_exp) for x in b["s21_db"])
    rl = max(max(b["s11_db"]), max(b["s22_db"]))
    ok = (e_nf <= tol["control_nf_db"] and e_s21 <= tol["control_s_db"] and rl <= tol["control_return_loss_db"]
          and not pl.problems)
    return {"ok": ok, "temp_c": temp_c, "nf_expected_db": nf_exp, "nf_err_db": e_nf, "s21_expected_db": s21_exp,
            "s21_err_db": e_s21, "return_loss_worst_db": rl, "problems": pl.problems}
