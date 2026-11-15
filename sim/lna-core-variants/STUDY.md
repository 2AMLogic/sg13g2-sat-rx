# lna-core-variants: study declaration (issue #79)

This file and `testbench/variants.json` are the declaration of the study.
They are committed **before** any recorded campaign, in their own commit. A
record made later cites the declaration's sha256 and freezes a copy of
`variants.json` (and of the #74 `study.json` it runs) under
`netlist-snapshots/<record-id>/`. To change anything below after a record
exists, add a new declaration and a new record that says why. This one is
never edited.

**Claim: none.** This is an ideal-element feasibility screen of core changes.
Every matching element, and the degeneration inductor `Le1`, is ideal. No PDK
inductor model exists (passive qualification is #46), and spec row 1 (the
band) is OPEN, so 17.7-21.2 GHz is DRAFT. Nothing here claims a spec row met.

## Question

Issue #74 (`sim/lna-match-tradeoff/records/20261010-042556-dae8519.md`) froze
the `design/lna_stage1` cascode and showed that no lossless input network of
any order reaches NF <= 2.5 dB with S11 <= -10 dB at 8 of the 18 in-rail PVT
points. At the row-3 binding corner (hbt_wcs, 125 C) the core's own Fmin is
2.43-2.73 dB (2.25 V), and the nominal margin is 0.03 dB at 21.2 GHz. #79
asks:

> Which change to the first-stage core moves the noise optimum and the
> power-match point together and lowers the hot-corner Fmin, so that the
> network-independent bound closes at every in-rail point?

## Method: the #74 bound, unchanged

Holding the method fixed is what makes the variants comparable. The grids,
thresholds, tolerances, port fixture, NF convention, the 9 probe networks and
the drawn (baseline) input network all come from the #74 declaration
`sim/lna-match-tradeoff/testbench/study.json` (sha256 pinned in
`variants.json`). They are executed by `sim/lna-match-tradeoff/matchstudy.py`.
Its only change for this study is an optional `devices` argument (default:
the #74 devices, so #74 decks stay byte-identical). With it, the operating
point follows a variant's terminal nodes and Nx.

Per variant and PVT point, one deck runs the drawn network and the 9 probes:

- **Noise parameters and bound.** As in #74, Fmin, Rn and Yopt are fitted per
  dense frequency from the probes, and the core S-parameters at node in2 come
  from `probe_thru`. The NF bound is the smallest NF with |S11| <= -10 dB,
  over any lossless input network. The model check is the drawn network's
  simulated NF and S11 against the prediction, within 0.01 dB.
- **Gain.** The transducer gain at the source reflection that attains the NF
  bound, at every band frequency. The screen is >= 10 dB, which is the #74
  S21 screen (row 2 split over two stages).
- **Stability.** k and |Delta| of the drawn network, in band and over
  1-100 GHz. k is invariant under a lossless input network, so it stands for
  every network.
- **Row 17.** The operating point of every device: V_CE <= 1.4 V, the card
  box, and fT > 21.2 GHz.

**Grid.** The same 27 points: hbt_typ/bcs/wcs x (-40, 27, 125 C) x (2.25,
2.5, 2.75 V). The 18 points at 2.25 and 2.5 V are in rail. The 2.75 V points
are a labelled EXCURSION and never enter the choice.

**Requests.** One `klt sim` request per (variant, supply), each with 9 units,
on the batch fleet: 8 x 3 = 24 requests. A failed submit stops the collection
with no record and no local fallback.

## What each variant changes (the single declared change)

Each variant is the frozen `design/netlist/lna_stage1.spice` (sha256 pinned)
with only its declared line edits. `corestudy.apply_changes` refuses an edit
whose line is not found exactly once. The input network (`Cshunt`, `Lin`,
`Cblk_in`) is protected, so `matchstudy.dut_text` parameterizes exactly the
#74 lines. A test checks every other line is unchanged, and that the frozen
core's deck equals the #74 deck apart from one comment line.

| variant | role | change |
|---|---|---|
| `core0` | baseline | none: the frozen core. It must reproduce the #74 bound at all 27 points (`reproduction_tol_db` = 1e-3 dB, and the jointly-infeasible counts exactly) |
| `a_le` | candidate (a) | ideal `Le1` in series with Q1's emitter, before `Re1` |
| `b_jopt` | candidate (b) | `Rref` retuned so Ic(Q1) at hbt_wcs/125 C/2.5 V = 1.70 mA, the Ka-band characterization's noise-optimal Ic for Nx = 8 there (`sim/hbt-kaband-characterization/records/20261009-095725-dbf8179.md`, per-Nx table; the frozen core runs 1.43 mA) |
| `b_nx10` | candidate (b) | Q1 and Q2 Nx 8 -> 10 (the card's upper limit) at constant current density: `Rref` 8k -> 6.4k, `Re1` 3 -> 2.4 ohm, so the mirror's area and emitter ratios are both 10 |
| `c_rbias` | candidate (c) | `Rbias` 2k -> 10k (5x less shunt noise power at the base), with a base-current-compensated mirror: `Rbr` from nr to Xqr's base. `Rbr` holds the nominal Ic(Q1) at the frozen 1.563 mA |
| `diag_rbias_noiseless` | diagnostic | `Rbias` 2k with `noisy=0`. Not a circuit: the most any class-(c) change can buy. Never chosen |
| `ac` | combination | (a) + (c) |
| `abc` | combination | (a) + (b, current density) + (c) |

## Derived values (declared rules; `run.py derive`)

Each value comes from one local `ngspice -b` at one PVT point: a parameter
scan inside one deck, which the host rules allow. Each value is rounded and
written into `variants.json` with its bracketing scan rows. The rounded value
is the one simulated.

| param | rule | point | value |
|---|---|---|---|
| `le_a` | Re(Z_in) of the core at in2 = 50 ohm at f0 (the textbook degeneration condition), 2 sig. digits | hbt_typ/27 C/2.5 V | 54 pH |
| `rref_b` | Ic(Q1) = 1.70 mA, 3 sig. digits | hbt_wcs/125 C/2.5 V | 6.50 kohm |
| `rbr_c` | Ic(Q1) = 1.563 mA (frozen nominal, `study.json` derivation op), 3 sig. digits | hbt_typ/27 C/2.5 V | 60.9 kohm |
| `le_ac` | as `le_a`, on the (c) core | hbt_typ/27 C/2.5 V | 67 pH |
| `rref_abc` | as `rref_b`, on the (c) core | hbt_wcs/125 C/2.5 V | 6.95 kohm |
| `le_abc` | as `le_a`, on the (b) + (c) core | hbt_typ/27 C/2.5 V | 63 pH |

Le is tied to the nominal point, not tuned to the hot corner. That way the
corner campaign tests the change, not a fit to the corner it is judged at.

## Selection rule (declared; `variants.json` `selection_rule`)

**Eligible.** Only candidate or combination variants. All 18 in-rail points
must:

- have a valid bound (model check);
- pass row 17 and the card box;
- have k > 1 and |Delta| < 1, in band and over 1-100 GHz;
- have GT >= 10 dB at the NF-bound source reflection at every band frequency;
- not be jointly infeasible. A point is jointly infeasible if, at some band
  frequency, no lossless input network reaches NF <= 2.5 dB with
  S11 <= -10 dB.

**Choice.** Among the eligible variants:

1. the fewest declared changes;
2. then the largest worst-case in-rail margin (2.5 dB minus the worst NF
   bound);
3. then the name.

If no variant is eligible, there is no choice. The outcome is then a
decision-record proposal that names the binding corner.

## Observed before this declaration was committed (disclosure)

Before this declaration was committed, only single-point local probes ran
(one `ngspice -b` each, sequentially, at hbt_typ/27 C and hbt_wcs/125 C).
They used the frozen core and hand-edited variants of it. That was enough to
see the following:

- The frozen core reproduces #74 exactly: 2.469 dB at nominal, and 3.307 dB
  with Fmin 2.43-2.73 dB at hbt_wcs/125 C/2.25 V.
- **Attribution at hbt_wcs/125 C/2.5 V.** A noiseless Rbias lowers Fmin by
  about 0.3-0.36 dB. A noiseless Rd lowers it by about 0.1 dB, and a
  noiseless Re1 by about 0.03 dB. A bypass capacitor at the reference node
  nr changes nothing, so the reference's own noise is negligible.
- **Degeneration alone** (30-150 pH) moves the bound toward Fmin. It does not
  lower Fmin, which stays above 2.5 dB at 21.2 GHz at that corner.
- **More current** lowers the hot-corner Fmin. On its own it widens the gap
  between the noise and power-match points.
- **Rbias at 10k with base-current compensation, plus 50-120 pH of
  degeneration,** gave an NF bound of about 2.2-2.3 dB at hbt_wcs/125 C at
  2.5 V. At 2.25 V it was 2.34 dB with 80 pH.

These probes set which variants are worth declaring. They did not set the
declared values. Those come from the rules above, at the nominal point
(Le, Rbr) or at the characterization's corner (Rref). The thresholds are the
ratified rows and are unchanged.
