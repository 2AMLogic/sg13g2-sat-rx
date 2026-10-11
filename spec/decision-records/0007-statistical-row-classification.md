# 0007: Statistical (Monte Carlo) classification of every spec row

- **Status**: proposed
- **Date**: 2026-10-11
- **Decided by**: Builder agent (issue #156); not an EE or market decision
- **Ratification**: two-key (EE key + market key). Neither key turned. This
  record is `proposed`; no claim may cite it as settled.

## Context

T1 item 6 requires that a block whose spec has no statistical row say so
explicitly rather than omit the item, and that any accuracy/offset/matching row
carry Monte Carlo evidence. This repo had no such statement:
`spec/target-spec.md` never mentions statistical or Monte Carlo analysis,
`spec/porting-plan.md:49` lists the mismatch/stat HBT cards as "not read
(TBD)", and the harness has no Monte Carlo path. Item 6 could not be scoped:
"not applicable" and "unstarted" were indistinguishable (issue #156; tracker #4).

## Decision

Each of the 20 rows of `spec/row-coverage.json` carries `statistical` (bool),
`statistical_rationale` (one line) and, when true, `statistical_card` (PDK
model file names only). `check_row_coverage()` enforces this. Classification:

| Row | Parameter | statistical | Reason |
|---|---|---|---|
| 1 | Receive band | false | Definition, not a figure |
| 2 | LNA gain | false | Bound by worst process/T/supply corner |
| 3 | LNA NF | false | Deterministic noise analysis at worst corner |
| 4 | S11 | false | Bound by cap/res process extremes; no inductor model |
| 5 | S22 | false | As row 4 |
| 6 | Stability | false | Bound by worst corner combination |
| 7 | IIP3 | false | Fixed-corner two-tone bench |
| 8 | P1dB | false | Fixed-corner sweep |
| 9 | Mixer CG | false | Worst corner binds; balance mismatch second-order |
| 10 | Mixer NF | false | Deterministic; open item is method, not randomness |
| 11 | Mixer IIP3 | false | Fixed-corner two-tone |
| 12 | Cascade NF | false | Deterministic cascade measurement |
| 13 | Cascade CG | false | Deterministic corner figure |
| 14 | LO range | false | Frequency arithmetic |
| 15 | LO leakage | **true** | Matching/symmetry effect; card: `sg13g2_hbt_mod_mismatch.lib`, `sg13g2_hbt_stat.lib` |
| 16 | IF BW | false | Bound by cap process corners |
| 17 | Supply | false | Operating-point constraint |
| 18 | DC power | false | Bound by `hbt_bcs`, -40 C |
| 19 | Area | false | Measured by `klt economy` |
| 20 | Area-eff | false | Measured by `klt economy` |

Only row 15 is `true`. Its verdict stays `placeholder_circuit`; it remains
unmet for item 6 until a Monte Carlo record exists. The card files are cited by
name only; their contents have not been read (porting plan: TBD).

## Argument

Rule applied: a row is `true` only if the spec itself names a randomness
mechanism that a deterministic corner cannot bound. `target-spec.md` states
exactly one: row 15 ("leakage is a matching/symmetry effect") and its mismatch
corner axis. At a typical, perfectly symmetric corner, leakage cancels by
construction, so only a mismatch/statistical run yields a meaningful number.

Judgment calls:

- **4, 5**: the binding corners are `cap_bcs`/`cap_wcs` x `res_*` extremes,
  which are deterministic process corners. Inductors and t-lines have no model
  at all (row 4 note), so S11 is not simulatable yet, and there is nothing to
  sample for the dominant element. Capacitor mismatch cards exist
  (`capacitors_mod_mismatch.lib`, `capacitors_stat.lib`) but the spec does not
  claim a mismatch-limited match. Revisit once an EM-extracted passive exists.
- **6**: the ratified binding case is the worst process x temperature x supply
  combination, in and out of band. Monte Carlo would add confidence but cannot
  replace the corner, so it is not what the row's claim rests on.
- **10, 12**: noise figure is a deterministic analysis. The image-rejection
  assumption behind SSB is an architecture open item, and the row 10 gate is
  the measurement method (issue #2). No offset/balance term is stated.
- **15**: true, as above. Row 9 is false because the spec states no mismatch
  mechanism for it; any balance effect on gain is second-order to the corner.

Over-marking `true` would create unmet rows with no bench; under-marking would
hide a real need. The classification is the narrowest one the spec text supports
and is reversible by a later record.

`statistical_card` on a `false` row is rejected by the checker: a card source is
only meaningful for a row that needs Monte Carlo, and allowing it would let a
row look scoped for item 6 while classified as not needing it.

## Alternatives considered

- **Also mark rows 4/5/6 true** (issue's initial candidates) - rejected: their
  binding mechanism is a deterministic corner, and `true` rows with no possible
  bench (no inductor model) would be permanently unmet without being testable.
- **Mark all false** - rejected: contradicts the spec's own row 15 note.
- **Prose-only classification in this DR** - rejected: not machine-checked, so
  a new row could silently omit the item.

## Trigger to revisit / what will decide this

Superseded by a later record if (a) an EM-extracted passive model lands and
rows 4/5 show a mismatch-limited spread, (b) a bench shows mixer rows 9/10/12
depend on device or balance mismatch, or (c) row 15 is ratified with a different
leakage mechanism.

## Consequences

This adds no limit and relaxes none; no spec value, corner, status or verdict
changes. Item 6 is now scoped: one row (15) needs a Monte Carlo run, via
`klt sim` `monte_carlo` requests to the batch fleet, not local grids; that run
is out of scope here. Bad side: the checker now requires three fields on every
new row, and a `false` classification of rows 4/5/10/12 is a judgment that may
prove wrong.
