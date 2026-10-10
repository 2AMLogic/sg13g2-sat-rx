# Conversion-matrix noise solver: interface feasibility and go/no-go (issue #89)

Scope: **interface feasibility on the pinned simulator/model only.** No solver is built, no
active-mixer NF number is produced, and nothing here is evidence for `spec/target-spec.md` row 10
or row 12 (`spec/row-coverage.json` row 10 stays `method_absent`). The LO drive in the probe is a
probe setting, not a design selection. The `MODEL_ABSENT` result of
[`../mixer-nf-method`](../mixer-nf-method/README.md) is unchanged.

## Decision

**NO-GO for a conversion-matrix noise solver that takes its noise terms from the pinned
ngspice-46 / VBIC `npn13G2` model.** Two of the five required interfaces are unsupported on
primary-source evidence, so the route is blocked regardless of how well the transfer half works:

- `noise_intensity_per_mechanism`: the model's noise intensities exist only inside the small-signal
  `.noise` / `.sp` analyses, about a fixed DC operating point. No analysis evaluates them along a
  periodic trajectory: there is no pnoise, and PSS is not in the release build. Filling the gap with
  intensities guessed from instantaneous currents would be a guessed external noise source, which
  the issue forbids.
- `noise_covariance_ib_ic`: `VBICnoise()` evaluates its 13 generators independently, so the model
  defines no ib/ic covariance and nothing exposes one.

This is a **blocker, not a failure of the investigation**: the issue names a reproducible blocker
as a successful outcome. No solver contract is written, because the contract is specified only on
a go.

## Status of the evidence (read this before citing it)

