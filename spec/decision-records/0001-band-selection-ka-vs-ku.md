# 0001: Receive band — Ka-band downlink (17.7–21.2 GHz), with Ku as the recorded fallback

- **Status**: **proposed** — argued here, **not ratified**. No key has been
  turned.
- **Date**: 2026-09-12
- **Decided by**: Builder agent, issue #1 (proposing; ratification is not the
  proposer's to give)
- **Ratification**: two-key (EE key + market key). **Neither key is turned.**
  Until both are, `spec/target-spec.md` row 1 stays DRAFT and every
  frequency-dependent row below it is provisional.

---

## Context

The band is the first thing that has to be settled, because almost nothing
else can be designed without it. The LNA's matching network, the device size
and bias, the mixer's LO range, the IF plan, the choice between lumped and
distributed passives, and whether an on-chip inductor exists at all in the
usable sense — every one of those follows from the band and none of them
survives a band change. `CLAUDE.md` says so directly: *"do not size a matching
network for a band nobody has ratified."*

The operator's standing direction is that the band is chosen **to take best
advantage of the PDK, not to be easy**. That direction is what this record
argues against the evidence, rather than assuming.

The top-level `README.md` already carries the Ka-band draft; this record is
where the argument for it lives, and where the condition that would overturn
it is written down in advance rather than after a disappointing result.

---

## Decision (proposed)

**Draft the receive band as the Ka-band satellite downlink, 17.7–21.2 GHz**,
with every `spec/target-spec.md` row required to hold across the *whole* band
(band edges and centre minimum; a swept result preferred) at every corner.

**Record the Ku-band downlink, 10.7–12.75 GHz, as the fallback**, together
with the explicit trigger below that would move the band to it.

> **Band-edge caveat, stated up front.** The 17.7–21.2 GHz and
> 10.7–12.75 GHz figures are stated from general knowledge of the ITU/FSS
> space-to-Earth plan and were **not** checked against the ITU Radio
> Regulations or any operator's published channel plan in the environment this
> record was written in. **TBD — needs verification before ratification.**
> The *argument* below does not turn on the exact edges (a ±0.5 GHz change
> moves no conclusion), but the ratified row must not carry an unverified
> allocation.

---

## Argument — why Ka exploits this PDK

### 1. The HBT has real headroom at 20 GHz, and the alternative device does not

From the PDK's own parametric spec
(`ihp-sg13g2/libs.doc/doc/SG13G2_os_process_spec.pdf` Rev. 1.2, §3.1–3.3):

| Device | AE | BVCEO min/target | FT min/target | FMAX min/target |
|---|---|---|---|---|
| `npn13g2` | 0.07 × 0.9 µm² | 1.4 / 1.6 V | **300 / 350 GHz** | **400 / 450 GHz** |
| `npn13g2l` | 0.07 × 1 µm² | 1.4 / 1.6 V | 280 / 330 GHz | 380 / 430 GHz |
| `npn13g2v` | 0.12 × 1 µm² | **2.2 / 2.5 V** | **90 / 120 GHz** | 280 / 330 GHz |

Ratios at the **upper band edge** (21.2 GHz — the worst case, not the centre):

- `npn13g2`, spec **minimum** fT: `300 / 21.2 = 14.2`.
- `npn13g2`, spec minimum fmax: `400 / 21.2 = 18.9`.
- `npn13g2`, **measured** fT at the *binding* corner — `sg13g2-lna` record
  `20260910-200059-7da7038`, `wcs`/125 °C, at the noise-optimum bias, 199 GHz:
  `199 / 21.2 = 9.4`.
- `npn13g2v`, spec minimum fT: `90 / 21.2 = 4.2`.

The README's claim of "an fT/f ratio near 15 at 20 GHz" checks out against the
spec-minimum fT (`300/20 = 15`). **The honest qualifier the README does not
carry** is that at the binding corner and the noise-optimum bias the measured
ratio is closer to **10**, not 15. Ten is still workable for a low-noise stage;
it is not comfortable, and the NF target is where that will show.

The second row of that arithmetic is the one that makes this a real
PDK-exploitation argument rather than a slogan: **`npn13g2v`, the only SG13G2
device with enough BVCEO to take a 2.5 V rail on one device, is useless at
Ka band** (fT/f ≈ 4–6). Ka band forces the design onto the fast, fragile
1.4 V-BVCEO device and therefore onto a cascode that distributes voltage
stress — which is exactly the kind of constraint that makes this block a
useful canary instead of a comfortable one.

