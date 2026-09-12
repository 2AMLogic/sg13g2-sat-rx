# Porting / design plan — what transfers, what is genuinely new

**Status: engineering input, not a ratified decision.** This document ratifies
nothing. [`target-spec.md`](target-spec.md) stays DRAFT, gated on the two-key
mechanism. What this document does is state, before any design work starts,
**which parts of this block already exist somewhere in the fleet** and which
parts have no precedent at all — so that the second category gets the
attention and the first does not get re-derived by hand.

- **Date**: 2026-09-12 (drafted, issue #1)
- **Written by**: Builder agent, issue #1
- **Block**: per-element satellite receive chain — SiGe HBT LNA + downconversion
  mixer, on IHP SG13G2.

**This block is half a port and half new ground.** The LNA is a second
instance of a block the fleet already has (`sg13g2-lna`, same PDK, same
device, different band). The mixer is not: **no repo in this fleet contains a
mixer of any kind, on any PDK.** Neither does any repo contain a Ka-band
anything. That asymmetry is the organizing fact of this plan.

---

## 0. Sources read for this document

Every claim below was read, not assumed. Where a source could not be read in
this environment, the entry says so.

### Sibling repos (read locally, at the commits named)

| Repo | Commit read | What was read |
|---|---|---|
| [`2AMLogic/sg13g2-lna`](https://github.com/2AMLogic/sg13g2-lna) | `main` @ `4a87eb8` (2026-09-11) | `spec/target-spec.md`, `spec/porting-plan.md`, `sim/hbt-characterization/README.md` + its record `20260910-200059-7da7038` |
| [`2AMLogic/sg13g2-vco`](https://github.com/2AMLogic/sg13g2-vco) | `main` @ `c348700` (2026-09-11) | `spec/target-spec.md`, `spec/porting-plan.md`, `sim/inductor-model/README.md`, `sim/inductor-model/em-extraction/README.md` + record `20260910-052657-3896421`, `sim/tank-characterization/README.md`, `sim/varactor-characterization/README.md` + record `20260909-231619-de50891` |
| [`2AMLogic/sg13g2-comparator`](https://github.com/2AMLogic/sg13g2-comparator) | `main` @ `c7838ca` (2026-09-11) | `spec/README.md`, `spec/porting-plan.md`, `sim/` directory structure |
| [`2AMLogic/sg13g2-bandgap`](https://github.com/2AMLogic/sg13g2-bandgap) | `main` @ `a79694f` (2026-09-11) | `spec/decision-records/TEMPLATE.md` (the DR format this repo adopts), issue #4 (the gap-to-T1 tracker shape) |
| [`2AMLogic/klayout-tools`](https://github.com/2AMLogic/klayout-tools) | working checkout, 2026-09-12 | `docs/design-evidence-tiers.md` — the T1 ladder and the AREA-EFF convention (issue #1086) |

### IHP-Open-PDK — exact files this block depends on

Read from the local PDK install tree (`ihp-sg13g2/`) on 2026-09-12. Paths are
PDK-repo-relative.

| PDK file | What it gives this block | Read? |
|---|---|---|
| `ihp-sg13g2/libs.doc/doc/SG13G2_os_process_spec.pdf` (Rev. 1.2, 2023-12-20) | §1 technology + backend stack (TopMetal1 2 µm, TopMetal2 3 µm, ILD εr 4.1); §1.1 full cross-section; §2.17 parasitic-capacitance tables; §3.1–3.3 `npn13g2` / `npn13g2l` / `npn13g2v` parametric tables (fT, fmax, BVCEO, BETA, ICMAX) | **yes**, via `pdftotext` |
| `ihp-sg13g2/libs.doc/doc/EM_Simulation_Overview.pdf` | the PDK's own statement of its EM-simulation story | listed, **not read** (TBD) |
| `ihp-sg13g2/libs.tech/ngspice/models/sg13g2_hbt_mod.lib` | the gain device. VBIC Rev. 1.15. Subcircuits `npn13G2`, `npn13G2_5t`, `npn13G2l`, `npn13G2l_5t`, `npn13G2v`, `npn13G2v_5t`, `pnpMPA`. Header states the model validity window: Nx 1–10, `ic < 0.003·Nx` A, `vbe` 0.65–0.96 V, **`vce` 0.4–2.0 V**, −40…+125 °C | **yes** |
| `ihp-sg13g2/libs.tech/ngspice/models/cornerHBT.lib` | HBT process corners. **Three**: `hbt_typ`, `hbt_bcs`, `hbt_wcs` (+ `_mismatch` each, + `hbt_typ_stat`) | **yes** |
| `ihp-sg13g2/libs.tech/ngspice/models/sg13g2_hbt_mod_mismatch.lib`, `sg13g2_hbt_stat.lib` | mismatch / statistical HBT cards, for row 15 (LO leakage is a symmetry effect) and for any future Monte Carlo (T1 item 6) | listed, **not read** (TBD) |
| `ihp-sg13g2/libs.tech/ngspice/models/capacitors_mod.lib`, `capacitors_mod_mismatch.lib`, `capacitors_stat.lib`, `cornerCAP.lib` | MIM caps — `cap_cmim` and **`cap_rfcmim`** (RF flavour, with bulk terminal). Corners `cap_typ`/`cap_bcs`/`cap_wcs` | **yes** (model + corner section names) |
| `ihp-sg13g2/libs.tech/ngspice/models/resistors_mod.lib`, `cornerRES.lib` | bias resistors; corners `res_typ`/`res_bcs`/`res_wcs` | corner names **yes** |
| `ihp-sg13g2/libs.tech/ngspice/models/sg13g2_svaricaphv_mod.lib` | `sg13_hv_svaricap` (4-terminal `G1 W G2 bn`) — the only real tuning element, if tunable matching or an on-chip LO tank is ever in scope | **yes** |
| `ihp-sg13g2/libs.tech/ngspice/models/cornerMOSlv.lib`, `cornerMOShv.lib`, `sg13g2_moslv_mod.lib`, `sg13g2_moshv_mod.lib` | the five-corner MOS set, relevant only if a MOS device (bias mirror, varactor) enters the design | corner-file presence **yes** |
| `ihp-sg13g2/libs.tech/xschem/sg13g2_pr/` | schematic symbols: `npn13G2*.sym`, `cap_cmim.sym`, `cap_rfcmim.sym`, `inductor.sym`, `inductor3.sym`, `sg13_hv_svaricap` family, `bondpad.sym`, ESD diodes. **No transmission-line symbol of any kind** | directory listing **yes** |
| `ihp-sg13g2/libs.tech/openems/openems_ihp_sg13g2/` | the PDK's EM path: openEMS Python workflow, `stackup_editor/`, `doc/Using_OpenEMS_Python_with_IHP_SG13G2_v3.pdf`, `doc/XML_stackup_format.md`, `doc/derived_layers.md` | directory listing **yes** |

> **Commit provenance — stated honestly rather than fabricated.** The PDK tree
> read for this document is an **unpacked install tree with no git metadata**,
> so no commit hash can be derived from it. `sg13g2-lna` and `sg13g2-bandgap`
> both record their own read as `IHP-GmbH/IHP-Open-PDK` `main` @
> [`5e6d592`](https://github.com/IHP-GmbH/IHP-Open-PDK/commit/5e6d592e4002946a4616f798c357f0f3c06cf3b6)
> (2026-09-01); `sg13g2-vco` records **v0.3.0**. Those are cited as the
> fleet's recorded revisions and are **not independently verified against the
> tree read here** — the file *paths* and *contents* above are verified, the
> *revision* is **TBD, needs verification**. Closing it: have `klt`'s
> PDK-resolver record a revision for this repo and commit a `sim/pdk.json`
> the way `sg13g2-lna` and `sg13g2-vco` do. That is a deliverable of issue #2
> (harness bootstrap), not of this document.

### Not readable in this environment

- **Published SiGe Ka-band LNA and active-mixer results.** No literature
  access. Every target-spec row that would rest on one is flagged `(E)` /
  `NEEDS-VERIFICATION` in [`target-spec.md`](target-spec.md) rather than given
  an invented citation. This is the largest open gap in the spec.
- **The ITU allocation tables** behind the band edges (17.7–21.2 GHz;
  10.7–12.75 GHz). Same treatment.

---

## 1. `sg13g2-lna` — the LNA path. What ports, and what does not.

Same PDK, same device, **different band** (that repo drafts 2.4 GHz ISM;
this one drafts 17.7–21.2 GHz). That single difference decides most of the
table below.

### Ports directly

- **The 50 Ω port convention**, stated the same way and implemented the same
  way. That repo's `hbt-characterization` bench uses an ideal bias tee (a DC
  source in series with a 1 H choke), a 1 F ideal DC block, a 50 Ω Thevenin
  source **pinned at `temp=27` regardless of the swept ambient corner** (the
  Friis/IEEE fixed-source-reference-temperature convention), and a 50 Ω load
  that is *not* pinned (it models on-die hardware at the DUT's temperature).
  **This whole convention ports unchanged, including the asymmetry** — and
  including the requirement that the choice be restated beside every number.
- **The noise-figure derivation from ngspice's `.noise` output**:
  `NF_dB = 10·log10(inoise_spectrum² / (4·k·T₀·Rs))` with `T₀ = 300.15 K`,
  `Rs = 50 Ω`. Ports unchanged for the LNA. **Does not port to the mixer** —
  see §4.
- **The fT bench**: `.ac dec 20 1MEG 3000G` sweeping
  `h21 = −i(Vce)/Ib_ac`, then `meas ac … WHEN h21db=0`. Also ports the
  *finding* behind it: this VBIC build does **not** expose a named `ft`
  op-info field, though `gm`, `cbe`, `cbc`, `cbcx`, `cbep`, `cbcp` are
  queryable via `show`/`@dev[param]`. That saves this repo a dead end.
- **The `npn13G2` device numbers themselves** (P §3.1) — same device, same
  card.
- **The Voinigescu-style noise-optimum-`J_C` framing**, and its recorded
  result that noise-optimum `J_C` sits **2–3× above** fT-peak `J_C` at every
  corner. The *shape* of that finding is device physics and ports; the
  *values* do not (see below).
- **The house rules**: stability is a spec row, not an afterthought; IIP3
  only via a two-tone bench with its FFT parameters recorded.

### Ports as method only — numbers do **not** transfer

- **Every NF, gain, and `J_C` number in that repo's records is at 2.4 GHz.**
  At 20 GHz the device is at `f/fT ≈ 1/15` instead of `1/150`; base
  resistance, `Cbc` feedback, and the input `Q` of any matching network all
  behave differently. The recorded **6.32 dB (typ) / 8.51 dB (wcs)**
  bare-device 50 Ω NF at 2.4 GHz is a *floor-setting reality check* for this
  repo's ≤ 2.5 dB target, **not** a number to scale to 20 GHz. Re-running the
  same bench at Ka-band frequencies is a first-order deliverable here.
- **The band, and everything downstream of it** — matching topology, device
  size, number of fingers, bias point.

### Does not exist there either (so there is nothing to port)

- No schematic, no layout, no matched-LNA S-parameter bench, no stability
  bench, no IIP3 bench. `sg13g2-lna/design/` contains only a README. That
  repo's S11/S22 work is itself **blocked on the inductor-model gap** it
  filed as `klayout-tools#1517`. This repo inherits the blocker, not a
  solution.

### One correction this repo must not inherit

`sg13g2-lna/spec/target-spec.md`'s "Verification corners" section states that
"SG13G2's `cornerHBT.lib` ships all five" (tt/ff/ss/fs/sf). **It ships
three** — `hbt_typ`, `hbt_bcs`, `hbt_wcs` — verified by reading the file's
`.LIB` section headers. That repo's own `sim/hbt-characterization` bench uses
`typ`/`bcs`/`wcs`, so only its spec prose is stale. This repo's corner table
is built from the PDK file, not from the sibling's prose.

---

## 2. `sg13g2-vco` — the passives and LO half. The most valuable sibling here.

This is the only repo in the fleet with **EM-extracted, recorded** SG13G2
passive data. For a 20 GHz block it is worth more than any schematic.

### Ports directly

- **The finding that the PDK ships no simulatable inductor**, and the
  documented consequence: the tank study recorded `MODEL_ABSENT` as *evidence*
  rather than substituting a hand-rolled formula. That posture ports
  verbatim — this repo will hit the same wall on its matching networks.
- **The openEMS extraction flow itself**: drawn PCell → GDS → stackup →
  FDTD → 2-port Touchstone `.s2p` → lumped fit → an ngspice-includable
  `.spice` model with a `w`/`s`/`d`/`nr_r` interface, with the fit's rms and
  max |ΔZ|/|Z| residual reported rather than asserted, and with each record
  naming the model file **by repo-relative path and content sha256** so an EM
  model can never be mistaken for PDK output. **This is the single most
  reusable asset in the fleet for this block.**
- **The convergence discipline**: one-variable-at-a-time mesh/boundary checks
  reported with the delta they move, instead of asserting the defaults were
  fine.
- **The varactor survey's device-selection method**, and its conclusion that
  `dantenna`/`dpantenna` are ESD/antenna devices with Cmax/Cmin 1.03–1.24 and
  Q ≈ 1–1.7 — i.e. not tuning elements. That conclusion saves this repo the
  same experiment if tunable matching is ever considered.

### Ports as a warning, not as a number

- **`p13` (5 turns) and `p11` (4 turns) self-resonate at 8.07 GHz and
  9.42 GHz.** Both are **below** this block's draft band. Multi-turn PDK
  spirals are unusable at Ka band, full stop. The analytic (Mohan) model
  overestimated those SRFs by **+77 % / +50 %**, so the analytic route cannot
  be trusted for the one quantity that decides this.
- **`p1` (1 turn) is the encouraging data point**: L = 89.7 pH at 20 GHz,
  **Q = 12.32 at 20 GHz**, no SRF below the 30 GHz scan ceiling. A sub-100 pH,
  Q ≈ 12 series element at 20 GHz is a usable matching component. It is
  **one geometry, one field solve, against one published stackup** — not a
  cornered model, and not silicon.
- **No varactor data exists above 10 GHz**, where `sg13_hv_svaricap`'s Q had
  already fallen to 0.19 on the largest geometry. Nothing about varactor
  behaviour at 20 GHz may be assumed from that dataset.

### Does not port

- The LC-VCO circuit itself, its phase-noise framework (Hajimiri–Lee ISF),
  its tuning-range rows. This repo needs an **LO port**, not an oscillator.
  Whether the LO comes from an external ideal source (bench), an off-chip
  synthesizer (system), or an on-chip VCO of that class (a future, separate
  decision) is open — and the last of those is out of this repo's stated
  scope until a decision record admits it.

---

## 3. `sg13g2-comparator` — structure, not circuit

Cited for `sim/` **shape** only. Its `sim/` layout — `env.sh`, `pdk.json`,
`toolchain.json`, `run_corners.py`, `characterize.sh`, `selftest.sh`, and one
directory per experiment each holding `testbench/`, `corners/`,
`netlist-snapshots/`, `records/`, and a `run_*.sh` cold-start entry point — is
the pattern this repo's generated `sim/harness/` already mirrors, and the one
`sim/` should grow into. Its
[`spec/README.md`](https://github.com/2AMLogic/sg13g2-comparator/blob/main/spec/README.md)
supplies the decision-record-process wording (two-key ratification; DRs
required when a row is *set*, *changed*, or *scoped*) that this repo's
`spec/README.md` adopts.

**No numeric value is taken from it.** A comparator shares no spec row with
an RF front end.

### One concrete edit the harness core needs

`sim/harness/corners.py` ships the classic five MOS corners
(`tt`/`ff`/`ss`/`fs`/`sf`) as its default set, and its own README names this
as "the one PDK-specific edit most blocks need before their first run."
**For this block that edit is mandatory and non-obvious**: the primary device
family is the HBT, whose corner file has **three** sections
(`hbt_typ`/`hbt_bcs`/`hbt_wcs`), not five. Registering an `hbt` corner family
via `corners.register_corner_set()` — rather than editing the built-in MOS
set — is the intended extension point. That work belongs to issue #2.

---

## 4. What is genuinely new — no precedent anywhere in the fleet

### 4.1 The mixer bench, end to end

**No repo in this fleet contains a mixer.** Every measurement below is new
bench-design work, and each has a specific reason it is not a re-parameterized
LNA bench:

- **Conversion gain.** Not an `.ac`/`.sp` quantity: a mixer is a
  *time-varying* circuit, and the wanted output is at a different frequency
  from the input. ngspice offers no PSS / harmonic-balance / periodic
  transfer-function analysis. The practical route is a **two-tone-free
  transient**: drive RF at a known level, drive LO at the design level, run
  long enough for a clean FFT, and read the IF bin. Everything about that
  sentence needs a stated convention — transient length, timestep, settling
  discard, window function, FFT bin resolution, and how the IF bin's
  amplitude converts to power into 50 Ω. **Power conversion gain into 50 Ω is
  the primary figure**; a voltage conversion gain into a stated capacitive
  load is permitted only as an explicitly labelled secondary.
- **SSB noise figure.** The hardest item. Mixer noise folds from every LO
  harmonic sideband into the IF; `.noise` is a linear time-invariant analysis
  and **cannot represent that**. ngspice has no `.pnoise`. Candidate routes,
  none yet chosen: (a) a periodic-steady-state-free transient-noise
  simulation, if the ngspice build supports transient noise sources, with the
  sample count and the resulting confidence interval stated; (b) a manual
  sideband-folding calculation from `.noise` runs at each significant LO
  harmonic sideband, with the number of sidebands summed and the truncation
  error stated; (c) an explicit "this is not measurable in this flow"
  `MODEL_ABSENT`-style honest record, the way `sg13g2-vco` handled the missing
  inductor. **Whichever is chosen, SSB vs. DSB must be stated with every
  number** — they differ by ~3 dB for an image-unfiltered downconverter, and
  conflating them is the standard way a mixer NF claim becomes false.
- **LO-to-RF and LO-to-IF leakage.** A *power at a port*, so it is only
  meaningful with the LO drive level stated beside it. It is a
  symmetry/matching effect, which makes it the one row in the table that
  genuinely needs the **mismatch** corner cards
  (`sg13g2_hbt_mod_mismatch.lib`, `hbt_*_mismatch` sections), not just the
  process corners.
- **Mixer IIP3, two-tone.** Same method rules as the LNA's, with the
  additional mixer-specific requirement that the tone placement be stated in
  **RF** terms and the IM3 product read at **IF**, and that the sweep show the
  1:3 slope region actually used for the extrapolation — an IIP3 extrapolated
  from a compressed point is not an IIP3.
- **Isolation and port count.** An LNA is a two-port. A mixer is a
  three-port (RF, LO, IF) and possibly differential on two of them. The
  harness's testbench manifest, the netlist fragment discipline, and the
  evidence schema all assume a simpler object than that today.

### 4.2 The 20 GHz passive question

Stated precisely, because it is the technical risk that decides whether this
block is buildable with open tools:

1. **The PDK ships no inductor model and no transmission-line model**
   (verified: 31 files in `libs.tech/ngspice/models/`, none of either; xschem
   has `inductor.sym`/`inductor3.sym` with no backing subcircuit and **no
   t-line symbol at all**).
2. **Multi-turn spirals are out** at Ka band — `p13`/`p11` self-resonate at
   8.07/9.42 GHz (S-VCO, EM-extracted).
3. **Single-turn spirals are promising but barely characterized** — one
   geometry (`p1`), Q ≈ 12.3 at 20 GHz, L ≈ 90 pH, no SRF < 30 GHz.
4. **Transmission lines on TopMetal1 (2 µm) / TopMetal2 (3 µm) are the
   textbook Ka-band answer** and are physically reasonable on this stack
   (thick Al, ILD εr 4.1, 750 µm bulk at 50 Ω·cm). A quarter-wave at 20 GHz
   in a medium with effective εr ≈ 4 is on the order of **1.9 mm** — far too
   long to use as a λ/4 element on a small die, so any t-line use here is as
   a **short, sub-λ/10 reactive element**, not as a distributed network.
   *(That length is a first-order `c/(4·f·√εr_eff)` estimate with an assumed
   `εr_eff`; it is a sanity check, not a design number — **TBD, needs a real
   `εr_eff` from EM extraction**.)*
5. **openEMS is the only path to a model for any of it**, and `sg13g2-vco`
   has already proven that path works on this PDK and recorded how.
6. **There is no process-corner axis for an EM-extracted passive.** A field
   solve is one geometry against one nominal stackup. How passive variation is
   cornered on this PDK is genuinely unanswered — see `target-spec.md`'s
   corner table, which marks this axis as an open hole rather than omitting it.

**Friction-protocol note.** `sg13g2-lna` already filed the generic tool gap as
[`2AMLogic/klayout-tools#1517`](https://github.com/2AMLogic/klayout-tools/issues/1517)
(`klt mom`'s extraction path is restricted to bar-shaped conductors, cannot
process spiral geometry, and has no Touchstone export). **This repo should not
re-file it.** If Ka-band work surfaces a *different* gap — e.g. no
transmission-line extraction path, or no way to corner an EM-extracted model —
that is a new, separately-filed, generically-worded issue against
`klayout-tools`, with this repo's spec values kept out of it.

### 4.3 Ka-band, at all

No block in this fleet has been designed above ~10 GHz. Consequences that have
no fleet precedent: bond-pad and ESD parasitics that are a significant part of
the input match at 20 GHz (`bondpad.sym` / `sg13g2_bondpad.lib` exist but have
not been characterized by anyone here); interconnect that must be treated as
distributed within the block; and the fact that at 20 GHz the *layout* is part
of the circuit, so the post-layout item (T1 item 7) is not a refinement step
but a correctness step.

### 4.4 The cascade as the deliverable

Both siblings verify a single block. This repo's real product is a **cascade**
(LNA → mixer) whose NF and gain must be measured as a cascade, not composed by
Friis from two independently 50 Ω-terminated measurements — unless the
interface really is 50 Ω, which is itself undecided. The evidence schema has to
carry which of the two a given record is.

---

## 5. Sequencing — what must happen before what

This is a dependency statement, not a schedule.

1. **Spec ratification** (this issue's artifacts → a DR, two keys). Nothing
   downstream of it is a *claim*; work can proceed against DRAFT rows but may
   not assert compliance.
2. **Harness bootstrap** (issue #2) — the HBT corner family registered, a
   `sim/pdk.json` that pins a real PDK revision (closing this document's
   provenance caveat), and the LNA S-parameter/NF bench.
3. **Ka-band device re-characterization** — re-run `sg13g2-lna`'s bench
   method at 17.7/19.45/21.2 GHz to get a Ka-band noise-optimum `J_C` and a
   real `NF_min` estimate. Until this exists, target-spec row 3 is an
   aspiration with a 2.4 GHz reality check and nothing else.
4. **The 20 GHz passive study** — openEMS extraction of whatever matching
   elements the topology needs, following `sg13g2-vco`'s recorded flow. Rows
   4, 5, 6 and (via matching loss) 3 are unsimulatable until this lands.
5. **Supply/bias topology DR** — resolving the two-sided constraint
   (BVCEO min 1.4 V, model validity `vce ≤ 2.0 V`).
6. **The mixer bench design** — §4.1. Independent of 3–5 in principle; in
   practice it wants the LO plan, which wants DR-0002.
7. **Beamsteering partition DR-0002** — deliberately deferred until the LNA
   and mixer benches exist, because the criteria that decide it are numbers
   those benches produce.

Nothing in this document authorizes schematic, layout, or simulation work
ahead of step 1 being at least *drafted* — which, with this issue, it now is.
