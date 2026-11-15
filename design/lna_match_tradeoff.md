# First-stage input-match tradeoff: design note (issue #74)

**Claim: none.** This note reads one ideal-element feasibility record. No
spec row is claimed met by ideal matching. The band (row 1) is OPEN, so
17.7-21.2 GHz is DRAFT here.

- **Evidence:** `sim/lna-match-tradeoff/records/20261010-042556-dae8519.md`
- **Declaration:** `sim/lna-match-tradeoff/STUDY.md` and
  `testbench/study.json`, committed before the record.

## Question

`design/lna_stage1` uses a 50 ohm power match at the band centre. Can any
ideal lossless **input** network on the frozen cascode jointly reach the
screen across the DRAFT band? The cascode's sizing, bias, Rd and output
network all stay as drawn. The screen is:

- NF <= 2.5 dB (row 3);
- S11 <= -10 dB (row 4);
- S21 >= 10 dB per stage (row 2 split over its two stages);
- k > 1 (row 6);
- row 17 operating limits.

## Answer

**No. Input matching alone does not close the first-stage gap.** The
evidence comes in two layers.

**1. The declared family.** 41 two-element lowpass L-sections were tested,
spanning the line from the circuit's power match to its own noise optimum,
plus rings around both ends. **None passes the joint nominal screen.** None
reaches S11 <= -10 dB anywhere on the band. At nominal (hbt_typ, 27 C,
2.5 V), with all values worst over the 71-point band:

| network | NF max (dB) | S11 max (dB) | S21 min (dB) | note |
|---|---|---|---|---|
| baseline (as drawn) | 3.91 | -4.72 | 19.72 | power match at f0 |
| `optr10a180_b` | 1.58 | -2.13 | 17.40 | lowest NF in the family |
| `seg0250_a` | 2.43 | -5.29 | 19.99 | lowest S11 with NF <= 2.5 dB |
| `pmr03a225_a` | 3.34 | -6.01 | 20.33 | best S11 and best joint margin |

Across the 18 in-rail PVT points, every shortlisted network fails at every
point. For the lowest-NF network, the worst values are NF 2.84 dB
(hbt_wcs/125 C/2.25 V) and S11 -1.71 dB (hbt_bcs/-40 C/2.5 V). The core's input Q is about 6.6 at
19.45 GHz (Z_in about 22 - j145 ohm at node in2), and a single L-section
cannot hold a match over the 18 % band.

**2. The network-independent bound.** For ANY lossless reciprocal input
network, the port NF and |S11| depend only on the source reflection that the
network presents to the core at each frequency. From the probe-fitted noise
parameters (model check within 3.2e-6 dB in-rail, 2e-5 dB at the screen
point), the record gives the smallest NF reachable with S11 <= -10 dB, per
frequency and per PVT point:

- **No lossless network can work (8 of 18 in-rail points).** At every
  125 C point (all three processes) and at hbt_wcs/27 C, no lossless input
  network of any order meets the joint screen, at any band frequency. The
  worst point is hbt_wcs/125 C/2.25 V: 3.31 dB.
- **The binding corner (hbt_wcs, 125 C).** The core's own Fmin is
  2.43-2.73 dB across the band. It is above 2.5 dB at the top of the band
  before any matching constraint. That is a property of the core (device
  noise, Rbias, the bias network), not of the input match.
- **The other 10 in-rail points.** A per-frequency feasible point exists,
  but the margin is thin: 0.03 dB at nominal (2.469 dB at 21.2 GHz). A
  realizable network would also have to track it across the band.

So even a perfect, lossless, arbitrarily complex input network cannot meet
the screen at the corners that bind rows 3 and 4.

## Supporting checks (in the record)

