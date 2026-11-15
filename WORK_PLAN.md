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
- **#260**: layout: bump the klt pin to 0.9.0 and verify runset-backed LVS recognises npn13G2 (T1 item 4 route)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#255**: Consolidate the evidence checker's three identical probe-log bench entry points and re-home its shared helper into common.py
- **#259**: Rename frozen_dut.sha256_bytes (it hashes a file, not bytes) and widen the harness single-hash guard past the 3 modules it inspects
- **#260**: layout: bump the klt pin to 0.9.0 and verify runset-backed LVS recognises npn13G2 (T1 item 4 route)
- **#263**: Consolidate the dB and power conversions (two naming schemes, three db* helpers, three Z0_OHM copies) into harness/rf.py, preserving each site's zero/NaN edge
- **#264**: Unify the two reference single-bin DFTs into harness/rf.py: measured as exact conjugates (e^+jwt vs e^-jwt), not the same expression their docstrings claim
- **#268**: Pick one zero/NaN convention for watts-to-dBm: linearity.dbm_from_w turns NaN into a finite -400 dBm while mixfeas.dbm propagates it (latent, guarded upstream today)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#245**: docs: roadmap as of 2026-11-13
- **#271**: fix: propagate NaN in watts-to-dBm instead of returning a finite -400 dBm
- **#280**: refactor(harness): rename sha256_bytes to sha256_path and widen the single-hash guard past three modules
- **#282**: layout: bump klt pin to 0.9.0 and record the PDK-runset LVS route

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#267**: refactor(evidence-checks): give the probe-log bench layout one home in common.py
- **#283**: rf: unify the two single-bin reference DFTs into harness/rf (deck-verified +j kernel)
- **#285**: refactor(sim): consolidate dB and power conversions into harness/rf, preserving each site's zero/NaN edge

## Proposed

Issues carrying `loom:curated`.

- **#38**: Auditor Capability Request: Python runtime for local harness smoke validation *(curated)*
- **#110**: sim: execute the prepared p1 EM campaign and reproduce frozen results *(curated)*
- **#260**: layout: bump the klt pin to 0.9.0 and verify runset-backed LVS recognises npn13G2 (T1 item 4 route) *(curated)*
- **#266**: Ratify a coherent-bin criterion in spec/: the two coherence_problems disagree 1000x in tolerance and 4x in Nyquist margin, and neither is ratified (decision record only, no code) *(curated)*
- **#276**: Two independent fit_iip3 implementations use different IIP3 estimators (free-slope intersection vs ideal-slope intercept) and can return different values for the same sweep rows *(curated)*
- **#277**: No stamped-copy convention or reuse.lock.json declaring the masters of the mechanics sibling repos consume from this repo *(curated)*
- **#278**: layout/lna_stage1/generate.py: guard-ring containment check asserts 'at least one bus inside', not 'every bus inside' *(curated)*

## Proposed (Architect / Hermit)

- **#252**: Remove the inert toolchain pin subsystem: sim/harness/toolchain.py checks a pins file that has never existed *(hermit)*
- **#254**: Remove the duplicated SPICE deck in sim/mixer-conversion-iip3-convstudy (byte-identical netlist, drifted header) and cite the study from the records it derives *(hermit)*
- **#257**: Consolidate the RF/DSP arithmetic duplicated across sim campaigns: two reference DFTs, two definitions of a coherent bin, three dB conventions *(hermit)*
- **#258**: Remove the root package.json: an uncustomized Loom workspace stub whose test/lint/check scripts echo "not configured" and exit 0 *(hermit)*
- **#272**: Delete the duplicate corner-id formatter in the evidence checker, and re-home the five shared names its bench adapters import from each other *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 2 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 6 |
| PRs awaiting review | 4 |
| Approved PRs awaiting merge | 3 |
| Curated | 7 |
| Architect / Hermit proposals | 5 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
