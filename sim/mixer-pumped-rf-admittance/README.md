# sim/mixer-pumped-rf-admittance: can the LO-on mixer RF-port admittance be measured?

Issue [#111](https://github.com/2AMLogic/sg13g2-sat-rx/issues/111). A bounded,
method-feasibility experiment at **one nominal point** (`hbt_typ` / 27 °C / 2.50 V). It asks
whether the LO-on (pumped) small-signal admittance of a mixer RF port can be extracted on the
pinned simulator with limits that can be stated, which is the measurement prerequisite that
[DR-0004](../../spec/decision-records/0004-lna-mixer-interface-convention.md) (proposed) names for
row 5 under its Option B, and whose absence is its falsifier 3.

**Scope.** Deterministic input admittance only. **No record here is, or may be read as, a
`spec/target-spec.md` row 5 compliance result**, and none is a mixer or cascade noise figure
(rows 10/12 stay where [`../mixer-cm-interface-probe`](../mixer-cm-interface-probe/README.md)
left them). The DUT is the existing single-`npn13G2` placeholder
(`sim/mixer-conversion-iip3/testbench/mixer_ce_placeholder.spice`, included verbatim) used only as
an exploratory device; its LO drive is the placeholder's own `vlo` = 0.08 V EMF, a probe setting
and not a qualified drive (that decision is [#68](https://github.com/2AMLogic/sg13g2-sat-rx/issues/68)).
No topology, matching network or drive is selected, no spec value is touched, and DR-0004 is
neither ratified nor reversed.

## Port model

A pumped port is linear periodically time-varying: a voltage at one frequency produces current
at every mixing frequency. Restricted to the two RF sidebands, f_u = f_LO + f_IF = 19.45 GHz
(wanted) and f_l = f_LO − f_IF = 17.45 GHz (image), with f_LO = 18.45 GHz, f_IF = 1 GHz:

```
I_u = Y_uu V_u + Y_ul conj(V_l)
I_l = Y_lu conj(V_u) + Y_ll V_l
```

The image enters conjugated. An LTI port has Y_ul = Y_lu = 0 (the scalar case). A
time-varying port whose 2·f_LO harmonic is significant couples the two sidebands, and a scalar
impedance then silently depends on what the source does at the other sideband.

Conventions (`pumped.py`):

- **Phasors** are cosine-referenced, `y(t) = Re(X e^{jωt})`, from `.meas tran INTEG` of
  `y·cos` and `y·sin` over a window holding an integer number of periods of f_u, f_l and f_LO
  (every tone is a multiple of 25 MHz). `X = (2/T)(C − jS)`.
- **Reference plane**: node `prf`, the placeholder's RF port, looking into its 1 pF coupling
  capacitor `Cin_rf`. **Current is positive into the mixer.**
- **Perturbation**: a Norton current per sideband injected into `prf` through a 0 V ammeter, in
  parallel with the placeholder's own 50 Ω `Rrf` (its RF source zeroed). That is exactly a
  Thevenin EMF through the placeholder's own 50 Ω, so the termination the mixer sees at every
  frequency is unchanged. `I = i(vpsense) + (v(rfsrc) − v(prf))/50`.
- **Baseline subtraction**: every response is the run's phasor minus the LO-only baseline's,
  same time step, same window.
- **Two independent perturbation phases**: `p1` drives both sideband tones at phases
  (20°, 70°), `p2` at (20°, 250°) (image tone inverted). Each phase is one row of the 2×2
  system per equation; the four elements are solved from **measured** port voltages and
  currents. The scalar `I/V` of `p1` and `p2` differ when a conjugate term exists, which is
  reported as a model-free discriminator.
- **Conditional quantity**: the matrix is embedded, not intrinsic. It holds for the
  termination the fixture presents at every other mixing frequency (IF, 2·f_LO ± …,
  3·f_LO ± f_IF), here the placeholder's 50 Ω + 1 pF. A different source (an LNA output)
  changes those terminations and therefore the matrix.

## Known-answer controls (run in the same deck, same runs, same extraction)

| fixture | file | closed form | must classify |
|---|---|---|---|
| passive series RC (25 Ω + 1 pF), Norton drive + 50 Ω termination exactly like the DUT | `controls/rc_known_answer.spice` | `Y = 1/(R + 1/(jωC))` at f_u, f_l; cross terms 0 | `SCALAR_ADEQUATE` |
| ideal modulated conductance `g0 + 2 g2 cos(2 ω_LO t + θ)` ‖ 0.1 pF, ideal V drive, plus an LO-only current at f_u | `controls/modulated_known_answer.spice` | `Y_uu = g0 + jω_u C`, `Y_ll = g0 + jω_l C`, `Y_ul = Y_lu = g2 e^{jθ}` (κ ≈ 0.26) | `MATRIX_REQUIRED` |

Sabotages (extraction-side, `--sabotage`, never write a record) must make the controls fail on
a measured check:

| sabotage | fault | how it fails (closed form and pinned ngspice) |
|---|---|---|
| `current_sign` | port current taken out of the DUT | every element 180° off (RC and modulated) |
| `omit_image` | scalar `I/V` from phase `p1`, conjugate coupling dropped | modulated `Y_ul`/`Y_lu` 100 % off, `Y_uu`/`Y_ll` off by ~κ; the LTI RC cannot see it, the modulated fixture does |
| `no_baseline` | LO-only baseline not subtracted | modulated `Y_uu` off; halving check fails |

## Thresholds (declared before the DUT result)

[`thresholds.json`](thresholds.json) holds every tolerance with its justification. It was
committed before the placeholder was ever run by this probe (only the two control fixtures had
been simulated); `run_probe.py` refuses to write a record while it is uncommitted or modified,
and each record carries its sha256 and the commit that last touched it. Summary:

| check | threshold |
|---|---|
| known-answer magnitude / phase per element | 0.5 % / 0.3° |
| RC cross-term null (relative to the diagonal) | 0.5 % |
| condition number of the two-phase voltage matrix | ≤ 10 |
| perturbation halving (2 mV → 1 mV EMF), max element change / max diagonal | ≤ 1 % |
| retained-window extension ([80,120] ns → [80,160] ns) | ≤ 0.5 % |
| timestep refinement (1 ps → 0.5 ps) | ≤ 0.5 % |
| response / LO-only baseline at every sideband, run, V and I | ≥ 10 |
| scalar bound on κ = max(\|Y_ul\|/\|Y_uu\|, \|Y_lu\|/\|Y_ll\|) | 0.05, with a dead-band of the convergence uncertainty |

## Statuses

| Status | Meaning |
|---|---|
| `SCALAR_ADEQUATE` | controls pass, every numerical check passes, κ + u < 0.05: one complex admittance per sideband describes the port at this point |
| `MATRIX_REQUIRED` | controls pass, every numerical check passes, κ − u > 0.05: the sideband-coupled 2×2 admittance is required; a scalar would misstate the port |
| `INCONCLUSIVE` | a control or numerical check failed, or κ straddles the bound within its uncertainty |
| `CAPABILITY_UNAVAILABLE` | the pinned executable or model integrity is missing on this host; no probe ran |

None of these is a compliance verdict, and `SCALAR_ADEQUATE` / `MATRIX_REQUIRED` describe the
DUT at one point only.

## Cold start

```
python3 -m pytest sim/mixer-pumped-rf-admittance/tests -q                 # no simulator
python3 sim/mixer-pumped-rf-admittance/run_probe.py --controls-only       # one local ngspice -b, controls only, no record
python3 sim/mixer-pumped-rf-admittance/ci_assert.py                       # controls + every sabotage on the pinned ngspice
python3 sim/mixer-pumped-rf-admittance/run_probe.py --no-write            # controls + DUT once, print only
python3 sim/mixer-pumped-rf-admittance/run_probe.py                       # appends a record (+ probe-logs/<id>/)
python3 sim/mixer-pumped-rf-admittance/run_probe.py --reparse probe-logs/<id>                      # re-derive, no simulator
python3 sim/mixer-pumped-rf-admittance/run_probe.py --reparse probe-logs/<id> --sabotage omit_image # controls must FAIL
python3 sim/mixer-pumped-rf-admittance/run_probe.py --reparse <dir> --declaration <thresholds file> # unrecorded log only
```

The executable must be the pinned ngspice major in `sim/pdk-artifact.json`, and the
`pdkartifact` model-integrity gate runs before the simulator; otherwise a
`CAPABILITY_UNAVAILABLE` record carries no result. `--allow-unpinned` explores on another
binary and never writes a record.

## Replay contract (`--reparse`)

Replay re-derives a frozen log without a simulator, judged by **the declaration that judged
it**, never by whatever `thresholds.json` says today (issue
[#129](https://github.com/2AMLogic/sg13g2-sat-rx/issues/129)). A later, justified change to
`thresholds.json` therefore cannot change what an older log means; it needs its own record.

- **Recorded log** (`probe-logs/<id>/`). The run id is the directory name. Replay resolves
  exactly one `records/<id>-<STATUS>.json` and evaluates with that record's stored
  `thresholds` (the same values `.github/scripts/check_evidence_formats.py` checks the
  record against). Before evaluating it checks the run identity and the record/package
  relationship: `record_id` equals `<id>`, the JSON `status` equals the file-name status and
  `classification`, the status carries a probe result (not `CAPABILITY_UNAVAILABLE`),
  `probe_logs` is `sim/mixer-pumped-rf-admittance/probe-logs/<id>/`, and the directory given
  is that package (not a copy elsewhere). The thresholds must be exactly the nine declared
  keys as positive finite numbers, and `thresholds_provenance` must be present.
- **Report.** The output's `replay` object names the mode, run id, log directory, record,
  and the declaration used (its source, file, sha256 and declaring commit, from the record's
  `thresholds_provenance`) with the threshold values. For a recorded log,
  `classification_check` compares the recomputed classification with the stored one.
- **Disagreement fails.** If the recomputed classification differs from the stored one, the
  replay prints both and exits **3**.
- **Unrecorded (exploratory) log** (for example a `--no-write` work directory). There is no
  historical declaration, so `--declaration <file>` (thresholds.json format; its `values`
  must be exactly the nine keys) is **required**; the current `thresholds.json` is never
  borrowed silently, though it may be passed explicitly. The report names the file and its
  sha256. `--declaration` is refused for a recorded log: its stored declaration is
  authoritative.
- **Sabotage.** `--sabotage` on a replay evaluates with the same resolved declaration (the
  record's, or the explicit one) and reports it; no classification comparison is made, since
  the sabotage changes the extraction on purpose.
- **Refusals** exit **1** with a `replay refused:` message and print no result: a missing log
  directory or `stdout.txt`/`stderr.txt`; an unrecorded log without `--declaration`; more
  than one record for the run id (ambiguous); any identity or package mismatch above;
  malformed record or declaration JSON; missing, extra, non-numeric or non-positive
  thresholds.

## Method

One `ngspice -b` process, eight sequential `.tran` runs inside its own control block (no grid,
no shell loop): `base` (LO only), `p1`, `p2`, `p1h`, `p2h` (both phases at half amplitude), all
to 160 ns at a 1 ps maximum step, and `base_r`, `p1_r`, `p2_r` to 120 ns at 0.5 ps. Each run
projects the port voltage, ammeter current and termination node of all three fixtures at f_u
and f_l over [80,120] ns and, for 160 ns runs, [80,160] ns. About 20 s for the controls-only
deck and under a minute with the DUT, on one core.

Extraction sets: `primary` (`p1`,`p2`,`base`,[80,120]), `halved`, `extended` ([80,160]) and
`refined` (`p1_r`,`p2_r`,`base_r`). The convergence metric is
`max_e |Y_e − Y'_e| / max(|Y_uu|, |Y_ll|)`; κ's uncertainty `u` is the worst of the three,
rescaled to the smaller diagonal.

## Layout

```
README.md  thresholds.json  run_probe.py  pumped.py  ci_assert.py
probe/admittance_probe.spice                deck template (placeholder included verbatim)
controls/rc_known_answer.spice              passive RC known answer
controls/modulated_known_answer.spice       ideal periodically modulated known answer
tests/                                      extraction, known answers, sabotages, classification, deck schema
records/<id>-<STATUS>.md|.json              <id> = <YYYYMMDD>-<HHMMSS>-<git-sha>
probe-logs/<id>/{deck.spice,stdout.txt,stderr.txt,inventory.json}
```

`inventory.json` carries the parsed marks and the full `evaluation`, which must equal the
record's. `.github/scripts/check_evidence_formats.py` enforces the layout through the
registered `mixer-pumped-rf-admittance` adapter (statuses, scope disclaimer in both halves,
committed thresholds, check flags agreeing with thresholds, κ following from the matrix,
status following from controls/checks/κ, log package, orphan logs, foreign evidence dirs) and
protects `records/` and `probe-logs/` append-only.

## Result at the nominal point

Record [`records/20261010-142503-1aaad2c-SCALAR_ADEQUATE.md`](records/20261010-142503-1aaad2c-SCALAR_ADEQUATE.md)
(thresholds from commit `e853ece`, committed before this run; one local `ngspice -b`, 30-45 s on this shared host):

- Both known-answer controls pass in the same runs: RC and modulated elements within
  ≤ 3.4e-4 magnitude and ≤ 0.04° phase, RC cross-term null ≈ 1e-6, RC → `SCALAR_ADEQUATE`,
  modulated → `MATRIX_REQUIRED` (κ = 0.263 recovered). All three sabotages fail them on the
  frozen log (`--reparse … --sabotage …`).
- DUT: `Y_uu` = 39.3 mS ∠ 37.7°, `Y_ll` = 37.7 mS ∠ 39.3°, cross terms ≈ 0.015 mS; κ = 3.7e-4,
  uncertainty 4.2e-4 (dominated by timestep refinement, 4.0e-4; halving 3e-6, window 4e-6,
  condition number 1.03, response/baseline ≥ 2.2e4). The p1/p2 scalar spread is 7.7e-4.
- So at this point the placeholder's RF port is described by one complex admittance per
  sideband. That is a statement about **this placeholder at this drive**, not about mixers:
  its base is shunted by two other 50 Ω + 1 pF ports (the second IIP3 tone and the LO port)
  and its LO is a weak 0.08 V EMF probe setting, so the device's 2·f_LO conductance harmonic
  is a small part of the port admittance. A double-balanced core or a stronger LO can couple
  the sidebands much more; the modulated control shows the extraction would then report
  `MATRIX_REQUIRED` rather than collapse it.

## What this means for DR-0004, and what stays blocked on #68

DR-0004 (proposed) says row 5 under Option B "needs a mixer RF-port impedance method that does
not exist in this repo (no PAC in ngspice)", and its falsifier 3 is that the LO-on RF-port
impedance "cannot be extracted with a method whose limits can be stated". This experiment is
evidence about that prerequisite only:

- **Supports**: on the pinned ngspice 46, without PSS/PAC, a transient two-phase
  perturbation extracts the LO-on sideband admittance with stated limits (sign and phasor
  conventions, baseline subtraction, termination conditionality, predeclared
  small-signal/window/timestep/conditioning bounds), qualified on two closed-form fixtures with
  sabotages that fail for numerical reasons. It also says when a scalar is not enough
  (`MATRIX_REQUIRED`), which a scalar method would hide. At this single point the method
  therefore does not trigger falsifier 3.
- **Does not decide**: DR-0004 stays proposed. Nothing here compares Option A with B, edits
  the port convention, or gives row 5 a number: the DUT is a placeholder, the point is single,
  and the conjugate-match form of row 5 under a `MATRIX_REQUIRED` port would itself need a
  definition in a DR.
- **Blocked on #68** (no acceptable LO drive at any declared mixer-core sizing): the pump level
  sets the 2·f_LO conductance harmonic that decides scalar versus matrix, so this result cannot
  be carried to a real drive. The band (17.7–21.2 GHz) and PVT campaign, a real mixer RF port
  (not the IIP3 placeholder with its extra ports), and the embedding by an actual LNA output
  (which changes the termination at every other mixing frequency) all wait for an acceptable
  drive and an approved follow-up.
- **Out of scope**: noise. Mixer and cascade NF stay blocked as
  [`../mixer-cm-interface-probe`](../mixer-cm-interface-probe/README.md) records.

## Campaign path

Not needed for this feasibility question. A band or PVT campaign waits for an acceptable mixer
drive (#68) and an approved follow-up; it would be expressed as a `klt sim` request so it goes
to the batch fleet, never as a local `ngspice` loop.

## CI coverage

`harness-tests` runs `tests/` simulator-free. `sim-smoke` runs `ci_assert.py` on the pinned
ngspice 46: one controls-only process, then the positive controls and all three sabotages are
evaluated on that log. It records nothing and asserts nothing about the DUT.
