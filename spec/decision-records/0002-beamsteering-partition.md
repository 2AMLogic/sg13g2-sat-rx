# 0002: Beamsteering partition — where the phase shift lives. **Deferred, deliberately.**

- **Status**: **deferred** — this is a recorded decision *not to decide yet*,
  with the criteria that will decide it written down. It is **not** a default,
  and nothing in this repo may assume an answer.
- **Date**: 2026-09-12
- **Decided by**: Builder agent, issue #1
- **Ratification**: two-key (EE key + market key). **Neither key is turned.**
  A deferral does not need ratification to be binding as a *statement of
  ignorance*; the eventual choice will.

---

## Context

An antenna array steers its beam by applying a controlled, per-element phase
(or time delay). That phase has to be applied *somewhere* in each element's
signal chain, and where it goes determines what this chip must contain.

`CLAUDE.md` is explicit that the array, the ADC, and the beamformer are **out
of this repo's scope** until a decision record admits a piece of them. This
record admits **none** of them. Its job is the opposite: to write down the
three candidate partitions and what each would ask of this chip, so that

1. nobody silently designs *as if* one of them had been chosen, and
2. when the LNA and mixer benches exist, the choice is made against recorded
   criteria rather than re-argued from scratch.

The top-level `README.md` already says the choice "is not a default and
nothing here assumes one answer." This record is what that sentence points at.

---

## Decision

**Defer.** The beamsteering partition is **OPEN**. `spec/target-spec.md` is
written so that no row presupposes an answer, and the three rows that are
*sensitive* to the answer — row 15 (LO drive level and leakage), row 16 (IF
centre and bandwidth), row 18 (per-element DC power) — are flagged in this
record as provisional against it.

**This repo commits to building none of the three.** It builds an LNA and a
mixer. Whichever partition is eventually chosen, the LNA and the mixer are
still needed, and the differences (below) are differences in their *interfaces
and budgets*, not in their existence. That is precisely why deferring is safe.

---

## The three candidate partitions, and what each asks of this chip

### (a) RF-path phase shift, per element, after the LNA

The phase shifter sits between the LNA output and the mixer RF input. Every
element has its own; the LO can be a single, unphased, broadcast signal.

**What it asks of this chip**

- A phase shifter operating at **17.7–21.2 GHz**, built from this PDK's
  passives and switches, inserted directly into the signal path.
- LNA gain must be raised to cover the shifter's insertion loss *before* the
  mixer, or the shifter's loss adds almost directly to the cascade noise
  figure (it sits after only one gain stage). Either way it costs power —
  `spec/target-spec.md` row 18 is the row that moves.
- An interstage interface that is a real, characterized impedance, not an
  undefined node — which sharpens the open question in `target-spec.md`'s
  "Port convention" section.
- Digital control lines and a phase-state decoder on an otherwise
  all-analog RF die.

**What the evidence says about feasibility here (direction only, no number)**

A phase shifter made of this PDK's reactive elements has insertion loss set by
their quality factor. The only EM-measured figure the fleet has is
`sg13g2-vco`'s single-turn spiral: **Q ≈ 12.32 at 20 GHz** (record
`20260910-052657-3896421`). A 360°-coverage network needs several such
elements in cascade, so its loss is a multiple of the per-element `1/Q`
penalty. **This repo has no number for that loss**, and no published Ka-band
SiGe phase-shifter result was reachable in the environment this record was
written in — so it is recorded as a *quantity to be measured*, not estimated.
**Anyone closing this record must produce that number, not assert it.**

### (b) LO-phase shifting at the mixer

The phase shifter sits in the LO path, not the signal path. Each element's
mixer receives an LO at a controlled phase; the RF path is untouched.

**What it asks of this chip**

- An LO port per element that accepts a **phase-controlled** LO over
  **16.7–20.2 GHz** (row 14), rather than a broadcast one — plus either a
  per-element LO phase shifter on-die or a phase-controlled LO delivered to
  the die.
- LO distribution at ~20 GHz to every element, with matched electrical length
  — a routing and power problem that mostly lives **off this chip**, on the
  board, which is exactly the boundary `CLAUDE.md` tells this repo not to
  cross unilaterally.
- Tighter **LO leakage and LO–LO isolation** requirements (row 15): with a
  phase-modulated LO per element, leakage is no longer a static spur.

**The structural argument in its favour, stated as physics rather than as a
citation**

A mixer's LO port is driven into switching — it is a hard-limited input. Loss
and amplitude error in the LO path therefore cost **drive power**, not signal-
to-noise ratio, whereas the same loss in partition (a) lands on the cascade
noise figure. That asymmetry is the standard reason LO-path phasing is
attractive at millimetre-wave frequencies. It is reasoning from how a
switching mixer works, not a measured result of this block, and it is recorded
as such.

### (c) IF / digital beamforming behind an ADC

No analog phase shifter anywhere. Each element downconverts to IF, is
digitized, and the phase is applied in the digital domain.

**What it asks of this chip**

- **The IF interface becomes the product.** Row 16 (IF centre and bandwidth)
  stops being a convenience and becomes an ADC-driving specification: drive
  level, output impedance, common-mode, anti-alias filtering, and IF linearity
  all become first-class spec rows this table does not currently carry.
- An ADC per element. **Explicitly out of scope** (`CLAUDE.md`). Nothing in
  this repo will build one, and this record does not admit one.
