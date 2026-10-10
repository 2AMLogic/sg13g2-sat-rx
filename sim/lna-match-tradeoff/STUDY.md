# lna-match-tradeoff: study declaration (issue #74)

This file and `testbench/study.json` are the declaration of the study. They
were committed **before** any recorded campaign, in their own commit. A
record made later cites the declaration's sha256 and freezes a copy of
`study.json` under `netlist-snapshots/<record-id>/`. To change anything below
after a record exists, add a new declaration and a new record that says why.
This one is never edited.

**Claim: none.** This is an ideal-element feasibility screen. Every input
network is ideal, lossless L/C. No PDK inductor model exists, and spec row 1
(the band) is OPEN, so the 17.7-21.2 GHz band here is DRAFT. The thresholds
below are screens traceable to rows 2, 3, 4, 6 and 17. They are not
compliance checks, and nothing here claims a spec row met.

## Question

`design/lna_stage1` uses a power (S11) match at the band centre, not a noise
match (`design/lna_stage1.md`, "Matching"). Its recorded NF at 19.45 GHz
spans 2.6-4.8 dB, and |S11| is about -5 dB at the band edges. The question:

> With the cascode's sizing, bias and output damping frozen, does any ideal
> lossless input network jointly reach NF <= 2.5 dB and S11 <= -10 dB across
> the DRAFT band, with enough gain and stability?

## What is frozen and what varies

- **DUT.** `design/netlist/lna_stage1.spice`, sha256
  `ad4fe1be5754f21fc4b2dd67863234858dc399e2a8232d3b20cf530014b8c447`.
  - `matchstudy.dut_text` changes exactly two lines. `Cshunt in gnd 170f`
    becomes `{c_sh1}` and `Lin in in2 1.41n` becomes `{l_in}`. It also adds
    one line, `Csh2 in2 gnd {c_sh2}`, a device-side shunt C.
  - It refuses to run if either original line differs. A test proves every
    other byte is unchanged.
  - Rd, the bias network, device sizing, `Cblk_in` and the output network
    (`Lfeed`, `Rd`, `Cm`) are untouched.
- **Baseline.** `baseline` is the schematic's own network: `c_sh1` = 170 fF,
  `l_in` = 1.41 nH, `c_sh2` = 0.
- **DC.** The input network is DC-isolated by `Cblk_in`. The operating point
  is therefore the same for every network at a given PVT point. The smoke
  checks this (op with the baseline vs with another network: identical), and
  every cell carries the op checks of its PVT point.

## Derivation of the range (this circuit, not the bare device)

The range is derived from one local single-point run at the nominal point
(hbt_typ, 27 C, 2.5 V; `run.py derive`, ngspice-46). Its output is the
`derivation` block of `study.json`.

- **Core input impedance.** `probe_thru` (series L = 1e-18 H, no C) shows
  the core's input impedance at node in2 directly from 50 ohm.
- **Noise parameters.** The core's four noise parameters come from a
  least-squares fit of NF over eight L-sections presenting |Gamma_s| = 0.5
  at f0, plus the thru. The fit residual is 2e-10 dB rms. The four-parameter
  model is exact for a linear noisy two-port. This includes the bench's noisy
  50 ohm load (see "NF convention").

| f (GHz) | Z_in core (ohm) | Z_opt circuit (ohm) | Fmin (dB) | Rn (ohm) |
|---|---|---|---|---|
| 17.70 | 24.0 - j160.1 | 156.1 + j101.4 | 1.430 | 37.5 |
| 18.55 | 22.9 - j152.4 | 151.6 + j100.4 | 1.441 | 37.2 |
| 19.45 | 21.9 - j145.0 | 146.1 + j99.9 | 1.466 | 37.2 |
| 20.30 | 21.3 - j138.7 | 140.5 + j99.7 | 1.499 | 37.5 |
| 21.20 | 20.7 - j132.6 | 134.4 + j99.6 | 1.540 | 38.0 |

At f0 = 19.45 GHz the declared family is built around two points (50 ohm
reference, seen from the core at node in2):

- **Gamma_pm = 0.7255 + j0.5534.** The power match, i.e. conj(Gamma_in) of
  the core; |Gamma| = 0.912.
- **Gamma_opt = 0.5952 + j0.2062.** The circuit's own noise optimum.

The bare-device Zopt (about 166 + j203 ohm, from the Ka-band
characterization) is **not** used. The circuit's optimum differs because of
Rbias, the cascode and the output network.

## The declared family (frozen in `study.json` `candidates`)

**Topology.** Two-element lowpass L-sections, in the baseline's own class:

