# sim/mixer-cm-interface-probe: interface feasibility for a mixer conversion-matrix NF solver

Issue [#89](https://github.com/2AMLogic/sg13g2-sat-rx/issues/89). A bounded, capability-first
investigation at one nominal point (`hbt_typ` / 27 °C / 2.50 V, the existing single-`npn13G2`
placeholder; the LO drive is a probe setting, not a design selection). It asks whether the
interfaces a **conversion-matrix** noise solver would need are reachable on the pinned
simulator/model, as the follow-up that [`../mixer-nf-method`](../mixer-nf-method/README.md)
deferred. It builds **no solver**, designs no mixer, edits no spec row, and reports **no
active-mixer NF number**. **No record here is, or may be read as, evidence for
`spec/target-spec.md` row 10 (mixer SSB NF) or row 12 (cascade NF)**; `spec/row-coverage.json`
row 10 stays `method_absent`. The design note with the go/no-go is
[`design-note.md`](design-note.md).

## Required interfaces

| Interface | What a solver needs |
|---|---|
| `lo_period_trajectory` | a settled LO-period operating trajectory |
| `wanted_sideband_transfer` | perturbation (fLO + fIF) to IF transfer |
| `image_sideband_transfer` | perturbation (fLO − fIF) to IF transfer, arriving conjugated |
| `noise_intensity_per_mechanism` | model-consistent device/resistor noise intensities **along** that trajectory |
| `noise_covariance_ib_ic` | the model's source covariance (ib/ic) |

A transfer interface is `demonstrated` only if the **known-answer control** passes in the same
run (`controls/ideal_mixer.spice`: an ideal multiplying mixer with closed-form wanted and image
transfers, a frequency-bookkeeping null and linearity/superposition checks). A failing control
leaves the interface `unknown`, never `unsupported`: a broken probe is not an absent capability.

## Statuses

| Status | Meaning |
|---|---|
| `INTERFACES_DEMONSTRATED` | all five interfaces demonstrated (interface feasibility only) |
| `INTERFACES_PARTIAL` | none unsupported, but at least one unresolved |
| `INTERFACES_BLOCKED` | at least one interface unsupported (no-go for that route) |
| `CAPABILITY_UNAVAILABLE` | the pinned executable is missing on this host; **no** probe result, never establishes absence |

None of these is `METHOD_VALIDATION`; a go here establishes interface feasibility only.

## Cold start

```
python3 -m pytest sim/mixer-cm-interface-probe/tests -q       # no simulator (pytest only; tests are stdlib unittest)
python3 sim/mixer-cm-interface-probe/run_probe.py --no-write  # one local ngspice -b, prints the record
python3 sim/mixer-cm-interface-probe/run_probe.py             # appends a new record (+ probe-logs/<id>/)
python3 sim/mixer-cm-interface-probe/run_probe.py --reparse probe-logs/<id>   # re-derive from a frozen log, no simulator
python3 sim/mixer-cm-interface-probe/run_probe.py --sabotage image_sign --allow-unpinned   # control must FAIL
```

The executable must be the pinned ngspice major in `sim/pdk-artifact.json`. On any other
binary the run writes a `CAPABILITY_UNAVAILABLE` record that carries no probe results;
`--allow-unpinned` runs an unpinned binary for exploration only and never writes a record.
Sabotage modes (`gain`, `drop_image`, `image_sign`, `wrong_lo`) break the control and exit 0
only when it fails; they never write a record.

Records are append-only (exclusive create; a re-run writes a new id). A later record made on a
host with the pinned executable supersedes an earlier `CAPABILITY_UNAVAILABLE` one; the earlier
file is not edited.

## Layout

```
README.md  design-note.md  run_probe.py  cmprobe.py  ci_assert.py
probe/interface_probe.spice      the deck template (placeholder included verbatim)
controls/ideal_mixer.spice       known-answer ideal multiplying mixer + sabotage .param knobs
tests/                           closed-form control, ci_assert failure modes, every sabotage failing it, status logic
records/<id>-<STATUS>.md|.json   <id> = <YYYYMMDD>-<HHMMSS>-<git-sha>
probe-logs/<id>/{deck.spice,stdout.txt,stderr.txt,inventory.json}
```

`inventory.json` carries the parsed marks plus an `interface_matrix` that must equal the
record's JSON `interface_matrix`. `.github/scripts/check_evidence_formats.py` enforces the
layout through the registered `mixer-cm-interface-probe` adapter (statuses, scope disclaimer,
matrix shape, status-follows-from-states, control-gated transfer claims, log package, orphan
logs) and protects `records/` and `probe-logs/` append-only. The sibling
`mixer-nf-method` adapter and its `MODEL_ABSENT` records are untouched.

## Method

One `ngspice -b` process; no grid, no seed campaign, no shell loop (the host rule is that
SPICE grids go to the fleet through a `klt sim` request, and none is needed here). Inside the
process the control block runs five short `.tran` runs of the placeholder with two extra
perturbation sources: a LO-only baseline `base`, the wanted tone `u`, the same tone at twice the
amplitude `u2`, the image tone `l`, and both `ul`. IF phasors are projected with `.meas INTEG`
over 40 IF periods at the end of a 120 ns run. The perturbation response is the run's phasor
minus the baseline's. The disjoint ideal-mixer control sees identical stimuli in the same runs.
A two-bias `.noise` run and `pss`/`pnoise` attempts follow.

Conventions (`cmprobe.py`): tones are `a·sin(ωt + φ)`, `P = a e^{jφ}`; an IF waveform is
`Re(X e^{jω_IF t})`; `X = Gw·P` for the wanted sideband and `X = Gi·conj(P)` for the image.
For the ideal mixer, `Gw = (k·A/2) e^{−jθ}` and `Gi = (k·A/2) e^{+jθ}`. These raw transfers are
source-EMF-to-node-voltage; the available-to-delivered gain reference is a solver-contract item
(`design-note.md`), not something this probe defines.

## Campaign path

None is needed for interface probing. If a later, justified task needs a sideband or seed
sweep, express it as a `klt sim` request (`corners` / `monte_carlo`) so it goes to the fleet;
do not loop `ngspice -b` locally.

## CI coverage (issue #104)

`harness-tests` runs `tests/` simulator-free (closed-form control, fake logs, and
`ci_assert.assess` for every failure mode). The `sim-smoke` job additionally runs
`python3 sim/mixer-cm-interface-probe/ci_assert.py` on the pinned ngspice 46: the positive
ideal-mixer control plus the `gain`, `drop_image`, `image_sign` and `wrong_lo` sabotages, five
sequential single-point ngspice processes (about one minute locally; no grid).

The helper reads structured control results, because `run_probe.py` exits 0 on a missing or
wrong executable. It fails CI if the pinned executable is missing or a different major, the deck
does not complete, control marks are missing or non-finite, the unsabotaged control does not
pass, or any sabotage passes or fails only a bookkeeping check. It does not assert an overall
interface status, so `INTERFACES_BLOCKED`/`PARTIAL` noise-side outcomes remain acceptable. It
runs in a temp directory and records nothing: this is a control-discrimination check, not
evidence, not a row 10/12 claim and not `METHOD_VALIDATION`. `design-note.md` still states
transfer feasibility as unresolved until a pinned, append-only record says otherwise.
