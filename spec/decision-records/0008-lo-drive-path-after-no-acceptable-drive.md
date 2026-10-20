# 0008: Mixer LO-drive path after "no acceptable drive" (#61) — comparative proposal, nothing selected

- **Status**: **proposed**. Written and argued, **not ratified**, and it **selects nothing**: its recommendation is a bounded, not-yet-authorized validation plan plus the explicit separate changes it would take to adopt any option. Design work may read it; no claim may cite it as settled.
- **Date**: 2026-10-19
- **Decided by**: Builder agent, issue #68 (proposing only; per [`spec/README.md`](../README.md) an agent turns neither key)
- **Ratification**: two-key (EE key + market key) via the ratification-via-PR path DR-0003 used. **Neither key has been turned.** EE review outcome: **pending**. Market review outcome: **pending**. Operator direction of 2026-10-19 (issue #68) authorizes this *proposal* only; it supplies neither key.
- **Related**: [#68](https://github.com/2AMLogic/sg13g2-sat-rx/issues/68) (referenced as `Part of #68`; closure not authorized), [#61](https://github.com/2AMLogic/sg13g2-sat-rx/issues/61), [#35](https://github.com/2AMLogic/sg13g2-sat-rx/issues/35), [DR-0006](0006-lo-source-class-and-port-convention.md), [DR-0007](0007-statistical-row-classification.md), source trail [`literature-citations-2026-10-19.md`](../literature-citations-2026-10-19.md).

**Status vocabulary used below.** *Ratified target rows*: 2, 3, 4, 6, 7, 8, 9, 10, 11, 17, 18 (DR-0003). *Open rows*: 1, 5, 12–16, 19, 20; rows 14 and 15 (LO range, LO drive/leakage) are the ones this record touches. *Proposed conventions*: DR-0006 (port form). *Compliance*: **none** — no row is shown met by any record. This DR edits no row, no plateau rule, no V_BE window, no sweep bound and no stress limit.

---

## Context

Seven fixed device-level sizings (stacked Gilbert and folded single-balanced at the original sizing and two higher-current sizings each, plus the single-HBT placeholder floor) all return `no acceptable drive in declared sweep` under the bench's LO-selection rule. Evidence (both append-only, untouched here):

- `sim/mixer-topology-feasibility/records/20261010-010744-a10c193.md` (3 candidates, ngspice-46, local).
- `sim/mixer-topology-feasibility/records/20261010-025859-2113f00.md` (7 candidates, ngspice-42, batch).

The rule being applied (README "Stress rules" and `tb.json` `lo_select`): V_CE in [0.4, 1.4] V; V_BE in [0.65, 0.96] V; Ic < 0.003·Nx A flagged; a DC-point or retained-window excursion makes a drive point `rejected_stress`; the selected LO is the start of a run of 3 consecutive stress-valid drives whose gain is within 0.5 dB (`plateau_db: 0.5`, `run_length: 3`); sweep −30…+6 dBm total available power, 3 dB steps, differential 100 Ω port (DR-0006), hbt_typ / 27 C / 2.25 V.

Observed (numbers from the two records, hbt_typ, f19p45 where a band is named):

- Gilbert original and folded original: last stress-valid drive −12 dBm, first rejected −9 dBm; gain rises 1.05 dB (Gilbert) / 1.06 dB (folded) into the last valid point and a further 0.43 dB at the first rejected point. First-rejection reason is V_BE retained trough below 0.65 V (0.565 V Gilbert original, 0.567 V folded original).
- Higher-current sizings: first-rejected troughs 0.592 V (Gilbert A), 0.626 V (Gilbert B), 0.616 V (folded A) — the trough rises with current but stays under 0.65 V. Folded B is rejected from −12 dBm on V_BE **above** 0.96 V; Gilbert A/B exceed 0.96 V at +6 dBm. Gain is still rising 1–4 dB at the last valid point at every sizing (per the #61 README summary).
- At +6 dBm the original candidates show V_BE troughs below −0.79 V and V_CE below 0.1–0.18 V: the unconstrained large-signal swing is far beyond the window, not marginally outside it.
- Placeholder floor: rejected from −3 dBm on V_BE above 0.972 V; gain still rising 2.57 dB into its last valid point.

So no stress-valid point lies on a gain plateau at any tested sizing. These are findings **about the declared sizings and sweep** (the records say so); they are not statements about the topologies in general. The ideal-balun, ideal-bias, no-matching, no-inductor fixture is itself a large caveat: a real LO path has finite source impedance, series elements and parasitics that change the waveform at the device pins.

### What the V_BE window actually is

The model card header (`sg13g2_hbt_mod.lib`, sha256 `ae9288f885dd`; source S1 in the citations file) lists *Meas. Range forward gummel: vbe = (0.3 - 1.04) V* and, separately, *Valid range for model … vbe : (0.65 - 0.96) V*. The window the bench enforces is therefore the owner's declared validity range, narrower than the measured range. The header does not say whether it applies to the instantaneous waveform, to DC bias points, or only to conducting intervals. **That interpretation is not answerable from this repo.** Only the model owner can say.

## Decision (proposed)

This record **does not select an option and does not change any rule.** If ratified as proposed, it records:

1. The four options in the #68 report plus two literature-lead alternatives (below) are the compared set, each judged against the **unchanged** baseline (plateau rule, stress limits, V_BE window, sweep, ports).
2. No option is adoptable today on the evidence in the repository. Options A and B require a *separate, explicit* rule change (named below as P-A, P-B) that goes through both keys; options C and D require a *declared topology change* (a new bench candidate under the unchanged rule), which needs only the validation plan, not a rule change.
3. The proposed next step is the bounded plan in "Validation plan", **conditional on separate authorization of simulation spend**, which this record does not grant. Until then the standing result remains: `no acceptable drive` for all seven sizings.
4. Open items stay open, in particular row 15's LO drive (**TBD**).

## Argument

### Baseline requirement and why the plateau criterion exists (engineering gate)

The plateau rule picks an LO level where conversion gain is insensitive to LO amplitude, so that gain, leakage and linearity are not set by LO level variation (source amplitude error, PVT, mismatch). Physical basis: in a switching mixer, once the quad is hard-switched, gain saturates with LO amplitude; below that, gain tracks LO amplitude (the 1–4 dB still rising at the last valid points is exactly the regime where gain tracks LO). The criterion is physically motivated but its *numbers* (0.5 dB, run of 3 at 3 dB steps) are bench conventions, not sourced from a reference. **Whether a design must sit on a plateau at all, or may instead meet gain/linearity/leakage rows at a controlled non-saturated drive, is a requirements question, not answered by the repo** — it is exactly the "binding criterion" the operator direction asks to keep unchanged initially and to challenge only through an explicit change (P-B).

Why the device-limit side binds: row 17 ratifies V_CE limits (BVCEO 1.4 V min; card 0.4–2.0 V). The V_BE window is the card's validity range (S1) and is enforced as a model-validity limit; a SPICE result outside it is not trustworthy as a prediction of silicon, in either direction. Note the asymmetry the data shows: the *lower* bound is violated by the off-going switch (V_BE trough 0.565–0.626 V, with Ic expected near zero), while the *upper* bound is violated by the highest-current sizings. A 0.31 V window cannot contain a hard-switching LO swing at a 100 Ω differential port at these sizings, per the records.

### Options (each vs. the unchanged baseline)

For each: what it changes, what physical question it answers, what evidence exists, what it would cost, and what it does **not** establish.

**A. Read the V_BE floor as applying to the conducting interval only.**
Requires change P-A: restate the model-validity limit as "V_BE in window whenever the device carries appreciable Ic". Physical argument: an off-going switch with V_BE below turn-on carries ~zero current, so the VBIC forward-current equations are not the active physics; leakage/junction-capacitance terms dominate. Counter-argument: the owner's header gives no such carve-out, the card was *measured* to 0.3 V but still declared valid only from 0.65 V, and the troughs at +6 dBm (below −0.79 V) reach reverse-bias regimes where junction capacitance and breakdown behaviour — important for switching speed and for LO feedthrough — are exactly what the card's validity statement does not cover. Evidence needed: the owner's statement of validity below 0.65 V (S1 gives none) and the VBIC reverse-region documentation (owed, citations #2). **Status: cannot be adopted by this repo alone; would be relaxing a device-validity limit to pass a result unless the owner supports it.** Cost to test: small (re-evaluate stored cells with a conduction-gated check) — but see Validation plan, since stored cells hold extrema, not waveforms; that re-evaluation may not be possible without a re-run.

**B. Define LO selection against the stress-valid maximum instead of a 3-point plateau.**
Requires change P-B: the selection basis becomes "highest stress-valid drive" (with gain-vs-LO slope reported), keeping all stress limits. Pro: keeps device limits intact (the operator's initial favoured direction, 69 % confidence per the operator triage comment). Con: at all seven sizings the stress-valid maximum is on the rising gain slope (1–4 dB), so gain, leakage and IIP3 would be sensitive to LO level by construction; the plateau's purpose (robustness to LO amplitude and PVT) is given up, and a bound reached by the first rejection is set by the *rejection mechanism* (a V_BE floor), not by any system requirement. Without a system requirement for conversion gain at a specified LO level, "accept the maximum" risks treating the observed maximum as the requirement — which the operator direction forbids. **Market evidence for the allowable LO sensitivity is unresolved (below).**

**C. Add an LO-path series element / limiter, or extend the sweep range (declared topology change).**
Physical question: can the waveform at the switch pins be shaped so the swing stays inside the window while the pair still commutates? Candidates: series resistance or capacitive divider at the LO pins (reduces swing at the pins, wastes LO power), clamp/limiter devices (adds their own V_BE/BE-junction stress and capacitance; nonlinear), LO common-mode bias that centres the swing in the 0.65–0.96 V window (the 0.31 V window equals ±0.155 V about 0.805 V — a differential pair needs roughly a few kT/q (≈ 0.1 V) of differential swing to commutate, so a centred small swing is the physics-first thing to test; this is a hand estimate, **not derived or simulated here**, and a sweep extension to smaller steps near the stress edge would be the cheapest probe). Evidence: none in repo; literature on LO-limiting for bipolar switching quads is owed. Extending the sweep to *higher* power does not help (rejections only get worse above −9 dBm); extending to *finer steps* between −12 and −9 dBm would show whether a narrow valid island exists. Note this changes the declared fixture (DR-0006 port form is preserved only if the series element is part of the mixer, not the source).

**D. Change topology (e.g. current-mode / passive-FET switching, or passive V–I with switching quad only).**
Physical rationale: a topology with no stacked HBT quad driven by a large voltage swing removes the V_BE-window problem rather than reinterpreting it. Leads exist (S3: passive input networks / transconductor-less SiGe mixers in 14–23 GHz and V-band, claimed with low LO drive and low power, **abstract-level only, unread**). Open questions that decide fit: whether the SG13G2 open PDK offers switches suited to Ka-band (the SG13G2 MOS devices exist, but their large-signal model validity windows were not reviewed here and the PDK has no inductor model per DR-0006/porting-plan), conversion *loss* instead of gain (row 9 asks ≥ 8 dB gain — a passive core would put the gain burden on the IF amplifier and cascade, which raises row 13/18 questions), and the IF-stage power. **Scope:** a change that stays inside the per-element chain (LNA + mixer) provided any IF amplifier is counted inside the mixer; flagged because the IF gain stage is a possible scope creep.

**E (literature lead). Reduce required LO swing by design: emitter degeneration / lower-gm switching pair, smaller switching devices at higher current density, or a sized LO-pair with explicit common-mode level.** #61 already tried higher current density (trough rose from 0.565 V to 0.626 V in the best case, still < 0.65 V), so current density alone is insufficient at the tested bias points. Not a new idea; kept here because it is the cheapest class (no topology change) and #61 only varied one lever.

**F (literature lead). Active-mixer variants known in the same process.** S3 notes a 24–30 GHz modified Gilbert in IHP's 0.13 µm SiGe process (2025) and other Gilbert-class SiGe mixers. These were run at supplies/power (3.3 V, 65 mW) outside rows 17/18, were not read, and so give no evidence of fit; a tie to this repo's constraints requires the full text (owed).

### Gate summary

| Option | Needs rule change? | Evidence in repo | Evidence from literature (verified) | Cost to test | Risk to ratified rows |
|---|---|---|---|---|---|
| A | P-A (validity reinterpretation) | none | none (owner statement needed) | low–medium | relaxes device-validity limit |
| B | P-B (selection basis) | consistent with #61 data | none | low | gives up LO-insensitivity; rows 9/13/15 undefined vs LO level |
| C | no (new candidate), plus fixture note | none | none | medium | adds LO-path loss/power |
| D | no (new candidate); scope check | none | leads only (unread) | high | rows 9/13/18 trade |
| E | no | partial (#61 current lever) | none | medium | low |
| F | no | none | none (unread) | n/a | n/a |

### Engineering gate — criteria coverage

- **Physical basis of drive criterion**: argued above; the 0.5 dB / run-of-3 constants are bench conventions without a source (flagged, not changed).
- **LO drive and source impedance**: DR-0006 fixes the port as differential 100 Ω, total available power. The waveform at the device pins depends on the mixer input impedance vs. that source; the records' "LO Vdiff loaded pk" column is empty because no drive was selected, so loaded-swing evidence is limited to extrema in the cell JSON sidecars. Whether a real LO source has this impedance is outside scope (DR-0006 item 4: no on-chip oscillator).
- **Bias / model validity across the waveform**: the central issue; see A, and "What the V_BE window actually is". Extrema, not full waveforms, are what the stored records hold.
- **Gain, noise, linearity, leakage**: at the last valid point conversion gain is −2.72 dB (folded original) and −3.05 dB (Gilbert original) at f19p45, against row 9's ≥ 8 dB target (so even at the maximum the *gain* row is not close for these ideal-balun cores; the placeholder at −4.5 dB is worse). Noise (row 10) and IIP3 (row 11) and leakage (row 15) are `not_applicable_no_drive` in both records: **no number exists**. SSB NF method is open (issue #2).
- **Supply and power**: 2.25 V ± 10 % is an exploratory nominal below the 2.5 V ceiling (not ratified). Gilbert tail currents of 2–4.5 mA at ~2.25 V put the Gilbert cores' mixer-only DC at roughly 4.5–10 mW (I×V only) before any LO buffer or IF stage — hand arithmetic, not a measured figure — against a 40 mW LNA + mixer budget (row 18). LO-path losses under option C raise the LO source's power, which is outside this block and has no budget row.
- **PVT / mismatch**: all #61 sweeps ran at hbt_typ / 27 C / 2.25 V only. The stress window's margin vs. corners (hbt_bcs/wcs, −40…+125 °C, supply ±10 %) is unknown; a margin that does not exist at nominal cannot appear at corners, but a pass at nominal may fail at corners. Mismatch leakage evidence: none.
- **Modeling / measurement capability**: ngspice has no `.pnoise`; no inductor model exists; the VBIC card is characterized to 27 C nominal with validity statements as quoted; no silicon exists. Any ratified outcome remains simulation-only.

### Market gate — status

**Unresolved.** No market evidence was gathered or exists in the repository. (2026-10-20: a third retrieval attempt found only unread vendor/agency leads, recorded as V2 in the citations file; none establishes a requirement.) Items needed, each marked unresolved here:

- Intended customer / use case for the per-element receive chain (LEO user-terminal phased array element?) — **unresolved**.
- System-level need that sets conversion gain and the acceptable LO-level sensitivity (cascade gain row 13 is OPEN and itself `(E)`) — **unresolved**.
- Competitive/source benchmarks for Ka-band SiGe receive-element power, area, cost — **unresolved** (owed, citations #4).
- Whether a passive/lossy mixer plus IF gain (option D) is acceptable for system NF (row 12) and power (row 18) — **unresolved**.
- Traceability: criteria trace to rows 9, 11, 13, 15, 17, 18 as they stand, all `(E)` or open except 9/11/17/18; **none of those rows' numbers is market-sourced**, so no option can be said to satisfy a market requirement. The observed maximum drive is **not** used as a requirement anywhere in this record.

## Alternatives considered

- **Silently accept the stress-valid maximum as "the plateau"** — rejected: it would change the selection basis without a record (violates CLAUDE.md and the operator direction).
- **Widen the V_BE window to the measured gummel range (0.3–1.04 V)** — rejected as unsupported: the owner declared a narrower valid range; widening it relaxes a device limit to pass a result.
- **Run a full multi-sizing sweep before deciding** — rejected for this PR: no new simulation spend is authorized; see the plan for a bounded version.
- **Treat 14–23 GHz / V-band literature results as evidence for SG13G2** — rejected: different technology nodes, supplies and models; unread.

## Validation plan (proposed; **not authorized and not run**)

Each step needs separate approval of simulation spend. Resource estimates are hand estimates from #61 (7 requests, one unit each, ngspice, batch fleet; no wall-clock recorded in the records read):

1. **Waveform re-read (no new sim, if raw waveforms exist; else 1 request per candidate)**: obtain device-pin V_BE(t) and Ic(t) at −12 and −9 dBm for the original and best-trough sizing (Gilbert B) to see how long and at what Ic the V_BE falls below 0.65 V. Cost: ~2 single-unit requests. Informs A. *Stop rule*: if V_BE < 0.65 V occurs while Ic > 1 % of the on-state current, A is not supportable without owner evidence.
2. **Fine-step LO sweep −12 … −9 dBm at 0.5 dB steps, 2 sizings, nominal corner, 3 band points**: ~14 single-unit requests. Informs B/C (is there a plateau between the valid and rejected points?). *Stop rule*: if gain still rises > 0.5 dB per 3 dB-equivalent at the last valid point, a plateau is not reachable at that sizing; stop.
3. **Option C probe**: LO common-mode centred in the V_BE window with a divided swing, 2 variants, same sweep as step 2: ~14 requests. *Stop rule*: if the V_BE window cannot be satisfied with swing sufficient to commutate (Ic imbalance > 90/10 across the pair), stop.
4. **Option D (only if steps 1–3 fail)**: a design-bench task, not a probe. Needs a scoping record first (switch device models, IF-stage budget). No estimate offered.
5. **Corner expansion** only for a candidate that passes step 2/3 at nominal.

Overall cap proposed: ≤ 30 single-unit requests on the batch backend before returning to a new DR. Ratification keys must be turned before any rule change P-A / P-B is applied.

## Trigger to revisit / what will decide this

This record is superseded or advanced when any of the following becomes available: (a) the model owner's statement of V_BE validity for off-going devices (decides A); (b) the full texts of the S3 papers recorded in the citations file with LO power and stress practice (decides D, E, F lean); (c) a market-side requirement for conversion gain/LO sensitivity (decides B); (d) the outcome of validation steps 1–3 once authorized. If none of (a)–(d) exists, the record remains `proposed` with the standing result `no acceptable drive`.

## Consequences

- No spec row, rule or limit changes now; #61's records stand untouched.
- Bad consequences stated plainly: the mixer-core bench still has **no selected LO drive**, so rows 9, 10, 11, 13, 15 have **no mixer evidence**, cascade rows 12/13 remain unmeasurable, and T1 items 5–8 stay blocked for the mixer. The literature trail is thin (one verified primary source, three V2 leads, four owed items); the market gate is entirely open. Option B would unblock the bench fastest but is the one most likely to relax intent; option C/D keep the rule but cost more.
- If ratified as written, this record authorizes nothing beyond itself; a later record or issue must authorize simulation spend and any rule change.
