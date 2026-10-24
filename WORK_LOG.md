# Work Log

Chronological record of merged pull requests and closed issues, maintained by the Loom Guide role.

### 2026-10-23

- **PR #231**: docs(manifests): record klt artifact delete/prune gap with upstream link
- **Issue #229** (closed): Follow-on from PR #227: live-verify stored harness evidence with klt artifact verify
- **PR #227**: feat(sim): store new harness evidence in the artifact store, commit manifests
- **Issue #226** (closed): Adopt the common artifact store for sim evidence (manifests in git, bytes via klt artifact)

### 2026-10-22

- **PR #224**: refactor(sim): share MARK-log parsing and pdk_integrity in harness.provenance
- **Issue #223** (closed): Consolidate MARK-log parser and pdk_integrity duplicated across sim probe drivers

### 2026-10-20

- **PR #220**: refactor: drop unreachable hbt-mismatch-pair statuses and evaluate_failure
- **Issue #219** (closed): Remove unreachable hbt-mismatch-pair statuses and the unused evaluate_failure()
- **PR #216**: test: share run/commit/edit_json/assertFails helpers across evidence-checker tests
- **Issue #215** (closed): Share duplicated run/commit/edit_json/assertFails helpers across evidence-checker tests
- **PR #214**: test: surface git output when evidence-format fixture commands fail
- **Issue #213** (closed): test flake: test_history_deleting_corner_log_fails errors in fixture git clone on evidence-formats job
- **PR #210**: refactor: share record-commit check across evidence adapters, drop dead helpers
- **Issue #209** (closed): Dedupe evidence-adapter commit check and remove dead imports/helpers
- **PR #206**: refactor(sim): share klt corner-log resolution via klt_driver.corner_log_path
- **Issue #204** (closed): Consolidate six copies of klt corner-log resolution into klt_driver
- **PR #205**: docs(spec): record third source-retrieval attempt for DR-0008
- **PR #203**: docs(spec): record second citation retrieval attempt for DR-0008 sources

### 2026-10-19

- **PR #201**: docs(spec): propose DR-0008 comparing mixer LO-drive paths (Part of #68)

### 2026-10-17

- **PR #199**: docs(layout): re-run klt readiness probe at klt 44cc423; DRC clean, rsil extracts, HBT blocked
- **Issue #197** (closed): layout: re-run the klt layout-chain readiness probe at a klt release with the resistor and contact-rule fixes (T1 items 2-4, 11)

### 2026-10-14

- **Issue #15** (closed): README: embed the fleet burndown chart (one line)

### 2026-10-13

- **PR #192**: signoff: negative controls for item 1/10 evidence generators (#191)
- **Issue #191** (closed): signoff: negative-control tests and byte-compile coverage for the item-1 and item-10 evidence generators

### 2026-10-12

- **PR #190**: sim/mixer-conversion-iip3: publish iip3_dbm as slope-3-constrained top-of-fit read
- **PR #189**: sim(hbt-mismatch-pair): Monte Carlo mismatch-card method probe on a matched npn13G2 pair
- **PR #188**: feat(layout): non-claiming klt layout-chain readiness probe (npn13G2 + cmim + rsil)
- **Issue #186** (closed): sim: Monte Carlo mismatch-card method probe on a matched npn13G2 pair (prepares T1 item 6 / row 15)
- **Issue #185** (closed): layout: non-claiming klt layout-chain readiness probe (npn13G2 + MIM + resistor) before the LNA layout
- **Issue #181** (closed): mixer-conversion-iip3: iip3_dbm local-vs-batch agreement is ~1.4 dB, not the 0.1 dB criterion (low-drive IM3 tolerance fragility)
- **PR #184**: evidence(signoff): attest T1 item 9 (testbenches shipped) with pinned-PDK lna-sparam-nf record
- **Issue #183** (closed): spec: cascade gain/NF margin analysis (Friis cross-check) for open rows 12-13
- **Issue #182** (closed): signoff: attest T1 item 9 (testbenches shipped) with a pinned-PDK bench record
- **PR #180**: mixer-conversion-iip3: swept two-tone IIP3 bench with one-tone floor control, convergence study and backend evidence
- **Issue #165** (closed): mixer-conversion-iip3: a method that actually resolves IM3/IIP3 (current IM3 read sits on the transient interpolation-error floor)
- **PR #177**: docs+ci: index every bench in sim/README.md Benches table (#175)
- **Issue #175** (closed): docs: sim/README.md Benches table omits lna-headroom and lna-linearity
- **PR #174**: test: make evidence-format marker-record fixtures glob-order independent
- **Issue #171** (closed): Test fixture _marker_record in test_check_evidence_formats.py depends on glob order of mixer-conversion-iip3 records
- **PR #173**: signoff: state item 1 attests LNA stage only (block_coverage)
- **Issue #170** (closed): signoff: state that T1 item 1 attests the LNA stage only (mixer has no design source)
- **PR #172**: Consolidate duplicated klt submit/CollectionError/provenance helpers in sim drivers
- **Issue #169** (closed): Consolidate duplicated klt submit/CollectionError/provenance helpers in sim drivers
- **PR #167**: Split check_evidence_formats.py into evidence_checks package (#163)
- **Issue #163** (closed): ci: split the 2,930-line check_evidence_formats.py into per-bench modules behind the same CLI
- **PR #164**: mixer-conversion-iip3: power-of-two FFT window, corrected FFT notes, supersession record (#135)

