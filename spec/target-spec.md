# Target specification — Ka-band receive front end (LNA + mixer)

- **Status: PARTIALLY RATIFIED (targets) — per [DR-0003](decision-records/0003-target-spec-first-ratification.md).**
  Eleven rows (2, 3, 4, 6, 7, 8, 9, 10, 11, 17, 18) are ratified as
  **binding targets**; nine rows (1, 5, 12, 13, 14, 15, 16, 19, 20) are
  **explicitly OPEN**, each with its gate recorded in that record. **No row
  is ratified as met** — no measurement of this block exists. Design work
  may proceed against the ratified rows and cite them as targets; it may
  not claim *compliance* with any row without a `sim/` evidence record.
- **Date**: 2026-09-12 (drafted, issue #1); first ratification pass
  2026-09-21 (issue #11, DR-0003)
- **Written by**: Builder agent, issue #1
- **Block kind** (per [`klayout-tools/docs/design-evidence-tiers.md`](https://github.com/2AMLogic/klayout-tools/blob/main/docs/design-evidence-tiers.md)
  § "Block kind"): **analog**. The block satisfies the Analog column of the
  T1 checklist only.
- **Scope**: the per-element receive chain — one SiGe HBT LNA plus one
  downconversion mixer. The antenna element, the array, the ADC, and the
  beamformer are **out of scope** (`CLAUDE.md`); see
  [`decision-records/0002-beamsteering-partition.md`](decision-records/0002-beamsteering-partition.md)
  for what that boundary does and does not decide.

**Ratification is a separate event from drafting.** It flows through the
two-key mechanism (EE key + market key) — here via the ratification-via-PR
standing path (see
[DR-0003](decision-records/0003-target-spec-first-ratification.md) for the
route and its precedent) — recorded as a decision record under
[`decision-records/`](decision-records/). This document does not ratify
itself, and the agent that wrote it has no authority to. **DR-0003 is the
first ratification pass**: its per-row dispositions set the Status column
below, and any later value change, rescope, or open-row closure requires a
DR that argues it on evidence. Per `CLAUDE.md`, no later result may relax
a ratified row to make itself pass.

**The band is drafted, not ratified.** See
[`decision-records/0001-band-selection-ka-vs-ku.md`](decision-records/0001-band-selection-ka-vs-ku.md)
for the argument, the Ku-band fallback, and the explicit trigger that would
move the band. Rows below are written against the Ka-band draft; if the band
moves, every frequency-dependent row is invalidated and must be re-derived,
not rescaled.

---

## Port convention (stated explicitly, per `CLAUDE.md`)

**Every S-parameter, gain, match, noise-figure, and linearity figure in this
document is defined at a 50 Ω reference impedance at every RF port** — LNA
input, LNA output, mixer RF port, mixer LO port, and mixer IF port. This is
the same convention `sg13g2-lna` states for itself
([`spec/target-spec.md`](https://github.com/2AMLogic/sg13g2-lna/blob/main/spec/target-spec.md)
§ "Port convention") and the one its `hbt-characterization` bench actually
implements (a 50 Ω Thevenin source pinned at `temp=27`, a 50 Ω load, ideal
bias tees).

A testbench that departs from 50 Ω at any port — an on-chip source-impedance
sweep for noise-match sensitivity, an LNA-to-mixer interstage node that is
deliberately not 50 Ω, a differential LO port referenced to 100 Ω
differential — **must state the departure beside its own recorded number**.
A stated departure does not change this row's definition; it makes that
particular measurement not directly comparable to it.

**The LNA-to-mixer interface is not assumed to be a 50 Ω port.** If the two
blocks are co-designed with an impedance-matched interstage network rather
than back-to-back 50 Ω ports, the cascade NF and cascade gain rows must be
measured on the co-designed cascade, not computed by Friis from two
separately 50 Ω-measured blocks. Which of the two it is, is an open design
decision (see "Open items" below), not something this table settles.

---

## Frequency coverage: what "across band" means

**A number at one center frequency does not satisfy any row in this table.**
Per `CLAUDE.md`: *do not call a design "wideband" unless every spec row holds
across the whole ratified band at every corner, not at one center frequency.*

Concretely, for every row marked "across band":

- Minimum evaluation set: **17.7, 19.45, 21.2 GHz** (both band edges and the
  arithmetic centre), at **every** corner in the corner set below.
- A swept result (e.g. `.ac dec` / `.sp` over the band) is preferred and
  supersedes the three-point set; the three points are a floor, not a target.
- The **worst** value over the band and the corner set is the value compared
  against the bound. The frequency and corner at which the worst value occurs
  is recorded beside it — a row's verdict is not complete without its binding
  frequency and binding corner.

---

## Where these numbers come from

Five source classes, cited per row via the **Src** column. **None of them is
silicon, and none of them is an ngspice simulation of this block** — this
repo has no schematic and no testbench as of this document.

### (P) — IHP SG13G2 PDK, read directly

Read from the PDK checkout this host resolves for `klt`/ngspice,
`ihp-sg13g2/`, on 2026-09-12. Paths below are PDK-repo-relative
(`IHP-GmbH/IHP-Open-PDK`).

- `ihp-sg13g2/libs.doc/doc/SG13G2_os_process_spec.pdf` (**Rev. 1.2**,
  2023-12-20, 26 pp.):
  - **§1 "General Information"** — SG13G2 has "the same device portfolio as
    SG13S but much higher bipolar performance with fT = 300 GHz and 500 GHz
    maximum oscillation frequency"; backend is "5 thin Al metal layers, two
    thick Al metal layers (2 and 3 µm thick) and a MIM layer".
  - **§1.1 backend cross-section** — TopMetal1 = **2000 nm**, TopMetal2 =
    **3000 nm**, TopVia2 = 2800 nm, ILD εr = 4.1 ± 0.1, MIM dielectric
    εr = 6.6 ± 0.1, Si bulk 750 µm at ρ = 50 Ω·cm, epi 3750 nm at ρ = 20 Ω·cm.
  - **§3.1 `npn13g2`** (AE = 0.07 × 0.9 µm²) — BETA min/target/max
    300/650/1200; VA 150 V; **BVCEO min 1.4 V / target 1.6 V**; BVCBO
    3.8/4.8 V; BVEBO 1.0/1.6 V; IC07 2.6/3.8 µA; ICMAX 5.2 mA (Nx=4);
    **FT min 300 / target 350 GHz**; **FMAX min 400 / target 450 GHz**.
  - **§3.2 `npn13g2l`** (AE = 0.07 × 1 µm²) — same BVCEO/BETA;
    FT 280/330 GHz, FMAX 380/430 GHz.
  - **§3.3 `npn13g2v`** (AE = 0.12 × 1 µm²) — **BVCEO min 2.2 / target
    2.5 V**, BVCBO 7/8.5 V, but **FT only min 90 / target 120 GHz** and FMAX
    280/330 GHz.
  - *Note the internal inconsistency in the PDK's own document*: §1 states
    fT = 300 GHz and fmax = 500 GHz for the technology, while §3.1's
    parametric table gives `npn13g2` FT min 300 / target 350 and FMAX min
    400 / target 450. **This document uses the §3.1 parametric table**, the
    per-device process-control spec, and treats §1's prose as a
    technology-level headline. The top-level `README.md`'s "about 300 GHz fT,
    450 GHz fmax" matches §3.1's FT-min / FMAX-target pair and is consistent
    with this choice.
- `ihp-sg13g2/libs.tech/ngspice/models/sg13g2_hbt_mod.lib` — the HBT SPICE
  deck. **VBIC Rev. 1.15**, TNOM 27 °C. Defines `npn13G2`, `npn13G2_5t`,
  `npn13G2l`, `npn13G2l_5t`, `npn13G2v`, `npn13G2v_5t` (4- and 5-terminal
  forms; the 5-terminal form exposes the self-heating thermal node `t`), plus
  `pnpMPA`. The card's own header states the **model validity range**:
  emitter size Nx × (0.07 × 0.90) µm² with **Nx = 1–10**, `ic < 0.003·Nx` A,
  `vbe` 0.65–0.96 V, **`vce` 0.4–2.0 V**, temp −40 … +125 °C. This `vce`
  ceiling is load-bearing for the Supply row below.
- `ihp-sg13g2/libs.tech/ngspice/models/cornerHBT.lib` — **ships three HBT
  process corners, not five**: `hbt_typ`, `hbt_bcs`, `hbt_wcs` (plus
  `_mismatch` variants of each and a `hbt_typ_stat`). Verified by reading the
  file's `.LIB` section headers directly (7 sections total).
  **This contradicts `sg13g2-lna/spec/target-spec.md`'s "Verification
  corners" paragraph, which states "SG13G2's `cornerHBT.lib` ships all
  five" (tt/ff/ss/fs/sf).** That claim is wrong for the HBT corner file;
  the five-corner set exists for MOS (`cornerMOSlv.lib`, `cornerMOShv.lib`).
  `sg13g2-lna`'s own `sim/hbt-characterization` bench in fact uses `typ`,
  `bcs`, `wcs` labels, so its *simulation* work already reflects the
  three-corner reality — only its spec prose is stale. Flagged here rather
  than silently copied; a corrective note on that repo is a separate,
  out-of-scope action for this issue.
- `ihp-sg13g2/libs.tech/ngspice/models/cornerCAP.lib`, `cornerRES.lib` —
  three corners each (`cap_typ`/`cap_bcs`/`cap_wcs`,
  `res_typ`/`res_bcs`/`res_wcs`), same shape as the HBT file.
- `ihp-sg13g2/libs.tech/ngspice/models/capacitors_mod.lib` — MIM models,
  including `cap_cmim` and **`cap_rfcmim`** (the RF-flavoured MIM with a
  bulk/substrate terminal). `cap_cmomf.lib` / `cap_cmomi.lib` are not present
  in this checkout's `models/` directory listing; MOM capacitance is covered
  by the parasitic-capacitance tables in the process spec §2.17 instead.
- `ihp-sg13g2/libs.tech/ngspice/models/sg13g2_svaricaphv_mod.lib` — the MOS
  accumulation-mode varactor `sg13_hv_svaricap` (4-terminal: `G1 W G2 bn`).
- **No inductor model, and no transmission-line model, anywhere in
  `libs.tech/ngspice/models/`.** The directory listing was read in full
  (31 files); there is no `induct*`, no `tline`, no `cpw`, no `.s2p`.
  `libs.tech/xschem/sg13g2_pr/` ships `inductor.sym` / `inductor3.sym`
  (LVS/layout symbols with no backing subcircuit) and **no transmission-line
  symbol at all**. The PDK's own answer is user-side EM extraction:
  `ihp-sg13g2/libs.tech/openems/openems_ihp_sg13g2/` (the
  `VolkerMuehlhaus/openems_ihp_sg13g2` workflow, with
  `doc/Using_OpenEMS_Python_with_IHP_SG13G2_v3.pdf` and an XML stackup
  editor) plus `libs.doc/doc/EM_Simulation_Overview.pdf`.

> **Provenance caveat, stated rather than papered over.** The PDK checkout
> this document read carries **no git metadata** (it is an unpacked install
> tree, not a clone), so **this document cannot attest a commit hash for it**.
> Sibling repos `sg13g2-lna` and `sg13g2-bandgap` both record their own read
> as `IHP-GmbH/IHP-Open-PDK` `main` @
> [`5e6d592`](https://github.com/IHP-GmbH/IHP-Open-PDK/commit/5e6d592e4002946a4616f798c357f0f3c06cf3b6)
> (2026-09-01); `sg13g2-vco` records the release as **v0.3.0**. Those are
> *their* recorded revisions, cited here as the fleet's best available
> reference and **not independently verified against the tree this document
> read**. Every path and number above was read from the local tree and is
> reproducible from it; the mapping from that tree to a specific upstream
> commit is **TBD — needs verification** once `klt`'s PDK-resolver records a
> revision for this repo (see `sim/pdk.json` in `sg13g2-lna`/`sg13g2-vco` for
> the shape that record takes).

### (S-LNA) — `2AMLogic/sg13g2-lna`, recorded evidence

`main` @ `4a87eb8` (2026-09-11), read locally.
[`sim/hbt-characterization/`](https://github.com/2AMLogic/sg13g2-lna/tree/main/sim/hbt-characterization),
record `20260910-200059-7da7038` (1586 rows). A *device* characterization of
bare `npn13G2` at **2.4 GHz**, not a matched LNA, and explicitly **not
comparable to a matched-circuit NF row** — that repo says so itself. Useful
figures, each with its bench stated in that directory's README:

- fT peak, `typ`/27 °C, `V_CE = 1 V`: **~416 GHz** at `J_C ≈ 21.4 mA/µm²`
  (`.ac dec 20 1MEG 3000G`, h21 0 dB crossing). Grid-wide best case
  `bcs`/−40 °C: 600 GHz.
- fT at the **noise-optimum** bias, binding corner `wcs`/125 °C,
  `V_CE = 1.0 V`: **199 GHz**.
- Bare-device 50 Ω NF at 2.4 GHz, noise-optimum `J_C`: **6.32 dB** at
  `typ`/27 °C, **8.51 dB** at `wcs`/125 °C. *Unmatched* — no noise match, no
  degeneration, no matching network. This is the honest reality check the NF
  row below carries, not a contradiction of it.
- Noise-optimum `J_C` sits **2–3× above** fT-peak `J_C` at every grid point.

### (S-VCO) — `2AMLogic/sg13g2-vco`, recorded evidence

`main` @ `c348700` (2026-09-11), read locally. The fleet's only EM-extracted
SG13G2 passive data, and the reason the 20 GHz passive question below is
answerable at all rather than merely asked.

- [`sim/inductor-model/em-extraction/`](https://github.com/2AMLogic/sg13g2-vco/tree/main/sim/inductor-model/em-extraction)
  — openEMS (FDTD) extraction of the PDK's own `inductor2` PCell at three
  LVS-testcase geometries, 0.1–30 GHz, 601 points, exported as 2-port
  Touchstone `.s2p` and fitted to a lumped topology. Record
  `20260910-052657-3896421`. Key numbers, read from
  `records/20260910-052657-3896421-delta-summary.csv` directly:
  - `p1` (1 turn, w = 8.22 µm, s = 3.29 µm, d = 47.65 µm): L = **98.5 pH** at
    1 GHz falling to **89.7 pH at 20 GHz**; **Q = 1.90 at 1 GHz rising to
    12.32 at 20 GHz**; **no SRF below the 30 GHz scan ceiling**.
  - `p13` (5 turns): L = 5.12 nH at 1 GHz, **SRF = 8.07 GHz**.
  - `p11` (4 turns): L = 4.28 nH at 1 GHz, **SRF = 9.42 GHz**.
  - The closed-form (Mohan et al. 1999) analytic model overestimated SRF by
    **+77 % / +50 %** on `p13` / `p11` — i.e. the analytic route is not
    trustworthy for SRF, which is exactly the quantity a 20 GHz design cares
    about most.
- [`sim/varactor-characterization/`](https://github.com/2AMLogic/sg13g2-vco/tree/main/sim/varactor-characterization)
  — record `20260909-231619-de50891`: `sg13_hv_svaricap` gives Cmax/Cmin up to
  **2.08** with Q from 224 (smallest geometry, 1 GHz) down to **0.19**
  (largest, 10 GHz); `dantenna`/`dpantenna` give Cmax/Cmin 1.03–1.24 at
  Q ≈ 1–1.7 at 1 GHz. **No varactor data above 10 GHz exists** — the LO-port
  and tunable-matching rows that would depend on it are TBD accordingly.
- [`sim/tank-characterization/`](https://github.com/2AMLogic/sg13g2-vco/tree/main/sim/tank-characterization)
  — MIM cap characterized across the full PVT grid; finding 6: the MIM cap is
  exactly bias-independent.

### (S-CMP) — `2AMLogic/sg13g2-comparator`, structure only

`main` @ `c7838ca` (2026-09-11). Cited for the `sim/harness/` corner and
evidence structure this repo's generated harness already mirrors, and for its
[`spec/README.md`](https://github.com/2AMLogic/sg13g2-comparator/blob/main/spec/README.md)
decision-record-process wording (the two-key ratification sentence this
document reuses). **No numeric value is taken from it** — a comparator has no
row in common with an RF front end.

### (L) — literature, cited second-hand

`sg13g2-lna/spec/target-spec.md` cites two references as its topology- and
device-level frame, and this document inherits them **at second hand, not
having read them in this environment**:

- D. K. Shaeffer and T. H. Lee, "A 1.5-V, 1.5-GHz CMOS Low Noise Amplifier,"
  *IEEE JSSC*, 1997 — the canonical inductive-degeneration LNA reference
  (simultaneous noise and power match).
- S. P. Voinigescu et al., "A Scalable High-Frequency Noise Model for Bipolar
  Transistors with Application to Optimal Transistor Sizing for Low-Noise
  Amplifier Design," *IEEE JSSC*, 1997 — the SiGe-HBT optimum-noise-current-
  density reference. `sg13g2-lna`'s recorded 2–3× separation between
  noise-optimum and fT-peak `J_C` is the expected Voinigescu-style result.

### (E) — engineering target set by this document — **NEEDS VERIFICATION**

**This is the honest name for every row whose bound is not derivable from
(P), (S-*), or (L).** The curated issue asks for citations to "published SiGe
Ka-band LNA and active-mixer results." **The environment this document was
written in has no literature access** — no journal database, no paper PDFs,
no way to check a citation. Rather than invent a plausible-looking author,
year, and number (the single most damaging thing an agent can do to an
evidence-based repo), every such row is marked **(E)** and carries an
explicit `NEEDS-VERIFICATION` flag.

An **(E)** bound is: a round, defensible engineering target, chosen to be
demanding rather than easy per the operator's standing direction, and
**sanity-checked against (P) device capability where possible** — but it is
**not** traceable to a published result, and **must not be presented as if it
were**. Closing the (E) flags — by citing real, checkable published Ka-band
SiGe LNA and active-mixer results with author, venue, year, and the exact
number taken from each — is a **precondition of ratification** and is listed
as open item 1 below.

---

## Target table

Per-row status is set by the first ratification pass,
[DR-0003](decision-records/0003-target-spec-first-ratification.md):
**RATIFIED (target)** rows bind as what the design must be measured against —
**no row is ratified as met**; **OPEN** rows keep their DRAFT value and are
gated on the condition the record names. "Binding corner (expected)" is an
*expectation to be tested by the bench*, not a measured result — a bench
that finds a different binding corner supersedes the expectation, and the
expectation being wrong is not a spec failure.

| # | Parameter | Status (DR-0003) | Target | Stretch | Src | Binding corner (expected, unverified) | Notes / flags |
|---|---|---|---|---|---|---|---|
| 1 | **Receive band** | **OPEN** — allocation edges unverified; DR-0001 still proposed | Ka-band satellite downlink, **17.7–21.2 GHz**; every row below holds across the full band | — | (E) + DR-0001 | — | **NEEDS-VERIFICATION**: the 17.7–21.2 GHz downlink allocation is stated from general knowledge of the ITU/FSS space-to-Earth plan and was **not** checked against the ITU Radio Regulations in this environment. Verify the exact allocation edges before ratification. Ku fallback (10.7–12.75 GHz, same caveat) and its trigger: DR-0001. |
| 2 | **LNA gain, S21** | **RATIFIED (target)** | **≥ 20 dB** across band (two-stage cascode assumed) | ≥ 25 dB | (E), device headroom from (P) §3.1 + (S-LNA) | `hbt_wcs`, 125 °C, min supply (lowest `J_C`, lowest fT) | **NEEDS-VERIFICATION** against published results. Device sanity check: `npn13g2` FMAX min 400 GHz ⇒ at 20 GHz, `fmax/f = 20`, so per-stage MAG headroom is real. But (S-LNA) measured only **8.5 dB** *50 Ω-terminated transducer gain* on a bare device at 2.4 GHz — an unmatched device is not a matched stage, and the gap between the two is exactly what the matching network must supply. |
| 3 | **LNA noise figure (NF₅₀)** | **RATIFIED (target)** — highest-risk row; see its own note | **≤ 2.5 dB** across band, all corners | ≤ 2.0 dB | (E) + (L)Voinigescu + (S-LNA) | `hbt_wcs`, 125 °C (device noise rises with T; worst self-heating) | **NEEDS-VERIFICATION, and the highest-risk row in this table.** (S-LNA) recorded **6.32 dB (typ/27 °C)** / **8.51 dB (wcs/125 °C)** for a *bare, unmatched* `npn13G2` at 2.4 GHz. Getting to 2.5 dB at 20 GHz requires a real noise match (Voinigescu-style sizing + degeneration), and the matching network's own loss lands directly on NF. A Ka-band `NF_min` derivation against `sg13g2_hbt_mod.lib`'s VBIC noise parameters does not exist in the fleet. Treat 2.5 dB as an aspiration to be tested, not a number already shown reachable on this PDK. |
| 4 | **LNA input match, S11** | **RATIFIED (target)** | **≤ −10 dB** across band | ≤ −15 dB | (E) + (L)Shaeffer–Lee | `cap_bcs`/`cap_wcs` × `res_*` extremes (L/C spread), temperature extremes | 50 Ω port convention above. Gated on a simulatable passive: no PDK inductor or t-line model exists (P), so S11 is **not simulatable at all** until EM extraction lands — see open item 3. |
| 5 | **LNA output / interstage match, S22** | **OPEN** — form choice (50 Ω vs conjugate match) needs its own DR | **≤ −10 dB** across band (50 Ω) **or** a stated conjugate match to the mixer RF port | ≤ −15 dB | (E) | as row 4 | Row deliberately admits two forms because the LNA→mixer interface convention is undecided (see "Port convention" above). Whichever is chosen must be recorded in a DR before this row is ratified. |
| 6 | **Stability, k-factor** | **RATIFIED (target)** | **k > 1** (unconditional) across band **and out-of-band to at least 3× the upper band edge (≥ 63.6 GHz)**, all corners | k > 1.5 | (E), house rule | worst process × temp × supply combination; out-of-band as well as in-band | Not optional and not an afterthought. An HBT with 400 GHz fmax has gain far above the band; out-of-band oscillation is the realistic failure. `μ`-factor may be reported alongside k/Δ. |
| 7 | **LNA IIP3** | **RATIFIED (target)** | **≥ −15 dBm** (input-referred) | ≥ −10 dBm | (E) | `hbt_typ`, nominal supply/temperature (to be confirmed — linearity's corner dependence is a bench finding, not an assumption) | Must be measured by **two-tone transient + FFT**, with tone spacing, tone powers, transient length, window, and FFT bin resolution recorded beside the number, and the extrapolation range stated. No IIP3 claim without that bench. |
| 8 | **LNA P1dB (input-referred)** | **RATIFIED (target)** | **≥ −25 dBm** | ≥ −20 dBm | (E) | as row 7 | Added because IIP3 alone does not bound compression, and a receive front end behind a real antenna sees blockers. Single-tone power sweep; the sweep range and the 1 dB fit method are recorded with the number. |
| 9 | **Mixer conversion gain (voltage or power — state which)** | **RATIFIED (target)** | **≥ 8 dB** across band, active (Gilbert-cell class assumed) | ≥ 12 dB | (E) | `hbt_wcs`, 125 °C, min supply | **NEEDS-VERIFICATION.** The row is meaningless without stating *which* conversion gain: this document requires **power conversion gain into a 50 Ω IF load** as the primary, with voltage conversion gain into a stated capacitive load permitted as a secondary, explicitly labelled figure. |
| 10 | **Mixer noise figure, SSB** | **RATIFIED (target)** — measurement method open (issue #2) | **≤ 12 dB** | ≤ 9 dB | (E) | `hbt_wcs`, 125 °C | **NEEDS-VERIFICATION.** SSB vs. DSB must be stated with every number (they differ by ~3 dB for an image-unfiltered downconverter, and confusing them is the classic way a mixer NF claim becomes wrong). The image-rejection assumption behind "SSB" is an open item — no image-reject architecture is chosen. ngspice has no `.pnoise`; the measurement method is a bench-design problem, see `porting-plan.md`. |
| 11 | **Mixer IIP3** | **RATIFIED (target)** | **≥ −5 dBm** | ≥ 0 dBm | (E) | `hbt_typ`, nominal | Same two-tone requirements as row 7; tones placed in-band, IM3 read at IF. |
| 12 | **Cascade (LNA + mixer) NF, SSB** | **OPEN** — gated on the interface-convention DR (open item 4) | **≤ 4.0 dB** | ≤ 3.0 dB | (E) | `hbt_wcs`, 125 °C | The row the system actually cares about. **Measured on the cascade**, not computed by Friis from rows 3 and 10, unless the two are genuinely 50 Ω-interfaced (see "Port convention"). Friis-computed values may be reported as a cross-check, labelled as such. |
| 13 | **Cascade conversion gain** | **OPEN** — gated on the interface-convention DR (open item 4) | **≥ 28 dB** | ≥ 35 dB | (E) | `hbt_wcs`, 125 °C, min supply | Same measurement rule as row 12. |
| 14 | **LO frequency range** | **OPEN** — moves with rows 1 + 16 | **16.7–20.2 GHz** (low-side LO, 1 GHz IF) | high-side LO 18.7–22.2 GHz as an alternative, not a commitment | derived from rows 1 + 16 | — | Arithmetic check: `f_LO = f_RF − f_IF` over 17.7–21.2 GHz at `f_IF = 1 GHz` ⇒ 16.7–20.2 GHz. The IF plan is itself DRAFT (row 16), so this row moves with it. LO source class (external ideal source for bench work vs. an on-PDK LC VCO of the `sg13g2-vco` class) is an open item, not settled here. |
| 15 | **LO drive level and LO-to-RF leakage** | **OPEN** — LO drive to be set by the mixer bench; provisional vs DR-0002 | LO drive **TBD** (to be set by the mixer bench, not guessed); **LO-to-RF leakage ≤ −30 dBm** referred to the RF port, and **LO-to-IF leakage ≤ −30 dBm** | leakage ≤ −40 dBm | (E) | `hbt_typ` and mismatch corners (leakage is a matching/symmetry effect, so `hbt_typ_mismatch` is in scope) | LO drive level is deliberately blank: the required drive is an output of the mixer design, and a guessed dBm here would silently constrain the topology. Leakage is a **power at a port**, so it is only meaningful with the LO drive level stated beside it. |
| 16 | **IF centre and bandwidth** | **OPEN** — LEO channel-bandwidth assumption unverified; interacts with DR-0002 | IF centre **1 GHz** (DRAFT); **IF BW ≥ 500 MHz** (−1 dB), one LEO broadband channel | IF BW ≥ 1 GHz | (E) | `cap_*` corners (IF load RC), 125 °C | **NEEDS-VERIFICATION**: "one LEO broadband channel ≈ 500 MHz" is stated from general knowledge and not checked against any published channel plan. The IF centre interacts with image rejection and with the beamsteering partition (DR-0002) — a digital-beamforming partition would want a different IF plan than an LO-phase-shift partition. |
| 17 | **Supply rail** | **RATIFIED (target)** | **≤ 2.5 V** total rail, with **no single `npn13G2` seeing `V_CE` above 1.4 V** (BVCEO min) **and no device operated outside the model card's own `vce` 0.4–2.0 V validity window** | a single 1.8 V rail if the topology allows it | (P) §3.1 + `sg13g2_hbt_mod.lib` header | — | This is the row most tightly bound by (P), and the binding constraint is **two-sided**: BVCEO min is 1.4 V, and the VBIC card is only *characterized* to `vce ≤ 2.0 V`. A cascode must distribute stress so each device sits inside both. **`npn13g2v` (BVCEO 2.2 V) is not a usable escape at Ka band**: its FT is min 90 / target 120 GHz (P §3.3), i.e. `fT/f ≈ 4.5–6` at 20 GHz — see DR-0001. |
| 18 | **DC power, LNA + mixer, per element** | **RATIFIED (target)** — provisional vs DR-0002 | **≤ 40 mW** | ≤ 25 mW | (E) | `hbt_bcs`, −40 °C (bias current typically peaks there for a fixed bias network) | Per-element power is the number the array multiplies. It is the single row most directly coupled to the beamsteering partition (DR-0002): an RF-path phase shifter per element adds loss the LNA must make up, i.e. power. |
| 19 | **AREA** (absolute) | **OPEN** — value needs a first floorplan + cost/reticle economics (open item 8) | **TBD — set at ratification**, method fixed here: the bound is the drawn bbox area in mm² of the LNA + mixer cell, measured by `klt economy` | — | (KLT) | — | Deliberately not guessed. The **element pitch does not set it**: half-wave spacing at the 21.2 GHz upper band edge is **7.07 mm** (DR-0001), enormous relative to any plausible die area, so the pitch constrains the *board*, not this die. The bound should therefore be set from **cost/reticle economics plus a first floorplan**, not from array geometry. |
| 20 | **AREA-EFF** (efficiency composite) | **OPEN** — utilization floor + dead-margin caps need `klt economy` evidence (open item 8) | Per [klayout-tools#1086](https://github.com/2AMLogic/klayout-tools/issues/1086) / [`design-evidence-tiers.md` § "Area-efficiency spec convention"](https://github.com/2AMLogic/klayout-tools/blob/main/docs/design-evidence-tiers.md): **hard bounds** — `bbox_tightness` = 1.0, `dead_margins_um` ≤ a per-edge cap set at ratification, `largest_empty_regions` ≤ a set bbox fraction; **calibrated bound** — `utilization` ≥ a floor **not set here**; **judgment layer** — an `economy-review` skill verdict of `pass` | — | (KLT) | — | Checked in one command via `klt economy`'s `--area-eff-*` flags. The utilization floor is **deliberately left unset**: the klt doc's own guidance is that analog block kinds carry *no named floor* (typical ranges 0.30–0.55) precisely because a wrong floor drives cramming, which trades against matching and DRC margin. Set it from this block's own `economy-review` evidence, not by default. |

---

## Verification corners

**Ratified as the binding corner frame for the RATIFIED (target) rows by
[DR-0003](decision-records/0003-target-spec-first-ratification.md)**, with
the passive/EM axis explicitly **OPEN** (last row below). Derived from the
PDK's actual corner files (P), **not** copied from a sibling:

| Axis | Set | Source |
|---|---|---|
| HBT process | `hbt_typ`, `hbt_bcs`, `hbt_wcs` (**three**, not five) | `cornerHBT.lib`, read directly |
| HBT mismatch | `hbt_typ_mismatch` / `hbt_bcs_mismatch` / `hbt_wcs_mismatch` for rows where matching matters (row 15 leakage) | `cornerHBT.lib` |
| Capacitor process | `cap_typ`, `cap_bcs`, `cap_wcs` | `cornerCAP.lib` |
| Resistor process | `res_typ`, `res_bcs`, `res_wcs` | `cornerRES.lib` |
| MOS process (only if a MOS device is used — e.g. `sg13_hv_svaricap` tuning, a MOS bias mirror) | five-corner `tt`/`ff`/`ss`/`fs`/`sf` | `cornerMOSlv.lib`, `cornerMOShv.lib` |
| Temperature | −40, 27, 125 °C | VBIC card's own validity window, `sg13g2_hbt_mod.lib` header |
| Supply | nominal ± 10 % around whatever row 17 ratifies | convention |
| Frequency | band edges + centre minimum, sweep preferred | "Frequency coverage" above |
| **Passive / EM** | **not yet resolvable** — no PDK inductor or t-line corner model exists; an EM-extracted model has *no* process corner axis at all (a field solve of one drawn geometry against one stackup) | (P), (S-VCO) |

**The passive axis is an open hole, not an omission.** (S-VCO)'s EM route
produces one model per drawn geometry against the PDK's published stackup —
it does not produce a process-cornered inductor. How a matching network's
passive variation is cornered at all on this PDK is an open question this
table does not pretend to answer; see open item 3.

---

## Open items

Status after the first ratification pass
([DR-0003](decision-records/0003-target-spec-first-ratification.md)):
items 1's *second route* was taken for rows 2, 3, 9 and 10 (re-stated
self-derived targets, defended there) — the citation gap itself remains
open follow-up; item 5's *row* (17) is ratified as a target and the
**topology** question stays open; items 2, 3, 4, 8 and 9 are the recorded
**gates** on the OPEN rows and stay open unchanged.

1. **Replace every (E) flag with a real citation.** Published SiGe Ka-band
   LNA and active-mixer results, each cited with author, venue, year, and the
   specific number taken — or the row is re-stated as an explicitly
   self-derived engineering target and defended as such (the route DR-0003
   took for rows 2, 3, 9, 10; the literature check remains open). This is
   the single largest gap in this document.
2. **Verify the band allocation edges** (row 1) and the LEO channel-bandwidth
   assumption (row 16) against a checkable primary source.
3. **The 20 GHz passive question.** No PDK inductor or transmission-line
   model exists (P). (S-VCO) proved openEMS extraction works on this PDK and
   that multi-turn spirals self-resonate at **8.07/9.42 GHz** — below the
   band — while the single-turn `p1` geometry holds **Q ≈ 12.3 at 20 GHz**
   with no SRF below 30 GHz. Whether this block's matching networks are
   single-turn spirals, TopMetal2 transmission lines, or both, and how they
   are cornered, is undecided. Rows 4, 5, 6, and (through matching loss) 3
   cannot be simulated at all until it closes.
4. **The LNA→mixer interface convention** (rows 5, 12, 13): 50 Ω back-to-back
   or co-designed interstage match. Decide in a DR before ratifying those rows.
5. **The supply/bias topology** (row 17) under a 1.4 V BVCEO and a 2.0 V
   model-validity ceiling. `sg13g2-lna` flags the identical question for its
   own block and has not closed it either.
6. **Mixer NF measurement method** (row 10). ngspice has no `.pnoise` and no
   PSS; SSB NF of a time-varying circuit is not a `.noise` analysis. The
   method — and its stated limits — is a bench-design deliverable of issue #2.
7. **The LO source class** (row 14) and whether the LO port is single-ended
   or differential, and at what reference impedance.
8. **AREA absolute bound** (row 19) and the `utilization` floor (row 20),
   both to be set from a first floorplan plus `klt economy` evidence.
9. **The beamsteering partition** (DR-0002) — deliberately deferred, but it
   bounds rows 15, 16, and 18, so ratifying those three is provisional until
   it closes.

---

## Process

Decision records live in [`decision-records/`](decision-records/), numbered
`NNNN-<slug>.md`, one decision per record, **append-only**: a record is never
deleted or rewritten once ratified — it is superseded by a later,
higher-numbered record that says why. A row in this table becomes ratified
only when a decision record says so, through the two-key mechanism (EE key +
market key).

Per `CLAUDE.md`: **agents do not relax the ratified spec to make a result
pass.** A failing result is a recorded failing result; changing the bound to
match it requires a decision record that argues the bound was wrong, on
evidence, before the fact.
