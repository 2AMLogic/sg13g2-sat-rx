# 0011: LNA stage-1 passive realization — resistors and capacitors (proposal, selects nothing)

- **Status**: proposed
- **Date**: 2026-11-21
- **Decided by**: — (written by the Builder of issue #340; an agent writes the
  record, argues it and leaves it `proposed`; ratification stays with the operator)
- **Ratification**: two-key (EE key + market key) — **neither key has been
  turned.** This record selects nothing, turns no ratification key, edits no
  schematic and changes no spec row. The inductor half (`Lin`, `Lfeed`, `Le1`)
  is **deferred to #110 / [DR-0005](0005-passive-p1-feasibility.md)** and is
  out of scope here.

## Context

T1 items 2 (Layout), 3 (DRC clean) and 11 (Power delivery) are `unmet` /
`no_evidence`, and `docs/ROADMAP.md` names their gate: a `spec/` decision
record on passive realization. The #198 realizability study measured *why*:
the stage's 8 resistors and 4 capacitors are generic `res.sym`/`capa.sym`
elements with no PDK primitive selected, `Re1` (3 Ω) is below minimum geometry
in every flavour at minimum width, `Cb2` (10 pF) exceeds `cmim`'s declared
8 pF maximum, and `Cblk_in` (1 nF) needs ~0.67 mm² of MIM plate. Issue #340
prepared four candidate sets for the operator. The original 63-cell comparison
per deck used a same-deck ideal-passive control. The archived measurements
reproduce the post-#79 operating points. The original V04 used an ideal shunt.
The revised study uses a drawn shunt, repeats the eight-cell selection screen,
and measures the 2 pF circuit and its control across the full 63-cell grid.
[Original study](../../sim/lna-passive-study/records/20261121-044750-495011a.md) ·
[Follow-up measurements and deck hashes](../../sim/lna-passive-study/testbench/prematch.json)

The sizing equations for drawn dimensions in µm are
`R = rsh·l/(w+2·lwd) + 2·rzspec/w` and
`C = carea·l·w + (0.040 fF/µm)·2(l+w)`. Only the area capacitance varies
with the selected capacitor process corner.
[PDK-model sizing table](../../layout/lna_stage1/passive_sizing.json)

## Options, sized from the PDK models, and what each measures out to

**Resistors** (per-element table in `passive_sizing.json`; corner spread is
`res_wcs`−`res_bcs` over typ at 27 °C):

| class | elements | feasible flavours (min-area sizing) | measured consequence |
|---|---|---|---|
| bias ladder | `Rref`, `Rbr`, `Rbias`, `R1b`, `R2b` | `rppd` (85.3 µm² total) or `rhigh` (15.3 µm²). For the 8 kΩ reference, the full spans are 19.65% and 48.01%, respectively. | At the row-2/3 worst-HBT, 125 °C cells, V01 ΔS21 spans −0.211…−0.119 dB and ΔNF +0.003…+0.015 dB. V02 ΔS21 spans +0.476…+0.957 dB and ΔNF +0.032…+0.143 dB. V02 ΔS11 spans −2.94…+2.65 dB at the eight row-4 cells. |
| collector damping | `Rd` 465 Ω | `rppd` (0.50 × 0.64 µm), `rsil` (16.6 µm²) or `rhigh` (7.9 µm²) | V01 and V02 exercise the compact `rppd` geometry. |
| degeneration | `Rer` 24 Ω, `Re1` 3 Ω | For `Re1`, `rsil` at 5 × 0.87 µm gives 3.013 Ω. A legal `rppd` at 70 × 0.54 µm gives 3.005 Ω and uses 37.8 µm². The table also gives a 495 µm² `rhigh` solution. | V01 exercises `rsil` for both resistors. The body of its `Re1` occupies 4.35 µm². |

**Capacitors**

| Element | Options and area | Evidence |
|---|---|---|
| `Cm` 57.8 fF | One 6.16 µm square `cmim`, 38 µm² | The 7 µm minimum `rfcmim` plate gives 74.62 fF, above the design value. |
| `Cshunt` | V01 uses a 10.6 µm square `cmim` for 170 fF. The revised V04 uses a 4.56 µm square for 31.92 fF typical. | A single `rfcmim` substitution on V01 costs 0.12 dB of gain at the nominal midband probe. |
| `Cb2` 10 pF | Two 57.69 µm square `cmim` plates, 6,656 µm² total. Each plate fits the 8 pF limit. A single 10 pF RF plate needs an 81.6 µm side, above the 75 µm model limit. | V01 exercises the two-plate bias bypass. The two-terminal multiplier probe reproduces the explicit pair. |
| `Cblk_in` (a), on-chip 1 nF | 119 parallel 74.8 µm square `rfcmim` plates, 0.666 mm² | V03 loses about 43 dB of gain at band centre. The one-at-a-time and terminal probes below identify the effect of the array in this circuit. |
| `Cblk_in` (b), on-chip with re-match | 2 pF `cmim`, 36.47 µm side, 1,330 µm². The 4.56 µm shunt and ideal 1.283 nH `Lin` complete the input match. | Smallest passing tested value in the corrected screen. The worst sampled S11 is −10.0086 dB. |
| `Cblk_in` (c), off-chip | V01 and V02 retain the intended 1 nF as an ideal DC block. On-chip plate area is zero. | This boundary requires a board capacitor. Pad, bond, PCB and external component parasitics remain unmodelled. |

