# mixer-topology-feasibility (issue #35)

A mixer-core topology feasibility study on `npn13G2`, done before any mixer
schematic is drawn in `design/`. It compares candidate cores under the
ratified supply constraint (`spec/target-spec.md` row 17: rail ≤ 2.5 V, no
device above 1.4 V V_CE, inside the card's windows).

**DEVICE-LEVEL TOPOLOGY STUDY. NOT A DESIGN AND NOT SPEC EVIDENCE.** Every
candidate uses ideal baluns, ideal R/C and ideal bias sources. Each has one
fixed, documented sizing. There is no matching network, no inductor and no
layout. Nothing here claims any spec row is met.

## Status: parts 1 and 2 landed; no acceptable drive at any declared sizing (records 20261010-010744-a10c193, 20261010-025859-2113f00)

Part 1 (PR #44) delivered the fixtures, the study declaration, the
extraction, LO-selection, IIP3, stress and acceptance-gate logic
(`mixfeas.py`), unit tests and the local `plan`/`smoke`/`selftest`/`converge`
modes. Part 2 (this directory's `collect.py`, driven by `run.py collect`)
adds:

- request generation: the study as `klt sim` requests, staged because each
  stage's LO drive depends on the previous stage's selection (below);
- ingest of the returned per-unit logs into declared cells, with the gate
  `mixfeas.validate_collection`, and a local convergence and cross-check
  control;
- the append-only record writer (`records/`, `corners/`,
  `netlist-snapshots/`) and `.github/scripts/check_evidence_formats.py`
  support for that layout, with negative controls in
  `.github/scripts/tests/test_check_mixfeas_adapter.py`;
- `tests/test_collect.py`: the whole collection against a closed-form fake
  `klt sim` (request plan, staging, no-drive cells, corrupt-run exits,
  typical-forced corners, stress rejection, rendering).

**Result of the first collection** (`records/20261010-010744-a10c193.md`):
all three topologies return `no acceptable drive in declared sweep` at their
declared sizing. For both balanced candidates the switching devices' V_BE
falls below the card's 0.65 V floor from -9 dBm total available LO power
upward, while the gain is still rising at the last stress-valid point
(-12 dBm). For the floor, V_BE exceeds 0.96 V from -3 dBm. No drive was
selected, so no main-matrix, leakage or IIP3 simulation ran: those cells are
explicit `not_applicable_no_drive` outcomes, the LO-selection cells are the
only gain/stress data, and the recommendation is **none**. This is a finding
about one fixed sizing and the declared sweep, not about the topologies in
general; the next step is a sizing follow-up or a decision-record proposal,
not an edited rule (see the record's conclusion).

**Not yet exercised against the real fleet.** The stage-2 path (IIP3, 243-cell
main matrix, 243-cell mismatch leakage matrix: 18 multi-unit `klt sim` batch
requests of 9 units each, plus 3 single-unit IIP3 requests) is covered by
`tests/test_collect.py` with a fake `klt sim`, but has never been submitted
for real, because no candidate reached it. The first time a sizing selects a
drive, `collect` will submit those requests with `--backend batch`. A failed
batch submit makes `collect` exit non-zero without a record; it never falls
back to a local grid. The fleet/client skew described in
`../hbt-kaband-characterization/README.md` ("Fleet/client version skew") may
require `--no-stage-models --runner-version-check warn`; if it does, the
local cross-check (which reproduces the nominal main cell and the seeded
nominal leakage cell on this host's model files) is what ties the fleet's
numbers to the checksums the record states. The first record ran three
single-unit `klt sim --backend local` requests and nothing else, so its
cross-check is local-vs-local (klt-body path vs harness path, both on this
host). Its data-provenance line is derived from the backend and unit count
recorded per request (`collect.execution_provenance`), not written by hand, and
a test fails if a record claims an off-host or multi-unit run that its requests
do not show. The batch stage-2 path has still not run against the real fleet.
That has to wait for a sizing that selects a drive (sizing follow-up #61).

## Sizing follow-up (issue #61): still no acceptable drive

Four alternative fixed sizings of the two balanced topologies were declared in
`testbench/tb.json` (`study.candidates`, rationale in `_notes` and in each
fragment header) in this directory's git history before any collection, and the original
three candidates stay in the study unchanged. The lever is on-state current
density (it raises V_BE,on so the off-going device's V_BE trough stays higher),
with the load resistor and LO base bias moved to keep the original ~0.4 V
average load drop and emitter-node level:

| name | tail / LO-pair sink | RL | LO bias |
|---|---|---|---|
| `gilbert_stacked_a` | 3 mA | 270 ohm | 1.88 V |
| `gilbert_stacked_b` | 4.5 mA | 180 ohm | 1.90 V |
| `folded_single_balanced_a` | 2 mA | 400 ohm | 1.72 V |
| `folded_single_balanced_b` | 2.7 mA | 300 ohm | 1.74 V |

Result (`records/20261010-025859-2113f00.md`, append-only; the first record is
untouched): **all seven topologies, original and new, return `no acceptable
drive in declared sweep`.** The V_BE trough does rise with current (first
rejected drive at LO -9 dBm: 0.565 V original, 0.592 V Gilbert A, 0.626 V
Gilbert B, 0.616 V folded A) but not past the 0.65 V floor, and the higher
currents run into the upper edge of the same window (folded B is rejected from
-12 dBm on V_BE > 0.96 V; Gilbert A/B exceed 0.96 V at +6 dBm). At every
sizing the gain is still rising 1-4 dB at the last stress-valid point, so the
plateau rule cannot start. The bounds, plateau rule and stress limits were not
touched. Main, leakage and IIP3 cells are `not_applicable_no_drive`; the
recommendation is **none**.

Reading: the card's V_BE window (0.65-0.96 V, 0.31 V wide) is narrower than the
swing a plateau-level LO drive needs at the 100 ohm differential port. Closing
that gap needs a rule or window decision, not another bias: see the
decision-record proposal routed from #61 (it changes nothing here).

Follow-up findings from running it for real:

- **Batch stage 1 on the fleet.** All seven single-unit LO-selection requests
  of the record ran on the Spot fleet (`--single-unit-backend batch`, new in
  `run.py collect`; default stays `local`) with `--no-stage-models
  --runner-version-check warn`. Without those flags the first submit is refused
  by the version check (runner klt 0.5.0 vs client 0.7.0, reported in each
  report's `environment.remote`). One earlier submit hit `batch_no_capacity`
  and was simply retried; it never fell back to local.
- **ngspice skew between hosts.** This worker has ngspice-42; the fleet and the
  host that produced the first record have ngspice-46. Under 42 the placeholder
  floor's weak-drive RF -66 dBm runs fail the extraction-floor check (numerical
  noise bins ~1000x larger), so a purely local stage 1 does not complete; the
  six real candidates gave the same no-drive outcome under 42 (local attempt,
  not recorded). The fleet (46) runs are what the record uses. The local
  cross-check, run on ngspice-42, differs from the fleet by up to 1.41e-2 dB
  (folded candidates, 0 dBm trial drive), so the 1e-3 dB cross-check tolerance
  was overridden for this record with `--crosscheck-tol-db 0.05` (printed in
  the record; far below the 0.2 dB convergence tolerance). The default is
  unchanged.
- **The multi-unit stage-2 path (243-cell main/leakage, IIP3) is still not
  exercised against the real fleet**, because nothing selected a drive.

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

`collect` runs it at the selected drive. With no selected drive, as in the
first record, it runs at the 0 dBm smoke trial drive and the record labels
that a diagnostic, not a selected drive. In the first record all deltas are
≤ 0.03 dB.

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

## Running it

Local, single corner, never writes:

```
python3 sim/mixer-topology-feasibility/run.py plan       # declared matrices / cell counts
python3 sim/mixer-topology-feasibility/run.py smoke      # ~20 s
python3 sim/mixer-topology-feasibility/run.py selftest   # ~30 s
python3 sim/mixer-topology-feasibility/run.py converge   # ~1 min
python3 -m pytest sim/mixer-topology-feasibility/tests -q
```

Collection (writes ONE record only if everything passes the gate):

```
python3 sim/mixer-topology-feasibility/run.py collect --dry-run      # write stage-1 requests only
python3 sim/mixer-topology-feasibility/run.py collect --stage1-only  # LO sweep, print selection, no record
python3 sim/mixer-topology-feasibility/run.py collect [--workdir DIR] [--backend batch]
```

- Stage 1 is one single-unit `klt sim` request per candidate (hbt_typ /
  27 C / 2.25 V; 78 transient runs, ~4 min each). Single-unit requests run
  with `--backend local`, as klt itself would keep them; every multi-unit
  request uses `--backend` (default `batch`).
- `--workdir` resumes: a request whose report already exists is not
  resubmitted. A corrupt or incomplete collection exits non-zero, leaves the
  work directory for inspection and writes nothing under `records/`.
- The sentinel `.meas` that every klt request needs is named
  `sentinel_rail_v`, not `mf_...`: the deck's own values all start with
  `mf_`, and a sentinel with that prefix is rejected by the parser as a value
  outside any run.
- Like the Ka-band bench, the request body carries its own `.control` block
  (klt's docs call that unsupported; it works, ngspice runs it before klt's
  sentinel analysis). No new klt gap was found beyond that known one.

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
- `klayout-tools` is not invoked for layout, DRC or LVS. `klt sim` is used for
  collection; see "Running it" for the one known friction (a body-level
  `.control` block).
- The first record never reached the multi-unit stage (see Status).