### 2. The PDK's own parametric spec is characterized into this frequency range

`SG13G2_os_process_spec.pdf` §2.11 (S-Varicap, thick gate oxide) specifies the
varactor's quality factor **at 15.8 GHz**: `QFACTOR_m3` min/target/max
**50 / 62 / 75**, `QFACTOR_0` **35 / 43 / 50**, `QFACTOR_3` **35 / 43 / 50**,
on a 10 × (3.74 × 0.3) µm² device; capacitance 23 / 35.3 / 39.5 fF/µm² at
−3 / 0 / +3 V (targets).

That is a **measured, process-controlled** parameter at 15.8 GHz. IHP does not
put a 15.8 GHz Q into its process-control spec for a process it expects to be
used at 2.4 GHz. It is the strongest single piece of evidence that the upper
end of this PDK's intended envelope is in the Ku/Ka region — and it is a
primary-source PDK number, not an inference from a datasheet headline.

### 3. The passive story at 20 GHz is *different*, and the difference cuts both ways

From `sg13g2-vco`'s openEMS extraction (`main` @ `c348700`, record
`20260910-052657-3896421`) of the PDK's own `inductor2` PCell:

| Geometry | turns | L @ 1 GHz | Q @ 20 GHz | SRF (EM) |
|---|---|---|---|---|
| `p1` | 1 | 98.5 pH | **12.32** | none below the 30 GHz scan ceiling |
| `p13` | 5 | 5.12 nH | — (past SRF) | **8.07 GHz** |
| `p11` | 4 | 4.28 nH | — (past SRF) | **9.42 GHz** |

Read honestly, this says three things:

- **Multi-turn spirals are dead at Ka band** — both multi-turn PDK testcase
  geometries self-resonate *below* 17.7 GHz. Not marginal: dead.
- **Single-turn spirals look genuinely good at Ka band** — Q ≈ 12 at 20 GHz
  with no self-resonance in the scanned range. And Q rises with frequency for
  this structure (1.90 at 1 GHz → 12.32 at 20 GHz), which is the usual
  series-`R`-limited behaviour and is *favourable* to the higher band.
- **The inductance you need at 20 GHz is small enough to be a single turn.**
  A 50 Ω-scale series reactance at 20 GHz is `L = 50/(2π·20e9) ≈ 400 pH`;
  at 12.75 GHz the same reactance needs `≈ 625 pH`. Higher frequency needs
  *less* inductance, and less inductance means fewer turns, which means higher
  SRF and higher Q. This is the core of why Ka is the PDK-exploiting choice
  rather than the reckless one. *(The 400/625 pH figures are one-line
  reactance arithmetic, not a matching-network design; the actual values
  depend on a topology that does not exist yet.)*

**The counter-argument, recorded because a one-sided band record is not
evidence.** A matching inductor wants SRF comfortably above the operating
frequency — the conventional bar is 2–3×. At 21.2 GHz that asks for
SRF ≥ 42–64 GHz; at 12.75 GHz it asks for SRF ≥ 26–38 GHz. The only data
point above 20 GHz is `p1`, and all we know about its SRF is that it is
somewhere above 30 GHz — **the scan stopped there.** Whether a ~400 pH
geometry on this PDK clears 42 GHz is **unknown**, and the geometry that
delivers 400 pH is not `p1` (which delivers ~90 pH). Ku is genuinely easier
on this axis, and pretending otherwise would be advocacy, not a decision
record. The trigger condition below is written precisely around this unknown.

### 4. The array the block serves is a better array at Ka

Half-wave element spacing, `d = c / (2·f)`, at the **upper** band edge (the
binding edge — grating lobes are set by the shortest wavelength):

| Band | upper edge | λ | λ/2 | d for grating-lobe-free ±60° scan (`λ/(1+sin 60°)`) |
|---|---|---|---|---|
| Ka | 21.2 GHz | 14.14 mm | **7.07 mm** | 7.58 mm |
| Ku | 12.75 GHz | 23.51 mm | **11.76 mm** | 12.60 mm |

