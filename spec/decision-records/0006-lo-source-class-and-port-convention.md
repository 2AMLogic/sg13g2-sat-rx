# 0006: LO source class and LO port convention — ideal external bench LO, port form and reference impedance stated with every LO number

- **Status**: **proposed**. Written and argued, **not ratified**. Design work
  may read it; no claim may cite it as settled. Rows 14 and 15 of
  [`spec/target-spec.md`](../target-spec.md) keep their current status and
  values; this record edits no spec row.
- **Date**: 2026-10-09
- **Decided by**: Builder agent, issue #51 (proposing only; per
  [`spec/README.md`](../README.md) an agent turns neither key)
- **Ratification**: two-key (EE key + market key), by the ratification-via-PR
  path [DR-0003](0003-target-spec-first-ratification.md) used. **Neither key
  has been turned.**
- **Related**: [#51](https://github.com/2AMLogic/sg13g2-sat-rx/issues/51)
  (this issue); `target-spec.md` open item 7, "Port convention", rows 14/15;
  [DR-0003](0003-target-spec-first-ratification.md) (row 15 left OPEN, LO drive
  to be set by the mixer bench); [DR-0004](0004-lna-mixer-interface-convention.md)
  (sibling port-convention record); issue #35 bench
  [`sim/mixer-topology-feasibility/`](../../sim/mixer-topology-feasibility/README.md).

---

## Context

Open item 7 asks for the LO source class (row 14) and whether the LO port is
single-ended or differential, and at what reference impedance. Row 15's LO
drive is deliberately blank ("an output of the mixer design") and its
leakage bounds are "a power at a port, so only meaningful with the LO drive
level stated beside it". An LO drive in dBm is meaningless without the source
impedance and the single-ended/differential form: the same available power
is a different open-circuit voltage at 50 Ω single-ended and at 100 Ω
differential (`V_open_peak = sqrt(8·R·P)`, so 100 Ω differential needs
sqrt(2) the single-ended 50 Ω amplitude for the same total power). Without
a convention each mixer bench picks its own and the numbers are not
comparable. The spec's "Port convention" section already requires a stated
departure beside any number not at 50 Ω and names "a differential LO port
referenced to 100 Ω differential" as the example; it does not say which form
the LO port takes.

Row 14 itself (16.7–20.2 GHz, low-side LO at 1 GHz IF) is untouched; it moves
with rows 1 and 16.

## Decision (proposed)

Stated as a convention, *if ratified* (spec-text edits, if any, belong to the
ratifying PR, not this one):

1. **Bench LO is an ideal external source.** No on-chip oscillator is part of
   the bench. The source is ideal and noiseless unless a record says
   otherwise (LO phase noise is therefore not evidenced by any bench under
   this record).
2. **The LO port form is stated explicitly, and the default is a
   differential 100 Ω reference port**: two 50 Ω legs driven in antiphase
   (+v/2, −v/2 peak), reference plane at the mixer's LO pins, with an ideal
   bias tee for the LO common-mode DC. LO drive is quoted as the **total
   available power** of that port, `P_av = V_open_diff_peak² / (8·R_diff)`,
   `R_diff = 100 Ω`, as one number, not per leg. A bench may instead use a
   **single-ended 50 Ω** LO port (`P_av = V_open_peak² / (8·50)`) when its
   mixer core is single-ended, provided it says so. Either way this is a
   **port departure** in the sense of the spec's Port convention for the
   differential case (100 Ω differential is not the 50 Ω reference) and must
   be labelled as such beside each number; the single-ended 50 Ω form is
   the spec's default reference and needs only the form stated.
3. **Every LO-drive, LO-to-RF leakage and LO-to-IF leakage number (rows 14–15)
   quotes, beside it: the port form (differential/single-ended), the source
   reference impedance, whether the drive is available power or delivered
   power, and the LO frequency.** Leakage is quoted as power delivered into
   the stated RF/IF termination, with the RF source off. A number missing any
   of these is not comparable and is not evidence for row 15.
4. **An on-chip LO (a `sg13g2-vco`-class LC VCO), LO distribution, and PLL
   work are out of scope** for this repo until a later decision record admits
   them. This preserves the per-element-chain scope rule in `CLAUDE.md`. The
   cost of that exclusion is stated under Consequences.
5. **This record sets no LO drive value.** The LO drive stays an output of the
   mixer bench (row 15 text); this record only fixes how it is quoted.

### Which recorded bench settings conform (read from source, not re-run)

Determined by reading
[`sim/mixer-topology-feasibility/mixfeas.py`](../../sim/mixer-topology-feasibility/mixfeas.py)
(`LO_RDIFF_OHM = 100.0`; `vlo_open_peak` = `v_open_peak_for(vlo_dbm, 100)`; module
docstring: "TOTAL available power of the differential 100 ohm port"),
`testbench/ports_common.spice` (two 50 Ω legs `Rlop`/`Rlon` in antiphase,
bias tee `lo_dc`, reference plane `lo_p`/`lo_n`; leakage = power delivered into
the 50 Ω `Rrf`/`Rif`) and `testbench/tb.json` (port wording and `lo_sweep_dbm`).
No simulation was run for this record.

| Setting | Conforms? | Basis |
|---|---|---|
| #35 bench, `gilbert_stacked` and `folded_single_balanced` candidates (LO pins driven directly by `lo_p`/`lo_n`) | **Yes** | differential 100 Ω, total available power, form stated in the bench's own header, README and `tb.json` |
| #35 `placeholder_floor` | **Yes** | same differential 100 Ω port, through an ideal balun (n = √2) to a single-ended base; available power preserved, stated in the fragment header |
| #35 `analytic_control` | **Yes** | same ports; senses `V(lo_p) − V(lo_n)` |
| #35 `lo_sweep_dbm` values (−30…+6 dBm) | **Conform as a quoting form only** | each value means total available power of the 100 Ω differential port; they must be reported with that form (item 3), which the bench's own outputs (`lo_avail_dbm`, `lo_vdiff_open_peak_v`) already carry |
| `sim/mixer-conversion-iip3` placeholder record `20260912-034727-9204518` (LO from a 50 Ω single-ended source, amplitude `vlo` = 0.08 V, 1 pF coupling to the base; leakage read at an unterminated node, "Z0 = 50 Ω is a reporting reference only") | **Does not conform; needs a correcting/annotating record** | LO is drive-quoted as a voltage amplitude, not as dBm with port form beside it; leakage is not power delivered into a stated termination. It was written before this convention and is **not edited**; a later record should state it and say it is not comparable to #35 |

Nothing in the #35 setup needs a correcting record *for port-convention
reasons*. Whether any #35 *result* needs one for other reasons is outside
this record.

## Argument

- A stated, ideal, external LO is the only form the existing evidence (#35)
  and the ratified scope allow: no oscillator model, no inductor model, and
  (open item 3) no simulatable on-chip passive exist, so an LC VCO cannot be
  evidenced here yet. Admitting it would pull LO distribution and
  phase-noise requirements into a per-element block.
- Differential 100 Ω is the default because both Gilbert-class candidate
  topologies being compared are LO-balanced and the bench is already built
  and unit-tested that way; adopting it makes #35's numbers comparable at
  once. It is a default for comparability, **not** a claim that the eventual
  LO feed is differential; that remains tied to the real source, which this
  record does not choose.
- Requiring the port form beside each LO number is what makes row 15's
  drive and leakage bounds checkable; it costs a few words per record.

## Alternatives considered

- **On-chip LC VCO as the LO source** — not chosen: out of scope until a
  record admits it; no passive/oscillator evidence in this repo; not
  decided here, only deferred.
- **Single-ended 50 Ω as the only allowed form** — not chosen: it would
  force a balun into every balanced candidate to no benefit, and make #35's
  conforming runs non-conforming. Kept as a permitted stated form.
- **Leave it per-bench** — not chosen: this is the failure the issue
  describes.

## Trigger to revisit / what will decide this

Superseded by a higher-numbered record when any of: (1) a record admits an
on-chip LO source into scope; (2) the chosen mixer topology is single-ended
or its real LO feed has a different reference impedance, such that the
default form is wrong for the design; (3) the ratifying review judges the
differential default to hide a single-ended-vs-differential comparison
penalty that matters to candidate ranking.

## Consequences

- Good: LO drive and leakage numbers across benches become comparable;
  #35's already-built bench conforms with no change.
- Bad: the placeholder record `20260912-034727-9204518` stays in the record
  set without the port form stated; readers must rely on a later annotating
  record. Old records are append-only and are not edited here.
- Bad: bench-LO results say nothing about LO phase noise, LO buffer power or
  LO distribution; row 18 (DC power) will not include any LO generation, so
  the real per-element power is understated until a record admits an
  on-chip LO.
- Bad: a differential default may flatter or penalize a candidate relative
  to a single-ended feed; the available-power quote is the same, the
  required open-circuit voltage is not.
- Rows 14 and 15 stay OPEN and unchanged; ratifying this record gates
  neither by itself.