- **Baseline reproduction.** The baseline reproduces
  `sim/lna-sparam-nf/records/20261010-012923-6cad7fc` at all 27 shared PVT
  points plus the screen point (17.7 / 19.45 / 21.2 GHz). The worst
  differences are 7e-9 dB in S, 2.5e-10 dB in NF and 4.5e-9 in k.
  - Fixture differences: the input lines are parameterized, Csh2 = 0 is
    added, values are set by `alterparam` + `reset`, and S and NF are
    computed in Python from printed port voltages.
  - These change nothing beyond print precision. A literal-value deck
    confirms the alterparam path exactly (smoke).
- **Normalization control.** A matched 6.02 dB pad reads its closed form
  to 2.6e-6 dB at 27 C and at -40 C. In this bench's convention, where the
  50 ohm load stays noisy, the closed form is F = 1 + (2L - 1) T/T0.
- **Refined-grid control.** The 25 MHz union grid moves no worst-case value
  (delta 0 in every cell). Every worst case falls on a band edge, and the
  edges are dense-grid points. That is the edge detuning the issue warned
  about, and the dense grid captures it. A unit test proves the control
  trips on a hidden mid-grid peak.
- **Fleet vs local.** The nominal unit from the fleet and the local screen
  agree exactly. Both ran ngspice-46 with the same model hash.
- **Stability.** k is unchanged by the lossless input network (min 4.12
  in-rail over 1-100 GHz). |Delta| stays at or below 0.953. Q1 V_CE fails
  row 17 at 6 of the 9 excursion points (2.75 V). They are labelled as the
  excursion, as in the baseline record; the input network does not move
  the DC point.

## What remains contingent

- **Passive loss (#46).** Every network here is lossless. Real input-network
  loss adds to NF dB for dB, so every figure here is optimistic.
- **The band decision (row 1).** The DRAFT band's edges set the worst cases.
  A different ratified band moves them.
- **Second-stage loading and the interstage convention (row 5).** One stage
  into 50 ohm was studied. A second stage adds noise; the screen's 2.5 dB is
  a necessary condition, not a budget. It also changes the load that the
  first stage's output sees.
- **NF convention.** The bench keeps the 50 ohm output load noisy
  (lna-sparam-nf convention). That load adds 0.01-0.3 dB here; the per-cell
  `NF excl. load` column quantifies it. At hbt_wcs/125 C the lowest-NF
  network is still 2.56 dB without the load share.

## The core change (#79): per-variant comparison

Meeting rows 3 and 4 together requires a change to the core, not to the
input network. #79 screened the three candidate classes the section above
named, over this study's own grid and bound, with the input network still
ideal and unsized.

- **Evidence:** `sim/lna-core-variants/records/20261114-031930-fbdf13c.md`
- **Declaration:** `sim/lna-core-variants/STUDY.md` and
  `testbench/variants.json`, committed before the record.
- **Method:** this study's `testbench/study.json` unchanged (grids,
  thresholds, probes, port fixture, NF convention), executed by
  `matchstudy.py`. Only the core netlist differs per variant, so the numbers
  below are comparable with the `core0` row, which reproduces the record
  above to 5.0e-07 dB at all 27 points with the jointly-infeasible counts
  equal.

Worst case over the 18 in-rail PVT points and the 71-point DRAFT band.
"infeasible" counts in-rail points where no lossless input network reaches
NF <= 2.5 dB with S11 <= -10 dB at some band frequency.

