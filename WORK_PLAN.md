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

- **#110**: sim: execute the prepared p1 EM campaign and reproduce frozen results

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#300**: Evidence checker rejects the `"-inf"` floor_dbm encoding the #268 watts-to-dBm convention can now produce
- **#306**: sha256 harness guard: class methods and aliased hashlib imports are still outside the needle
- **#307**: test_rf.py: the probe selector's 'fallback scan found a probe' branch has no test

## In Progress

Issues currently being built (`loom:building`).

- **#266**: Ratify a coherent-bin criterion in spec/: the two coherence_problems disagree 1000x in tolerance and 4x in Nyquist margin, and neither is ratified (decision record only, no code)
- **#286**: Decide whether the ten z0=50.0 function defaults in matchstudy/kaband are the same constant as harness.rf.Z0_OHM
- **#287**: Running several sim/*/tests dirs in one pytest invocation fails at collection: bare 'from conftest import' collides across benches
- **#299**: Decision record: which IIP3 intercept definition is the single reference for the Python fitters
- **#302**: Multi-bench pytest run (not just collection) fails in 3 benches that bare-import run_probe.py / ci_assert.py
- **#310**: Wire in or remove unused block_coverage evidence check (never called by CI checker)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#320**: test(sim): isolate bench pytest namespaces so multi-bench runs pass

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#38**: Auditor Capability Request: Python runtime for local harness smoke validation *(curated)*
- **#110**: sim: execute the prepared p1 EM campaign and reproduce frozen results *(curated)*
- **#266**: Ratify a coherent-bin criterion in spec/: the two coherence_problems disagree 1000x in tolerance and 4x in Nyquist margin, and neither is ratified (decision record only, no code) *(curated)*
- **#286**: Decide whether the ten z0=50.0 function defaults in matchstudy/kaband are the same constant as harness.rf.Z0_OHM *(curated)*
- **#287**: Running several sim/*/tests dirs in one pytest invocation fails at collection: bare 'from conftest import' collides across benches *(curated)*
- **#299**: Decision record: which IIP3 intercept definition is the single reference for the Python fitters *(curated)*
- **#300**: Evidence checker rejects the `"-inf"` floor_dbm encoding the #268 watts-to-dBm convention can now produce *(curated)*
- **#302**: Multi-bench pytest run (not just collection) fails in 3 benches that bare-import run_probe.py / ci_assert.py *(curated)*
- **#306**: sha256 harness guard: class methods and aliased hashlib imports are still outside the needle *(curated)*
- **#307**: test_rf.py: the probe selector's 'fallback scan found a probe' branch has no test *(curated)*

## Proposed (Architect / Hermit)

- **#252**: Remove the inert toolchain pin subsystem: sim/harness/toolchain.py checks a pins file that has never existed *(hermit)*
- **#254**: Remove the duplicated SPICE deck in sim/mixer-conversion-iip3-convstudy (byte-identical netlist, drifted header) and cite the study from the records it derives *(hermit)*
- **#257**: Consolidate the RF/DSP arithmetic duplicated across sim campaigns: two reference DFTs, two definitions of a coherent bin, three dB conventions *(hermit)*
- **#258**: Remove the root package.json: an uncustomized Loom workspace stub whose test/lint/check scripts echo "not configured" and exit 0 *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 1 |
| Ready (`loom:issue`) | 3 |
| In Progress (`loom:building`) | 6 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 0 |
| Curated | 10 |
| Architect / Hermit proposals | 4 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
