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

## Next circuit decision (identified, not made)

Meeting rows 3 and 4 together requires a change to the core, not to the
input network. One option is inductive emitter degeneration, which
co-locates Gamma_opt with conj(Gamma_in). Others are the device size or
current density at 125 C, and the noise of the Rbias base feed. That
decision is filed separately as #79. This issue changes no schematic, no
spec value and no row-coverage verdict.