- `shunt_first`: C at the port, then series L (the baseline's arrangement);
- `series_first`: series L, then C at node in2.

**Targets.** Each target is a source reflection Gamma_s at f0:

- **Segment.** Nine points from Gamma_pm to Gamma_opt, at t = 0, 0.125, ...,
  1. This is the classic power-to-noise tradeoff line.
- **Opt rings.** Rings of radius 0.1 and 0.2 around Gamma_opt, every 45
  degrees.
- **Pm rings.** Rings of radius 0.03 and 0.06 around Gamma_pm, every 45
  degrees. These are small radii because the power match sits at |Gamma| =
  0.91.

**Realization.** Every realizable orientation of every target becomes one
candidate. The closed form is `matchstudy.synthesize`.

- Element values are rounded to 4 significant digits, and the rounded value
  is what is simulated. The test `test_declared_candidates_hit_their_targets`
  checks the result against its target within 2e-3 in Gamma.
- Unrealizable pairs are kept in `excluded_targets` with the reason. A
  target with |Gamma| >= 0.98 is excluded. A target/orientation pair is also
  excluded when it would need a series C or a shunt L, or when it needs
  Rs > 50 ohm (`shunt_first`) or Gs > 1/50 S (`series_first`).

**Result.** 41 family candidates (19 `shunt_first`, 22 `series_first`), plus
the baseline and 9 probes. 49 target/orientation pairs are excluded with
reasons.

**Fixed across corners.** Element values never change across corners.

**Scope of the family.** It is deliberately small. Two-element sections
cannot track the core's Q of about 6.6 over an 18 % band; the baseline
already shows this. So the study adds a network-independent bound, which is
not limited to L-sections.

## Network-independent bound (probes)

Behind any lossless reciprocal input network, the port NF and the port |S11|
depend only on Gamma_s(f), the source reflection the network presents to the
core:

- NF = F_core(Gamma_s);
- |S11| = |(Gamma_in - Gamma_s*) / (1 - Gamma_in Gamma_s)|.

So at each dense frequency the study fits the noise parameters from the
probes, takes the core S-parameters from `probe_thru`, and computes two
bounds:

- `nf_bound`: the smallest NF with |S11| <= -10 dB. This is the minimum
  over a mismatch circle.
- `s11_bound`: the smallest |S11| with NF <= 2.5 dB. This is the minimum
  over a noise circle.

**How to read the bound.**

- If `nf_bound` > 2.5 dB at any band frequency, then **no lossless input
  network of any order** meets the joint screen at that PVT point. This is a
  necessary condition.
- If `nf_bound` <= 2.5 dB everywhere, a realizable network is not implied.
  It would still have to make Gamma_s(f) track the feasible region across
  the band, which reactance (Foster) constraints limit.

**Model check.** The bound is used at a point only if two conditions hold:

- every selectable network's simulated NF and S11 match the prediction from
  (noise parameters, S_core, closed-form Z_s(f)) within
  `tolerances.model_db` = 0.01 dB;
- the fit rms is within the same tolerance.

## Bench method (unchanged from sim/lna-sparam-nf)

- **Ports.** 50 ohm Thevenin per port; forward and reverse by
  `alterparam mag1/mag2` + `reset`. S11 = 2 V(p1) - 1 and S21 = 2 V(p2),
  computed in Python from the printed complex port voltages. Transducer gain
  into the declared 50 ohm load is |S21|^2.
- **NF convention** (issue #22).
  - Rs1 is noiseless and F = 1 + inoise^2 / (4 k T0 50), with T0 = 300.15 K.
  - The 50 ohm output load stays noisy at the circuit temperature. This is
    the lna-sparam-nf convention, kept so the baseline reproduces its
    record.
  - The load's share, (T/T0) |1 + S22|^2 / |S21|^2, is reported per
    frequency as `nf_excl_load_db`.
  - **Screens use the bench-convention NF.** It is pessimistic by that
    share, roughly 0.02-0.1 dB at this stage's gain.
- **Frequency grids.**
  - Dense in-band grid: `ac lin 71` over 17.7-21.2 GHz (50 MHz steps). It
    contains 17.7, 19.45 and 21.2 GHz exactly.
  - Refined-grid control: the 70 midpoints (`ac lin 70`, 17.725-21.175 GHz),
    for 141 points at 25 MHz.
  - Wide stability sweep: `ac dec 100` over 1-100 GHz (201 points), forward
    and reverse. Probes run the dense grid only.
- **Stability.** k, |Delta| and mu are computed at every point, in band and
  over 1-100 GHz.

## Joint screen (declared thresholds; `study.json` `screen`)

| quantity | screen | traced to |
|---|---|---|
| NF max over the dense band | <= 2.5 dB | row 3. Applied to one stage, so it is a necessary condition: a second stage only adds noise. |
| S11 max over the dense band | <= -10 dB | row 4 |
| S21 min over the dense band | >= 10 dB | row 2 (>= 20 dB for two stages) split evenly in dB per stage. A derived study screen, not a spec value. |
| k, in band and 1-100 GHz | > 1 | row 6 |
| \|Delta\|, in band and 1-100 GHz | < 1 | row 6 (second Rollett condition) |
| operating point, every device | V_CE <= 1.4 V, V_CE 0.4-2.0 V, V_BE 0.65-0.96 V, Ic < 3 mA x Nx, fT > 21.2 GHz | row 17 and the model card box |

The supply points above the 2.5 V row-17 ceiling (2.75 V) are reported as a
labelled **EXCURSION**. They are never merged into a verdict.

## Shortlist rule (`study.json` `shortlist_rule`)

The rule is applied to the nominal screen.

**Eligible.** Only `ok` (valid) selectable candidates that are stable (k > 1
and |Delta| < 1, in band and over the wide sweep).

**Shortlist.** The union of the following; duplicates merge and ties break
by name:

- the baseline, always;
- up to 4 candidates that pass the joint nominal screen, ranked by joint
  margin min(2.5 - NFmax, -10 - S11max, S21min - 10);
- the best joint-margin candidate;
- the lowest-NFmax candidate;
- the lowest-S11max candidate;
- the lowest-NFmax candidate among those with S11max <= -10 dB, if any;
- the lowest-S11max candidate among those with NFmax <= 2.5 dB, if any.

## PVT campaign

**Grid.** The shortlist plus the probes, at every point of the existing
grid: `hbt_typ/bcs/wcs` x (-40, 27, 125 C) x (2.25, 2.5, 2.75 V), 27 points.

**Requests.** One `klt sim` request per supply, each with 9 process x
temperature units, on the batch fleet. The screen is a single-unit request
and runs locally.

**Failures.** A failed batch submit stops the collection. Nothing is
recorded, and nothing falls back to a local grid.

## Validity, tolerances and the gate

**Corruption: no record.** A missing printed block, a network missing from a
log, a grid that differs from the declared one, or a deck that never reaches
`LM_DONE` all mean corruption. The collection exits non-zero and writes no
record.

**Scientific rejection: `rejected_invalid`.** Some outcomes are kept in the
record with their reason but can never enter selection:

- any non-finite value;
- a failed refined-grid control: worst-case NFmax, S11max or S21min on the
  141-point union differing from the 71-point grid by more than
  `refine_db` = 0.05 dB;
- missing operating-point values.

**Tolerances (`study.json` `tolerances`).** Each has its reason in
`_notes`:

| tolerance | value | what it bounds |
|---|---|---|
| refine_db | 0.05 dB | refined-grid control |
| model_db | 0.01 dB | bound model check and fit rms |
| baseline_db | 1e-3 dB | S11/S21/S22/S12/NF vs the record |
| baseline_k | 1e-3 | k vs the record |
| crosscheck_db | 1e-3 dB | screen (local) vs corner campaign (fleet) at the nominal point |
| control_nf_db | 1e-3 dB | pad control NF |
| control_s_db | 1e-3 dB | pad control S21 |
| control_return_loss_db | -60 dB | pad control S11 and S22 |

**Baseline reproduction.** The baseline must reproduce
`sim/lna-sparam-nf/records/20261010-012923-6cad7fc` at 17.7, 19.45 and
21.2 GHz, at all 27 shared PVT points plus the screen point.

**Controls**, run locally at single points. Each is a closed form or an
independent path:

- a matched 6.02 dB pi pad (K = 2) behind the thru, at 27 C and at -40 C. In
  this convention F = 1 + (2L - 1) T/T0, and the reported load share must
  remove exactly L T/T0;
- the alterparam path vs a deck with the values written literally;
- op invariance to the input network;
- hbt_wcs vs hbt_typ (the corner section must move the baseline);
- in the gate, process corners must move the baseline's S21 across the
  campaign.

**Gate.** `matchstudy.validate_collection` requires every declared cell
exactly once and nothing undeclared, scientific statuses, finite ok
summaries, passing refined controls, and model section = process. The gate
also requires the controls, the baseline reproduction, the cross-check and a
bound at every point. Only a collection that passes the gate is written.

## Conclusion rule (no forced winner)

A shortlisted network is a **conditional candidate for passive
qualification** only if it passes the joint screen at every in-rail PVT
point (18 points: 2.25 and 2.5 V). Otherwise the record states the explicit
finding: no tested input match meets the joint screen. The record also
states:

- the bound's verdict per point, i.e. whether any lossless network could;
- the worst in-rail values;
- what remains contingent: passive loss (#46), the open band (row 1) and
  second-stage loading.

## Observed before this declaration was committed (disclosure)

Before this declaration was committed, only the following was run, all at
the nominal point:

- the derivation above, i.e. the probe networks and the baseline;
- the smoke for its tooling checks, which ran the baseline, `seg0375_b` and
  `seg0000_a`. The baseline reproduced its record to 5e-9 dB.
  - `seg0375_b`: NFmax 2.06 dB, S11max -4.3 dB.
  - `seg0000_a`: NFmax 4.12 dB, S11max -4.9 dB.
  - Nominal bound: NF floor 2.469 dB at 21.2 GHz with |S11| <= -10 dB.

None of this changed a threshold: the thresholds are the ratified rows. The
pad control's first closed form was wrong for this bench's noisy-load
convention, and it was corrected to F = 1 + (2L - 1) T/T0 before this
commit. The NF convention itself was not changed.
