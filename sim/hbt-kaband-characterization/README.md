# hbt-kaband-characterization — Ka-band `npn13G2` device characterization

Issue [#17](https://github.com/2AMLogic/sg13g2-sat-rx/issues/17): step 3 of
`spec/porting-plan.md` §5 ("Ka-band device re-characterization"). The data
here are the prerequisite for choosing any LNA transistor size or bias point
(T1 item 1); they are **not** that choice, and not a design.

**Device-level evidence, not a matched-amplifier result.** Every number is a
two-port parameter of one bare `npn13G2` behind ideal bias tees with ideal,
noiseless terminations. NFmin is a lower bound on what a circuit built around
the device could reach *before* matching-network loss, bias/degeneration
noise and the following stage. MAG/MSG is device gain, not a designed
stage's gain. Nothing here claims a `spec/target-spec.md` row is met; the
row-3 comparison in each record is a feasibility screen only.

## What is measured, and how

All at 17.7 / 19.45 / 21.2 GHz (the draft band edges and centre), at every
bias point, at every PVT point.

| Quantity | Method |
|---|---|
| **NFmin, Zopt, Rn, Tmin** (two-port noise parameters) | `.noise` with a **noiseless** source impedance `Zs = R + jX` (`noisy=0` resistor, ideal L/C) at 10 declared impedances from 25 Ω to 1000+1500j Ω, per frequency. For a linear noisy two-port the input-referred noise voltage density is exactly `Sv(Zs) = a + b|Zs|² + c·Rs + d·Xs`; a 1/Sv-weighted least-squares fit gives `Xopt = −d/2b`, `Ropt = √(a′/b)` with `a′ = a − d²/4b`, and `Tmin = (2√(a′b) + c)/4k`, so `NFmin(T0) = 10·log10(1 + Tmin/T0)` (`kaband.fit_noise_parameters`). The source plane is the device base terminal; the 1 nF DC block in the source chain is included exactly in every Zs. |
| Independent checks of the noise parameters | (1) a separate `.noise` run at the optimum (picked in-deck from a closed form over the first four impedances, applied at full precision) must reproduce NFmin to 0.001 dB; (2) a separate `.noise` run at 50 Ω (not one of the fitted impedances) must agree with the fit's prediction to 0.001 dB; (3) the fit residual must be below 1e-4 relative. A point failing any check is excluded with its reason. |
| Bias consistency | Every analysis re-solves the operating point and prints the Ic it actually ran at; a point is excluded unless every analysis agrees with the reported Ic to 1e-4 relative (observed scatter ≤ 2.6e-6 at 125 °C; an analysis that lands in a different electrothermal state differs at the percent level). The two DUT copies must agree to 1e-6. |
| **NF₅₀** | The direct 50 Ω run above: `F = 1 + Sv/(4·k·T0·50)`. Device-only (the load is noiseless — its noise belongs to the next stage of a cascade, not to this device's figure). |
| **fT** | Short-circuit current gain `|h21| = |y21/y11|` (output AC-shorted, ideal voltage drive at the base) swept `ac dec 10 1e9 3e12` at the same operating point; the 0 dB crossing is log-log interpolated between the two bracketing sweep points. No crossing → `ft_status` says why (`below_sweep_start`/`above_sweep_stop`); nothing is extrapolated or carried over. This VBIC build exposes no named `ft` operating-point field (the finding `sg13g2-lna` records), hence the sweep. |
| **K, \|Δ\|, MAG or MSG** | Y-parameters from two `.ac` runs (ideal voltage drive at one port, the other AC-shorted), converted to S at 50 Ω. MAG is reported only where the device is unconditionally stable (K > 1 **and** \|Δ\| < 1); otherwise MSG = \|S21/S12\| with `gmax_kind = MSG`. At these frequencies the bare device is generally *not* unconditionally stable, so MSG dominates — an MSG is not achievable gain without stabilization. |
| **J_C** | Measured: `Ic / (Nx · 0.063 µm²)` [mA/µm²]. 0.063 µm² = 0.07 × 0.90 µm², the emitter size the model card header and the process spec both state. `jc_alt_ma_um2` uses 0.1152 µm² (the subckt's `le·we` default, `sg13g2-lna`'s convention) for comparison. |
| **DC power** | `Ic·VCE + Ib·VBE` of the device. |
| **ΔTj** | The VBIC thermal node of the DUT (`selft=1`, self-heating active). |

### Source-noise reference temperature

The source resistor is `noisy=0` and its thermal noise is added analytically
at an explicit `T0`; the bench reports NFmin and NF₅₀ at **T0 = 290 K**
(IEEE; used for the row-3 screen) and **300.15 K** (this repo's porting-plan
convention), plus the T0-independent Tmin.

The per-instance resistor `temp=` convention that `sim/lna-sparam-nf`'s
fixture (and `sg13g2-lna`'s original bench) relies on is **not used**.
`testbench/resistor_noise_temp_probe.spice`, run by `run.py probe` and by
`selftest`, measures on ngspice-46:

| analysis temperature | plain 50 Ω resistor T_eff | 50 Ω with `temp=27` T_eff | `noisy=0` |
|---|---|---|---|
| −40 °C | 233.15 K | **327.15 K** | 0 |
| 16.85 °C | 290.00 K | **327.15 K** | 0 |
| 27 °C | 300.15 K | **327.15 K** | 0 |
| 125 °C | 398.15 K | **327.15 K** | 0 |

A resistor with instance `temp=T` generates thermal noise at **T + 300.15 K**
(also seen with `temp=0` → 300.15 K and `temp=−40` → 260.15 K), regardless of
the analysis temperature. `sg13g2-lna`'s issue-25 erratum attributes the same
defect to "noise computed at the analysis temperature"; that reading is
consistent with its single probe point (analysis at 54 °C = 327.15 K) but not
with this probe's four. Either way the convention is unusable, and the
method here does not depend on it: the probe also shows that, for the DUT,
the textbook noisy-50 Ω-source figure and this bench's noiseless-source
figure agree to 1e-6 dB whenever the analysis temperature equals T0, and
differ (as they should) when it does not.

### Bias-tee element values

The "ideal" bias tee here is 1 mH / 1 nF, not 1 H / 1 F. With 1 H / 1 F
(impedances spanning ~23 decades at 20 GHz) ngspice-46's `.noise` was only
self-consistent to ~1e-3 relative: the noise-parameter fit residual was
1.3e-3 and the independently simulated optimum came out 0.0018 dB *below* the
fitted minimum, which no exact linear two-port can do. With 1 mH / 1 nF the
residual is ~1e-10 and NFmin did not move (to 1e-5 dB) for a further 100× on
the choke or 1000× on the block. The fit-residual gate (1e-6) exists to catch
this class of problem.

### Simulator messages are annotations, not verdicts

At 125 °C ngspice prints thousands of recovered `singular matrix` /
`Dynamic gmin stepping failed` / pivot warnings across the whole bias range
and carries on; klt grades the same lines as warnings. In a log written with
`-o`, stdout and stderr also interleave, so a message can land next to the
wrong bias point. Excluding points on message text therefore discarded ~20 %
of the 125 °C data at random in a first fleet run, while every such point's
values were complete and passed every check above (fit residual ≤ 7.4e-7,
optimum check ≤ 1.1e-5 dB). Validity is decided from values instead: a failed
analysis leaves no vector behind (`destroy all` precedes every analysis, so a
failure is a *missing* value, never a stale one), and the bias-consistency
gate and the three noise checks catch a wrong-but-present value. Messages are
kept as a per-row `sim_messages` annotation (best effort) and tallied per
corner in the record.

The fit-residual and bias gates were set from the same data: 1e-6 rejected
in-box 125 °C points whose separately converged operating points scattered by
up to 2.6e-6 while their NF checks agreed to 4e-6 dB; 1e-4 sits well above
that scatter and well below the known-bad 1 H / 1 F case (1.3e-3).

### Which bias points count

Every point is kept in the per-point sidecar. The reported optimum of a cell
(PVT point × Nx × VCE × frequency) is the lowest NFmin over points that are

- **inside the model card's validity box** (`sg13g2_hbt_mod.lib` header:
  Ic < 3 mA·Nx, VBE 0.65–0.96 V, VCE 0.4–2.0 V, −40…125 °C, Nx 1–10), and
- **active**: fT above the frequency and MAG/MSG above 0 dB.

The second condition matters: NFmin(J_C) has a second, spurious low-current
branch — at fT ≈ 1 GHz the bare device is a nearly lossless reactive network
with no current gain at 20 GHz, and its two-port NFmin falls again (≈ 0.9 dB
in this bench's own data). That is not an amplifier operating point.

An optimum on the edge of the eligible J_C range is reported as
**constrained**, naming the side and why the next point is ineligible (e.g.
`upper: ic_high`, `lower: vbe_low`); an interior optimum is bracketed. The
J_C optimum is grid-sampled (VBE step 10 mV ≈ ×1.47 in J_C at 27 °C); the Zs
optimization at each sampled bias is exact.

## Sweep

Declared in `testbench/tb.json` `sweep.full` (and `sweep.reduced` for
smoke/selftest, which only narrows the bias axes):

- **27 outer PVT points**: `hbt_typ`/`hbt_bcs`/`hbt_wcs` × −40/27/125 °C ×
  2.25/2.50/2.75 V.
- **Inside each**: Nx ∈ {1, 4, 8} × VCE ∈ {0.6, 1.0, 1.4} V × VBE 0.60–1.04 V
  (45 points) = 405 bias points, × 3 frequencies.
- **The supply axis does not reach the DUT.** The bias is an ideal regulator
  (ideal VBE/VCE sources through ideal chokes), so the 2.25/2.50/2.75 V rail
  (`vsupply`, printed back per point) is present in every deck but physically
  inert by construction, independent of the 0.6/1.0/1.4 V VCE sweep. The
  record reports the observed invariance across supply; no supply-sensitivity
  floor is attached to it.

## Running it

```
python3 sim/hbt-kaband-characterization/run.py smoke      # 1 PVT point, reduced sweep, no evidence
python3 sim/hbt-kaband-characterization/run.py probe      # source-noise normalization probe
python3 sim/hbt-kaband-characterization/run.py selftest   # negative controls (see below)
python3 -m pytest sim/hbt-kaband-characterization/tests   # postprocessor unit tests (no simulator)
```

`sim/characterize.sh smoke|selftest|characterize` runs these together with
the repo's other benches.

`selftest` runs, on the reduced sweep: (1) the probe; (2) the three process
corners at 27 °C — every quantity (Ic, fT, NFmin, Gmax) must move; (3) the
same with every corner sabotaged to `hbt_typ` (`harness.corners.sabotage`) —
every quantity must be *identical*; (4) a deliberately invalid deck (one
required operating-point quantity reads a nonexistent field) — it must be
rejected, not recorded with a hole in it.

### Running the full grid

```
python3 sim/hbt-kaband-characterization/run.py characterize [--backend batch] [--runner-version-check warn]
```

writes three `klt sim` requests (one per supply value, each covering the 9
process × temperature corners) and submits them; on success it ingests the
returned per-corner logs into one append-only record. `ingest` refuses to
write anything unless all 27 PVT points and every bias point are present,
and unless a **local re-simulation of the nominal point** (one ngspice
process on this host) reproduces the off-host result to rounding — which is
what ties off-host numbers to the model-file checksums the record states.

Each per-corner unit is ~6 s (27 °C) to ~25 s (125 °C) of ngspice on one
core. On a shared host, send the grid off-host (`--backend batch`);
`--backend local`/`local-parallel` are for a workstation.

**Fleet/client version skew (as of 2026-10-09).** The batch fleet's runner
image runs klt 0.5.0 while the dispatch hosts run klt 0.7.0. With klt's
default `runner_version_check: enforce` every job is refused before it runs;
klt 0.5.0 itself has no batch backend; and a 0.7.0 client's model staging
rewrites `models.lib` to a staged name the 0.5.0 runner cannot resolve. The
working combination is

```
python3 sim/hbt-kaband-characterization/run.py characterize --backend batch \
    --no-stage-models --runner-version-check warn
```

i.e. the request is restricted to what klt 0.5.0 understands (a `.meas tran`
sentinel rather than an `expr` measurement — verified to run under a pinned
`uvx --from klayout-tools==0.5.0 klt` locally), the runner resolves the model
library from its own image, and the version skew is recorded in each klt
report's `environment.remote`. What makes that acceptable is `ingest`'s local
cross-check: the record is only written if this host's own simulation of the
nominal point, with the model files whose checksums the record states,
reproduces the fleet's result to rounding. Drop both flags once the runner
image is updated.

**How the sweep rides on `klt sim`.** `klt sim` runs one analysis per corner
and owns the deck's `.control` block; there is no supported way to run a
caller-owned control loop (here: a bias sweep with ~40 analyses per bias
point) per corner. The request body therefore carries its own `.control`
block, which ngspice executes before klt's; klt's own analysis is a 2 ps
transient whose `.meas` reads the supply rail as a sentinel. klt's docs call
a body-level `.control` block unsupported, so this is a documented
workaround, not a contract. If klt grows a supported form, switch to it.

Records land in `records/<record-id>.md` with sidecars
`records/<record-id>-points.csv.gz` (every row, including excluded and
out-of-model ones with reasons), `-cells.csv` (per PVT × Nx × VCE × f
optimum and fT peak) and `-best.csv` (per PVT × f best optimum and row-3
margin); per-corner ngspice logs in `corners/<record-id>/*.log.gz`; the exact
klt bodies, requests and reports in `netlist-snapshots/<record-id>/`.
Append-only: a re-run mints a new record id and never touches an old one.

## Records

- `records/20261009-095220-7f35db5.md`: the first full-grid record (27 PVT
  points, Nx 1/4/8, VCE 0.6/1.0/1.4 V, 45 VBE points, 3 frequencies). Kept
  as committed; superseded (not deleted) by the next entry.
- `records/20261009-095725-dbf8179.md`: **current**. Same simulations,
  re-ingested from the same klt reports and per-corner logs; numeric
  sidecars are identical. It supersedes the first record only because the
  report generator now states how far the reported optima sit from the run's
  worst self-heating / simulator-message / excluded-row conditions and
  carries a model-fidelity caveat in the row-3 verdict. Read this one.

## Known limits

- Bare device, ideal bias tees and terminations: no matching network (no PDK
  inductor model exists), no bias-network noise, no pads or interconnect.
- Zopt scales roughly as 1/Nx: ~1300+1600j Ω at Nx=1 and ~160+200j Ω at Nx=8
  at 27 °C — a small device is hard to noise-match from 50 Ω, and that
  matching loss lands directly on NF.
- VBIC Rev. 1.15 card, deterministic corners only; no measured noise
  parameters were available to validate the card's 20 GHz noise model.
  Self-heating is active and the validity box is an ambient limit.
- Only the declared Nx/VCE values were run; noise-optimum J_C is not
  Nx-invariant in general, so other sizes need their own run.
