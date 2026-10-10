# lna-linearity (issue #57)

Nonlinear characterization of `design/lna_stage1`: **two-tone IIP3** (spec
row 7, ratified target >= -15 dBm) and **single-tone input P1dB** (spec row 8,
ratified target >= -25 dBm). It is kept apart from `sim/lna-sparam-nf`, which
measures small-signal S parameters and noise.

**PLACEHOLDER CIRCUIT, ONE CORNER.** The DUT has IDEAL lossless L/C matching
(no PDK inductor model exists) and is evaluated at `hbt_typ`, 27 C, 2.5 V only.
Results are placeholder-circuit, nominal-corner evidence. They are not
compliance for rows 7 or 8, the band (row 1) is still a draft, and nothing here
relaxes a ratified target: a failing, bounded, unavailable or unconverged
outcome is published as it is.

## Cold start

```bash
python3 -m pytest sim/lna-linearity/tests -q              # method qualification, no simulator
python3 sim/lna-linearity/run.py check-plan               # band + coherence of every declared placement/variant
python3 sim/lna-linearity/run.py controls                 # closed-form positive and negative controls
python3 sim/lna-linearity/ci_assert.py                    # reduced cubic deck on the pinned ngspice (records nothing)
python3 sim/lna-linearity/run.py collect --dry-run        # write the klt bodies/requests only
python3 sim/lna-linearity/run.py collect \
    --runner-version-check warn --no-stage-models         # submit to the Spot batch fleet, write ONE record
python3 sim/lna-linearity/run.py verify                   # re-derive every committed verdict from the frozen logs
```

`collect` needs the plan, code and DUT committed (it refuses a dirty tree) and
uses an explicit `--backend batch` for every request, including the
single-unit ones, so the sweeps run on the fleet and never as a local loop. A
failed submit stops the collection, writes nothing and does not fall back to
a local run. The two flags above are the documented skew between this host's
`klt` client and the fleet runner (see `../mixer-topology-feasibility/README.md`).

## Method (declared in `testbench/plan.json` before any collection)

* **Ports.** Ideal Thevenin source behind 50 ohm (per-tone available power
  `Vs^2/(8*Z0)`), 50 ohm load. A component of peak `V` across the load delivers
  `V^2/(2*Z0)`. The swept axis is *available* source power, so the reported
  IIP3/P1dB are referred to the source, not to the (imperfectly matched) input
  port's absorbed power.
* **Placements.** Three in-band tone pairs, 100 MHz apart, with both tones and
  both IM3 products (2f1-f2, 2f2-f1) inside 17.7-21.2 GHz: 17.9/18.0,
  19.4/19.5 and 20.9/21.0 GHz. The single tone sits at each pair's midpoint.
* **Coherent bins.** The retained window is 20 ns (two periods of the
  spacing); every analysed frequency (tones, IM3 products, floor probes 50 MHz
  off the products) is a multiple of 1/window = 50 MHz, so the rectangular
  window is exactly coherent and no window correction exists or is applied.
  The deck computes `2*mean(x*cos)` and `2*mean(x*sin)` on a uniform
  `linearize` grid and `linearity.py` takes the magnitude. `check-plan` and the
  negative controls reject non-coherent placement.
* **Floor.** Per run, the larger of the delivered powers at two coherent bins
  that carry no product. The integrator's truncation error also makes spurious
  products *at* the IM3 bins that those probes do not see (method-development
  observation: IM3 at -50 dBm moved by ~0.3 dB between `reltol` 1e-6 and
  1e-7/`trtol`=1), so IM3 uses the tight solver setting and the
  timestep-halving check, not the floor probes alone, is the qualification.
* **IIP3.** Only from a contiguous run of at least 4 sweep points in which the
  fundamental slope is 1+/-0.1 and the IM3 slope 3+/-0.3, residuals <= 0.5 dB,
  both fundamental and IM3 >= 20 dB above the floor, gain within 0.25 dB of the
  small-signal baseline, and the device inside its operating limits. The value
  is the intercept at the ideal 1 and 3 slopes, cross-checked against the
  free-slope intersection; the lower of the two IM3 sidebands is reported and
  the extrapolation distance above the highest fitted power is recorded.
  Otherwise `unavailable` with a reason.
* **P1dB.** Gain = delivered / available power. A baseline needs 3 consecutive
  usable points flat within 0.15 dB. The crossing needs two consecutive usable
  points straddling a 1 dB drop; the value interpolates the amplitude
  compression `1-10^(-drop/20)` against linear power (exact for a cubic). A
  sweep that never crosses, or whose next step is rejected, is `bounded`
  (a one-sided bound, never a number); with no baseline it is `unavailable`.
* **Operating limits.** Spec row 17 (V_CE <= 1.4 V, V_CE within the card's
  0.4-2.0 V window) and the card V_BE box 0.65-0.96 V, applied to the
  instantaneous extremes of Q1 and Q2 over the retained window. A point that
  breaks one is classified and excluded, never fitted through; an "unrestricted
  reference" fit is also shown, labelled NOT A RESULT. The card Ic box is not
  monitored (collector current is not saved).
* **Aborted transients.** A transient that the simulator aborts (solver
  timestep too small at high drive) is a published `sim_failed` sweep point,
  excluded from every fit; it is not a corrupt log.
* **Convergence.** Each sweep is repeated with the solver/DFT step halved and
  with the retained window doubled. A refinement must reproduce the baseline
  estimator outcome (IIP3 within 0.25 dB, P1dB within 0.1 dB, same status) and
  the points the estimator used (fundamentals within 0.05 dB, IM3 within
  0.5 dB). Otherwise the result is `unconverged` and no verdict is drawn.
