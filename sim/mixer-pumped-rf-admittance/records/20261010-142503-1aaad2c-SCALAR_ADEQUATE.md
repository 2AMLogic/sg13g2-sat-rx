# mixer-pumped-rf-admittance record 20261010-142503-1aaad2c-SCALAR_ADEQUATE

- **Status: SCALAR_ADEQUATE**
- **Scope: method-feasibility evidence only.** One nominal point of an exploratory
  placeholder DUT. This record asks whether the LO-on (pumped) RF-port admittance can be
  extracted with stated limits. It makes
  **no claim of `spec/target-spec.md` row 5 compliance**,
  reports no mixer or cascade noise figure, selects no topology, matching network or LO
  drive, and neither ratifies nor reverses DR-0004.
- Nominal point: `hbt_typ` / 27 C / VDD = 2.50 V; placeholder
  `sim/mixer-conversion-iip3/testbench/mixer_ce_placeholder.spice` (included verbatim), LO
  18.45 GHz at the placeholder's own `vlo` = 0.08 V EMF (a probe setting, not a qualified drive;
  issue #68). Sidebands f_u = 19.45 GHz, f_l = 17.45 GHz (IF 1 GHz).
- Port: node `prf` looking into `Cin_rf`, terminated by the placeholder's own 50 ohm `Rrf`; current
  positive into the mixer. The matrix is conditional on that termination at every other mixing
  frequency.

## Reasons

- kappa 0.000373 + uncertainty 0.00042 < 0.05: a scalar sideband admittance describes the port at this point

## Pumped port admittance (retained window, primary phases p1/p2)

I_u = Y_uu V_u + Y_ul conj(V_l);  I_l = Y_lu conj(V_u) + Y_ll V_l

| element | magnitude / phase |
|---|---|
| `Y_uu` | 39.26 mS / 37.70 deg |
| `Y_ul` | 0.01464 mS / 68.29 deg |
| `Y_lu` | 0.01283 mS / 69.58 deg |
| `Y_ll` | 37.73 mS / 39.34 deg |

- kappa = max(|Y_ul|/|Y_uu|, |Y_lu|/|Y_ll|) = 0.000373; uncertainty 0.00042;
  scalar bound 0.05
- Model-free discriminator: the scalar I/V of phase p1 and phase p2 differ by
  0.0007697 (relative)

## Numerical checks (DUT)

| check | result | detail |
|---|---|---|
| halving | pass | {'rel_change': 3.010519757164502e-06, 'tol': 0.01} |
| window | pass | {'rel_change': 3.95122663792825e-06, 'tol': 0.005} |
| timestep | pass | {'rel_change': 0.0004036845868081623, 'tol': 0.005} |
| conditioning | pass | {'cond_max_over_sets': 1.0318204925191525, 'tol': 10.0} |
| response_to_baseline | pass | {'min_ratio': 22476.711436335587, 'tol': 10.0} |

## Known-answer controls (same runs, same extraction)

