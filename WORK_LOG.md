# Work Log

Chronological record of merged pull requests and closed issues, maintained by the Loom Guide role.

### 2026-10-10

- **PR #124**: sim: run reduced lna-linearity cubic control on pinned ngspice in CI
- **PR #119**: sim: qualify LNA two-tone IIP3 and single-tone input P1dB; nominal lna_stage1 record (#57)
- **PR #116**: feat: add pumped mixer RF-port admittance method probe (scalar vs 2x2)
- **PR #115**: spec: carry completed source findings into RF-band and IF rationale
- **PR #114**: Deduplicate probe-log package validation in evidence checker
- **PR #112**: ci: propagate real check failures from single-corner smoke
- **PR #108**: sim: freeze pinned mixer interface-probe runtime evidence (#107)
- **PR #105**: ci: exercise mixer CM-probe controls and sabotages on pinned ngspice
- **PR #102**: fix(sim): close mixer feasibility gate and conclusion validation gaps
- **PR #101**: docs: reconcile active LNA DUT status and characterization claims
- **Issue #122** (closed): ci: run the LNA cubic linearity control on pinned ngspice
- **Issue #57** (closed): sim: qualify LNA two-tone IIP3 and single-tone input P1dB power sweeps
- **Issue #77** (closed): Auditor guard review: retain raw-field body literal-path protection
- **Issue #111** (closed): sim: demonstrate pumped RF admittance for the proposed interstage convention
- **Issue #113** (closed): spec: carry completed source findings into RF-band and IF rationale
- **Issue #109** (closed): Deduplicate mixer probe-log package validation in the evidence checker
- **Issue #92** (closed): ci: propagate real check failures from single-corner smoke
- **Issue #107** (closed): sim: freeze pinned mixer interface-probe runtime evidence
- **Issue #104** (closed): ci: exercise mixer conversion-matrix probe controls on pinned ngspice
- **Issue #45** (closed): fix(sim): close mixer feasibility gate and conclusion validation gaps
- **Issue #94** (closed): docs: reconcile active LNA DUT status and characterization claims
- **PR #95**: sim: conversion-matrix interface probe, checker adapter and go/no-go note (#89)
- **PR #98**: evidence: verify native frozen netlist payload digests
- **PR #96**: sim(passive-p1): reproducible openEMS runner and real solver smoke control
- **PR #88**: spec: ITU Art. 5 table-body check (row 1) and channel-bandwidth source (row 16)
- **PR #87**: ci: bench cold-start READMEs and checked invariant for T1 item 9 preconditions
- **PR #84**: ci: run passive numerical known-answer and sabotage controls (#83)
- **PR #82**: fix(sim): verify full Cartesian PVT coverage before reporting a complete matrix
- **PR #80**: feat: LNA first-stage input-match tradeoff study, fleet record and bound
- **Issue #89** (closed): sim: probe periodic transfer and model-noise interfaces before a mixer NF conversion-matrix solver
- **Issue #93** (closed): evidence: verify native frozen netlist payload digests
- **Issue #46** (closed): sim: prepare a reproducible openEMS runner and solver smoke control
- **Issue #86** (closed): spec: verify row 1 band edges (ITU Art. 5 table body) and row 16 channel bandwidth against primary sources
- **Issue #85** (closed): ci: make T1 item 9 (testbenches shipped) attestable — bench cold-start READMEs and a checked invariant
- **Issue #83** (closed): ci: run passive numerical known-answer and sabotage controls
- **Issue #81** (closed): fix(sim): verify full Cartesian PVT coverage before reporting a complete matrix
- **Issue #41** (closed): Auditor: use literal worktree paths for simulation output confinement
- **Issue #74** (closed): sim: map the first-stage LNA noise versus input-match feasibility tradeoff
- **PR #76**: ci: fix overclaim negative control after #73 (closes #75)
- **PR #73**: row-coverage: refresh rows 2-6/17/18 and flag stale latest_record (#70)
- **PR #72**: signoff: attest T1 item 10 (repo hygiene)
- **PR #69**: sim: mixer-core sizing follow-up after #35 (no acceptable drive at any declared sizing)
- **PR #67**: refactor: share klt-driver helpers across study drivers
- **PR #66**: ci: exercise mixer-topology real-model smoke and negative controls
- **PR #64**: design: first xschem LNA stage (cascode) + ideal-matching feasibility record; signoff item 1 (#28)
- **PR #62**: sim: mixer-topology feasibility collection, record and evidence-format adapter (#35)
- **Issue #75** (closed): ci: main red after #73 — test_check_row_coverage::test_overclaimed_verdict fails
- **Issue #70** (closed): spec: refresh row-coverage.json stale rows 17/18 and latest_record pointers, with a staleness check
- **Issue #71** (closed): signoff: attest T1 item 10 (repo hygiene) and, if checkable, item 9 (testbenches shipped)
- **Issue #40** (closed): Auditor: retain destructive cleanup guard for uncommitted evidence
- **Issue #61** (closed): sim: mixer-core sizing follow-up after the #35 'no acceptable drive' finding
- **Issue #65** (closed): Consolidate duplicated klt driver helpers across sim study scripts
- **Issue #63** (closed): ci: exercise mixer-topology real-model smoke and negative controls
- **Issue #28** (closed): design: first xschem LNA first-stage schematic from the Ka-band HBT characterization (T1 item 1)
- **Issue #35** (closed): sim: mixer-core topology feasibility under the row-17 supply limits (before any mixer schematic)

