# Work Log

Chronological record of merged pull requests and closed issues, maintained by the Loom Guide role.

### 2026-10-09

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