## Decision (proposed — nothing is selected by this record)

1. Prefer `rppd` for the bias ladder. For `Rref` the best/typical/worst values
   are 7.215/8.001/8.787 kΩ (±9.8%). The smaller `rhigh` alternative gives
   6.100/8.027/9.953 kΩ (±24.0%) and the larger measured gain and NF excursions.
2. Prefer `rppd` for `Rd` and `rsil` for `Rer` and `Re1` on the measured V01
   geometries and their body area.
3. Prefer `cmim` for `Cm` and for the drawn input shunt. Only `Cm` has the
   RF-MIM minimum-capacitance exclusion.
4. Prefer two parallel 5 pF `cmim` plates for `Cb2` on the bias node.
5. Carry the **2 pF on-chip block** into layout and extraction if the operator
   chooses integrated DC blocking. The historical 1 pF recommendation depended
   on an ideal shunt and four screened cells. Option (c) is still available
   if the board supplies the block. Full-band row-4 compliance awaits EM
   extraction and re-characterization.

Adopting a set replaces generic devices in `design/lna_stage1.sch` and
requires body connections for three-terminal parts. Option (b) also changes
the input blocking value, shunt and series inductor. The [post-#79
characterization](../../sim/lna-sparam-nf/records/20261114-211735-8a92c6e.md)
and sibling headroom, linearity and match-tradeoff records describe the
earlier core. The changed schematic requires fresh characterization. Rows
2–6 retain their `placeholder_circuit` disposition.

## Argument

The study measured four frozen candidate sets against a same-deck control
(the committed ideal-passive DUT) with the lna-sparam-nf method pinned by
sha256, at 63 cells per deck (7 process bundles — hbt and the four
`res_*`/`cap_*` cross extremes — × 3 temperatures × 3 supplies). The recheck of the archived control covered all 27 reference
transistor rows. The maximum voltage difference was 0.4985 mV and the maximum
collector-current difference was 0.1884%. All 63 controls were inside all 18
published RF envelopes. The passive-inertness and finite-measurement checks
also passed. The historical erratum reports each gate and corrects the
whole-grid stability extrema and the sign of ΔNF. These comparisons use
ideal inductors and make no spec-row claim.
[Historical erratum](../../sim/lna-passive-study/errata/20261121-044750-495011a.md)

**RF-MIM isolation.** At typical process, 27 °C, 2.5 V and 19.45 GHz, V01
has 18.378 dB gain. Replacing only `Cshunt` gives 18.254 dB and replacing
only `Cb2` gives 18.523 dB. Replacing only `Cblk_in` gives −25.061 dB,
close to the complete V03 at −25.297 dB. This identifies the blocking array
as the dominant substitution at that point. The model equations give 26.90 pH
for `lplate` and 10.83 pH for `lfeed` on one 74.8 µm plate with a 2 µm feed.
Their sum contributes 4.61 Ω of inductive reactance per plate at band centre.
The full RF model also has skin, feed and substrate branches.

With a 1 V AC input, 50 Ω load and grounded substrate, one RF instance with
`m=119` reproduces 119 explicit units at that frequency. Input current is
0.05411+j0.47550 A, load voltage is 1.01223−j0.00632 V, and substrate
current is 0.03386+j0.47563 A. Each real and imaginary component agrees
within 1e−10 in its reported unit. The large substrate current is present
in both simulations.

**Realized input match.** The probe gives 48.17−j143.38 Ω at band centre.
With both capacitors sized for each candidate, worst sampled S11 for
0.5, 1, 2, 5 and 10 pF is respectively −9.173, −9.753, −10.009, −10.066
and −10.101 dB. The 10 pF point uses two legal 5 pF plates. The limiting
2 pF cell is `res_wcs / cap_wcs`, 125 °C, 17.7 GHz, with only 0.0086 dB
margin to the design screen. A separate run of the frozen two-port method
reproduced each selected grid S11 within 0.001 dB.

