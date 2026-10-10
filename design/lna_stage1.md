# lna_stage1: design note (issue #28)

First xschem schematic in this repo: **one npn13G2 cascode LNA stage with ideal
behavioral matching**. It is a *device-feasibility* design, not a spec-compliant
LNA: row 2 assumes two stages, and nothing here claims any `spec/target-spec.md`
row met. The evidence for this circuit is the lna-sparam-nf record
`sim/lna-sparam-nf/records/20261010-012923-6cad7fc.md` (27-point HBT x T x V
grid on the off-host batch fleet, plus the per-device operating-point table and
the k / |Delta| / mu sweep).

## Files

| File | What |
|---|---|
| `lna_stage1.sch`, `lna_stage1.sym` | the schematic and its symbol (xschem 3.4.4) |
| `export_netlist.sh` | regenerates `netlist/lna_stage1.spice` through `klt netlist --block` (and normalizes the absolute `** sch_path:` line); `--check` fails if the committed netlist is stale |
| `netlist/lna_stage1.spice` | the derived subcircuit netlist (T1 item 1: "the netlist derived from them") |

`sim/lna-sparam-nf/testbench/lna_stage1.spice` embeds `netlist/lna_stage1.spice`
verbatim (the harness takes one fragment, no `.include`);
`sim/lna-sparam-nf/make_stage1_fixture.py` builds it and
`sim/lna-sparam-nf/tests/test_lna_stage1.py` fails if the two drift.

## Topology argument (from the Ka-band characterization record)

Source data: `sim/hbt-kaband-characterization/records/20261009-095725-dbf8179.md`
(bare npn13G2, ideal bias tees and terminations, 17.7 / 19.45 / 21.2 GHz,
27-point grid).

1. **Row 17 forces a stack, not a single device.** Every reported best noise
   optimum in that record sits at V_CE = 1.4 V, the top of the sampled V_CE
   values and exactly row 17's per-device ceiling. A single CE device from a
   2.5 V rail with an inductive (zero-DC-drop) load would see about 2.5 V, above
   the ceiling; an emitter-degenerated or resistively loaded single device would
   have to burn at least 1.1 V in the degeneration or load, which is the
   headroom the gain needs. A cascode splits the rail across two devices so each
   sits near 1.2-1.3 V at 2.5 V.
2. **The bare device is conditionally stable and gain-limited.** The record
   reports K <= 1 for the bare device across the band and quotes MSG (not MAG)
   as its gain at every optimum, about 13-17 dB per device. The cascode's common-
   base upper device removes most of the collector-to-base feedback path, which
   is the part of S12 that makes the bare device's K small.
3. **Device size.** The record's per-Nx table at 19.45 GHz shows NFmin nearly
   flat across Nx = 1, 4, 8 (differences of a few thousandths of a dB at typ/27 C)
   while Zopt scales roughly as 1/Nx. With ideal matching the NF is indifferent,
   so Nx = 8 is chosen because its Zopt is nearest 50 ohm, which minimizes the
   transformation (and therefore the loss) any real passive match will have to
   supply. Both stack devices use Nx = 8.
4. **Current density.** The record's optimum J_C at Nx = 8 is about 3.2 mA/um^2
   (about 1.6 mA per device) with the optimum a bracketed interior point, and the
   self-heating at the reported optima is a few kelvin. Chosen bias:
   I_C ~ 1.56 mA per device at typ / 27 C / 2.5 V, i.e. J_C ~ 3.1 mA/um^2
   (0.063 um^2 per emitter, the record's convention).

Why not an emitter-degenerated single CE: see 1. Why not a two-stage design:
that is the next step, not this issue; the stage count is the one place this
schematic is knowingly short of row 2's assumption.

## Bias network and rail (row 17)

* **Q1 (CE) bias**: diode-connected `Xqr` (Nx = 1) fed from `vdd` through
  `Rref` = 8 k sets the reference current (~0.2 mA); `Rer` = 24 ohm in its
  emitter mirrors Q1's `Re1` = 3 ohm scaled by 8 (so the 8:1 area ratio is a
  current ratio, 1:8). `Rbias` = 2 k isolates the RF base node from the
  reference (its DC drop at I_B ~ 2 uA is ~4 mV). The mirror tracks V_BE over
  temperature and process by construction; the reference current follows the
  supply (so I_C moves ~ +/- 12 % with the +/- 10 % supply, visible in the
  operating-point table).
* **Q2 (CB) bias**: `R1b` = 1.5 k / `R2b` = 7 k divider of `vdd` with `Cb2` =
  10 pF bypass: V_B2 = 0.82 x vdd. With V_BE2 ~ 0.8 V this sets
  V_CE1 = V_B2 - V_BE2 - V_E1 and V_CE2 = vdd - V_B2 + V_BE2.
