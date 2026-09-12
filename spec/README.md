# spec — target specification, porting plan, decision records

```
spec/
  README.md                 this file
  target-spec.md            the DRAFT target-spec table: per-corner rows, a
                              source citation per row, the 50 Ω port
                              convention, AREA + AREA-EFF
  porting-plan.md           what transfers from sg13g2-lna / sg13g2-vco /
                              sg13g2-comparator, the exact IHP-Open-PDK model
                              files this block depends on, and what is
                              genuinely new (the mixer bench, 20 GHz passives)
  decision-records/
    TEMPLATE.md             copy this to start a new record
    0001-band-selection-ka-vs-ku.md    band (proposed, with the Ku trigger)
    0002-beamsteering-partition.md     beamsteering (deferred, on purpose)
```

## Status: nothing here is ratified

[`target-spec.md`](target-spec.md) is **DRAFT**. So is the band
([DR-0001](decision-records/0001-band-selection-ka-vs-ku.md), status
*proposed*). The beamsteering partition
([DR-0002](decision-records/0002-beamsteering-partition.md)) is *deferred* —
a recorded decision not to decide yet, not a default.

No design, layout, or simulation work may cite a row in `target-spec.md` as
settled. Work may proceed *against* the draft; it may not claim *compliance*
with it.

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

Ratification flows through the standard **two-key mechanism (EE key + market
key, both installed by the standard tooling)**; a scope-only spec DR ratified
with both keys needs no per-PR operator statement. Wording adopted from
[`sg13g2-comparator/spec/README.md`](https://github.com/2AMLogic/sg13g2-comparator/blob/main/spec/README.md).

**An agent does not turn either key.** An agent writes the record, argues it,
and leaves it `proposed`.

## The largest open gap, named here so it is not lost

`target-spec.md`'s source class **(E)** marks every row whose bound is an
engineering target rather than a traceable citation. The environment those
documents were written in had **no literature access**, so no published SiGe
Ka-band LNA or active-mixer result could be checked — and inventing one would
have been worse than flagging it. **Replacing every (E) flag with a real,
checkable citation is a precondition of ratification**, and it is open item 1
in `target-spec.md`.

The same applies to the band edges themselves (17.7–21.2 GHz) and the LEO
channel-bandwidth assumption behind the IF row: both are flagged
`NEEDS-VERIFICATION` in place rather than presented as sourced.

## Where the downstream consequences are tracked

[Issue #4](https://github.com/2AMLogic/sg13g2-sat-rx/issues/4) — the
gap-to-T1 tracker — holds the honest, artifact-presence survey of everything
that sits downstream of ratification. T1 items 5 (full corner verification),
7 (post-layout) and 8 (characterization report) all grade against a
**ratified** spec, so none of them can close until this directory's table
stops being DRAFT.