- The arithmetic that makes this the most demanding option at the *system*
  level: at a ≥ 500 MHz IF bandwidth, an element needs an ADC in the
  ≥ 1 GS/s class. At 8 bits, I and Q, that is **≈ 16 Gb/s per element** of raw
  data leaving each element. With half-wave spacing at the 21.2 GHz band edge
  (**7.07 mm**, DR-0001), one element occupies ≈ 50 mm², so a 0.5 m × 0.5 m
  aperture is ≈ **5 000 elements**. The array-level data rate that implies is
  the reason this option is a system-architecture decision and not a chip
  decision. *(All of this is arithmetic from stated assumptions — bit depth
  and sample rate are illustrative, not specified.)*

**What it gives back**: every beam simultaneously, arbitrary beamforming,
adaptive nulling, and calibration in software — capabilities (a) and (b)
cannot offer at all.

---

## Criteria that will decide this

Recorded now so the eventual decision is made against them, not around them.

| # | Criterion | What has to be measured or stated | Who can produce it |
|---|---|---|---|
| 1 | **Per-element DC power** (`target-spec.md` row 18) under each partition — including the gain the LNA must add to cover an RF-path shifter's loss | mW per element, per partition | this repo, once the LNA and mixer benches exist |
| 2 | **Phase-shifter insertion loss at 17.7–21.2 GHz** on this PDK, and its NF penalty when placed after the LNA | dB, EM-extracted or simulated against a real topology — **not** an estimate | this repo (an EM study), or a checkable published Ka-band SiGe result |
| 3 | **LO distribution cost** — power, routing complexity, and matched-length feasibility of delivering a phase-controlled ~20 GHz LO to N elements | a board/system analysis | **not this repo** — needs the array side |
| 4 | **Elements per chip** — whether this die serves one element or several. Changes the AREA row's meaning, the LO distribution problem, and the pin count | a floorplan plus a product decision | this repo (floorplan) + operator (product) |
| 5 | **What the open-source array side can absorb** — whether the board-level project can carry per-element ADCs and their data rate, or wants an analog-combined output | a statement from the array project | **not this repo** |
| 6 | **IF-interface specification burden** under (c) — how many new spec rows the ADC interface adds, and whether this block wants to own them | a spec delta | this repo |
| 7 | **Calibration burden** — per-element amplitude/phase error, and whether it is correctable in the chosen domain | measured spread across mismatch corners | this repo (mismatch corners exist: `hbt_*_mismatch`) |

**Criteria 3 and 5 are structurally outside this repo.** That is the honest
reason this record cannot be closed by engineering work here alone, and it is
why deferring is the correct answer rather than a stalling one: two of the
seven inputs belong to a project this repo is forbidden to reach into.

---

## Trigger to revisit — when this record gets closed

This record is superseded by a partition-choice record when **both** hold:

1. **This repo's own inputs exist** — the LNA bench and the mixer bench are
   committed and have produced recorded results for criteria 1, 2, 6 and 7.
   Specifically: a measured per-element power figure, and an
   EM-extracted-or-simulated phase-shifter loss at Ka band (criterion 2 is the
   one most likely to be the long pole).
2. **The array-side inputs are stated** — criteria 3 and 5 are answered by
   whoever owns the array, in a form this repo can cite.

**A partial trigger, recorded so it is not treated as the full one**: if the
array side states criteria 3 and 5 *first*, and that statement excludes one or
more partitions outright, a superseding record may narrow the field from three
to two (or one) **without** choosing — that is still progress and still a
recordable decision.

**What does NOT trigger it**: convenience. If a later issue finds it awkward
to design the mixer without knowing the LO plan, the correct response is to
design the mixer so the LO plan does not bind it (a broadcast-LO-compatible
mixer works under all three partitions), not to quietly pick (b) and call it
settled.

---

## Consequences of deferring

**Good**

- No spec row is written against an assumption that later turns out false.
- The LNA and the mixer are needed under all three partitions, so the deferral
  blocks no work that this repo is actually chartered to do.
- The `CLAUDE.md` scope boundary stays intact — no board-level or digital work
  is pulled in by an architecture decision made early for tidiness.

**Bad — stated because a deferral is not free**

- Rows 15, 16 and 18 of `spec/target-spec.md` are **provisional against this
  record**. Ratifying them before this closes means ratifying them under an
  assumption; a later partition choice may force a superseding spec record.
- The mixer must be designed to be **partition-agnostic** (a broadcast-LO
  design that does not depend on a phase-controlled LO), which may cost
  something relative to a design tuned for one partition. That cost is
  accepted, not measured.
- Criterion 2 (phase-shifter loss) is a real experiment that nobody is
  currently scheduled to run, and the deferral does not by itself cause it to
  happen. Whoever next touches this record should check whether it has been
  filed as work.

---

## Sources

- `CLAUDE.md` (this repo) — the scope boundary: array, ADC, and beamformer are
  out of scope until a decision record admits a piece of them.
- `README.md` (this repo) — the standing statement that the partition "is not
  a default and nothing here assumes one answer."
- [`0001-band-selection-ka-vs-ku.md`](0001-band-selection-ka-vs-ku.md) — the
  7.07 mm element pitch and the 2.8×-elements-per-aperture figure used above.
- `2AMLogic/sg13g2-vco` `main` @ `c348700`, record
  `20260910-052657-3896421` — the Q ≈ 12.32 at 20 GHz figure that is the only
  EM-measured input to criterion 2 available today.
- Element-count and data-rate figures above are arithmetic from stated
  assumptions, not measurements or citations.