All cells below use typical HBT process and 2.5 V. Each triple is ordered
17.7 / 19.45 / 21.2 GHz. NF deltas compare the revised V04 with the ideal
control at the same cell. Its gain deltas span −0.506…+1.418 dB. For context,
the original ideal-shunt V04 gain deltas included −0.565 dB.

| Resistor / capacitor corner | Temperature | Absolute S11 (dB) | ΔNF (dB) |
|---|---:|---|---|
| bcs / bcs | -40 °C | −10.982 / −22.763 / −12.303 | −0.781 / −0.896 / −1.049 |
| bcs / bcs | 125 °C | −11.374 / −29.091 / −10.775 | −1.017 / −1.198 / −1.437 |
| bcs / wcs | -40 °C | −10.873 / −21.340 / −12.450 | −0.790 / −0.884 / −1.025 |
| bcs / wcs | 125 °C | −11.304 / −33.293 / −11.092 | −1.052 / −1.182 / −1.391 |
| wcs / bcs | -40 °C | −10.223 / −27.019 / −12.845 | −0.785 / −0.915 / −1.077 |
| wcs / bcs | 125 °C | −10.051 / −24.702 / −11.253 | −0.988 / −1.198 / −1.448 |
| wcs / wcs | -40 °C | −10.151 / −24.824 / −13.127 | −0.795 / −0.901 / −1.048 |
| wcs / wcs | 125 °C | −10.009 / −26.529 / −11.665 | −1.026 / −1.174 / −1.389 |

The revised 2 pF deck and matched control also ran with ngspice 47 at all
63 declared cells. At the worst HBT process and 125 °C the row-2/3 comparison
is as follows, in the same low / mid / high frequency order.

| Supply | ΔS21 (dB) | ΔNF (dB) |
|---|---|---|
| 2.25 V | −0.019 / +0.315 / +1.252 | −1.088 / −1.272 / −1.550 |
| 2.50 V | +0.048 / +0.382 / +1.291 | −1.101 / −1.294 / −1.572 |
| 2.75 V | +0.147 / +0.498 / +1.367 | −1.115 / −1.322 / −1.607 |

Across the full row-6 grid, the revised V04’s minimum absolute sweep k
is 10.5714 at res_bcs/cap_bcs, −40 °C, 2.75 V (Δk +1.6903). Its smallest
Δk is +0.6126 at hbt_wcs, 125 °C, 2.25 V.
[Revised record and stored evidence](../../sim/lna-passive-study/records/20261121-101130-e6a7e3e.md) ·
[Screen and model probe](../../sim/lna-passive-study/testbench/prematch.json)

## Alternatives considered

The `rhigh` ladder saves a factor of 5.6 in body area. The `rsil` geometry
for the 60.9 kΩ `Rbr` would exceed its 1 mm length limit at minimum width.
The off-chip block avoids on-chip plate area while adding a board component.
The 1 nF RF array uses about 500 times the plate area of the 2 pF option and
has the measured loss described above.

## Trigger to revisit / what will decide this

Ratification requires the operator's two-key decision. #110 and DR-0005
govern the inductor route. Extract the complete input, including pad, routing
and realized passives, and repeat the band and corner sweep before claiming
input match. A change to the core impedance or inductor route also requires
a new re-match.

## Consequences

- **Unblocks (on ratification)**: the claiming stage-1 layout (T1 items 2, 3,
  11 — `layout/lna_stage1` can draw every resistor and capacitor at a PDK
  primitive), and the schematic change `design/lna_stage1.sch` → re-netlist →
  full re-characterization on the substituted core.
- **Invalidates (on ratification)**: the post-#79 characterization and the
  sibling `lna-*` records as evidence *for the new core* (they stay valid for
  the old one); the input-match section of `design/lna_stage1.md` (V04's
  re-match numbers replace the pre-`Le1` sizing if option (b) is taken).
- **Area**. Option (b) uses about 1,330 µm² for the blocking plate,
  6,656 µm² for the bypass pair and 150 µm² for resistors, `Cm` and the
  smaller shunt. Their sum is about 8,136 µm², equivalent to a 90.2 µm
  square before spacing, routing and inductors. The earlier 1 pF estimate
  of 7,470 µm² corresponds to an 86.4 µm square.
- **Electrical consequences**. At 19.45 GHz the ideal reactance of a 1 pF
  block is −j8.18 Ω and that of a 2 pF block is −j4.09 Ω. Resistor bodies
  require substrate connections. Resistor and capacitor corners enter future
  comparisons. The row-17 disposition of the 2.75 V excursion stays open.