* **Target assessment.** `meets` only if value minus the *measured*
  convergence spread is still >= the unchanged target; `fails` if value plus
  the spread is below it; `marginal` otherwise; `not_determined` when there is
  no number. A lower bound on P1dB at or above the target is `meets`.

## Controls

A memoryless cubic `y = a1 x + a3 x^3` (a1 = 10, a3 = -2000) between the same
50 ohm terminations has closed-form IIP3, P1dB and small-signal gain
(`linearity.cubic_expectations`; the 9/4, 3/4 coefficients are verified against
a brute-force transform in the tests). It runs through the **identical
generated deck and extractor** as the DUT (as `control_two` / `control_one`
klt requests) and must recover IIP3 within 0.15 dB, P1dB within 0.1 dB and the
gain within 0.05 dB. Common output scaling is invisible to IIP3 and P1dB (only
differences enter), so the gain check is what catches a wrong amplitude
normalization; the swept-power axis catches the available-power convention
(rms/peak, `Vs^2/(2 Z0)`). Negative controls (all must be rejected): wrong
amplitude normalization, wrong power axis, non-coherent placement, non-integer
window, IM3 below the floor, missing 1:3 region, unbracketed P1dB, missing
baseline, out-of-limit points.

### CI control (`ci_assert.py`, issue #122)

The eight fleet collection requests are the only place the real ngspice
controls ran; `ci_assert.py` closes that gap between campaigns. It generates
ONE reduced cubic-only deck through the bench's own generator (the analytic
control circuit on a declared sweep subset: two-tone -50..-36 dBm at 1 dB,
single-tone -48..-16 dBm at 2 dB -- same step and time grid as the plan, so
coherence is inherited; the subset keeps a flat baseline, a 1:3 region far
above the measured floor and a bracketed 1 dB crossing), runs it in ONE
pinned ngspice process (deck-wide the plan's TIGHT two-tone numerics: the
looser single-tone setting guards against DUT high-drive aborts, a stress the
memoryless cubic does not have), and evaluates the measured log with the
bench's own extractor. It asserts the pinned executable identity, completion
(`LNLIN_DONE`) and finite marks, that the measured log recovers all three
known-answer quantities, and that the two extraction-side sabotages (every
measured bin amplitude scaled; the swept power axis shifted) each fail their
intended measured check (the gain; the input-referred dB answers). Green
means the method still works on the pinned simulator -- nothing else: no
record is written (temp dir only), no spec row is claimed, and the DUT
collection stays on the fleet. It runs in the sim-smoke CI job.

## Files

| file | role |
|---|---|
| `testbench/plan.json` | the declaration: ports, placements, sweeps, time grid, solver options, tolerances, limits, controls, ratified targets |
| `linearity.py` | pure logic: power conventions, coherence, deck text, log parsing, the IIP3 and P1dB estimators, convergence verdicts, analytic controls |
| `analysis.py` | frozen logs to published verdicts (deterministic, simulator-free) |
| `run.py` | CLI: `check-plan`, `controls`, `build`, `collect`, `verify` |
| `ci_assert.py` | reduced cubic-only CI control on the pinned ngspice (one process, records nothing; sim-smoke job) |
| `tests/` | method qualification (`test_linearity.py`), CI-control assertions (`test_ci_assert.py`), record round trip (`test_records.py`), closed-form fake logs (`fakes.py`) |
| `records/`, `corners/`, `netlist-snapshots/` | append-only evidence; the checker is the `lna-linearity` adapter in `.github/scripts/check_evidence_formats.py` |

## Status: one record, nominal corner, ideal-matching placeholder

Record: `records/20261010-174208-0f67eaf.md` (plan committed at `0f67eaf`, all
eight klt requests on the batch fleet, both analytic ngspice controls and all
17 negative controls passing, every convergence check passing).

| placement | IIP3 (two-tone, row 7, target >= -15 dBm) | input P1dB (row 8, target >= -25 dBm) |
|---|---|---|
| 17.9/18.0 GHz | -13.29 dBm, `ok`, converged, fitted -56..-44 dBm per tone | `bounded` > -38 dBm within limits; limit-ignoring reference -16.1 dBm (NOT A RESULT) |
| 19.4/19.5 GHz | -13.88 dBm, `ok`, converged | `bounded` > -38 dBm; reference -17.5 dBm |
| 20.9/21.0 GHz | -11.77 dBm, `ok`, converged | `bounded` > -36 dBm; reference above -16 dBm |

* IIP3 meets the unchanged target at this corner on this placeholder, with a
  ~30 dB extrapolation above the highest fitted power (the declared extrapolation
  range). It is not recorded as measured compliance.
* **P1dB is not determined.** Q2's instantaneous V_CE exceeds the 1.4 V row-17
  limit from -36 dBm (single tone; -43/-40 dBm per tone for two tones), far below
  the -25 dBm target level, so no crossing lies inside the operating limits. The
  DUT therefore cannot be shown to meet row 8 without also breaking row 17 at that
  input level; that is a design finding for the first-stage biasing/output
  network, not something the bench may relax.
* Rows 7 and 8 in `spec/row-coverage.json` stay `placeholder_circuit`, now
  citing this record. Corners other than nominal, real (lossy) passives and the
  second stage are not covered.

Method-development probes (a handful of local single-unit runs at the mid
placement) fixed the solver options, the sweep ranges and the IM3 floor margin
before the plan was committed; the limits, the targets and the tolerances were
not tuned on DUT results.