(At 20 GHz exactly, λ/2 = 7.50 mm — the "~7.5 mm" figure the README quotes.
The **7.07 mm** figure is the one a design should use, because it is set by
the band edge, not the centre.)

For a fixed aperture area, Ka packs `(11.76/7.07)² ≈ 2.8×` as many elements as
Ku. That is 2.8× as many per-element chips per square metre of array, and a
correspondingly finer beam for the same aperture — which is the entire reason
a *per-element* chip is the right product to build. Ka also carries more
spectrum: 3.5 GHz of allocation against Ku's 2.05 GHz, which is what makes the
≥ 500 MHz IF bandwidth row worth having.

**What this does *not* imply**: 7.07 mm is enormous next to any plausible die,
so element pitch imposes **no** area constraint on this chip. The AREA row
(`target-spec.md` row 19) must be set from cost and floorplan, not from array
geometry. Stating this explicitly so a later reader does not mistake the
tiling argument for an area budget.

### 5. The "a CMOS open PDK cannot follow" claim — weakened, not dropped

The README asserts that Ka band is where SG13G2's HBTs "are decisive and a
130 nm CMOS open PDK cannot follow." The direction of that claim is
uncontroversial (a 130 nm CMOS NMOS has an fT one small multiple of the HBT's,
so fT/f at 20 GHz is a single-digit number where the HBT's is ~15). **But no
fT figure for SG13G2's own MOS devices appears anywhere in
`SG13G2_os_process_spec.pdf`'s MOS sections**, and none was obtained from any
other checkable source in this environment. So: **TBD — needs verification.**
The decision does not rest on it; it is a differentiation claim for the README,
not a design input, and it should not be repeated as a sourced number until it
is one.

---

## Alternatives considered

- **Ku-band downlink, 10.7–12.75 GHz — the fallback, not a rejected option.**
  Every device and passive margin improves: fT/f ≈ 23.5 on spec-minimum fT,
  ≈ 15.6 at the measured binding corner; the SRF bar drops to 26–38 GHz;
  `sg13g2-vco`'s existing passive dataset partially covers it. It is a real
  band with real commercial traffic. It is **not** chosen as the draft because
  it asks less of the PDK than the PDK can give, it halves the element count
  per aperture, and it narrows the available spectrum — and because the
  standing direction is to choose for PDK advantage. If the trigger below
  fires, moving here is a *planned* retreat with the evidence already
  gathered, not a failure.
- **X band (~7–8 GHz) or lower.** Rejected: comfortably inside what a CMOS
  open PDK can do, so the block stops being a canary for *this* PDK's
  distinguishing capability. It would also sit close to `sg13g2-vco`'s
  measured multi-turn SRFs (8.07/9.42 GHz), which is the worst possible place
  to put a band — right where the available passives self-resonate.
- **Q/V band (~37–50 GHz).** Rejected for now: fT/f falls to ~6–8 on
  spec-minimum fT, the whole design becomes distributed (a λ/4 line at 40 GHz
  is under 1 mm, which is on-die-plausible and genuinely interesting), and
  **zero** EM-extracted passive data exists there in this fleet. It is the
  right *next* canary, not the right *first* one. Recorded here so a future
  record can pick it up rather than re-derive it.
- **Two bands / a "wideband 10–22 GHz" front end.** Rejected explicitly.
  `CLAUDE.md`: *"do not call a design 'wideband' unless every spec row holds
  across the whole ratified band at every corner."* A 10–22 GHz span is a
  1:2.2 bandwidth; claiming every row across it, at every corner, with no
  simulatable passive model, would be a claim this repo cannot back.

---

## Trigger to revisit — the explicit condition that moves the band to Ku

**This record is superseded by a Ku-band record if, and only if, the following
is demonstrated and recorded in `sim/`:**

> No matching-network passive realizable on SG13G2 — single-turn spiral,
> TopMetal1/TopMetal2 transmission line, or any combination — simultaneously
> delivers **(a)** the reactance the input/output match needs across
> 17.7–21.2 GHz, **(b)** a self-resonant frequency at least **2×** the upper
> band edge (**≥ 42.4 GHz**), and **(c)** a quality factor high enough that
> the network's own insertion loss leaves `spec/target-spec.md` row 3
> (LNA NF ≤ 2.5 dB) reachable — where all three are established by an
> **openEMS extraction of the actual drawn geometry**, following
> `sg13g2-vco`'s recorded flow, with the fit residual reported, **not** by a
> closed-form estimate.

The last clause is not a formality. `sg13g2-vco` measured the closed-form
(Mohan) model overestimating SRF by **+77 % / +50 %** on the two multi-turn
geometries — the analytic route is demonstrably untrustworthy for exactly the
quantity clause (b) turns on. **A band change argued from an analytic
inductance model does not satisfy this trigger.**

Two further, narrower triggers, recorded so they are not argued about later:

- **If the ITU allocation check (the caveat above) finds the band edges are
  materially different** from 17.7–21.2 GHz, this record is amended by a
  superseding record stating the verified edges — not silently edited.
- **A trigger that does NOT fire this record**: a disappointing *circuit*
  result. If the first LNA misses NF ≤ 2.5 dB at Ka, that is a design result,
  not a band verdict. Per `CLAUDE.md`, agents do not relax or re-scope the
  spec to make a result pass — and moving the band is the largest possible
  form of that. Only the passive-realizability finding above moves it.

---

## Consequences

**What this makes possible**

- Matching networks can be designed around **sub-nH, single-turn or
  transmission-line** elements, where this PDK's thick top metals
  (TopMetal1 2 µm, TopMetal2 3 µm) and its EM-extracted Q ≈ 12 at 20 GHz are
  actually favourable.
- The array the block serves gets 2.8× the elements per unit aperture versus
  Ku, and 3.5 GHz of spectrum to put the ≥ 500 MHz IF row inside.
- The block becomes a genuine test of the open flow at a frequency where the
  open flow has never been exercised — which is the point of a canary.

**What this makes harder — the honest half**

- **The NF row is at risk.** At the binding corner the measured fT/f is ≈ 10,
  and `sg13g2-lna`'s bare-device 50 Ω NF at 2.4 GHz was already 6.32 dB (typ) /
  8.51 dB (wcs). Reaching ≤ 2.5 dB at 20 GHz needs a real noise match whose
  own loss lands directly on NF. This is the row most likely to fail.
- **`npn13g2v` is off the table**, so the supply/bias topology must solve the
  two-sided constraint (BVCEO min 1.4 V *and* VBIC model validity
  `vce ≤ 2.0 V`) with cascoding on the fast device. No fleet precedent exists.
- **Nothing in the RF path is simulatable until an EM study lands.** S11, S22,
  k-factor, and the matching-loss component of NF are all gated on it. This is
  a hard schedule dependency, not a refinement.
- **Layout becomes part of the circuit.** At 20 GHz, post-layout verification
  (T1 item 7) is a correctness step, not a polish step, and bond-pad/ESD
  parasitics enter the input match. Nobody in this fleet has characterized
  `sg13g2_bondpad.lib`.
- **The `sg13g2-vco` passive dataset only partially transfers.** Its varactor
  data stops at 10 GHz; its useful inductor data is one geometry. Most of the
  passive characterization this block needs does not exist yet.
- **If the trigger fires**, every frequency-dependent target-spec row is
  invalidated and must be **re-derived**, not rescaled — and the matching
  network, device sizing, LO range, and IF plan all restart.

---

## Sources

- `ihp-sg13g2/libs.doc/doc/SG13G2_os_process_spec.pdf`, Rev. 1.2 (2023-12-20)
  — §1, §2.11, §3.1, §3.2, §3.3. Read directly from the local PDK install
  tree; see [`../target-spec.md`](../target-spec.md) § "(P)" for the commit-
  provenance caveat (the tree has no git metadata; the revision is TBD).
- `ihp-sg13g2/libs.tech/ngspice/models/sg13g2_hbt_mod.lib` — VBIC Rev. 1.15
  model card header (validity window `vce` 0.4–2.0 V).
- `2AMLogic/sg13g2-lna` `main` @ `4a87eb8`,
  `sim/hbt-characterization/` record `20260910-200059-7da7038`.
- `2AMLogic/sg13g2-vco` `main` @ `c348700`,
  `sim/inductor-model/em-extraction/` record `20260910-052657-3896421`
  (per-geometry delta summary CSV read directly).
- Wavelength and reactance figures above are one-line arithmetic from
  `c = 299 792 458 m/s`; they are reproducible, not cited.
