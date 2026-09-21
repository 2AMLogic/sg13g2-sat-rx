# spec — target specification, porting plan, decision records

```
spec/
  README.md                 this file
  target-spec.md            the target-spec table (PARTIALLY RATIFIED, per
                              DR-0003: per-corner rows, a source citation
                              per row, the 50 Ω port convention, AREA +
                              AREA-EFF)
  porting-plan.md           what transfers from sg13g2-lna / sg13g2-vco /
                              sg13g2-comparator, the exact IHP-Open-PDK model
                              files this block depends on, and what is
                              genuinely new (the mixer bench, 20 GHz passives)
  decision-records/
    TEMPLATE.md             copy this to start a new record
    0001-band-selection-ka-vs-ku.md    band (proposed, with the Ku trigger)
    0002-beamsteering-partition.md     beamsteering (deferred, on purpose)
    0003-target-spec-first-ratification.md   first ratification pass
                              (eleven rows RATIFIED as targets, nine OPEN)
```

## Status: partially ratified — targets, not compliance

Since [DR-0003](decision-records/0003-target-spec-first-ratification.md)
(the first ratification pass, merged via the ratification-via-PR two-key
path), [`target-spec.md`](target-spec.md) carries **eleven RATIFIED (target)
rows** — 2, 3, 4, 6, 7, 8, 9, 10, 11, 17, 18 — and **nine explicitly OPEN
rows** — 1, 5, 12, 13, 14, 15, 16, 19, 20 — each with its gate recorded in
that record. **No row is ratified as met**: no measurement of this block
exists.

The band ([DR-0001](decision-records/0001-band-selection-ka-vs-ku.md))
stays *proposed* — row 1 is one of the OPEN rows, gated on allocation-edge
verification — so every ratified frequency-dependent row is provisional
against its trigger. The beamsteering partition
([DR-0002](decision-records/0002-beamsteering-partition.md)) stays
*deferred*; row 18 is ratified provisionally against it.

Design work may proceed against the ratified rows and cite them as binding
targets. It may still not claim *compliance* with any row — open or
ratified — without a `sim/` evidence record substantiating it.

## Decision-record process

Per `CLAUDE.md`: **spec changes go through `spec/` with a decision record, and
agents do not relax the ratified spec to make a result pass.** A DR is required
whenever a `target-spec.md` row is:

- **set** — a DRAFT bound is ratified for the first time,
- **changed** — a ratified row's number moves, or
- **scoped** — a row's applicability changes (e.g. the LNA→mixer interface
  convention is fixed; the beamsteering partition is chosen).

One decision per record, filed as `decision-records/NNNN-<slug>.md`, numbered
sequentially. Before choosing `NNNN`, check every filename already in that
directory on `main` — including superseded records — and use one greater than
the highest, to avoid a collision with a concurrently-landing record.

**Records are append-only.** A record is never deleted or rewritten once
ratified; it is **superseded** by a later, higher-numbered record that says
why. This mirrors `sim/`'s evidence convention: a result is not superseded by
deletion, it is superseded by a later record that says why.

The numbering convention (`NNNN-<slug>.md`) is adopted from
[`sg13g2-bandgap/spec/decision-records/`](https://github.com/2AMLogic/sg13g2-bandgap/tree/main/spec/decision-records).

## Ratification

Ratification flows through the **two-key mechanism (EE key + market key)**.
This repo has no `ratification/` tree (fleet-wide gap:
[2AMLogic/product#135](https://github.com/2AMLogic/product/issues/135)), so
the keys are turned by the **ratification-via-PR standing path**
([2AMLogic/2am#357](https://github.com/2AMLogic/2am/issues/357), 2026-08-19):
the record travels as a PR, **Judge review is the first key,
Champion/operator merge is the second**, and the merge commit is the durable
evidence both keys were turned. That is the path DR-0003 took.

**An agent does not turn either key.** An agent writes the record, argues it,
and leaves it `proposed` (the record's own text states what its dispositions
mean on merge — the known `Status:`-line wart).

## The largest open gap, named here so it is not lost

`target-spec.md`'s source class **(E)** marks every row whose bound is an
engineering target rather than a traceable citation. The environment those
documents were written in had **no literature access**, so no published SiGe
Ka-band LNA or active-mixer result could be checked — and inventing one would
have been worse than flagging it. DR-0003 therefore ratified rows 2, 3, 9 and
10 via open item 1's *second route* (re-stated self-derived engineering
targets, defended in the record); **replacing every (E) flag with a real,
checkable citation remains open follow-up** and may sharpen or supersede
those rows' bounds on evidence. It is still open item 1 in `target-spec.md`.

The same applies to the band edges themselves (17.7–21.2 GHz) and the LEO
channel-bandwidth assumption behind the IF row: both are flagged
`NEEDS-VERIFICATION` in place rather than presented as sourced, and both
**stay unratified** — rows 1 and 16 are among DR-0003's OPEN rows, gated
exactly on that verification.

## Where the downstream consequences are tracked

[Issue #4](https://github.com/2AMLogic/sg13g2-sat-rx/issues/4) — the
gap-to-T1 tracker — holds the honest, artifact-presence survey of everything
that sits downstream of ratification. T1 items 5 (full corner verification),
7 (post-layout) and 8 (characterization report) all grade against a
**ratified** spec. Since DR-0003 they grade against **eleven binding target
rows**; verdicts against the nine OPEN rows remain provisional by
construction until each row's gate closes.