Record: `records/20261010-123114-1755c6d-INTERFACES_BLOCKED.*` with frozen package
`probe-logs/20261010-123114-1755c6d/` (issue #107). It was produced on the pinned
`ngspice-46` (`/home/ubuntu/.local/bin/ngspice`, sha256 `555e04b8...aa5dd5`) after the harness
model-integrity gate (`sim/harness/pdkartifact.py`, `require_ngspice=True`) reported OK: the
four-file IHP closure matches the pin at `5cccb161f749`. The gate outcome is stored in the record
(`environment.pdk_integrity`). This record **supersedes**
`records/20261010-083631-709284d-CAPABILITY_UNAVAILABLE.*` (the missing-tool outcome, which
carried no probe result and is unchanged). Caveat: the run used the working tree with the
`run_probe.py` integrity-gate change (#107) uncommitted, so the record shows `dirty: True`
against base commit `1755c6d`.

| Item | State |
|---|---|
| Transfer side (measured, pinned) | The known-answer control passed all five checks in the same run (wanted/image magnitude error about `3e-6`/`5e-6`, phase error about `5e-5` degrees, wrong-IF null `6e-7`, linearity `5e-17`, superposition `1e-4`). Gated on that: LO-period trajectory demonstrated (window-to-window change at most `7.2e-4`, in the LO 2nd harmonic; fundamental and mean unchanged), wanted-sideband transfer `|G| = 0.0576` and image-sideband transfer `|G| = 0.0583` (source EMF to `coll` voltage; phase about 177 degrees; linearity `3e-5`, superposition `4e-5`). This is the nominal placeholder point only. |
| Measured on the pinned binary, noise side | `pss`, `pnoise` and `pac` each answered `no such command available in ngspice` (`probe-logs/20261010-123114-1755c6d/stderr.txt`). This is the first pinned-binary observation for `pnoise` and `pac` (issue #27 probed only `pss`). Per-generator `.noise` totals exist at two DC biases (quasi-static, not along the trajectory). |
| Reference-based (not a probe result) | That `VBICnoise()` evaluates 13 independent generators (no ib/ic covariance), that no analysis evaluates intensities along a trajectory, and the manual 11.3.12 / 1.2.8 statements rest on primary references (below); the absence of a command in this binary is consistent with them but does not establish the source-level claims. |

Observed status `INTERFACES_BLOCKED` matches the earlier prediction (transfers and trajectory
demonstrated, the two noise interfaces unsupported); the prediction is now a result. It is
interface feasibility only: no solver, no NF number, nothing for row 10 (`method_absent`) or
row 12.

## Required-interface matrix

| Interface | State | Primary basis |
|---|---|---|
| LO-period trajectory | **demonstrated** (pinned record, `.tran` settling) | probe: window-to-window change of the LO-only harmonics and mean below `1e-3` |
| Wanted-sideband transfer | **demonstrated** (pinned record; control passed) | probe: base-referred perturbation at fLO + fIF, IF projection minus LO-only baseline |
| Image-sideband transfer | **demonstrated** (pinned record; control passed) | probe: perturbation at fLO − fIF, arrives conjugated |
| Per-mechanism noise intensity along the trajectory | **unsupported** | manual v46 section 11.3.12 (`.PSS` "Experimental code, not yet made publicly available") and 1.2.8 (PSS is the basis of PAC/PNoise, neither exists in the release); source `ngspice-46` `vbicnoise.c` reached only via `DEVnoise` from `cktnoise.c` (`.noise`) and `noisesp.c` (`.sp`); `dcpss.c` only under `--enable-pss`; no pnoise in the tree |
| Noise covariance (ib/ic) | **unsupported** | source `ngspice-46` `src/spicelib/devices/vbic/vbicnoise.c`: 13 independent generators |

Each noise mechanism's evidence: collector and base shot, terminal-resistance thermal, flicker
(`vbicnoise.c` generators) and resistor thermal (`.noise` only; `resload.c` has no noise term)
are all DC-point quantities. Their per-bias sizes are probed in step N (two DC biases) only to
show that they exist and move with bias; that is quasi-static access at a fixed operating point
and is not the interface a pumped mixer needs. The source findings are carried from #27, which
inspected tag `ngspice-46` (`ebdaf58e`); they were not re-fetched for this issue.

## Known-answer control

`controls/ideal_mixer.spice` is an ideal multiplying mixer with closed-form transfers
`Gw = (k·A/2) e^{-jθ}` and `Gi = (k·A/2) e^{+jθ}` (the image conjugated), run in the same
`ngspice` process and stimuli as the HBT. The probe checks wanted and image magnitude to `1e-3` and
phase to `0.1°`, a null at a wrong IF (frequency bookkeeping), 2x-amplitude linearity and
two-tone superposition. `tests/` proves each sabotage fails it: scaled gain, dropped image path,
sign-flipped image path, shifted LO. `run_probe.py --sabotage <mode>` repeats that against the real
simulator and exits non-zero if a sabotaged control ever passes.

## Exploratory dry run (unpinned `ngspice-42`, Debian build; not evidence, not recorded)

Run with `--allow-unpinned --no-write` on this host to validate the probe itself:

- Control: magnitude errors about `3e-6`, phase errors about `5e-5` degrees, wrong-IF null `5e-7`,
  linearity `2.5e-7`, superposition `1e-4`; all four sabotages failed it.
- HBT placeholder, LO 80 mV: both sideband transfers `|G| ≈ 0.058` (source EMF to `coll` voltage),
  linearity and superposition errors below `1e-4` at 2 mV, LO fundamental window-to-window change
  below `1e-6`. A 20 ns settle was **not** enough (mean drifted 0.1 %, which is why the probe
  projects over the last 40 ns of a 120 ns run).
- Noise: per-generator `.noise` totals are reachable at a DC point. `pnoise` and `pac` do not exist
  in this Debian build (an observation on the unpinned binary only; on ngspice-46 their absence is
  still reference-based, see "Status of the evidence"). This Debian build does ship a `pss` command, unlike the pinned build, and
  it did **not** converge on the placeholder (`Convergence not reached` after 50 shooting
  iterations); this is a single observation on an unpinned binary, recorded only as a pointer for
  a later question, not as an interface finding.

## What would change this decision

- A simulator or build that provides periodic noise (pnoise or harmonic-balance noise) with the VBIC
  generators, or a documented way to read the model's instantaneous noise intensities along a
  trajectory. Then re-run this probe; the transfer half is already in place.
- A model whose covariance is stated (or an agreed, cited convention for the model's diagonal
  independent-generator structure that a reviewer accepts as "model-consistent"). That is a
  methodology decision for a spec/decision record, not something this investigation may settle.

## If a go is ever reached: what the solver contract must pin down

Listed for the future task, not specified here: the source covariance convention, wanted / image /
load accounting, the available-to-delivered gain reference (the probe's raw transfers are
source-EMF-to-node-voltage), T0 matching the existing estimator (`300.15 K`), the retained
harmonic/sideband sets, explicit numerical convergence controls (timestep, window, harmonics) and
the independent controls required before any solver could claim `METHOD_VALIDATION` (this
investigation can never grant that status).

## Reproduce

See [`README.md`](README.md) "Cold start". The pinned record was produced with
`python3 sim/mixer-cm-interface-probe/run_probe.py` (preceded by `python3 -m harness.cli verify-pdk
--require-ngspice` from `sim/`), and
`python3 sim/mixer-cm-interface-probe/run_probe.py --reparse probe-logs/<id>` re-derives its status
from the frozen logs without a simulator.
