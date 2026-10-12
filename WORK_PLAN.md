# Work Plan

This roadmap is generated from the repository's current GitHub label state by the Loom Guide role.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs stuck under a `loom:operator` merge-risk hold — implementation work is done, only a human merge decision is missing.

_None._

## Operator Priority

Issues the operator starred (`loom:operator-priority`); land these first.

_None._

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#163**: ci: split the 2,930-line check_evidence_formats.py into per-bench modules behind the same CLI

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#167**: Split check_evidence_formats.py into evidence_checks package (#163)

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#38**: Auditor Capability Request: Python runtime for local harness smoke validation *(curated)*
- **#79**: design: choose the first-stage core change that lets NF and input match close together *(curated)*
- **#132**: sim: refine headroom shortlist (C08/C05) - convergence, two-tone IIP3, gain/NF/stability vs baseline *(curated)*
- **#135**: mixer-conversion-iip3: FFT-bin metrics depend on the ngspice FFT build (local zero-padded vs batch unpadded) *(curated)*
- **#163**: ci: split the 2,930-line check_evidence_formats.py into per-bench modules behind the same CLI *(curated)*

## Proposed (Architect / Hermit)

_None._

## Epics

_None._

## Backlog Balance

| Tier | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Operator priority | 0 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 0 |
| Curated | 5 |
| Architect / Hermit proposals | 0 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
