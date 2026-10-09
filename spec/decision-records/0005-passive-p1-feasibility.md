# 0005: p1 single-turn spiral feasibility — passive-family choice deferred

- **Status**: **deferred**. The p1 EM campaign is built but has **not produced
  an EM result** (see Context), so no passive family is chosen. Not ratified;
  design work may read it, no claim may cite it as settled. This record edits
  no spec row and relaxes nothing in [`spec/target-spec.md`](../target-spec.md).
- **Date**: 2026-10-09
- **Decided by**: Builder agent, issue #25 (recording a deferral only; per
  [`spec/README.md`](../README.md) an agent turns neither key)
- **Ratification**: two-key (EE key + market key). **Neither key has been
  turned.** Nothing here is ratifiable until the evidence listed under "What
  will decide this" exists.
- **Related**: [#25](https://github.com/2AMLogic/sg13g2-sat-rx/issues/25);
  `target-spec.md` open item 3 (the 20 GHz passive question) — **stays open**;
  [`spec/porting-plan.md`](../porting-plan.md) §4.2 and §5 step 4;
  [`sim/passive-p1/`](../../sim/passive-p1/README.md) and its records;
  [DR-0001](0001-band-selection-ka-vs-ku.md) (band, still proposed: every
  frequency below is the draft Ka downlink band, not a ratified one).

## Context

Rows 3 (via matching loss), 4, 5 and 6 of the target spec cannot be simulated
until some inductive or distributed element has a usable ngspice model;
the PDK ships none (`sim/README.md` "Passive/EM model provenance").
Issue #25, as revised on 2026-10-09, bounded the first step to **one recorded
geometry** — the sibling VCO's `p1` single-turn `inductor2` (w=8.22 µm,
s=3.29 µm, d=47.65 µm, nr_r=1) — run through the sibling's recorded
geometry → openEMS → de-embedding → Touchstone → lumped fit → ngspice flow,
at 17.7 / 19.45 / 21.2 GHz, with declared numerical limits.

What exists now ([`sim/passive-p1/`](../../sim/passive-p1/README.md)):

- The campaign driver, analysis chain, pinned/hashed inputs
  (`sg13g2-vco` @ `ee69f8529df347b871f52067f6f054821ac75b32`), and
  known-answer / wrong-value / malformed-data controls, all passing (this is
  evidence about the **analysis chain only**).
- A `CAPABILITY_UNAVAILABLE` record: on the build host `openEMS` is absent,
  there is no openEMS python and `import CSXCAD` fails, so the baseline,
  mesh-refinement and margin solves **did not run**. No L, Q, SRF, convergence
  or fit number exists in this repo for p1. No number from the sibling
  repository is used as a substitute.

## Decision

**Defer** the passive-family choice (spiral vs. transmission line vs. both vs.
something else). Record only:

1. p1 feasibility at 17.7–21.2 GHz is **unestablished**, not negative and not
   positive. The sibling's p1 figures cited in `porting-plan.md` §4.2 remain
   *historical comparison*, produced and recorded in the sibling repository and
   not reproduced here, so they are not evidence for this repo.
2. The tooling to establish it is in place and reproducible; what is missing is
   a host with openEMS.
3. Even a `QUALIFIED` p1 record would qualify one inductor in one band at one
   nominal stackup point. It would say nothing about transmission lines,
   MIM capacitors, other inductor geometries, or process/temperature spread.

## Argument

- The revised issue explicitly allows an honest `CAPABILITY_UNAVAILABLE`
  outcome rather than substituting historical numbers; recording a family choice
  on no new data would manufacture a decision that the evidence does not support.
- Choosing a family now would pre-size matching networks, which CLAUDE.md
  forbids until the band is ratified (DR-0001 is still proposed).
- The campaign's limits are *proposed acceptance limits* (mesh/margin
  ΔL ≤ 5 %, ΔQ ≤ 10 %; fit ≤ 5 %), not measured accuracy or silicon guarantees.

## Alternatives considered

- **Choose "single-turn spiral" on the sibling's historical p1 numbers** —
  rejected: those numbers were not produced or reproduced here, and the issue
  says missing solver access is not a reason to substitute them.
- **Choose "transmission line"** — rejected: no extraction exists for it in
  this repo, and its first-order length estimate in `porting-plan.md` §4.2 is
  marked TBD by that document itself.
- **Close the issue as infeasible** — rejected: the blocker is host
  provisioning, which is outside this issue.

## Trigger to revisit / what will decide this

Supersede this record (with a higher-numbered one) when **all** of the following
hold, each checkable in a `sim/passive-p1/records/` file:

1. A record with status `QUALIFIED`, or an explicit `UNCONVERGED` / `FIT_FAILED`
   record, produced by `sim/passive-p1/run_extraction.sh` on a host where the
   `em` and `convergence` stages ran, with solver version, mesh and margin deltas
   at all three band frequencies, and the SRF lower bound.
2. For a family choice (not just p1 feasibility): comparable evidence for at
   least one transmission-line or alternative-element candidate, and an
   independently sourced position on process/temperature spread (currently
   *unsupported*; the EM stackup is one nominal point).
3. The band (row 1 / DR-0001) ratified, so that "the band" the choice must hold
   across is no longer a draft.

## Consequences

- Rows 4, 5, 6 and the matching-loss part of row 3 **remain unsimulatable**; no
  testbench may include a p1 stand-in until a `QUALIFIED` record exists, and then
  only within its stated band and exact geometry.
- The porting plan's step 4 is now partly *tooled*, not resolved.
- Bad consequences: the longest pole to T1 items 5/7/8 is unchanged by this PR; a
  future solver run may come back `UNCONVERGED` (which would push the
  geometry-refinement cost onto a follow-on); the analysis chain was validated
  only on generated data, so a defect specific to real openEMS output would show
  only at the first real run. The honest record is the guard against that: any
  malformed file is rejected, not silently analysed.
