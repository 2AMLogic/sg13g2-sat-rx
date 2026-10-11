# LNA stage 1 — cascode bias / collector-load headroom screening (issue #123)

Status: **stage 1 (single-tone screening) collected; refinement not done.** Evidence:
`sim/lna-headroom/records/20261011-053527-d60e79a.md`. The production schematic and netlist
(`design/lna_stage1*`) are **unchanged**; every variant below is a study deck under
`sim/lna-headroom/variants/`. DUT passives remain IDEAL lossless L/C, the band (row 1) is a draft,
scope is the nominal corner (hbt_typ, 27 C, 2.5 V). No ratified bound (rows 7/8/17, V_CE <= 1.4 V) was
touched and no row is claimed met.

## Question

`design/lna_stage1.md` records a deliberately chosen cascode. The nonlinear campaign
(`sim/lna-linearity/records/20261010-174208-0f67eaf`) could not determine input P1dB inside the device
limits: Q2 V_CE broke 1.4 V from -36 dBm (-34 dBm high placement), 11 dB below the -25 dBm row-8 target.
Do the Q2 divider ratio and the collector damping resistor alone give useful headroom?

## What was done

Twelve predeclared variants (R1b + R2b = 8.5 kohm held; R2b 7.0/7.15/7.3/7.45 kohm; Rd 465/300/200
ohm), with the candidate table, gates, ranking and shortlist rules frozen in
`sim/lna-headroom/testbench/plan.json` before collection. Each ran the baseline's single-tone sweep at the
three placements on the Spot batch fleet (13 klt requests incl. the analytic cubic control, all `pass`).
The committed DUT (C00) reproduced the historical stress cutoff exactly (0.00 mV, 0.000 dB deltas).

## Findings (screening, base timing only)

* **DC allocation.** Q1 + Q2 DC V_CE sum to ~2.4 V, so the divider only moves headroom between the two
  devices. Baseline: V_CE(Q2) = 1.253 V (0.147 V below the limit), V_CE(Q1) = 1.243 V. R2b = 7.3 kohm:
  1.165 / 1.330 V. R2b = 7.45 kohm puts Q1 at 1.374 V DC, which fails the DC-margin gate, and at
  that point the first violation moves to Q1 (V_CE peak), so the bias lever is exhausted at about
  R2b = 7.3 kohm. Bias alone (Rd = 465) buys +4 dB input-referred (C06) at no gain cost.
* **Load.** Lowering Rd trades gain for headroom nearly one-for-one in dB at the output
  (net output headroom ~0 for pure Rd changes at the committed bias), as expected.
* **Best combination.** C08 (R2b = 7.3 kohm, Rd = 200 ohm): the first limit violation moves from
  -36/-36/-34 dBm to -26/-26/-24 dBm (+10 dB input-referred) with 4.4 dB less gain (16.4-18.0 dB
  vs 20.2-22.3 dB); net stress-free OUTPUT power improves by 5.6 dB. C05 (R2b = 7.15, Rd = 200) is
  second (+8 dB, net +3.6 dB).
* **Row 8 is still not determined for any candidate.** The best stress-free power is -28/-28/-26 dBm,
  with only 0.11/0.15/0.06 dB of gain compression there. The 1 dB crossing is not bracketed by stress-valid
  points, so P1dB is a one-sided bound `> -28 dBm`, 1-3 dB short of even a lower-bound pass of
  the unchanged -25 dBm target. No threshold was relaxed.
* **Outcome class** (frozen rule): `headroom_improved_p1db_undetermined`. Shortlist: C08, C05.
* Collector-current diagnostics were recorded per plan v2 (applicability unresolved, envelope not claimed
  complete); no candidate point was admitted or rejected on a current bound.

## What this does and does not support

* Supports: bias and load changes alone give a measurable but limited headroom gain at the nominal corner;
  the mechanism is Q2's V_CE peak, with Q1's V_CE the next ceiling once Q2 is given more room.
* Does not support: any claim that rows 8 or 17 are met, that C08 is a better LNA (it loses 4.4 dB gain and
  its noise figure and stability were **not** evaluated), or anything about other corners, real
  passives or the second stage. These numbers are single-run, base-timing screening values: no timestep or
  window convergence check, no two-tone IIP3 and no NF/stability comparison has been done on the shortlist.
* Follow-up the evidence supports (not done here): (1) refine C08/C05 with the half-step/double-window
  controls and a nominal two-tone IIP3; (2) compare small-signal gain, NF and stability against C00 with
  the `sim/lna-sparam-nf` conventions; (3) only then, and in a new frozen plan version, extend the table
  (Rd below 200 ohm) if the remaining 1-3 dB gap is worth the further gain loss. Any schematic adoption
  is a subsequent reviewed change; #79's core/noise selection should treat this as an input, not a result.