### 2026-10-09

- **PR #60**: sim: freeze per-record passive solver artifacts before publishing evidence
- **Issue #58** (closed): sim: freeze per-record passive solver artifacts before publishing evidence
- **PR #56**: spec: machine-checked spec-row to bench/record coverage manifest (#50)
- **PR #55**: docs(sim): refresh stale spec-status paragraph in sim/README.md
- **PR #54**: spec: DR-0006 LO source class and port convention (proposed)
- **PR #53**: ci: verify immutable IHP model artifact; simulator smoke/selftest job (#47)
- **PR #49**: ci: run mixer noise-method analytic tests
- **PR #44**: feat(sim): add mixer-topology feasibility bench fixtures and validated extraction
- **Issue #50** (closed): spec: machine-checked spec-row to bench/record coverage manifest (T1 item 5 bookkeeping)
- **Issue #52** (closed): docs: sim/README.md still says the target spec is DRAFT and issue #1 is open
- **Issue #51** (closed): spec: DR-0006 LO source class and port convention (open item 7, gates rows 14/15)
- **Issue #47** (closed): ci: verify an immutable IHP model artifact and run simulator smoke controls
- **Issue #48** (closed): ci: run the existing mixer noise-method analytic tests
- **PR #42**: ci: validate passive and mixer-method records and protect frozen probe logs (#39)
- **PR #37**: sim: mixer SSB-NF method feasibility — MODEL_ABSENT (no intrinsic noise in ngspice .tran) (#27)
- **Issue #39** (closed): ci: validate passive and mixer-method records and protect frozen probe logs
- **Issue #27** (closed): sim: mixer SSB noise-figure measurement method without pnoise (row 10)
- **Issue #17** (closed): sim: Ka-band npn13G2 device characterization (noise-optimum current density, NFmin, fT, available gain at 17.7 / 19.45 / 21.2 GHz), the prerequisite for T1 item 1
- **Issue #18** (closed): ci: run the harness smoke test, the negative control and an evidence-format check on every push (T1 item 10)
- **Issue #20** (closed): Install ratification/ee-key and ratification/market-key reviewer trees (product#151)
- **Issue #21** (closed): Install ratification/ee-key and ratification/market-key reviewer trees (product#151)
- **Issue #22** (closed): sim/lna-sparam-nf: NF reference source is at 327.15 K, not 300.15 K (ngspice-46 resistor temp= behaviour); needs a correction record
- **Issue #25** (closed): sim: 20 GHz passive characterization (EM-extracted spiral / t-line / MIM) to unblock matching-network rows
- **Issue #26** (closed): spec: decision record 0004 — LNA→mixer interface convention (50 Ω back-to-back vs co-designed match)
- **Issue #29** (closed): spec: replace (E)/NEEDS-VERIFICATION flags with checkable literature citations
- **PR #23**: sim: Ka-band npn13G2 device characterization (NFmin, fT, MAG/MSG at 17.7/19.45/21.2 GHz)
- **PR #24**: ci: harness tests, evidence-format checker and append-only check (T1 item 10)
- **PR #30**: ratification: install ee-key and market-key reviewer trees; correct DR-0003 Status
- **PR #31**: lna-sparam-nf: correct NF reference source; superseding 27-point record (#22)
- **PR #32**: spec: DR-0004 proposed — LNA→mixer interface convention (#26)
- **PR #33**: spec: literature citation table for (E)/NEEDS-VERIFICATION rows (#29)
- **PR #34**: sim: bounded p1-only passive campaign (CAPABILITY_UNAVAILABLE) + DR-0005 deferred (#25)

### 2026-09-21

- **PR #13**: spec: DR-0003 target-spec first ratification pass — 11 rows ratified as targets, 9 explicitly open
- **Issue #11** (closed): spec: ratify target-spec.md — it is DRAFT, which blocks T1 item 5 (and items 6/7/8 that grade against its rows)
- **PR #12**: feat: add klt signoff block manifest, graded T1 report, and CI gate
- **Issue #10** (closed): Commit a klt signoff block manifest so this block's T1 state is graded, not hand-read

### 2026-09-12

- **Issue #9** (closed): Remove unused pdk_available() helper in sim/harness/pdk.py
- **Issue #2** (closed): Harness bootstrap: LNA S-parameter/NF bench and mixer bench on the scaffold's sim/harness core
- **PR #6**: sim: harness bootstrap -- LNA S-parameter/NF and mixer conversion/IIP3 benches
- **Issue #7** (closed): Remove unused pdk_available() helper in sim/harness/pdk.py
- **PR #8**: Remove unused pdk_available() helper in sim/harness/pdk.py
- **Issue #1** (closed): Ratify the target spec: Ka-band receive front end (LNA + mixer) — draft spec, porting plan, band and beamsteering decision records, gap-to-T1 tracker
- **PR #5**: spec: draft the Ka-band target spec, porting plan, and the band + beamsteering decision records