### 2026-10-11

- **PR #166**: docs: fix stale Pdk.version 'unknown' claim in sim/README.md
- **Issue #162** (closed): docs: sim/README.md still says Pdk.version stays 'unknown' for IHP (stale after #155)
- **PR #160**: refactor: consolidate probe provenance helpers into harness.provenance
- **Issue #144** (closed): Consolidate duplicated provenance helpers in mixer probe drivers into the harness
- **PR #159**: spec: per-row statistical classification and DR-0007 (#156)
- **Issue #156** (closed): spec: classify each target-spec row as statistical or deterministic for T1 item 6
- **PR #158**: harness: Pdk.version reads the installed .fetched-version marker
- **Issue #155** (closed): harness: report the installed PDK revision from .fetched-version instead of 'unknown'
- **PR #154**: harness: refuse PVT grids whose points alias one artifact id, before dispatch
- **PR #153**: harness: reject non-finite and malformed numeric grading bounds
- **PR #151**: harness: freeze the testbench manifest next to each record's DUT snapshot
- **PR #148**: ci: bound every workflow job with timeout-minutes
- **PR #147**: fix: reject duplicate PVT identities in klt batch report collection
- **PR #146**: sim(passive-p1): make the pipeline control immune to same-second record ids (#97)
- **PR #145**: docs: reproduce guard classification of inert source and executed cleanup
- **PR #142**: harness: local grading requires clean execution and finite values (#138)
- **PR #137**: ingest: validate stage1 tables before publishing record (#130)
- **PR #136**: harness: route multi-point grids through klt sim batch (#134)
- **PR #133**: sim(lna-headroom): cascode bias/load headroom screening, stage 1 (#123)
- **PR #131**: sim(mixer-pumped-rf-admittance): replay frozen logs with their recorded thresholds
- **PR #128**: sim: qualify collector-current diagnostics for nonlinear LNA fits (plan v2)
- **Issue #150** (closed): harness: reject artifact filename collisions before PVT dispatch
- **Issue #149** (closed): harness: reject non-finite and malformed numeric grading bounds
- **Issue #143** (closed): ci: bound every workflow job with timeout-minutes and guard it in test_ci_pins
- **Issue #141** (closed): harness: freeze native testbench manifests with each evidence record
- **Issue #140** (closed): docs: reproduce guard classification of inert source and executed cleanup
- **Issue #139** (closed): harness: reject duplicate PVT identities in batch reports
- **Issue #138** (closed): harness: reject failed local simulator runs with complete measurements
- **Issue #134** (closed): harness: route multi-point grids through klt sim batch instead of a local ngspice loop
- **Issue #130** (closed): sim: preflight LNA stability tables before publishing evidence
- **Issue #129** (closed): sim: replay pumped-admittance logs with their recorded thresholds
- **Issue #123** (closed): sim: map cascode bias and output-load headroom before a stress-valid P1dB claim
- **Issue #121** (closed): sim: qualify collector-current diagnostics for nonlinear LNA fits
- **Issue #120** (closed): Auditor guard review: retain scoped stash protection
- **Issue #106** (closed): passive-p1 pipeline control flakes: same-second record-id collision on rerun
- **Issue #100** (closed): Flaky: passive-p1 controls.py 'pipeline' control failed once in CI (rerun_digest_equal=false)
- **Issue #97** (closed): ci: passive-p1 synthetic pipeline control is intermittently failing (rerun_digest_equal false)
- **Issue #91** (closed): Auditor: keep git clean -fd guarded against uncommitted loss

### 2026-10-10

- **PR #118**: ci: guard that every sim bench tests file is run by ci.yml
- **PR #126**: sim: carry verified PDK artifact identity into native evidence provenance
- **Issue #117** (closed): ci: guard that every sim bench tests directory is run by ci.yml
- **Issue #103** (closed): sim: carry verified PDK artifact identity into native evidence provenance
- **Issue #90** (closed): Auditor: guard rejects worktree writes with unresolved variables
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
