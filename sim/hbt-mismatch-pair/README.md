# sim/hbt-mismatch-pair: Monte Carlo mismatch-card METHOD probe on a matched npn13G2 pair

Issue [#186](https://github.com/2AMLogic/sg13g2-sat-rx/issues/186). A bounded, non-claiming
method qualification: can a `klt sim` **`monte_carlo`** request run the pinned SG13G2 HBT
mismatch/stat cards at all — on the batch fleet, reproducibly under a fixed seed, with a
local unit agreeing with the fleet unit of the same seed — measured on a known-answer
matched pair, independent of any mixer topology.

**This bench is METHOD evidence only.** It is **not** evidence for
[`spec/target-spec.md`](../../spec/target-spec.md) row 15 (LO leakage) or any other row;
[`spec/row-coverage.json`](../../spec/row-coverage.json) row 15 keeps its verdict and
cites this bench as a note only. The pair is a method observable, not a mixer, and no
number in `records/` is a design figure. Row 15's Monte Carlo bench remains the
mixer-conversion bench, gated on the mixer decision (#68).

## Why a matched pair, and why these three corners

The bench (`bench/pair_body.spice`) is a differential pair of `npn13G2` instances with
equal resistive loads, both bases tied to one bias. Its only measured quantities are
known-answer observables: collector currents through the loads, their ratio `m_ratio`
(exactly 1.000000 on a perfectly matched pair) and the output offset `m_off` (exactly 0 V).
The three corner sections of `cornerHBT.lib` then separate the randomness mechanisms the
two cards implement — see the record's "Cards read" table for the full reading:

| corner | card mechanism | expected on this pair |
|---|---|---|
| `hbt_typ` | none (`sg13g2_hbt_mod.lib` has no mismatch draw) | ratio exactly 1 in every sample — the nominal known answer |
| `hbt_typ_stat` | `sg13g2_hbt_stat.lib`: **global** `gauss()` draws, one value per run shared by both devices | the variation cancels in the matched pair: ratio stays exactly 1 while the absolute currents move — the negative control proving the bench measures mismatch, not noise |
| `hbt_typ_mismatch` | `sg13g2_hbt_mod_mismatch.lib`: **per-instance** `agauss` area draws (mean 1, 10% 1σ) | the only corner allowed to spread: a current-ratio σ of order 10%·√2 ≈ 14% |

A run that violates any of these three expectations is a method failure
(`MC_METHOD_CONTROL_FAIL`), never a circuit result.

## What is gated, and the statuses

| Status | Meaning |
|---|---|
| `MC_METHOD_WORKS` | all units returned; all three known-answer gates pass; the fixed-seed rerun reproduces per sample; the local unit agrees with the fleet unit (number stated in the record) |
| `MC_METHOD_CONTROL_FAIL` | a known-answer gate failed (nominal not symmetric / stat spread the pair / mismatch not sampled) |
| `MC_METHOD_REPRODUCIBILITY_FAIL` | gates pass but the fixed-seed rerun differs beyond `mcpair.REPRO_TOL` |
| `MC_LOCAL_AGREEMENT_FAIL` | gates pass but the local-vs-batch unit of the same seed disagrees beyond `mcpair.LOCAL_AGREEMENT_TOL` |

Outcomes that are **not records** (`run_probe.py` writes nothing for them):

- no klt client on this host — reported on stderr, exit 1;
- klt refused the request outright — the error is reported, exit 3;
- a corner returned fewer units than `monte_carlo.n` (older runner silently ignoring the block) — detected, never averaged over; `ingest_error.txt` is written, exit 1.

None of these is `METHOD_VALIDATION` of any spec row.

## Cold start

```
python3 -m pytest sim/hbt-mismatch-pair/tests -q            # no simulator, no PDK (stdlib unittest)
python3 sim/hbt-mismatch-pair/run_probe.py --no-write       # all three legs, print only
python3 sim/hbt-mismatch-pair/run_probe.py                  # all legs, append a record
python3 sim/hbt-mismatch-pair/run_probe.py --skip-rerun --skip-local --no-write
                                                            # primary fleet leg only
python3 sim/hbt-mismatch-pair/run_probe.py --reparse probe-logs/<id>
                                                            # re-derive the status from the committed
                                                            # per-sample JSON (no simulator)
python3 sim/hbt-mismatch-pair/run_probe.py --sabotage stat_noise --reparse probe-logs/<id>
                                                            # negative control: classification MUST
                                                            # degrade (never writes a record)
```

Legs (each reuses its own report, so an interrupted probe resumes):

1. `mc` — the primary request (`monte_carlo {n, seed, vary: both}` over the three corners
   at 27 °C) on `--backend` (default `batch`: the shared Spot fleet path per host rules).
   A failed submit writes nothing and is reported, never rerun as a local grid.
2. `rerun` — the same request bytes a second time: the fixed-seed reproducibility gate.
3. `local` — same corners, same order, `n=1`, local backend: the agreement unit. klt
   derives each sample's seeds from the request alone, so fleet unit 0 and local unit 0
   are the same draw; any difference is build/backend, and the record states it as a
   number (cross-build by construction: the local leg runs this host's ngspice, the fleet
   leg the runner image's — both majors are in the record, the #135/#181/#165 precedent).

The `sim/harness/pdkartifact.py` model-integrity gate runs before any submit. It does
NOT require the pinned ngspice major locally (there is deliberately no local ngspice
dependency in the batch legs; the local agreement leg is cross-build on purpose).

## Seed handling (what the record states)

klt derives per-sample seeds from the request (`_derive_mc_seed(seed, axis,
corner_index, sample_index)`) and seeds ngspice with `.options seed=<rndseed>` **before**
the model cards parse; every returned unit echoes its seed block. The schedule is
version-stable between the fleet runner (klt 0.5.0) and this client (0.7.0): both tags
carry the identical `_derive_mc_seed` (diffed before the run). One method note the cards
force: neither IHP card references klt's `mc_process_seed`/`mc_mismatch_seed` params, so
with these cards all per-sample randomness is ngspice's single RNG stream — klt's
`vary:` axis separation cannot decorrelate card draws, only its seed bookkeeping reports
per-axis seeds. Tool friction is filed generically at `2AMLogic/klayout-tools`.

## Evidence layout

Records are append-only (exclusive create; a re-run writes a new id):

```
probe-logs/<id>/pair_body.spice      the netlist exactly as submitted (sha256 in the record)
probe-logs/<id>/request_mc.json      the primary request (monte_carlo block echoed by klt)
probe-logs/<id>/request_local.json   the local agreement request (n=1)
probe-logs/<id>/report_{mc,rerun,local}.json   the klt JSON reports (per-unit seed blocks)
probe-logs/<id>/samples_{mc,rerun,local}.json  every unit's parsed m_* values (the
                                               --reparse source; raw logs kept for
                                               samples 0-2 in logs/)
probe-logs/<id>/stats.json           the gate/distribution findings
records/<id>-<STATUS>.md/.json       the record
```

The per-sample values are committed for every unit of every leg, so a fixed-seed rerun
can be diffed against the record without any simulator.
