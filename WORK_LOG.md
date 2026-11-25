# Work Log

Chronological record of merged pull requests and closed issues, maintained by the Loom Guide role.

## Archives

- [2026-09](work_log/WORK_LOG_2026-09.md)

### 2026-11-24

- **PR #353**: refactor: collapse lna-headroom finalize/finalize_refined, drop dead _conv_line
- **Issue #351** (closed): Deduplicate finalize/finalize_refined and remove dead _conv_line in sim/lna-headroom/run.py

### 2026-11-23

- **PR #350**: docs(sim): cite convstudy dir in mixer IIP3 README and sync drifted deck header
- **Issue #254** (closed): Remove the duplicated SPICE deck in sim/mixer-conversion-iip3-convstudy (byte-identical netlist, drifted header) and cite the study from the records it derives
- **PR #347**: fix: fail npm checks honestly and drop dangling worktree:return alias
- **Issue #258** (closed): Keep the root package.json and make npm checks report skipped verification

### 2026-11-19

- **PR #338**: signoff: grade against the klt wheel's bundled checklist
- **Issue #336** (closed): Use the pinned klayout-tools checklist for T1 signoff

### 2026-11-18

- **PR #333**: fix: keep closing keywords out of Guide docs-PR bodies
- **Issue #332** (closed): Guide docs-maintenance PR bodies emit "closed #N", which auto-closes N on merge
- **Issue #286** (closed): Decide whether the ten z0=50.0 function defaults in matchstudy/kaband are the same constant as harness.rf.Z0_OHM

### 2026-11-17

- **PR #331**: docs: state the sha256 alias guard's file-wide collection scope
- **Issue #330** (closed): sha256 guard: rebound-name aliases are collected file-wide, so a shadowed name in another def can false-positive
- **PR #329**: test: catch sha256 rebound to a bare name and record the guard's enforced scope
- **Issue #328** (closed): sha256 single-definition guard: digest must be reached by a direct call, and same-named defs in one file collapse
- **PR #327**: test: widen sha256 single-definition guard to class methods and aliased hashlib imports
- **Issue #306** (closed): sha256 harness guard: class methods and aliased hashlib imports are still outside the needle
- **PR #326**: fix: accept the "-inf" floor_dbm encoding at the lna-linearity evidence gate
- **Issue #300** (closed): Evidence checker rejects the `"-inf"` floor_dbm encoding the #268 watts-to-dBm convention can now produce
- **PR #325**: test: cover the probe selector's fallback-scan return branch
- **Issue #307** (closed): test_rf.py: the probe selector's 'fallback scan found a probe' branch has no test
- **PR #313**: spec: propose IIP3 intercept reference definition (DR-0010, proposed)
- **Issue #299** (closed): Decision record: which IIP3 intercept definition is the single reference for the Python fitters
- **PR #292**: spec: propose coherent-bin criterion 0009 with committed cross-criterion measurement
- **Issue #266** (closed): Ratify a coherent-bin criterion in spec/: the two coherence_problems disagree 1000x in tolerance and 4x in Nyquist margin, and neither is ratified (decision record only, no code)
- **Issue #257** (closed): Consolidate the RF/DSP arithmetic duplicated across sim campaigns: two reference DFTs, two definitions of a coherent bin, three dB conventions

### 2026-11-16

