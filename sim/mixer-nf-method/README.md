# sim/mixer-nf-method: mixer SSB noise figure without pnoise (feasibility)

Issue [#27](https://github.com/2AMLogic/sg13g2-sat-rx/issues/27). This is a bounded
methodology investigation at one nominal point (`hbt_typ` / 27 °C / 2.50 V, the existing
single-`npn13G2` placeholder). It asks whether ngspice can measure an active mixer's SSB
noise figure by transient noise. It designs no mixer and edits no spec row. **No record
here is, or may be read as, evidence for `spec/target-spec.md` row 10 (mixer SSB NF) or
row 12 (cascade NF).**

## Outcome: `MODEL_ABSENT`

| Item | State |
|---|---|
| Intrinsic HBT noise (shot / terminal-resistance thermal / flicker) during `.tran` | **absent** in ngspice-46: probe, source and manual agree |
| Resistor thermal noise during `.tran` | **absent** |
| Explicit `TRNOISE` source injection | works, but it is an external source. It cannot qualify active-device NF (gate 2) |
| PSS / pnoise | absent (`pss: no such command`; no pnoise in the source tree) |
| Active-mixer SSB NF of the placeholder | **not measured, and no number is reported** |
| Estimator (PSD/ENBW normalisation, SSB/image accounting, Y-factor, intervals, gates) | implemented and tested on analytic fixtures only |

The record is `records/<id>-MODEL_ABSENT.md` (+ `.json`), and the full probe logs are in
`probe-logs/<id>/`. Gate 2 of the issue stops the active-mixer path at this point.
Controls 4(b)/(c) and the step-5 convergence campaign were therefore never run, because
there is no coverage for them to qualify. The conversion-matrix alternative, which needs
periodic transfer extraction, source covariance and sideband convergence, is deferred to
separate work, as the issue directs.

## Capability inventory (executable `ngspice-46`, model `npn13G2` VBIC level 9)

Pins: `ngspice-46` at `~/.local/bin/ngspice` (sha256 is in the record);
IHP-Open-PDK `.fetched-version` 0.3.0, `cornerHBT.lib` section `hbt_typ` →
`sg13g2_hbt_mod.lib` `npn13G2_NX_vbic` (`level = 9`, VBIC rev 1.15 card, `kfn/afn/bfn`
flicker parameters present). File hashes are in each record.

| Mechanism | in `.tran` | in `.noise` | Evidence |
|---|---|---|---|
| HBT collector shot (`_ic`, `_iccp`) | unsupported | supported | probe A/B; source |
| HBT base shot (`_ib`, `_ibep`) | unsupported | supported | probe A/B; source |
| HBT terminal-resistance thermal (`_rb _rbi _rbp _rc _rci _re _rs`) | unsupported | supported | probe A/B; source |
| HBT flicker (`_1overfbe`, `_1overfbep`) | unsupported | supported | probe A (determinism); source |
| ib/ic noise correlation | unsupported | unsupported | source: every VBIC generator is evaluated independently |
| Resistor thermal | unsupported | supported | probe B (1k/1k divider flat); source |
| External `TRNOISE` (V/I source) | supported | n/a | probe C; manual 4.1.7 |
| PSS / pnoise | n/a | unsupported | probe E; manual 11.3.12; source |

Official references:

- *ngspice User's Manual v46*, <https://ngspice.sourceforge.io/docs/ngspice-46-manual.pdf>
  (sha256 `b5bc7c4f…f766`):
  - 4.1.7: "The noise generators are implemented into the independent voltage (vsrc)
    and current (isrc) sources."
  - 11.3.11: transient noise is "added to your circuits" through those sources. Its
    open questions include "how to generate noise from a transistor model" and
    "calibration of noise spectral density".
  - 11.3.12: `.PSS` is "Experimental code, not yet made publicly available".
  - 1.2.8: PSS is the basis of "PAC or PNoise" (neither of which exists).
- Source at tag `ngspice-46` (`ebdaf58e…`):
  - `devices/vbic/vbicnoise.c` defines the 13 generators.
  - `VBICnoise` is reached only through `DEVnoise`. That is called only from
    `analysis/cktnoise.c` (`.noise`, via `noisean.c`) and `span.c`/`noisesp.c` (`.sp`
    noise).
  - `vbicload.c` and `res/resload.c` (the `.tran` load routines) have no noise term.
  - `TRNOISE` lives only in `vsrc/` and `isrc/`.
  - `dcpss.c` is built only with `--enable-pss`.
  - The structure is the same at `ngspice-47` (`a80f6e3e…`). That was checked from the
    source only; the 47 binary was not run.

How the probe separates "absent" from "too small to see" (`probe/capability_probe.spice`
is one `ngspice -b` run of the placeholder included verbatim, plus two disjoint helper
circuits):

- **A**: LO on, two consecutive `.tran` runs in one process. The collector waveforms are
  bit-identical, with a maximum difference of 0 over 24 008 points. Any RNG-driven
  generator, however small, would make them differ. The RNG stream does advance: probe C
  shows the `TRNOISE` draw changing run to run.
- **B**: LO off. The settled collector peak-to-peak is 2.7e-8 V, deterministic settling
  only. `.noise` about the same DC point puts **2.0 mV rms** of HBT noise on that node
  over 250 MHz to 500 GHz, which is the band the 4 ns window and 1 ps step resolve.
  `.tran` is about 98 dB short. The 1k/1k divider is exactly flat, against an expected
  2.0 mV rms of thermal noise.
- **C**: positive control. `TRNOISE(1m 1p)` into 50/50 Ω is visible, with a window rms of
  about 0.41 mV. That matches 0.5 mV·√(2/3), the rms of a linearly interpolated white
  sequence. `setseed` did **not** reproduce the draw, which is consistent with
  [klayout-tools#2963](https://github.com/2AMLogic/klayout-tools/issues/2963).
- **D**: per-mechanism `.noise` sizing (the numbers above). This step sizes the probe
  only. It is not used as evidence of coverage, and it does not linearise the
  LO-pumped mixer.
- **E**: `pss` → `pss: no such command available in ngspice`.

## Definitions (the method, if a capable simulator existed)

These conventions are enforced by `nfmethod.py` and tested in `tests/test_nfmethod.py`.

- **Sideband convention.** IEEE SSB:
  `F_SSB = N_out / (k·T0·B·G_w)`.
  - `N_out` is the delivered IF noise power in bandwidth `B` with the source termination
    at T0 in **both** the wanted and the image sideband.
  - `G_w` is the available-power gain from the wanted RF sideband
    (`f_LO + f_IF`, low-side LO) to the delivered IF power.
  - Image noise is always part of `N_out`. The image gain `G_i` must be declared
    (`0.0` for an image-rejecting front end). An undeclared image gain, or a missing
    image-source term, raises.
  - A DSB figure, `N_out / (k·T0·B·(G_w+G_i))`, is reported only beside the SSB figure
    and labelled DSB. It is never substituted for SSB. For equal sideband gains the two
    differ by exactly 3.01 dB.
- **T0 = 300.15 K**, the same as the corrected LNA bench (issue #22). A source simulated
  at another temperature is re-referenced to T0 in each sideband separately.
- **Contributions.** `N_out` is split into `source_wanted`, `source_image`, `dut` and
  `load`. Their sum must equal the measured `N_out`, so a silently dropped image term
  fails the accounting.
- **Y-factor.** The hot/cold temperature change is applied in both sidebands (broadband
  termination). This gives `Te_DSB = (T_hot − Y·T_cold)/(Y − 1)`, which is converted to
  the SSB reference with `F_SSB = (1 + G_i/G_w)(1 + Te_DSB/T0)`.
- **Known answer** (control a). A matched attenuator of loss L at temperature `T_att`,
  ahead of a noiseless mixer, gives `F_SSB = (1 + G_i/G_w)(1 + (L−1)·T_att/T0)`. For
  equal sidebands and `T_att` = T0 this is `2L` (3.01 dB + L_dB).
- **PSD.** This is a one-sided periodogram: `psd = c·|X_k|²/(fs·Σw²)`, with `c = 2`
  except at DC and Nyquist.
  - A Parseval check rejects any PSD whose integral is not the record variance within
    5 %. That catches two-sided, window-uncorrected and mis-scaled estimates.
  - Hann ENBW = 1.5 bins (rect 1.0).
  - Band power is `Σ psd·df` over bins inside `[f_lo, f_hi]`. The band must lie strictly
    inside (0, fs/2) and span at least 4 ENBW.
- **Sampling.** The output is uniformly resampled (`linearize`) after a settling
  discard of at least 10 time constants of the slowest bias/coupling network, and the
  discard is recorded. The step `dt` must hold at least 20 points per period of the
  highest significant tone, so fs/2 sits well above every RF/LO product that can alias
  into the IF band. A `TRNOISE` source with step `NT` has a sinc⁴(f·NT) PSD (linear
  interpolation). `NT ≤ 1/(10·f_RF,max)` keeps the droop at 0.07 dB or less, and the
  droop must be corrected separately at the wanted and image frequencies.

## Uncertainty and run length

- Seeds: at least 8 independent ones.
- Interval: Student-t 95 % on the per-seed linear F,
  `h = t₀.₉₇₅,ₙ₋₁·s/√n`. The dB half-width is `max(10log((m+h)/m), 10log(m/(m−h)))`
  and must be **≤ 0.25 dB**, which requires `h/m ≤ 0.0559`.
- Per-seed scatter: a band-power estimate over `B` from a record of retained length `T`
  has relative standard deviation `1/√K_eff`.
  - Rectangular window: `K_eff ≈ B·T`.
  - Hann: `K_eff ≈ B·T/1.94`. Adjacent-bin power correlations of 4/9 and 1/36 give the
    1.94; a numerical check gave 1.86 at 205 bins.
- Required length: with n = 8 (t = 2.365) the gate needs `K_eff ≥ 224`, i.e.
  `B·T ≥ 435` with Hann. Allow 2× margin for the χ₇ scatter of `s`: `B·T ≥ 900`.
  - Example: a 100 MHz IF integration band needs T ≥ 9 µs retained per seed. At 2.4 ps
    steps (20 points per period at 21.2 GHz) that is about 3.8 M points per seed, before
    the duration-doubling and timestep-halving checks.
- Convergence: double the retained duration and, separately, halve the maximum
  timestep. Each change must be ≤ 0.25 dB. At most three duration doublings from the
  recorded initial duration are allowed; failing that, the status is `UNCONVERGED`.
  Bandwidth and seed count are recorded with every estimate.
- These are methodology qualification limits. They are not row-10 acceptance limits.

## Stopping gates and statuses (`nfmethod.decide_status`)

1. Runner or executable unavailable → `CAPABILITY_UNAVAILABLE`. This status can never
   establish model absence.
2. Any of `REQUIRED_TRAN_MECHANISMS` not *supported* in LO-driven `.tran` (unsupported
   **or unknown**) → `MODEL_ABSENT`. No external surrogate is substituted.
3. Analytic known-answer control off by more than 0.25 dB, or not run → estimator defect.
   The code raises and **no record** is written.
4. Any of the following → `MODEL_ABSENT`:
   - the LO-off HBT `.tran`-vs-`.noise` control misses by more than 0.25 dB;
   - the omission control does not demonstrate a failure;
   - there is no LO-driven internal-noise coverage evidence.
5. Seeds < 8, half-width > 0.25 dB, a duration or timestep change > 0.25 dB (or not
   run), more than 3 doublings, or no recorded bandwidth → `UNCONVERGED`.
6. Only when all of the above pass → `METHOD_VALIDATION`. That is still methodology
   evidence, never compliance.

A capability probe alone can never produce `METHOD_VALIDATION`; `run_probe.py` refuses.

## Campaign path

A seed/duration/timestep campaign exists only past gate 4. It would be expressed as a
`klt sim` request, with seeds as `monte_carlo` samples, submitted to the batch fleet
(`KLT_SIM_BACKEND=batch`) in the same way as `hbt-kaband-characterization/run.py`. It
would not be run as a local loop. Before any such campaign,
[klayout-tools#2963](https://github.com/2AMLogic/klayout-tools/issues/2963) must be
resolved: `TRNOISE` streams are not governed by the seed contract, and probe C confirms
that `setseed` does not reproduce the draw. No campaign was submitted for this record.

## Upstream

The demonstrated gap is an **ngspice capability**: there is no device or resistor noise
in `.tran`, and no PSS/pnoise. klt cannot fix that. The **`klt sim` orchestration** part
is that its contract and envelope do not disclose this, so a transient-noise request
passes silently without intrinsic noise. That part is filed generically, with a PDK-free
reproducer, as
[2AMLogic/klayout-tools#2985](https://github.com/2AMLogic/klayout-tools/issues/2985).

## Reproduce

```
pip install -r requirements-test.txt                          # numpy + pytest (use a venv)
python3 -m pytest sim/mixer-nf-method/tests -q                # no simulator
python3 sim/mixer-nf-method/run_probe.py --no-write           # one local ngspice -b, prints the record
python3 sim/mixer-nf-method/run_probe.py                      # appends a new record + probe-logs/<id>/
python3 sim/mixer-nf-method/run_probe.py --reparse probe-logs/<id>   # re-derive status from a committed log
```

Records are append-only. Files are created exclusively, and a re-run writes a new id.
`sim/mixer-conversion-iip3`'s gain/IIP3 bench and records are untouched; its fragment is
`.include`d read-only.

## CI coverage

CI's `harness-tests` job runs `sim/mixer-nf-method/tests/test_nfmethod.py` as its own
named step after `pip install -r requirements-test.txt`. These are analytic fixtures for
the estimator's methodology (PSD/Parseval, SSB/image accounting, status gates). Passing
them says nothing about active-device noise, and does not qualify spec rows 10/12.

`.github/scripts/check_evidence_formats.py` validates the record pair and the
`probe-logs/<id>/` package (all four files present, `inventory.json` equal to
the record's inventory) and protects `probe-logs/` append-only; see the
top-level README. A run that crashes between writing logs and records leaves an
orphan `probe-logs/<id>/` that fails format CI until its record exists.
