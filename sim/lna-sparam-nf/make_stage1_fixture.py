#!/usr/bin/env python3
"""Assemble testbench/lna_stage1.spice from the xschem-exported netlist.

    python3 sim/lna-sparam-nf/make_stage1_fixture.py          # (re)write
    python3 sim/lna-sparam-nf/make_stage1_fixture.py --check  # exit 1 if stale

The harness requires a single netlist fragment (no .include), so the
lna_stage1 subcircuit exported from design/lna_stage1.sch
(design/netlist/lna_stage1.spice, itself derived by design/export_netlist.sh)
is embedded verbatim between BEGIN/END markers; the two-port test fixture
around it is the text below. tests/test_lna_stage1_fixture.py fails if the
embedded copy and the design netlist ever differ.
"""

from __future__ import annotations

import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
REPO = BENCH.parent.parent
SRC = REPO / "design" / "netlist" / "lna_stage1.spice"
DST = BENCH / "testbench" / "lna_stage1.spice"
BEGIN = "* ==== BEGIN design/netlist/lna_stage1.spice (verbatim; do not edit here) ===="
END = "* ==== END design/netlist/lna_stage1.spice ===="

HEADER = """\
* LNA first-stage (lna_stage1) S-parameter / noise-figure two-port fixture (issue #28).
*
* DUT: design/lna_stage1.sch -- npn13G2 cascode (Q1 common-emitter with a small
* emitter resistor, Q2 common-base), diode-mirror bias for Q1, divider bias for
* Q2, ideal lossless L/C input and output matching. Embedded below verbatim
* from design/netlist/lna_stage1.spice (xschem export).
*
* IDEAL / BEHAVIORAL MATCHING: Cshunt, Lin (input) and Lfeed, Cm (output) are
* ideal lossless ngspice L and C. No SG13G2 inductor model exists, so no loss,
* Q, self-resonance or layout parasitic is represented; every S11/S22/S21/NF
* number from this fixture is an upper bound for what a real passive match
* allows and is a FEASIBILITY figure only. Nothing here claims a spec row.
*
* Two-port test method: unchanged from lna_ce_placeholder.spice (power-wave
* injection through a Thevenin Z0 = 50 ohm source per port, forward/reverse by
* alterparam + reset, S = 2*V(port) - 1 for the driven port and 2*V(other)
* for the transmission term; Rs1 noiseless with the source noise added
* analytically at T0 = 300.15 K, issue #22). The DUT has its own DC blocks
* (Cblk_in, Cblk_out), so the ports connect directly.
*
* Ports: p1 = input, p2 = output, vdd = the PVT supply rail (vdd_val).

"""

BENCH_TEXT = """\

.param z0=50
.param mag1=1 mag2=0

Vdd vdd 0 DC {vdd_val}
Xdut p1 p2 vdd 0 lna_stage1

Vs1 s1n 0 DC 0 AC {mag1}
Rs1 s1n p1 {z0} noisy=0

Vs2 s2n 0 DC 0 AC {mag2}
Rs2 s2n p2 {z0}
"""


def build() -> str:
    return HEADER + BEGIN + "\n" + SRC.read_text().rstrip("\n") + "\n" + END + "\n" + BENCH_TEXT


def embedded(text: str) -> str:
    lo = text.index(BEGIN) + len(BEGIN) + 1
    hi = text.index(END)
    return text[lo:hi]


def main(argv=None) -> int:
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    want = build()
    if check:
        have = DST.read_text() if DST.exists() else ""
        if have != want:
            print(f"{DST} is stale vs {SRC}; run make_stage1_fixture.py", file=sys.stderr)
            return 1
        print("lna_stage1 fixture matches design netlist")
        return 0
    DST.write_text(want)
    print(f"wrote {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