- **Issue #322** (closed): sim/README.md one-bench-per-invocation note (PR #294) contradicts the multi-bench support landed by PR #320
- **PR #294**: fix: remove pytest flat-namespace collection collisions across sim benches
- **Issue #287** (closed): Running several sim/*/tests dirs in one pytest invocation fails at collection: bare 'from conftest import' collides across benches
- **PR #311**: refactor(sim): bind Class A z0 defaults to rf.Z0_OHM; close pumped synth_marks divergence
- **PR #319**: ci: run the block-coverage honesty check in check_format
- **Issue #310** (closed): Wire in or remove unused block_coverage evidence check (never called by CI checker)
- **PR #320**: test(sim): isolate bench pytest namespaces so multi-bench runs pass
- **Issue #302** (closed): Multi-bench pytest run (not just collection) fails in 3 benches that bare-import run_probe.py / ci_assert.py
- **PR #318**: fix: use ast to decide declared-master symbols in reuse guard
- **Issue #312** (closed): reuse_masters: column-0 docstring text counts as a top-level definition (measured), plus two adjacent precision gaps
- **PR #316**: docs: point README roadmap line at docs/ROADMAP.md, keep WORK_PLAN.md as queue view
- **Issue #309** (closed): README calls WORK_PLAN.md "the current roadmap" and does not link docs/ROADMAP.md
- **PR #317**: docs: list DR-0006 and DR-0007 in the spec/README decision-record index
- **Issue #315** (closed): spec/README.md decision-record index omits DR-0006, DR-0007 (and any new record)
- **PR #289**: feat: declare reuse masters (reuse.lock.json) with a CI pointer check
- **Issue #277** (closed): No stamped-copy convention or reuse.lock.json declaring the masters of the mechanics sibling repos consume from this repo
- **PR #304**: test: pin the dft_bin_amplitude accessor's rounding-order bits
- **Issue #284** (closed): Pin harness.rf.dft_bin_amplitude's exact bits: an abs(dft_bin(...)) simplification would move recorded amplitudes with green tests
- **PR #297**: test: make the pow-vs-multiply probe platform-conditional via a seeded F-divergence selector
- **Issue #279** (closed): test_rf.py's concrete pow-vs-multiply probe hard-asserts a libm property, so a correctly-rounded pow would fail CI
- **PR #305**: test: catch aliased sha256 file hashers in the harness via an AST check
- **PR #303**: lna-linearity: pin the DUT by declaration, run the post-#79 core campaign, supersede the pre-#79 record
- **PR #245**: docs: roadmap as of 2026-11-13
- **Issue #291** (closed): The harness single-hash guard matches one spelling (def sha256_file) — a differently-named file hash still passes it
- **Issue #273** (closed): Re-run sim/lna-linearity on the post-#79 core (new declaration, one campaign)
- **PR #293**: refactor: single-source the two-tone IIP3 estimator into sim/harness/iip3.py
- **Issue #276** (closed): Two independent fit_iip3 implementations use different IIP3 estimators (free-slope intersection vs ideal-slope intercept) and can return different values for the same sweep rows
- **PR #295**: docs: drop stale tool-provenance prose from lna_stage1 note and nf fixture
- **Issue #256** (closed): design/lna_stage1.md: two stale tool-provenance lines in the Files table
- **PR #301**: refactor: share the sidecar-group bench layout and tighten hbt-mismatch-pair's evidence gate
- **Issue #265** (closed): Extend the evidence checker's layout consolidation to the sidecar-group benches and the hbt-mismatch-pair adapter
- **PR #271**: fix: propagate NaN in watts-to-dBm instead of returning a finite -400 dBm
- **Issue #268** (closed): Pick one zero/NaN convention for watts-to-dBm: linearity.dbm_from_w turns NaN into a finite -400 dBm while mixfeas.dbm propagates it (latent, guarded upstream today)
- **PR #298**: fix: assert guard-ring containment on drawn bus boxes by identity, naming escapes
- **Issue #278** (closed): layout/lna_stage1/generate.py: guard-ring containment check asserts 'at least one bus inside', not 'every bus inside'

### 2026-11-15

