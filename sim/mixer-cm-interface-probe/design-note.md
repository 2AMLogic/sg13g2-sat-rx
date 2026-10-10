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

| Item | State |
|---|---|
| Frozen record on this branch | `records/20261010-083631-709284d-CAPABILITY_UNAVAILABLE.*`: the pinned `ngspice-46` is **not installed on the build host** (`/usr/bin/ngspice` is 42). No probe result is claimed from it. |
| Noise-side blockers | Supported by primary references (below), independent of any binary run on this host. The pinned-binary corroboration (`pss: no such command`, `pnoise: no such command`) is the inventory of issue #27 (probe E) and is re-checked by this probe's step E when it runs on a host with the pinned binary. |
| Transfer-side feasibility | **Not yet frozen on the pinned executable.** An unpinned exploratory run on `ngspice-42` (not evidence, nothing recorded) passed the known-answer control and showed both sideband transfers and a settled orbit; see "Exploratory dry run". A record on `ngspice-46` has to be appended by a host that has it (CI builds exactly that tarball). |

The expected record on the pinned binary is `INTERFACES_BLOCKED` (transfers and trajectory
demonstrated, the two noise interfaces unsupported). That expectation is a prediction, not a
result, until the record exists.

## Required-interface matrix

| Interface | State | Primary basis |
|---|---|---|
| LO-period trajectory | demonstrable via `.tran` settling; frozen only on a pinned host | probe: window-to-window change of the LO-only harmonics and mean below `1e-3` |
| Wanted-sideband transfer | demonstrable; gated on the known-answer control | probe: base-referred perturbation at fLO + fIF, IF projection minus LO-only baseline |
| Image-sideband transfer | demonstrable; gated on the known-answer control | probe: perturbation at fLO − fIF, arrives conjugated |
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
  in this build either. This Debian build does ship a `pss` command, unlike the pinned build, and
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

See [`README.md`](README.md) "Cold start". A host with the pinned `ngspice-46` appends the
pinned record with `python3 sim/mixer-cm-interface-probe/run_probe.py`, and
`python3 sim/mixer-cm-interface-probe/run_probe.py --reparse probe-logs/<id>` re-derives its status
from the frozen logs without a simulator.