| check | result | detail |
|---|---|---|
| rc.uu | pass | {'expected': [0.03612937189220536, 0.011825538565449599], 'measured': [0.03613797076689063, 0.011813627031469006], 'mag_rel_err': 0.00011757024305203423, 'phase_err_deg': 0.021091018909061177} |
| rc.ul | pass | {'expected': [0.0, 0.0], 'measured': [-3.0133038217375417e-08, -1.7719425320449506e-08], 'relative_to_diagonal': 9.194337460850679e-07, 'tol': 0.005} |
| rc.lu | pass | {'expected': [0.0, 0.0], 'measured': [3.796218471844855e-08, 1.4735294153783011e-08], 'relative_to_diagonal': 1.0835501868171094e-06, 'tol': 0.005} |
| rc.ll | pass | {'expected': [0.035301468381128555, 0.012878861183401393], 'measured': [0.03530972724983219, 0.012868948283955014], 'mag_rel_err': 0.00011611206458028711, 'phase_err_deg': 0.01851289870552364} |
| rc.numerics | pass | {'failed': []} |
| rc.classification | pass | {'expected': 'SCALAR_ADEQUATE', 'got': 'SCALAR_ADEQUATE'} |
| md.uu | pass | {'expected': [0.02, 0.012220795422464296], 'measured': [0.020000001127182865, 0.0122359980679647], 'mag_rel_err': 0.00033839228607535077, 'phase_err_deg': 0.031699892093314475} |
| md.ul | pass | {'expected': [0.004596266658713868, 0.0038567256581192354], 'measured': [0.00459624272466747, 0.0038567329879819526], 'mag_rel_err': 2.270493593470313e-06, 'phase_err_deg': 0.00020053099564165677} |
| md.lu | pass | {'expected': [0.004596266658713868, 0.0038567256581192354], 'measured': [0.004596247533407243, 0.003856736243936655], 'mag_rel_err': 1.3077279829021293e-06, 'phase_err_deg': 0.0001948318480913258} |
| md.ll | pass | {'expected': [0.02, 0.010964158361028379], 'measured': [0.019999985747701617, 0.010975164881521246], 'mag_rel_err': 0.00023151838045110118, 'phase_err_deg': 0.024256566598268137} |
| md.numerics | pass | {'failed': []} |
| md.classification | pass | {'expected': 'MATRIX_REQUIRED', 'got': 'MATRIX_REQUIRED'} |

## Thresholds (declared before the DUT result)

`sim/mixer-pumped-rf-admittance/thresholds.json` sha256 `d6736f98e3535936c6c1055907d0c7a0a184038cd67a9316605471f57521f69b`, last changed in commit `e853ece742175050afa4b57f01c2f38ac26b12e2`.

| threshold | value |
|---|---|
| `control_mag_rel_tol` | 0.005 |
| `control_phase_tol_deg` | 0.3 |
| `control_null_rel_tol` | 0.005 |
| `cond_max` | 10 |
| `halving_rel_tol` | 0.01 |
| `window_rel_tol` | 0.005 |
| `timestep_rel_tol` | 0.005 |
| `response_to_baseline_min` | 10 |
| `kappa_scalar_max` | 0.05 |

## Provenance

- ngspice: `/home/ubuntu/.local/bin/ngspice` -- ngspice-46 : Circuit level simulation program, sha256 `c874869b16dc8a31cfa9d37d2b90a2a9e0e5b996f8e2535db89eb82855072931`
- PDK: `/home/ubuntu/share/pdk/ihp-sg13g2` (.fetched-version 0.3.0), section `hbt_typ`;
  cornerHBT.lib `bae3d705445de8d6b8de4aa798a0e3e5e7cab617d6495d9c56473bc5377de462`, sg13g2_hbt_mod.lib
  `ae9288f885dd30fab24b07ed1e7e02e69eac9154022a0a6da576985183b0bd79`; npn13G2 (subckt) -> npn13G2_NX_vbic, VBIC level=9, Nx=4 in the placeholder
- Model integrity gate (`sim/harness/pdkartifact.py`, run before the simulator): OK; install marker '0.3.0' recorded as provenance (not an integrity check); IHP model closure (4 files) matches the pin at 5cccb161f749 (https://github.com/IHP-GmbH/IHP-Open-PDK)
- Placeholder sha256 `e2cd2af3fd9aa34b9c36dde453c7919abbec69fe9f675f1848657a5a85c7a74d`; pdk-artifact.json sha256 `2ca42a292eeef18dc0da32004bb2cfa66dfead21c73b4f77d4609d60dadeabf1`
- Repo commit `1aaad2c970e0e3a66dcd2919d3d0f92a1a42b9de` (dirty: False); host loom-worker-2
- Probe logs: `probe-logs/20261010-142503-1aaad2c/`
- Command: `python3 sim/mixer-pumped-rf-admittance/run_probe.py`