- **PR #296**: refactor: re-home the evidence checker's shared scalar helpers into common.py
- **Issue #272** (closed): Delete the duplicate corner-id formatter in the evidence checker, and re-home the five shared names its bench adapters import from each other
- **PR #285**: refactor(sim): consolidate dB and power conversions into harness/rf, preserving each site's zero/NaN edge
- **Issue #263** (closed): Consolidate the dB and power conversions (two naming schemes, three db* helpers, three Z0_OHM copies) into harness/rf.py, preserving each site's zero/NaN edge
- **PR #267**: refactor(evidence-checks): give the probe-log bench layout one home in common.py
- **Issue #255** (closed): Consolidate the evidence checker's three identical probe-log bench entry points and re-home its shared helper into common.py
- **PR #280**: refactor(harness): rename sha256_bytes to sha256_path and widen the single-hash guard past three modules
- **Issue #259** (closed): Rename frozen_dut.sha256_bytes (it hashes a file, not bytes) and widen the harness single-hash guard past the 3 modules it inspects
- **PR #283**: rf: unify the two single-bin reference DFTs into harness/rf (deck-verified +j kernel)
- **Issue #264** (closed): Unify the two reference single-bin DFTs into harness/rf.py: measured as exact conjugates (e^+jwt vs e^-jwt), not the same expression their docstrings claim
- **PR #282**: layout: bump klt pin to 0.9.0 and record the PDK-runset LVS route
- **Issue #260** (closed): layout: bump the klt pin to 0.9.0 and verify runset-backed LVS recognises npn13G2 (T1 item 4 route)
- **PR #281**: test: derive the bench-discovery and workflow-timeout guard universes from the tree
- **Issue #261** (closed): Two guard tests name a universe they do not inspect: bench discovery checks 3 of 5 benches, workflow timeouts a hardcoded 2-file list
- **PR #275**: consolidate K_BOLTZMANN and the noiseless-source noise factor into sim/harness/rf
- **Issue #262** (closed): Consolidate K_BOLTZMANN (4 copies) and the noiseless-source noise factor (4 sites) into a new sim/harness/rf.py, with T0 a required argument
- **PR #269**: layout(lna_stage1): record why T1 items 2/3 cannot be claimed, with the klt chain run
- **Issue #198** (closed): layout: LNA stage-1 layout with DRC, LVS and ERC supply evidence (T1 items 2, 3, 4, 11)
- **PR #274**: lna-sparam-nf: re-run the 27-point grid on the post-#79 core; add the new-DUT record-note branch
- **Issue #250** (closed): Re-characterize the post-#79 LNA first-stage core (S-parameters, NF, linearity, headroom)

### 2026-11-14

- **PR #249**: docs: list all nine content directories in README repo layout
- **Issue #247** (closed): docs: README repo-layout block omits signoff/, manifests/, ratification/ and docs/
- **PR #253**: docs(layout): record the readiness probe re-run at the klt 0.8.0 pin
- **Issue #246** (closed): layout: re-run the klt layout-chain readiness probe at the pinned release klt 0.8.0 (npn13G2 extraction)
- **PR #251**: design(lna_stage1): add Le1 degeneration and a quieter base feed, selected by the #79 core-variant campaign
- **Issue #79** (closed): design: choose the first-stage core change that lets NF and input match close together

### 2026-10-31

- **PR #242**: sim: lna-headroom stage-2 refinement record for C08/C05 vs C00
- **Issue #132** (closed): sim: refine headroom shortlist (C08/C05) - convergence, two-tone IIP3, gain/NF/stability vs baseline
- **Issue #135** (closed): mixer-conversion-iip3: FFT-bin metrics depend on the ngspice FFT build (local zero-padded vs batch unpadded)

### 2026-10-28

- **PR #239**: feat: attest signoff items 1, 9, 10 via klt signoff --attest inventories
- **Issue #237** (closed): T1 grading: replace hand-rolled single-file envelopes for items 1/9/10 with klt signoff --attest inventories and re-vendor the v0.8.0 checklist

### 2026-10-27

- **PR #235**: chore: pin klayout-tools 0.8.0 for signoff grading and toolchain record
- **Issue #234** (closed): Bump klayout-tools pin 0.5.0, 0.7.0, b770c86e0e96 → 0.8.0
- **Issue #68** (closed): spec: decision-record proposal after #61 (no acceptable LO drive at any declared mixer-core sizing)

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

