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
prepared the measured options; this record is the proposal those measurements
argue. Every number below carries its source; the deltas are from the study
record [`sim/lna-passive-study/records/20261121-044750-495011a.md`](../../sim/lna-passive-study/records/20261121-044750-495011a.md)
(comparative deltas vs a same-deck ideal-passive control, lna-sparam-nf method
pinned by sha256, 63 cells per deck, control gate-passed against the post-#79
record's op table)
and the sizing table
[`layout/lna_stage1/passive_sizing.json`](../../layout/lna_stage1/passive_sizing.json)
(PDK models: `R = rsh·l/(w+2·lwd) + 2·rzspec/w`, `C = carea·l·w + 40 fF/µm·2(l+w)`,
each verified against the instanced `r3_cmc`/MIM models on the batch fleet).

## Options, sized from the PDK models, and what each measures out to

**Resistors** (per-element table in `passive_sizing.json`; corner spread is
`res_wcs`−`res_bcs` over typ at 27 °C):

| class | elements | feasible flavours (min-area sizing) | measured consequence |
|---|---|---|---|
| bias ladder | `Rref` 8k, `Rbr` 60.9k, `Rbias` 10k, `R1b` 1.5k, `R2b` 7k | `rppd` (85.3 µm² total, ±20 % spread) or `rhigh` (15.3 µm² total, ±48 % spread); `rsil` out of range for `Rbr` (4.5 mm body > 1 mm maxL) | V01 (`rppd`) vs V02 (`rhigh`): both within ±1.5 dB S21 / ±0.5 dB NF / ±3 dB S11 of the ideal control at every row-2/3/4/6 bound cell; `rhigh`'s ±48 % spread moves the bias visibly further (S21 −1.5 dB at `res_wcs`/`cap_wcs`, −40 °C) |
| collector damping | `Rd` 465 | `rppd` (0.5×0.64 µm, 0.3 µm²), `rsil` (16.6 µm²), `rhigh` (w=5 µm) | in V01/V02 (`rppd`): sub-dB deltas |
| emitter / mirror degeneration | `Rer` 24, `Re1` 3 | `Rer`: `rsil` (0.75×1.32 µm) or wide `rppd`; **`Re1`: `rsil` only** (w=5 µm, l=0.87 µm — the deliberately wide, short body #198 predicted; `rppd` and `rhigh` contact floors exceed 3 Ω at every width) | `rsil` in V01: sub-dB deltas |

**Capacitors**:

| element | options measured | area | verdict the deltas argue |
|---|---|---|---|
| `Cm` 57.8 fF | `cmim` 6.16 µm side | 38 µm² | `cmim` — `rfcmim`'s 7 µm geometry floor is already 74.6 fF (> design value) |
| `Cshunt` 170 fF | `cmim` 10.6 µm side | 112 µm² | `cmim` — V03 measures `rfcmim` unusable in the Ka signal path (below) |
| `Cb2` 10 pF | (i) 2 parallel `cmim` 5 pF (57.69 µm sides), (ii) 2 parallel `rfcmim` 5 pF, (iii) single `rfcmim` 10 pF | 6 656 µm² (i = ii); (iii) is outside the model's own 7–75 µm valid window | two parallel `cmim` — (ii) buys nothing (same plates, plus a substrate node the schematic lacks) and V03 rules the primitive out of the signal path anyway; `Cb2` sits on a bias node, so it is the *least* constrained element |
| `Cblk_in` 1 nF | (a) on-chip `rfcmim` array: 119 × 74.8 µm at the model's largest valid plate | **0.666 mm²** total plate | **measured out.** V03 carries it: S21 **−43 dB**, S11 **+8 dB**, NF **+38 dB** vs control at the row-2/3 cell — `cap_rfcmim`'s own model includes the plate/feed inductances (`lplate`+`lfeed` ≈ 13 nH at 74.8 µm with the PDK-default `wfeed`, still ≈ 9 nH at the model's largest legal `wfeed` = 30 µm), i.e. > 1 kΩ of series reactance at 19.45 GHz. The PDK's own model rules the primitive out of the Ka-band signal path at these plate sizes |
| | (b) smallest on-chip `cmim` that still closes the input match, **re-matched** (Lin/Cshunt re-derived at 19.45 GHz from the probed substituted-core base impedance 48.17 − j143.4 Ω, the design's own L-section method) | **1 pF** (25.77 µm side) = **664 µm²** | measured in: holds S11 ≤ −10.15 dB at all three DRAFT band points at all four row-4 bound corner cells (0.5 pF misses at −9.90 dB). V04: dS21 +0.0…+1.5 dB, **dNF −0.8…−1.6 dB (better than the ideal 1 nF network)**, dS11 −2…−22 dB across the row-4 cells — the re-match also deepens the match and lowers input-network loss |
| | (c) off-chip with a boundary port (designed 1 nF value kept as an ideal element; pad/bond/PCB path unmodelled — a stated omission) | 0 µm² on-chip | the V01/V02 baseline: sub-dB deltas; the omission is what the operator accepts |

## Decision (proposed — nothing is selected by this record)

For the operator to ratify or amend, per element class:

1. **Bias ladder → `rppd`** (V01): 85.3 µm² total, ±20 % corner spread, sub-dB
   measured cost. `rhigh` (V02) is the area option (15.3 µm²) at the price of a
   ±48 % spread that visibly detunes bias across corners; take it only if a
   later area budget forces it.
2. **RF path → `rppd` for `Rd`, `rsil` for `Rer` and `Re1`** (`Re1` has no other
   feasible flavour; w = 5 µm wide-short body).
3. **`Cm`, `Cshunt` → `cmim`**; `rfcmim` is measured out of the Ka-band signal
   path (V03) and its 7 µm floor exceeds `Cm`'s value outright.
4. **`Cb2` → two parallel `cmim` (5 pF each)**, 6 656 µm²; revisit only if the
   area budget forces `rfcmim` on this non-RF node.
5. **`Cblk_in` → option (b): 1 pF `cmim` + re-match (Lin 1.317 nH, Cshunt
   31.9 fF)** — 664 µm² (a 1000× area saving over the 1 nF array) with the
   match *closing* at the row-4 corner cells and a measured NF improvement.
   Option (c) (off-chip) remains the fallback if the operator prefers not to
   re-spin the input network now. Option (a) is measured out.

Adopting any option set changes `design/lna_stage1.sch` (adds substrate/body
nodes for the 3-terminal resistor and any `rfcmim`, changes `Cblk_in`'s value
and the match elements), so **it invalidates at minimum**: the post-#79
characterization record (`sim/lna-sparam-nf/records/20261114-211735-8a92c6e.md`)
and every `lna-*` record measured on that DUT (headroom, linearity,
match-tradeoff), each of which stays valid as evidence for the earlier core.
Rows 2–6 stay `placeholder_circuit` in `spec/row-coverage.json` until the
re-characterization lands; no row, area target, tier roll-up or evidence rule
changes by this record.

## Argument

The study measured four frozen candidate sets against a same-deck control
(the committed ideal-passive DUT) with the lna-sparam-nf method pinned by
sha256, at 63 cells per deck (7 process bundles — hbt and the four
`res_*`/`cap_*` cross extremes — × 3 temperatures × 3 supplies); the control
passed the op-table gate against the post-#79 record (≤ 10 mV / 2 % on all
nine 2.5 V cells) and the passive-inertness negative control. The deltas are
comparative only — row 4's own note says S11 is not simulatable as a claim
until EM extraction lands — so no row is shown met or missed anywhere above.
The one degraded-mechanism finding (V03) is not a spec failure to recover:
the bounded iteration that would "recover" it is the option-(b) re-match,
which V04 already measures.

## Alternatives considered

- **`rhigh` everywhere it fits (minimum area)** — rejected as the primary
  recommendation: 5.6× less ladder area but a ±48 % `res_*` spread on nodes
  that set bias; V02 measures the consequence (S21 −1.5 dB at the
  `res_wcs`/`cap_wcs` cell). Kept as the documented area fallback.
- **`rsil` ladder** — out of range for `Rbr` (4.5 mm body vs the PDK's 1 mm
  maxL); not a candidate set.
- **On-chip 1 nF `Cblk_in` (`rfcmim` array)** — measured out by the PDK's own
  model (V03); 0.67 mm² of plate *and* > 1 kΩ of model feed reactance at
  19.45 GHz.
- **`Cb2` as one 10 pF `rfcmim`** — outside the model's declared 7–75 µm
  geometry window (81.6 µm side needed); two `cmim` reach it inside every
  declared range.
- **Off-chip `Cblk_in`** — viable (option c) but keeps a board-level part and
  an unmodelled pad/bond path on the noisiest node in the receiver; the
  measured option (b) removes both for 664 µm².

## Trigger to revisit / what will decide this

Ratification (two-key) or amendment by the operator. #110's EM campaign
decides the inductor half; if a ratified inductor route changes the input
network topology, the option-(b) re-match (and V04's numbers) must be
re-derived — the prematch probe and grid are frozen in
`sim/lna-passive-study/testbench/prematch.json` and re-runnable. If a future
PDK release ships a `cap_rfcmim` model without the feed-inductance dominance
at large plates, option (a) can be re-measured unchanged.

## Consequences

- **Unblocks (on ratification)**: the claiming stage-1 layout (T1 items 2, 3,
  11 — `layout/lna_stage1` can draw every resistor and capacitor at a PDK
  primitive), and the schematic change `design/lna_stage1.sch` → re-netlist →
  full re-characterization on the substituted core.
- **Invalidates (on ratification)**: the post-#79 characterization and the
  sibling `lna-*` records as evidence *for the new core* (they stay valid for
  the old one); the input-match section of `design/lna_stage1.md` (V04's
  re-match numbers replace the pre-`Le1` sizing if option (b) is taken).
- **Costs**: 664 µm² (`Cblk_in`) + 6 656 µm² (`Cb2`) + ~150 µm² (resistors +
  `Cm`/`Cshunt`) ≈ 7.5 µm × 7.5 µm of added passives; two substrate/body node
  classes admitted into the schematic (`rsil`/`rppd` bodies, `cmim` is
  2-terminal); the `res_*`/`cap_*` corner axes become real and enter every
  future corner campaign (row 4's bound corner already names them).
- **Bad consequences kept visible**: the `rhigh` fallback's ±48 % spread; the
  unmodelled off-chip path if option (c) is chosen; `Cblk_in` at 1 pF puts
  818 Ω of reactance in series with the base at band centre — legal only with
  the re-match, and the re-match must be re-derived if anything upstream of
  the base changes; and nothing about this record relaxes row 17's open
  2.75 V excursion question — that stays an operator decision.