| variant | the single change | infeasible | worst NF bound (dB) | Fmin @ hbt_wcs/125 C/2.25 V (dB) | margin @21.2 GHz nominal (dB) | min GT (dB) | min k | max V_CE (V) |
|---|---|---|---|---|---|---|---|---|
| `core0` | none (the frozen core) | 8/18 | 3.307 | 2.43-2.73 | +0.031 | 15.29 | 4.12 | 1.342 |
| `a_le` | (a) Le1 = 54 pH emitter degeneration | 2/18 | 2.885 | 2.45-2.78 | +0.832 | 13.19 | 10.31 | 1.342 |
| `b_jopt` | (b) Rref retuned to Ic(Q1) = 1.70 mA at the binding corner | 9/18 | 3.286 | 2.32-2.58 | -0.011 | 16.56 | 3.37 | 1.333 |
| `b_nx10` | (b) Nx 8 -> 10 at constant current density | 9/18 | 3.257 | 2.19-2.50 | -0.029 | 17.11 | 2.49 | 1.332 |
| `c_rbias` | (c) Rbias 2k -> 10k, base-current compensated | 8/18 | 3.120 | 1.93-2.27 | +0.056 | 16.50 | 3.62 | 1.340 |
| `diag_rbias_noiseless` | diagnostic: Rbias made noiseless | 3/18 | 2.937 | 2.07-2.43 | +0.552 | 15.29 | 4.12 | 1.342 |
| **`ac`** | **(a) + (c): Le1 = 67 pH and Rbias 10k** | **0/18** | **2.459** | **1.98-2.36** | **+1.224** | **13.49** | **9.88** | **1.340** |
| `abc` | (a) + (b, current density) + (c) | 0/18 | 2.370 | 1.90-2.25 | +1.257 | 14.26 | 9.13 | 1.334 |

Row 17 and the card box pass at every in-rail point for every variant, and
every variant holds k > 1, |Delta| < 1 and GT >= 10 dB there, so no variant
buys noise by breaking another row.

**What the comparison says.** Neither (a) nor (c) alone closes the bound,
and they fail for different reasons, which is why their combination does:

- **(a) degeneration moves the optimum but not the floor.** `a_le` lifts the
  nominal margin by 0.8 dB and raises min k from 4.1 to 10.3 -- it brings
  Re(Z_in) at node in2 from ~22 to ~50 ohm, so the power-match and
  noise-match points stop fighting -- but Fmin at the binding corner is
  *unchanged* (2.45-2.78 vs 2.43-2.73 dB). Two 125 C points stay infeasible.
- **(c) a quieter base feed lowers the floor but not the conflict.**
  `c_rbias` drops hot-corner Fmin by ~0.5 dB (2.43-2.73 -> 1.93-2.27 dB) and
  the `diag_rbias_noiseless` diagnostic bounds what the class can ever buy
  (3/18). But the bound stays infeasible at 8 of 18 points, because the
  source reflection that reaches Fmin still cannot also hold S11 <= -10 dB.
- **(b) more current, or more device, is not the answer here.** Both (b)
  variants lower Fmin yet make the bound *worse* (9/18): they widen the gap
  between the noise and power-match points, and `b_nx10` additionally
  detunes the unchanged output network.
- **`ac` closes it; `abc` closes it by more but changes more.** The declared
  rule takes the fewest changes first, so the choice is `ac`: 2.459 dB worst
  in-rail bound against the 2.5 dB screen, a +0.041 dB worst-case margin.

**That margin is thin, and on ideal elements.** 0.041 dB is a necessary
condition met, not a row met: see "What remains contingent" above, which
applies unchanged, plus Le1's own loss and Q (no PDK inductor model exists;
passive qualification is #46). A realizable input network must still track
the feasible region across the band.

## The decision this landed

`design/lna_stage1.sch` now carries the `ac` core change -- `Le1` = 67 pH in
series with Q1's emitter ahead of `Re1`, and `Rbias` 2k -> 10k with the
`Rbr` base-current compensation that holds the nominal Ic(Q1) at 1.563 mA.
`design/lna_stage1.md` records it against the evidence. No spec row text or
value changed, and no row-coverage verdict moved.

**The records of this study and of #74 were both taken on the core as it was
before that change.** They are not superseded by it: each pins the netlist
it ran by sha256 and keeps a byte copy under its own
`netlist-snapshots/<record-id>/`, and their drivers read that pinned copy
(`harness/frozen_dut.py`), so re-running either reproduces its own campaign
rather than silently measuring a different circuit. A campaign of the new
core is a new declaration and a new record.
