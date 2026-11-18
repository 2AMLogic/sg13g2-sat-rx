# Work Plan

This roadmap is generated from the repository's current GitHub label state by the Loom Guide role.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

- **#110**: sim: execute the prepared p1 EM campaign and reproduce frozen results *(held)*

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#332**: Guide docs-maintenance PR bodies emit "closed #N", which auto-closes N on merge

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#333**: fix: keep closing keywords out of Guide docs-PR bodies

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#38**: Auditor Capability Request: Python runtime for local harness smoke validation *(curated)* *(held)*
- **#110**: sim: execute the prepared p1 EM campaign and reproduce frozen results *(curated)* *(held)*
- **#332**: Guide docs-maintenance PR bodies emit "closed #N", which auto-closes N on merge *(curated)*

## Proposed (Architect / Hermit)

- **#252**: Remove the inert toolchain pin subsystem: sim/harness/toolchain.py checks a pins file that has never existed *(hermit)* *(held)*
- **#254**: Remove the duplicated SPICE deck in sim/mixer-conversion-iip3-convstudy (byte-identical netlist, drifted header) and cite the study from the records it derives *(hermit)* *(held)*
- **#258**: Remove the root package.json: an uncustomized Loom workspace stub whose test/lint/check scripts echo "not configured" and exit 0 *(hermit)* *(held)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 1 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 0 |
| Curated | 3 |
| Architect / Hermit proposals | 3 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
