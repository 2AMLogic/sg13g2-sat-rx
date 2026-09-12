# 0000: <short title>

<!--
Copy this file to spec/decision-records/NNNN-<slug>.md and fill it in.
Use the next unused NNNN (zero-padded 4 digits). One decision per record;
keep it to one page where the decision allows it. A decision record is
required for every spec change (see CLAUDE.md). Do not delete or rewrite a
ratified record — supersede it with a new, higher-numbered one that says why.

Numbering rule: before picking NNNN, check every filename already in this
directory on `main` (including superseded records) and use one greater than
the highest number found — never guess or reuse a number, and re-check if
another record may have landed concurrently, to avoid a collision.

Convention note: this repo uses the `NNNN-<slug>.md` numbering adopted from
2AMLogic/sg13g2-bandgap/spec/decision-records/. Nothing about the choice is
load-bearing beyond consistency.

Status values:
  proposed        — written, argued, NOT ratified. Design work may read it;
                    no claim may cite it as settled.
  ratified        — both keys turned (EE key + market key). Binding.
  deferred        — a decision to NOT decide yet, with the criteria that
                    will decide it recorded. This is a real, citable
                    outcome, not an empty record.
  superseded by NNNN
-->

- **Status**: proposed | ratified | deferred | superseded by NNNN
- **Date**: YYYY-MM-DD
- **Decided by**: <name / role>
- **Ratification**: two-key (EE key + market key) — state whether either key
  has been turned, and do not mark `ratified` without both.

## Context

What forced this decision? The constraint, the measurement, or the conflict
that made the current spec inadequate. Link the issue, the `sim/` evidence, or
the prior record this revises. If a number appears here, it carries its source.

## Decision

Stated as a change to the spec — the parameter and its new value, or the
approach now adopted. Specific enough that design work can lock to it without
further interpretation. If the decision is to defer, say what is deferred, and
put the deciding criteria under "What will decide this".

## Argument

Why this and not the alternatives. Every number cited with its source; every
number that is an estimate marked as an estimate.

## Alternatives considered

- **<alternative>** — why it was not chosen, on what evidence.

## Trigger to revisit / what will decide this

The explicit, checkable condition under which this record is superseded. A
record whose revisit condition is "if we change our minds" has not stated one.

## Consequences

What follows: what becomes possible, what becomes harder, which testbenches or
corner sets change, what work is invalidated or must be re-run. **Include the
bad consequences, not just the good ones.**
