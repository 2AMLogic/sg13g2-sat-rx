# Work Plan

This roadmap is generated from the repository's current GitHub label state by the Loom Guide role.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#250**: Re-characterize the post-#79 LNA first-stage core (S-parameters, NF, linearity, headroom)

## Important

`loom:important`; taken before unlabelled work.

- **#110**: sim: execute the prepared p1 EM campaign and reproduce frozen results
- **#198**: layout: LNA stage-1 layout with DRC, LVS and ERC supply evidence (T1 items 2, 3, 4, 11)
- **#260**: layout: bump the klt pin to 0.9.0 and verify runset-backed LVS recognises npn13G2 (T1 item 4 route)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#259**: Rename frozen_dut.sha256_bytes (it hashes a file, not bytes) and widen the harness single-hash guard past the 3 modules it inspects
- **#261**: Two guard tests name a universe they do not inspect: bench discovery checks 3 of 5 benches, workflow timeouts a hardcoded 2-file list
- **#262**: Consolidate K_BOLTZMANN (4 copies) and the noiseless-source noise factor (4 sites) into a new sim/harness/rf.py, with T0 a required argument

## In Progress

Issues currently being built (`loom:building`).

- **#198**: layout: LNA stage-1 layout with DRC, LVS and ERC supply evidence (T1 items 2, 3, 4, 11)
- **#255**: Consolidate the evidence checker's three identical probe-log bench entry points and re-home its shared helper into common.py
- **#268**: Pick one zero/NaN convention for watts-to-dBm: linearity.dbm_from_w turns NaN into a finite -400 dBm while mixfeas.dbm propagates it (latent, guarded upstream today)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#245**: docs: roadmap as of 2026-11-13
- **#267**: refactor(evidence-checks): give the probe-log bench layout one home in common.py
- **#269**: layout(lna_stage1): record why T1 items 2/3 cannot be claimed, with the klt chain run

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#38**: Auditor Capability Request: Python runtime for local harness smoke validation *(curated)*
- **#110**: sim: execute the prepared p1 EM campaign and reproduce frozen results *(curated)*
- **#198**: layout: LNA stage-1 layout with DRC, LVS and ERC supply evidence (T1 items 2, 3, 4, 11) *(curated)*
- **#250**: Re-characterize the post-#79 LNA first-stage core (S-parameters, NF, linearity, headroom) *(curated)*

## Proposed (Architect / Hermit)

- **#252**: Remove the inert toolchain pin subsystem: sim/harness/toolchain.py checks a pins file that has never existed *(hermit)*
- **#254**: Remove the duplicated SPICE deck in sim/mixer-conversion-iip3-convstudy (byte-identical netlist, drifted header) and cite the study from the records it derives *(hermit)*
- **#257**: Consolidate the RF/DSP arithmetic duplicated across sim campaigns: two reference DFTs, two definitions of a coherent bin, three dB conventions *(hermit)*
- **#258**: Remove the root package.json: an uncustomized Loom workspace stub whose test/lint/check scripts echo "not configured" and exit 0 *(hermit)*
- **#263**: Consolidate the dB and power conversions (two naming schemes, three db* helpers, three Z0_OHM copies) into harness/rf.py, preserving each site's zero/NaN edge *(hermit)*
- **#264**: Unify the two reference single-bin DFTs into harness/rf.py: measured as exact conjugates (e^+jwt vs e^-jwt), not the same expression their docstrings claim *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 1 |
| Important | 3 |
| Ready (`loom:issue`) | 3 |
| In Progress (`loom:building`) | 3 |
| PRs awaiting review | 3 |
| Approved PRs awaiting merge | 0 |
| Curated | 4 |
| Architect / Hermit proposals | 6 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