* **Collector feed** `Lfeed` is ideal with zero DC drop, so
  V_CE1 + V_CE2 = vdd - (I_E x Re1): at 2.5 V that is ~2.49 V split about 1.25 /
  1.25 V at typ / 27 C.
* **Verified, not argued**: the record's per-device table (all 27 cells x 3
  devices) checks V_CE <= 1.4 V, V_CE in 0.4-2.0 V, V_BE in 0.65-0.96 V,
  I_C < 3 mA x Nx and fT > 21.2 GHz. At supplies <= 2.5 V every device-cell
  passes (max Q1 V_CE 1.342 V). The 2.75 V rows are a labelled excursion: six
  Q1 cells exceed 1.4 V there (up to 1.537 V at 125 C). A two-device stack at
  2.75 V and a 1.4 V per-device cap leaves about 0.05 V of total margin
  (2 x 1.4 - 2.75), which no fixed divider can hold across -40..125 C; the
  record reports it rather than hiding it. Whether 2.75 V is in row 17's scope
  is an open operator question (spec ambiguity, not decided here).
* Self-heating at the chosen bias is measured per cell (max dTj 5.8 K, at the
  2.75 V excursion; 4.1 K at <= 2.5 V), so the characterization record's
  run-wide 284 K maximum (at high current density, far from these optima) does
  not apply at this bias.

## Matching (ideal / behavioral, labelled as such)

No SG13G2 inductor model exists, and spec row 1 (the band) is still OPEN, so
nothing here is a sized-for-the-band matching network. The ideal L/C exist only
to give the bench defined, roughly 50 ohm ports at the DRAFT band centre
(19.45 GHz). They were sized from one single-corner small-signal probe of the
stage with bare ports (hbt_typ, 27 C, 2.5 V; one local ngspice run, not a grid):

* Input: the probe gave Z_in ~ 24 - j148 ohm. `Lin` = 1.41 nH cancels the
  reactance and adds the series reactance of an L-section (Q = sqrt(50/24 - 1) =
  1.04); `Cshunt` = 170 fF completes it. This is a **power (S11) match, not a noise
  match**: Zopt for Nx = 8 is ~166 + j203 ohm in the characterization record, so
  the NF below carries the cost of that choice.
* Output: the probe gave a parallel R ~ 14 k with ~18 fF at the collector. An
  undamped high-Q tank of that impedance was unstable (k < 0, |S11| > 0 dB in the
  exploration probes), so `Rd` = 465 ohm damps the collector (a deliberate,
  behavioral loss); `Cm` = 57.8 fF is a series cap that both transforms the damped
  ~450 ohm to 50 ohm (Q = 2.83) and blocks DC; `Lfeed` = 0.962 nH resonates the
  total shunt capacitance at 19.45 GHz.
* The values are **not re-tuned per corner**, so the process / temperature /
  supply spread in S11, S22 and S21 includes match detuning. Narrowband input
  (|S11| ~ -5 dB at the band edges with ~ -25 dB at the centre, typ) is a
  property of this ideal Q ~ 6 input section, not something to fix with the
  numbers; the passive study owns that.

## What the record shows (reported, not claimed)

From the record's Summary and tables (27 cells, 2.75 V included):

* S21 at the three band points spans about 12.9 to 26.2 dB across the grid; the
  hbt_wcs / 125 C / 2.25 V cell is the low end at the band top.
* NF at 19.45 GHz spans about 2.6 to 4.8 dB (mean 3.6): above row 3's DRAFT 2.5 dB
  in essentially every cell. The device-level floor in the characterization record
  is well below that; the gap is the input-match choice, Rbias / Rd noise and the
  absence of a noise-optimal source impedance.
* k > 1 and |Delta| < 1 in band and across the 1-100 GHz sweep (201 logarithmic
  points, 100 per decade) in every cell, min k 3.48 at 66 GHz. **That is the
  ideal-element circuit with a damping resistor and no parasitics, and the
  sweep stops at 1 GHz and 100 GHz**; it is reported against row 6, not claimed.
  The cascode's stabilization came from `Rd`, not from layout-realistic
  design. The record labels any cell with k <= 1 or |Delta| >= 1
  `POTENTIALLY UNSTABLE` and reports MSG for it; none qualified here.
* DC power 3.8-7.5 mW for the stage including bias (row 18's 40 mW budget is for
  LNA + mixer together).

## What this does not do

* No second stage, no real inductors, no layout, no mismatch / statistical
  sections, no noise match, no linearity (P1dB / IIP3) bench.
* Not a wideband result: the match is detuned at the band edges and varies over
  corners; no flatness is claimed between the three band points.
