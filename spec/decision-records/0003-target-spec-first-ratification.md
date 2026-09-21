# 0003: Target-spec first ratification pass — eleven rows ratified as *targets*, nine left explicitly open

- **Status**: **proposed**, travelling as this PR. Per the ratification-via-PR
  standing policy ([2AMLogic/2am#357](https://github.com/2AMLogic/2am/issues/357),
  2026-08-19 — the path issue #11 selected over installing a `ratification/`
  tree here, fleet-wide gap
  [2AMLogic/product#135](https://github.com/2AMLogic/product/issues/135)):
  **nothing in this record is binding until this PR merges. On merge, the
  per-row dispositions in "Decision" below take effect exactly as stated** —
  eleven rows (2, 3, 4, 6, 7, 8, 9, 10, 11, 17, 18) move DRAFT → **RATIFIED
  (target)** and nine rows (1, 5, 12, 13, 14, 15, 16, 19, 20) stay **OPEN**,
  explicitly, not silently. This status line deliberately still reads
  `proposed` after merge — nothing updates it mechanically, the known wart
  issue #11 names — so **after merge, read the ratification state from the
  per-row dispositions below, not from this line**.
- **Date**: 2026-09-21
- **Decided by**: Builder agent, issue #11 (proposing only; per
  [`spec/README.md`](../README.md) an agent turns neither key)
- **Ratification**: two-key (EE key + market key), executed by the
  ratification-via-PR path on repos without a `ratification/` tree:
  **Judge review is the first key, Champion/operator merge is the second.**
  The merge commit is the durable evidence both keys were turned. Worked
  precedent: `sky130-comparator` PR
  [#29](https://github.com/2AMLogic/sky130-comparator/pull/29) (merged
  2026-09-16, commit `36a7373`), whose DR-002 is the partial-ratification
  shape this record follows.
- **Related**: #11 (this issue), [#4](https://github.com/2AMLogic/sg13g2-sat-rx/issues/4)
  (gap-to-T1 tracker — its item 5 is the row this record exists to unblock;
  per that tracker's own convention it is **not** edited by this PR and is
  updated separately once this merges),
  [DR-0001](0001-band-selection-ka-vs-ku.md) (band, *proposed* — row 1 and
  every frequency-dependent disposition here is provisional against its
  trigger),
  [DR-0002](0002-beamsteering-partition.md) (beamsteering, *deferred* — rows
  15, 16, 18 are provisional against it),
  [`spec/target-spec.md`](../target-spec.md) (the table dispositioned here;
  edited by this PR),
  [`spec/README.md`](../README.md) (its "Status" section is edited by this
  PR).

---

## Context

Issue #4 (gap-to-T1 tracker) item 5 — full corner verification vs a
**ratified** spec — is doubly blocked, and the spec side of the block is this
issue's subject: `spec/target-spec.md` is DRAFT, so T1 items 5, 7 and 8
cannot close no matter what simulation lands, because "verdicts against a
draft spec are provisional by construction."

**No design, no layout, and no simulation of this block exists.** That is
not a defect of this record — it is the state it exploits. Issue #11 states
the rationale exactly: with nothing measured, every row ratifies **as a
target**, and that is the correct moment to bind numbers, "while the numbers
are still being chosen on their merits rather than to match a result." The
`CLAUDE.md` guardrail cuts the same way: *agents do not relax the ratified
spec to make results pass* — the guardrail only has teeth if the spec is
ratified **before** results exist to be tempted by.

This record therefore does not read measurements against bounds (the state
`sky130-comparator` DR-002 was written in). It takes the pre-measurement
route the table's own open item 1 offers as its second alternative: re-state
the engineering-target rows as **explicitly self-derived engineering targets,
defended as such**, and leave open every row whose value is blank, externally
unverified, or gated on a convention no record has chosen. No number below is
new: every value already stood in the DRAFT table; every defence it gets here
was already recorded there as its `Src` chain.

The two-key mechanism is not installed as a `ratification/` tree in this repo
(product#135 tracks that fleet-wide). The ratification-via-PR path
(2am#357) is the standing-policy substitute for exactly this case, and is
the option this issue's own body selects.

## Decision

### Semantics, stated once

1. **Target, not compliance.** A row "RATIFIED (target)" here binds the
   number as what the design must be measured against. **No row is ratified
   as *met*. No measurement of this block exists, so no compliance claim is
   made or implied by this record, and none may be cited from it.** Design
   work may now proceed **against** the eleven bound rows and cite them as
   binding targets; it still may not claim *compliance* with them without a
   `sim/` evidence record.
2. **Provisionality is recorded, not smuggled.** Every ratified row that
   depends on frequency is **provisional against DR-0001**: if the band
   moves, those rows are *re-derived, not rescaled*
   ([`target-spec.md`](../target-spec.md) "The band is drafted, not
   ratified"). Row 18 is **provisional against DR-0002** (the partition
   choice changes the gain the LNA must carry — see that record's own
   flagging of rows 15/16/18). Neither flag softens a bound today.
3. **The conventions travel with the rows.** The 50 Ω port convention, the
   "across band" evaluation rule (17.7, 19.45, 21.2 GHz minimum, every
   corner, worst value binds with its binding frequency and corner
   recorded), and each ratified row's own measurement-discipline note
   (e.g. row 7's two-tone + FFT requirement, row 9's power-gain-into-50 Ω
   primary form, row 10's SSB/DSB-stating requirement) are ratified **as
   part of the row they define**, not as free-standing text.
4. **Corner set.** The verification corner set
   ([`target-spec.md`](../target-spec.md) "Verification corners") is
   ratified as the binding frame for every ratified row — three HBT
   process corners (`hbt_typ`/`hbt_bcs`/`hbt_wcs`, read from
   `cornerHBT.lib`), `hbt_*_mismatch` where matching matters (row 15 is
   open, so no ratified row currently needs mismatch, but the axis stays
   in the set for when it closes), three corners each for capacitors and
   resistors, five MOS corners if a MOS device is used, −40/27/125 °C,
   supply ±10 % about row 17's rail, band-edge + centre frequencies
   minimum with sweeps preferred. The **passive/EM axis stays OPEN**: an
   EM-extracted model is a field solve of one drawn geometry against one
   stackup and carries no process-corner axis at all.

### Rows RATIFIED (target) — eleven

| Row | Bound (unchanged) | Why it can bind now |
|---|---|---|
| 2 | LNA S21 ≥ 20 dB (stretch 25) | §A below |
| 3 | LNA NF₅₀ ≤ 2.5 dB (stretch 2.0) | §A, flag retained |
| 4 | LNA S11 ≤ −10 dB (stretch −15) | §B |
| 6 | k > 1 to ≥ 63.6 GHz out-of-band (stretch 1.5) | §B, arithmetic 3 × 21.2 GHz |
| 7 | LNA IIP3 ≥ −15 dBm (stretch −10) | §C |
| 8 | LNA P1dB ≥ −25 dBm (stretch −20) | §C |
| 9 | Mixer power conv. gain ≥ 8 dB into 50 Ω (stretch 12) | §A |
| 10 | Mixer SSB NF ≤ 12 dB (stretch 9) | §A, method gap named |
| 11 | Mixer IIP3 ≥ −5 dBm (stretch 0) | §C |
| 17 | Rail ≤ 2.5 V; per-device V_CE ≤ 1.4 V, model window 0.4–2.0 V | §D — best-evidenced row in the table |
| 18 | LNA + mixer DC power ≤ 40 mW (stretch 25) | §C, **provisional against DR-0002** |

Values are identical to the DRAFT table — this record changes *status*, not
one number. (Stretch bounds ride along as non-binding aspiration levels, as
before.)

**§A — self-derived targets, the honest name kept.** These are the rows the
table itself flags (E)-NEEDS-VERIFICATION *against published results*. This
record takes open item 1's second route: re-stated self-derived engineering
targets, defended from the only checkable data this environment holds — (P)
PDK device capability and the fleet's recorded (S-LNA)/(S-VCO)
characterizations — while the literature-verification gap stays **open
follow-up** (see "What will decide this"). Sanity checks that already stand
in the table and are adopted here as the defence: row 2's per-stage MAG
headroom (`npn13g2` FMAX min 400 GHz against 21.2 GHz, ratio ≈ 18.9, with
(S-LNA)'s bare-device 8.5 dB transducer gain at 2.4 GHz as the honest floor
the matching network must lift); row 3's own caveat — bare unmatched device
NF 6.32/8.51 dB at 2.4 GHz means the 2.5 dB target is an **aspiration to be
tested**, and it is ratified *as exactly that*; row 9's primary form fixed
(power gain into a 50 Ω IF load, rows graded on nothing else); row 10 with
SSB-vs-DSB stated beside every future number and the `.pnoise`-absent
measurement method named as a bench-design deliverable (issue #2's scope) —
a missing method gates *measurement*, not the validity of the target it will
eventually measure.

**§B — well-formed match/stability targets whose simulation is not yet
possible.** Open item 3 (no PDK inductor or transmission-line model; (S-VCO)
proved openEMS extraction works but it is per-geometry) means rows 4, and
through matching loss row 3, cannot be *simulated* yet, and row 6 cannot be
swept out-of-band until a topology with passives exists. That gates
**verification**, not the target: the bounds (−10 dB match; k > 1 across
band and to 3× the upper edge — 63.6 GHz, one-line arithmetic from row 1's
draft band) are what any eventual matching solution must meet, whatever the
passive technology turns out to be. Ratifying now also fixes the target
*before* the passive choice exists to bias it — the same
choose-on-merits-first argument as the rest of this record.

**§C — linearity and power budgets.** IIP3/P1dB rows (7, 8, 11) carry their
measurement discipline in-row (two-tone + FFT with recorded tone spacing,
powers, window, resolution; extrapolation range stated) and those conditions
are ratified with them — "no IIP3 claim without that bench" becomes binding.
Row 18 (per-element DC power) is the number the array multiplies and the row
most coupled to DR-0002; it is ratified **provisionally** against that
record (per DR-0002's own flagging and open item 9), binding now, revisited
if a partition (typically (a): RF-path phase shift) forces the LNA to make
up shifter loss.

**§D — supply rail.** The two-sided constraint is a (P) fact, not an
estimate: BVCEO min 1.4 V on `npn13g2` (process spec §3.1) and the VBIC
card's own `vce` 0.4–2.0 V validity window (`sg13g2_hbt_mod.lib` header).
The stretched form (a single 1.8 V rail if topology allows) stays
conditional. The design question this leaves open — *which supply/bias
topology distributes the stress* (open item 5) — is work the bound now
constrains, which is the point of ratifying it.

### Rows left OPEN — nine, each with its gate

| Row | Why it cannot bind yet | What will close it |
|---|---|---|
| 1 (band) | Allocation edges 17.7–21.2 GHz **never checked against a checkable primary source** (row's own NEEDS-VERIFICATION); DR-0001 is *proposed* and says "the ratified row must not carry an unverified allocation" | Primary-source verification of the FSS space-to-Earth edges, then DR-0001's own ratification; rows then move **re-derived, not rescaled** |
| 5 (LNA S22 / interstage) | Row deliberately admits two forms (50 Ω back-to-back or conjugate co-designed match); its own text: "whichever is chosen must be recorded in a DR before this row is ratified" | The LNA→mixer interface-convention DR (open item 4) |
| 12 (cascade NF) | Same gate — open item 4 names rows 5, 12, 13; whether the row is cascade-measured or Friis-computable is exactly the undecided convention | Interface-convention DR |
| 13 (cascade gain) | Same gate | Interface-convention DR |
| 14 (LO range) | Pure arithmetic on rows 1 + 16 (`f_LO = f_RF − f_IF`), both open — it moves with them | Rows 1/16 ratifying (and the IF plan surviving DR-0002) |
| 15 (LO drive + leakage) | LO drive is **deliberately blank** — an output of the mixer bench, not a guess; leakage is a power at a port, meaningful only with the drive stated beside it; also DR-0002-provisional | Mixer bench (issue #2 deliverables) setting the drive; then re-enter with DR-0002 still open but the value complete |
| 16 (IF centre / BW) | "One LEO broadband channel ≈ 500 MHz" is an **unchecked external assumption** (open item 2, row's own NEEDS-VERIFICATION), and interacts with DR-0002 (partition (c) would re-spec the IF interface) | Checkable channel-plan source; the partition's IF-facing consequence, if any |
| 19 (AREA absolute) | Value is TBD by design — "set at ratification" *from cost/reticle economics plus a first floorplan* (open item 8). A blank cannot bind | A first floorplan and a cost statement |
| 20 (AREA-EFF) | Utilization floor and per-edge dead-margin caps deliberately unset pending this block's own `economy-review` evidence (open item 8; klayout-tools guidance: analog blocks carry no default floor) | `klt economy` output / `economy-review` on a first layout |

Every open row keeps its DRAFT value, its flags, and its existing notes —
open here means *not yet bound*, never *rejected*.

## Argument

**Why ratify targets at all before anything is measured.** Because the
alternative is the exact inversion of this block's founding guardrail. If
the first ratification pass happened after simulation, every number would be
chosen in the shadow of a result that already existed — the temptation
`CLAUDE.md` names is not hypothetical, it is the default failure mode of
spec-after-measurement ordering. Issue #11's whole framing is the positive
case: bind the demanding numbers now, from device data, so that a future
failing measurement is a *recorded failing result* and any bound that moves
needs a DR arguing why the bound was wrong **on evidence, before the fact**.

**Why these eleven, and not more or fewer.** More (all 20): rejected — rows
1 and 16 would smuggle *unverified external facts* (ITU/FSS allocation
edges; a LEO channel plan) into binding status, which the spec's own open
items 1–2 and DR-0001's band-edge caveat all forbid; rows 5/12/13 have an
explicit recorded precondition (a convention DR) the spec itself set; rows
15/19/20 have **unset values** — ratifying a blank is false precision. Fewer
(until literature citations exist): rejected — open item 1's own text
offers the self-derived-target route this record takes, and waiting for an
environment this repo may never have would leave eleven defensible rows
unbound for no evidentiary reason, keeping T1 items 5/7/8 blocked from the
spec side indefinitely.

**Why the corner set is ratified with the rows.** T1 item 5 grades "every
spec row at its bound corners" — a ratified row without a ratified corner
frame is a bound with no ruler. The corner axes are (P)-derived facts (the
three-corner HBT file read directly, the VBIC temperature window), which is
the same evidentiary class as row 17, and the one axis that is *not* a fact
(passive/EM cornering) is explicitly left open rather than papered over.

**What this record does not do.** It does not choose the LNA→mixer
interface, the passive technology, the LO source class, the supply
topology, or the beamsteering partition — those remain open items with DRs
of their own to come, exactly as DR-0002 demands. It does not close the
(E)-citation gap: rows 2, 3, 9, 10 keep their NEEDS-VERIFICATION flags and
the literature check stays open follow-up. It does not touch one number in
the table.

## Alternatives considered

- **Ratify all twenty rows.** Rejected: nine rows are blank-valued (15, 19,
  20), externally-unverified (1, 16), convention-gated (5, 12, 13), or
  arithmetic derivatives of open rows (14). Binding any of them now would
  be the false ratification issue #11 explicitly prefers openness to.
- **Leave the whole table DRAFT until measurements exist (the
  DR-002-shaped route, ratify-from-evidence).** Rejected as a matter of
  ordering: this repo cannot measure *anything* yet (no schematic, no
  bench), so that route delays binding indefinitely, and when it finally
  happened, numbers would be chosen against results — the ordering failure
  argued above. The sky130 precedent measured first because it *had* a
  design to measure; this repo deliberately binds first for the same
  reason that record declined to relax a bound to match a result.
- **Install the `ratification/` tree here (issue #11's option 1) and use
  the in-tree two-key mechanism.** Rejected for this pass: a fleet-wide
  scaffold change tracked in product#135, and the standing policy (2am#357)
  already supplies equivalent two-key semantics — Judge review + operator
  merge — with the sky130-comparator merge as proof it executes. The tree
  can still land later; nothing here blocks it.
- **File twenty single-row records instead of one pass.** Rejected: the
  precedent's granularity is the ratification *pass* (DR-002 dispositioned
  five rows in one record; the decision is "the table's first ratification
  pass", one decision), and the shared semantics (target-not-compliance,
  provisionality, conventions) would be repeated twenty times or, worse,
  drift between copies.

## Trigger to revisit / what will decide this

- **Open rows**: their gates, named per row in the Decision table —
  external verifications (rows 1, 16), the interface-convention DR (5, 12,
  13), the mixer bench (15), derived-row closure (14), floorplan/economy
  evidence (19, 20). Closing each gate is new-DR work that ratifies the
  row by-name.
- **Ratified rows**: a value can move only by a superseding record that
  argues the bound was wrong on evidence — never by relaxing it to match
  a result (`CLAUDE.md`). Replacing the (E) bases of rows 2, 3, 9, 10 with
  real published citations is *expected* superseding work and may sharpen
  bounds in either direction.
- **DR-0001's band trigger** (Ka fails its EM/passive feasibility gate →
  Ku): every frequency-dependent disposition here is re-entered —
  re-derived, not rescaled.
- **DR-0002's partition closure**: row 18's provisionality resolves, and
  rows 15/16 are re-entered with the partition known.

## Consequences

1. **T1 item 5's spec-side blocker partially lifts.** The tracker (#4) can
   stop calling the table "DRAFT (pending #1)" wholesale: eleven rows are
   now bindable verdict targets. Item 5 still cannot close — no `sim/`
   experiment exists, and verdicts against the nine open rows remain
   provisional by construction — but it is now singly (work) blocked rather
   than doubly.
2. **Design and bench work may cite eleven rows as binding targets.** This
   is the unblock for the porting plan's later stages: the LNA and mixer
   benches, when they exist, grade against ratified rows 2–11 and 17/18
   without a spec caveat, and only the open rows keep their "provisional"
   asterisks.
3. **The numbers can now be failed.** The honest bad consequence: binding
   demanding targets before measurement means a future bench result *can*
   fail row 3 (flagged highest-risk in its own text). That is the design
   intent, not a defect — a failure will be a recorded failing result
   driving design work, not a number quietly moved.
4. **Band risk is taken with eyes open.** Ratifying frequency-dependent
   rows while the band row itself stays open (pending DR-0001 and edge
   verification) means a band move re-opens all of them. Recorded here and
   per-row in the table rather than avoided: the alternative — blocking
   eleven rows on row 1 — was rejected in Alternatives; the Ku trigger is
   written tightly enough (DR-0001) that a move is an evidence event, not
   a mood.
5. **The `Status:` wart is documented, not fixed.** This record's own status
   line stays `proposed` post-merge (nothing updates it mechanically); the
   text of this record and the per-row markers in
   [`spec/target-spec.md`](../target-spec.md) are where a later reader must
   look. Suggested cleanup if the fleet ever installs the in-tree
   mechanism here: a follow-up that stamps ratified records is product#135
   territory, not this PR.
6. **The gap-to-T1 tracker (#4) is not edited by this PR** (its item-5 row
   updates separately after merge, per its own convention) — issue #11's
   tracker-update scope item is discharged post-merge by the Builder of
   #11, so the tracker never cites an unmerged PR as ratified.
