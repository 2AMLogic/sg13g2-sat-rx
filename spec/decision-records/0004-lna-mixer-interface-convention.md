# 0004: LNA→mixer interface convention — 50 Ω back-to-back vs co-designed conjugate interstage match

- **Status**: **proposed**. Written and argued, **not ratified**. Design work
  may read it; no claim may cite it as settled. Rows 5, 12 and 13 of
  [`spec/target-spec.md`](../target-spec.md) stay **OPEN** until this record is
  ratified; this record edits no spec row.
- **Date**: 2026-10-09
- **Decided by**: Builder agent, issue #26 (proposing only; per
  [`spec/README.md`](../README.md) an agent turns neither key)
- **Ratification**: two-key (EE key + market key), by the ratification-via-PR
  path [DR-0003](0003-target-spec-first-ratification.md) used. **Neither key
  has been turned.** Judge review is the first key, Champion/operator merge
  the second.
- **Related**: [#26](https://github.com/2AMLogic/sg13g2-sat-rx/issues/26)
  (this issue); `target-spec.md` "Port convention" and open item 4;
  [DR-0002](0002-beamsteering-partition.md) (an RF-path shifter would sit on
  this interface); [DR-0003](0003-target-spec-first-ratification.md) (rows
  5/12/13 left OPEN on this gate);
  [`sim/hbt-kaband-characterization/`](../../sim/hbt-kaband-characterization/README.md)
  record `20261009-095725-dbf8179` (device-level numbers only).

---

## Context

`target-spec.md` states that the LNA→mixer interface "is not assumed to be a
50 Ω port", that a co-designed interstage requires cascade rows 12/13 to be
**measured on the cascade, not computed by Friis**, and (open item 4) that
the choice must be a DR before rows 5, 12, 13 are ratified. Row 5 (S22) is
written in two forms for exactly this reason. This record supplies the choice.

**Evidence status, stated first.** There is no schematic, no matched stage, and
no passive model for this block. The only simulated evidence is device level
(the hbt-kaband record), which says so itself: bare `npn13G2`, ideal bias tees,
ideal noiseless terminations, "not a matched-amplifier result". The
comparison below is therefore **a budget argument from ratified bounds plus
labelled device-level feasibility figures**, and every number that is an
estimate is marked as one. Nothing here sizes a matching network.

### The ratified bounds that decide this (all binding as *targets*, DR-0003)

| Row | Bound | Binding corner |
|---|---|---|
| 2 LNA gain | ≥ 20 dB | `hbt_wcs`, 125 °C, min supply |
| 3 LNA NF₅₀ | ≤ 2.5 dB | `hbt_wcs`, 125 °C |
| 9 Mixer conversion gain | ≥ 8 dB (power, into 50 Ω IF) | `hbt_wcs`, 125 °C, min supply |
| 10 Mixer NF (SSB) | ≤ 12 dB | `hbt_wcs`, 125 °C |
| 18 DC power | ≤ 40 mW per element | `hbt_bcs`, −40 °C |
| 12 Cascade NF (OPEN) | ≤ 4.0 dB | `hbt_wcs`, 125 °C |
| 13 Cascade gain (OPEN) | ≥ 28 dB | `hbt_wcs`, 125 °C, min supply |

### Two arithmetic facts about those bounds (derived here, not measured)

1. **Gain has zero slack.** Row 2 + row 9 = 20 + 8 = **28 dB = row 13**, at the
   *same* binding corner. If each block just meets its own row, any net loss at
   the interface, or any mismatch between what each block was measured into and
   what it actually sees, makes row 13 fail. The interface is first a **gain**
   question. (The OPEN rows' bounds are not edited here; the *stage* rows would
   need margin, or row 13 would need to be revisited by its own DR, which this
   record does not propose.)
2. **NF has headroom, and it is not at risk from interstage loss.** Friis with
   rows 3/10/2 at their bounds: F = 1.778 + (15.85 − 1)/100 = 1.926 ⇒
   **≈ 2.85 dB** against 4.0 dB, i.e. ≈ 1.15 dB of slack (estimate; ideal 50 Ω
   Friis, which is precisely the computation the spec forbids relying on for a
   co-designed interface). A lossy interstage of 1 dB adds ≈ 0.09 dB to that
   figure (same formula with an interposed 1 dB passive: F ≈ 1.968 ⇒ ≈ 2.94 dB),
   because the mixer's NF is divided by the LNA gain. Interstage loss costs
   **gain ≈ 1:1 and NF ≈ 0.1:1**.

### Device-level feasibility figures (labelled: bare-device, not circuit)

From `sim/hbt-kaband-characterization/records/20261009-095725-dbf8179.md`
(ideal terminations, VBIC Rev. 1.15, 17.7/19.45/21.2 GHz); used for direction
only, not as a design number for either option:

- NFmin of a bare `npn13G2` at its best eligible bias: worst case **1.287 dB**
  (`hbt_wcs`/125 °C/21.2 GHz, T0 = 290 K), i.e. +1.21 dB below row 3's 2.5 dB
  before matching loss, bias noise and the second stage. A feasibility screen
  that says nothing about a matched amplifier.
- Zopt at the noise optimum is ~10³ Ω with a large reactive part at Nx = 1
  (e.g. 1202+1503j Ω at `hbt_wcs`/125 °C/17.7 GHz), and "scales roughly as
  1/Nx" (README "Known limits"): the noise-optimum source is far from 50 Ω.
  This is an **input**-side fact; it shows that device ports at this
  frequency are high-Z reactive and that a 50 Ω port is a transformation, not
  a default. It does not give the LNA's output impedance, which depends on the
  not-yet-chosen topology.
- Bare-device gain at the NF-optimum bias is MSG (K < 1), **12.5 dB** at
  `hbt_wcs`/125 °C/17.7 GHz (the worst reported row): a stage is gain-limited,
  so row 2's 20 dB needs ≥ 2 stages and every dB lost between stages is
  expensive.
- DC power of the bare device at the noise optimum: **0.23–0.37 mW** per
  Nx = 1 device across the reported rows. This is ≈ 10⁻² of row 18's budget;
  device bias at the NF optimum does not decide row 18. What decides it (mixer
  core, LO buffering, any stage that must drive a 50 Ω port) is topology that
  does not exist yet.
- Passive quality, from `target-spec.md` open item 3 (`sg13g2-vco` EM
  extraction, record `20260910-052657-3896421`): a single-turn spiral holds
  **Q ≈ 12.3 at 20 GHz**; multi-turn spirals self-resonate **below** the band
  (8.07/9.42 GHz). Any interstage network is therefore made of low-inductance
  elements with finite loss. **Its actual loss is unknown until the passive
  study closes; this record does not estimate it.**

---

## Decision (proposed)

**Adopt Option B — a co-designed, conjugate-matched interstage — as the
LNA→mixer interface convention, conditional on the falsifier below.**

Stated as a change to the spec, *if ratified* (to be executed in the same PR
that ratifies, not here):

- Row 5 takes its second form: S22 is a stated conjugate match of the LNA
  output to the **mixer RF port's** impedance, reference impedance recorded
  with the number (a complex reference, via power-wave reflection
  Γ = (Z_out − Z_in,mix*)/(Z_out + Z_in,mix)), across band, all corners.
- Rows 12 and 13 are **measured on the cascade** only; Friis from rows 3 and
  10 is a labelled cross-check, never the verdict.
- The LNA and mixer are no longer 50 Ω-port blocks at the interface. Rows
  2/3/9/10 keep their 50 Ω definitions at the *external* ports (LNA input, mixer
  IF/LO), and **at the interface they are measured under a stated departure**
  (LNA into its design load, mixer from its design source). Whether rows 2, 3,
  9, 10 then need restating is flagged under Consequences; it is not decided
  here.

### What is NOT decided

No network topology, element values, Nx, bias, or interstage impedance level.
Option B fixes a *convention*, not a design.

---

## Argument: the options compared

Both options need passive matching at 20 GHz (the device ports are not 50 Ω;
see Zopt above). The difference is **how many lossy transformations sit in the
gain path between the LNA transistor and the mixer transistor**.

| Axis | (A) 50 Ω back-to-back | (B) co-designed conjugate interstage |
|---|---|---|
| Matching networks in the interstage path | Two: LNA output → 50 Ω and 50 Ω → mixer RF port, in series (estimate: up to ~2× the passive loss of B, plus a 50 Ω midpoint that nobody needs) | One: LNA output → mixer RF port directly |
| Gain budget (rows 2/9/13; zero slack) | Each network's loss is paid in gain; the 50 Ω port is also what rows 2 and 9 were stated against, so A *inherits* the 28 = 20 + 8 identity but with the larger loss. Cascade gain ≈ sum of the two blocks' 50 Ω gains **only if** both S11/S22 at the interface are good. At the row-4/5 bound (−10 dB), \|Γ\|² = 0.1, i.e. **0.46 dB mismatch loss per side** (derived: −10·log₁₀(1 − 0.1) = 0.458 dB; ≈ 0.92 dB if both sides sit at the bound, ignoring re-reflection). Against zero gain slack, a single bound-limited mismatch alone fails row 13 unless rows 2/9 carry that margin | Loss is one network's. Conjugate match maximizes transferred power at the interface. Cascade gain is not a sum of 50 Ω-measured gains; must be measured as a cascade |
| NF budget (rows 3/10/12; ≈ 1.15 dB slack) | Friis holds only where the interface is genuinely 50 Ω. Treated as an interposed loss, the 0.458 dB bound-limited mismatch (see gain row) costs little NF: F = 1.778 + (1.111 − 1)/100 + 1.111·(15.85 − 1)/100 = 1.944 ⇒ 2.888 dB, i.e. **+0.040 dB** over 2.848 dB, ≈ 3.4 % of the 1.15 dB slack (derived; consistent with Fact 2's ≈ 0.1:1; both sides at the bound: ≈ +0.08 dB). A's real NF risk is not quantified here: the mixer's NF is source-impedance dependent, so 50 Ω-measured mixer NF is not the NF the mixer shows behind a mismatched LNA output (**unquantified**; no mixer exists) | Insensitive to interstage loss (≈ 0.1 dB NF per dB loss, derived above). The mixer's NF must be taken with the LNA's actual output impedance as source, which is exactly the cascade bench |
| Matching-network loss | Two lossy networks; each depends on the passive study (open item 3, Q ≈ 12.3 single-turn at 20 GHz) | One lossy network; same dependency |
| DC power (row 18, ≤ 40 mW) | A 50 Ω-capable output stage (lower impedance level ⇒ more current for the same swing) is likely, i.e. power goes *up* (estimate, qualitative; no topology exists). Device bias at the NF optimum is ~10⁻² of the budget, so this is a stage/buffer question, not a device one | No 50 Ω driver is required by the interface; higher impedance level lets the LNA output stage run at lower current (estimate, qualitative). But does not remove mixer-core or LO power |
| Stability (row 6, k > 1 to ≥ 63.6 GHz) | Blocks are isolated by a nominal 50 Ω; each block's k is checkable on its own at 50 Ω, but a 50 Ω-measured k does not bound out-of-band behaviour behind a non-50 Ω real load | LNA load is the mixer's out-of-band impedance, so k is a **cascade** property and must be evaluated there (harder, not impossible) |
| Verification modularity | Strong: per-block benches map to existing 50 Ω benches (`sim/lna-sparam-nf`); blocks can be developed independently | Weak: LNA and mixer cannot be signed off against each other as separate 50 Ω blocks; a change to either re-opens the other |
| Layout/area | Two networks plus a 50 Ω line/pad-free midpoint | One network, shorter interstage routing (in a regime where "layout is part of the circuit", `porting-plan.md` §4.3) |

**Why B, and the honest weakness of the argument.** The simplicity assumption
(prefer A) was tested, not assumed. The test found the gain budget has zero
slack and A puts two lossy transformations in the one place loss cannot be
afforded, while B puts one; A's 50 Ω ports also each allow up to 0.46 dB of
mismatch loss at their −10 dB bound, which is a gain cost against that same
zero slack. The NF argument does **not** favour either option by itself:
interstage loss, mismatch loss included, is cheap in NF (0.46 dB of it moves
cascade NF by ≈ 0.04 dB). A's remaining NF risk is the source-dependent mixer
NF behind a non-50 Ω LNA output, which is unquantified, not loss. What B costs is modularity and the
simplicity of Friis. That is a real cost, accepted because the gain row is the
binding one. **This is a reasoned budget argument, not a measurement**: it
rests on an estimate that two networks lose more than one, and on no number
for what either network loses. It could be wrong, which is why a falsifier is
stated.

### How rows 5, 12, 13 would be measured, per option

Common to both: the mixer SSB NF is **not** a `.noise` result (ngspice has no
`.pnoise`/PSS; open item 6, issue #2), so row 12 on the cascade depends on that
bench's method in both options. Three-point minimum (17.7/19.45/21.2 GHz),
all corners, worst value with binding frequency and corner recorded
(`target-spec.md` "Frequency coverage").

**Option A**

- *Row 5*: LNA S22, 50 Ω reference, `.sp`/`.ac`-derived two-port on the LNA
  alone with a 50 Ω load; ≤ −10 dB. Standard, no departure to state.
- *Row 12*: primary = a cascade-level deck (LNA output tied to the mixer RF
  port through the 50 Ω-designed networks, LO on, 50 Ω source and IF load).
  Friis from rows 3 and 10 is admissible as the verdict **only** with recorded
  interface S-parameters showing the mismatch term is inside the 1.15 dB
  slack at every corner; otherwise cross-check only. The Friis path requires
  the mixer NF to have been measured from a 50 Ω source, which is its row 10
  definition.
- *Row 13*: cascade deck as above (power into 50 Ω IF / available power from
  the 50 Ω source); product of rows 2 and 9 is a cross-check.
- *Benches needed*: existing `sim/lna-sparam-nf` (LNA, 50 Ω) + a mixer bench
  (a placeholder testbench exists in `sim/mixer-conversion-iip3`) + the cascade
  deck. Per-block benches are sufficient for rows 2/3/5/9/10; the cascade deck
  is needed to *confirm* 12/13.

**Option B**

- *Row 5*: LNA output impedance versus the mixer RF-port impedance, stated as
  a complex-reference reflection coefficient (see Decision). Requires the
  **mixer's LO-on RF-port impedance**, which ngspice cannot give by periodic
  AC (no PAC); it must come from an LO-on large/small-signal method that this
  repo does not yet have. This is a bench-design item that must be solved
  before row 5 can be measured at all; when benched, any klt tool gap found
  gets filed per the friction protocol.
- *Row 12*: **cascade-only** deck (LNA directly tied to the mixer RF port, no
  50 Ω midpoint, LO on, 50 Ω external source and IF load), using issue #2's mixer
  NF method applied at the cascade input. Friis from rows 3/10 is a labelled
  cross-check and is expected to disagree.
- *Row 13*: same cascade deck.
- *Benches needed*: cascade deck as the primary bench for rows 5/12/13, plus
  per-block benches run **into the stated design load/source** (a departure
  stated beside each number) for rows 2, 3, 9, 10. Because those per-block
  numbers are not at 50 Ω, they are not directly comparable to the 50 Ω
  definition of those rows.

---

## Alternatives considered

- **(A) 50 Ω back-to-back** — not chosen on the gain-slack argument above; its
  genuine advantages (modular verification, Friis, existing 50 Ω benches) are
  real, and it wins if the falsifier fires.
- **(C) Defer** — decline to decide until a first matched LNA stage and the
  passive study exist. Rows 5/12/13 would stay OPEN and no cascade-level
  design could start without picking a form by default (a convention chosen
  by accident). Not chosen: the choice shapes the first schematic, and the
  falsifier below is checkable early. It is the fallback if the proposer's
  key-holders judge the evidence too thin.
- **Unmatched direct coupling** (no interstage network at all) — not considered
  a convention; it is a design option within B whose feasibility depends on the
  passive study.

## Trigger to revisit / what will decide this

Falsifier for the recommendation (B): **supersede this record with a
decision to adopt A** if, once the 20 GHz passive study (open item 3) provides
extracted matching elements and a first LNA output stage and mixer RF port
exist, **either**:

1. a cascade of the same devices and the same extracted passives built to
   Option A meets row 13 (≥ 28 dB) and row 12 (≤ 4.0 dB) at `hbt_wcs`/125 °C
   with *no less* margin than the Option B build — i.e. B's single-network
   advantage is not visible in the gain budget — so simplicity and modularity
   win; **or**
2. the Option B cascade cannot meet row 6 (k > 1 to 63.6 GHz, all corners)
   without adding resistive loss that consumes B's gain advantage; **or**
3. the LO-on mixer RF-port impedance cannot be extracted with a method whose
   limits can be stated, so row 5 under B cannot be measured at all.

A result that only a *single* corner or centre frequency supports does not
count (`target-spec.md` "Frequency coverage").

## Consequences

- **Good**: one lossy network in the gain path where gain has zero slack; the
  cascade is measured as the thing the system consumes; Friis is demoted to a
  cross-check, which the spec already requires of a co-designed interface.
- **Bad**: LNA and mixer lose independent sign-off; changing one re-opens the
  other. Rows 2/3/9/10 are ratified at 50 Ω ports; under B, their interface-side
  measurements are stated departures, so they are not directly comparable to
  the ratified definition. If that is judged unacceptable, a **separate** DR
  must restate those rows. This record does not.
- **Bad**: row 5 under B needs a mixer RF-port impedance method that does not
  exist in this repo (no PAC in ngspice); until it does, row 5 cannot be
  measured under B, only its cascade consequences (rows 12/13).
- **Bad**: stability (row 6) becomes a cascade property and is harder to bound.
- **Bad**: the recommendation rests on a budget argument and an estimate that
  one network loses less than two. It is unmeasured. The rows it unblocks
  (5/12/13) still need `sim/` evidence records before any compliance claim.
- **Unchanged**: no ratified row is edited here; the spec's "Port convention"
  text and rows 5/12/13 stay as they are until the two keys are turned.
  `CLAUDE.md` scope (per-element chain only) is unaffected.
