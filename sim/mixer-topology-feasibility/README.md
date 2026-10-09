# mixer-topology-feasibility (issue #35)

A mixer-core topology feasibility study on `npn13G2`, done before any mixer
schematic is drawn in `design/`. It compares candidate cores under the
ratified supply constraint (`spec/target-spec.md` row 17: rail ≤ 2.5 V, no
device above 1.4 V V_CE, inside the card's windows).

**DEVICE-LEVEL TOPOLOGY STUDY. NOT A DESIGN AND NOT SPEC EVIDENCE.** Every
candidate uses ideal baluns, ideal R/C and ideal bias sources. Each has one
fixed, documented sizing. There is no matching network, no inductor and no
layout. Nothing here claims any spec row is met.

## Status: part 1 of 2 (fixtures and extraction validation)

The issue allows the work to be split: fixture and extraction validation
first, then collection. **This directory is part 1.** It contains:

- the three candidate fixtures and the analytic control;
- the study declaration (`testbench/tb.json`, block `study`);
- the extraction, LO-selection, IIP3, stress and acceptance-gate logic
  (`mixfeas.py`);
- unit tests on analytic and synthetic data (`tests/`);
- a local driver (`run.py`) with `plan`, `smoke`, `selftest` and `converge`.

**No record exists yet, and none of these modes writes one.** Every number
printed by `smoke`/`converge` comes from one corner at a trial LO drive. It
is a method check, not a result, and must not be quoted as evidence.

Still to do (part 2, on #35):

1. Submit the LO-selection sweep and the full matrices as `klt sim`
   requests. Per the host rules these must not run locally.
2. Ingest the results through `mixfeas.validate_collection`.
3. Re-run `converge` at the drive the sweep selects.
4. Write the append-only comparison record and the recommendation
   (`mixfeas.conclude`).
5. Teach `.github/scripts/check_evidence_formats.py` the record layout.
   Today the checker treats this bench as harness-native, and that is
   harmless only while `records/` does not exist.

## Candidates

| name | role | topology | sizing (all `npn13G2`) |
|---|---|---|---|
| `gilbert_stacked` | candidate | classic double-balanced Gilbert cell: ideal 2 mA tail sink → RF pair Q1/Q2 → LO quad Q3–Q6 → 400 Ω loads. Three stacked levels share the rail. | Nx=1 each. RF-pair bases at 1.10 V (balun centre tap); LO quad bases at 1.85 V. |
| `folded_single_balanced` | candidate | single-balanced mixer. The RF transconductor Q1 has its own 1 kΩ load and is folded into the LO pair Q2/Q3 through 2 pF. Each DC path stacks one device on an ideal 1 mA sink. | Nx=1 each. Q1 base at 1.10 V; LO pair bases at 1.70 V; 800 Ω loads. |
| `placeholder_floor` | **floor** | the existing single-HBT placeholder core. Element values are copied verbatim from `../mixer-conversion-iip3/testbench/mixer_ce_placeholder.spice` (Nx=4, Rc 300 Ω, Re 10 Ω, Vbb 0.90 V through 3 kΩ, 1 pF couplings), re-wrapped in this bench's ports. **Never recommended.** | — |
| `analytic_control` | control | an ideal behavioural multiplier whose gain, LO leakage and IM3 have closed forms. It goes through the same ports, deck generator, DFT and parser. | `ac_k`, `ac_k3`, `ac_c`, `ac_g` in `tb.json` |

The two real candidates draw the same 2 mA from the rail, so DC power is
compared at equal current.

The placeholder's own fixture and records are untouched.

Every fragment's device list (c/b/e nodes, Nx, collector sense source) is
declared in `tb.json` and checked against the netlist by
`mixfeas.check_fragment_devices`.

## Port and power conventions (`testbench/ports_common.spice`)

Every candidate gets the same port fragment prepended.

- **RF port:** a single-ended 50 Ω Thevenin source. Available power per tone
  is `P = vrf²/(8·50)`. With the RF source off, the source resistor is the
  RF port's 50 Ω termination.
  - LO-to-RF leakage is `|V(rf_port) at f_LO|²/(2·50)`: the power delivered
    into that termination.
- **LO port:** a differential 100 Ω reference port, made of two 50 Ω legs
  driven in antiphase. The quoted figure is **total** available power,
  `P = Vdiff_open_peak²/(8·100)`, not power per leg.
  - The loaded differential voltage `V(lo_p) − V(lo_n)` at f_LO is recorded
    beside it.
  - The single-ended placeholder gets an ideal balun (100 Ω diff ↔ 50 Ω SE).
- **IF port:** a physical 50 Ω resistor `Rif`. Conversion gain is the IF
  fundamental power delivered into `Rif`, divided by the RF available power.
  - LO-to-IF leakage is the power in `Rif` at f_LO with the RF source off.
  - Output transformation: the balanced candidates use an ideal balun of
    200 Ω diff ↔ 50 Ω. It sits directly across the collectors with a
    floating centre tap, so there is no DC block. (A DC differential from
    mismatch lands in the DC bin.)
  - The placeholder uses a 5 pF DC block and an ideal 200 Ω ↔ 50 Ω
    transformer.
  - Every output node also has 0.5 pF to ground as an IF filter.
  - The placeholder's old "unloaded node, assumed 50 Ω" power approximation
    is **not** used.
- **Rail:** mixer-only DC rail power is `V_dd × I(V_dd)`.
  - It is reported at the DC point and averaged over the retained window.
  - Ideal bias sources are not counted as rail power.
  - The voltage across each **ideal current sink** is reported as its
    compliance headroom (`ideal_sink_nodes`). This matters because the sink
    is the Gilbert cell's third stacked level. No pass/fail is applied: a
    real sink needs some headroom, and this bench does not size one.

## Declared coverage (see `run.py plan`)

| matrix | process | T (°C) | supply (V) | bands | per cell |
|---|---|---|---|---|---|
| main (gain, DC power, stress) | `hbt_typ/bcs/wcs` | −40, 27, 125 | 2.025, 2.25, 2.475 | 17.7 / 19.45 / 21.2 GHz | RF −60 dBm at the selected drive |
| leakage | `hbt_typ/bcs/wcs_mismatch`, seed 35001 | −40, 27, 125 | 2.025, 2.25, 2.475 | all three | RF off at the selected drive |
| LO selection (**reduced**) | `hbt_typ` | 27 | 2.25 | all three | 13 drives × RF −60 and −66 dBm |
| IIP3 (**reduced**) | `hbt_typ` | 27 | 2.25 | all three | two-tone, −70…−10 dBm per tone in 5 dB steps |

That totals 837 declared cells over three topologies.

- **Supply.** The supply axis is 2.25 V ± 10 %, an exploratory nominal. All
  three values sit below the 2.5 V ceiling. The legacy 2.5 V ± 10 % grid is
  not used and not clipped, and `study_from_manifest` refuses any supply
  above the rail ceiling. This choice ratifies no rail.
- **Reductions.** The LO-selection and IIP3 sweeps run at the nominal cell
  only. There are no MOS, capacitor or resistor corner axes, because the
  fixtures use no such PDK model. Ideal passives do not cover the open
  passive/EM axis. So there is no all-corner linearity, yield or compliance
  claim.
- **Mismatch.** The `*_mismatch` cards draw each instance's area as
  `agauss(1, 0.1, 1)`.
  - `.options seed=35001` fixes the draws, so each leakage cell is one
    deterministic realization. This is card coverage, not Monte Carlo yield
    evidence.
  - Draw order follows instance order, so realizations differ between
    candidates.
  - Checked locally: the same seed reproduces exactly, a different seed and
    the typical card differ, and `reset`/`alterparam` inside a deck do not
    redraw. `selftest` step 3 re-checks this on every run.
- **Frequency plan.** LO is RF − 1 GHz (low-side, row 14). Each two-tone pair
  stays in band and uses its centre − 1 GHz as the LO. Both IF fundamentals
  and both IM3 products are extracted.

## Stress rules

These limits apply to every HBT, using row 17's effective V_CE interval and
the card's other windows:

- V_CE in [0.4, 1.4] V;
- V_BE in [0.65, 0.96] V;
- Ic ≥ 0.003·Nx A is flagged.

Extrema are measured separately for three intervals: the DC point, startup
(t < settle) and the retained window. A violation in the DC point or the
retained window makes the run an explicit `rejected_stress` outcome. A
rejected run is not a measurement averaged with the others, and it cannot
support a feasibility verdict.

Startup-only violations are recorded as flags. They are not rejections,
because the bench's sources step on at t = 0.

Switching excursions are flagged even when they are intentional. **Smoke
observation (not evidence):** at the 0 dBm trial drive, the switching
devices of both balanced candidates swing V_BE down to about 0 V. The LO
sweep therefore decides whether any drive keeps the switching devices inside
the card's 0.65 V floor while still switching.

## Extraction

| item | value |
|---|---|
| settle (discarded) | 20 ns |
| retained window | 20 ns single-tone (50 MHz resolution); 80 ns two-tone (12.5 MHz) |
| max timestep / resampling | 1 ps / 1 ps (`linearize`); `.options reltol=1e-5` |
| window | rectangular over an integer number of periods of every tone and bin (`coherence_problems` refuses otherwise) |
| bins | IF fundamental; f_LO at the IF and RF ports; f_LO of the loaded LO differential voltage; two-tone IF1/IF2/IM3-low/IM3-high |
| normalization | single-bin DFT `(2/N)·Σ x·e^(−jωt)`, so a sine reads its peak amplitude |
| floor | the larger of the strongest neighbouring empty bin and −140 dBm. A value less than 10 dB above its floor is reported as an upper bound only. |

**Known bias.** ngspice's own time points are not on the resampling grid, so
`linearize` interpolates linearly. That attenuates a sine by at most
(2πf·Δt)²/8: 4·10⁻⁶ dB at the 1 GHz IF, and about 0.015 dB for f_LO-band
quantities at 1 ps (`mixfeas.interp_bound_db`). The analytic control's
tolerance includes this bound.

**Why `reltol=1e-5`.** At the default reltol of 1e-3, the placeholder's
−60 dBm IF product shares its node with LO feedthrough about 48 dB larger.
It moved 0.77 dB when the timestep was halved. At 1e-5, every candidate's
gain agrees to ≤ 0.12 dB from 1 ps down to 0.25 ps (local single-corner
probe).

**Convergence control (`run.py converge`).** It checks each candidate at
19.45 GHz:

- with a doubled retained window, and with the maximum timestep halved;
- gain on `hbt_typ`, leakage on `hbt_typ_mismatch` with the declared seed;
- the requirement is agreement within 0.2 dB.

Today it runs at the 0 dBm trial drive. Part 2 must repeat it at the
selected drive. On this commit, all deltas are ≤ 0.03 dB.

## Decision rules

- **LO drive (`select_lo_drive`).** At each band, find the maximum gain over
  stress-valid points. A point qualifies when all three of these hold:
  - it is stress-valid;
  - it passes the small-signal check, `|G(−60) − G(−66)| ≤ 0.2 dB`;
  - its gain is within 0.5 dB of that maximum.

  The selected drive is the lowest drive that starts three consecutive
  qualifying drives at **all three** bands. Otherwise the outcome is
  `no acceptable drive in declared sweep`. Any missing or invalid point
  makes the outcome `inconclusive`. The sweep bounds are never extended
  silently.
- **IIP3 (`fit_iip3`).** For each IM3 sideband, the fit uses the longest
  contiguous run of at least 3 steps that meets all of these:
  - each step is OK;
  - IM3 is at least 10 dB above the floor;
  - gain is within 1 dB of the lowest-power step;
  - least-squares slopes are 1 ± 0.1 (fundamental) and 3 ± 0.3 (IM3);
  - residuals are ≤ 0.5 dB.

  The intercept is where the fitted lines meet. The reported value is the
  lower of the two sidebands. Otherwise the result is `IIP3 unavailable`
  with a reason.
- **Acceptance gate (`validate_collection`).** The gate requires every
  declared cell exactly once, with no undeclared cells, and every cell in a
  scientific status (`ok` / `rejected_stress` / `not_applicable_no_drive`).
  In addition:
  - `ok` cells must carry finite required values;
  - the stress classification must agree with the recorded violations;
  - the model section must be the declared corner;
  - leakage cells must carry the declared seed;
  - process corners must actually move the gain (the sabotage control).

  A collection that fails the gate exits non-zero and is never recorded.
- **Conclusion (`conclude`).** A candidate is "feasible (device-level,
  conditional)" only when it has a selected drive and no main cell is
  stress-rejected. Otherwise it is "infeasible at the declared sizing" or
  "inconclusive". The recommendation is the feasible non-floor candidate
  with the highest worst-case gain, or **none**. A topology is never forced.

## Running it (local, single corner, never writes)

```
python3 sim/mixer-topology-feasibility/run.py plan       # declared matrices / cell counts
python3 sim/mixer-topology-feasibility/run.py smoke      # ~20 s
python3 sim/mixer-topology-feasibility/run.py selftest   # ~30 s
python3 sim/mixer-topology-feasibility/run.py converge   # ~1 min
python3 -m pytest sim/mixer-topology-feasibility/tests -q
```

`selftest` covers five controls:

1. The analytic control matches its closed forms, including a swept
   two-tone IIP3: −4.98 dBm extracted vs −4.77 dBm small-signal closed form.
   The fitted interval carries some compression.
2. `hbt_wcs` moves the Gilbert gain against `hbt_typ` (−3.40 vs −2.33 dB),
   and sabotaged corners collapse to typical exactly.
3. The mismatch seed reproduces; it differs from typical and from another
   seed. The Gilbert's LO→IF leakage goes from below the floor (typical) to
   about −50 dBm (mismatch, at the trial drive).
4. A deck with a deleted measurement is rejected.
5. The gate and conclusion negative controls pass.

## Known limits

- Ideal baluns, ideal passives and ideal bias sources/sinks. The balanced
  candidates' IF balun is DC-transparent; a real winding would short a DC
  differential instead.
- The RF input is not matched. Gain is quoted against 50 Ω available power,
  so input mismatch counts against every candidate equally.
- One sizing per topology. A different bias could change any verdict; a
  verdict is "at the declared sizing".
- SSB NF is out of scope (#27).
- `klayout-tools` is not invoked. No klt friction was hit in part 1; part 2's
  `klt sim` submission is where any would surface.
