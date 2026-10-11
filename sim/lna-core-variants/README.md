# lna-core-variants (issue #79)

This study tests changes to the first-stage cascode **core** of
`design/lna_stage1`. It re-runs the issue-#74 network-independent bound
(`sim/lna-match-tradeoff`) on each variant. The bound is the smallest NF that
any lossless input network can reach with S11 <= -10 dB, per frequency. It
runs over the same 27-point PVT grid (18 in rail) and the DRAFT band.

**IDEAL-ELEMENT FEASIBILITY SCREEN. NO SPEC ROW IS CLAIMED.** The matching
elements and the degeneration inductor are ideal (no PDK inductor model;
#46). The band (row 1) is OPEN. The bound is a necessary condition, not a
realized network.

The declaration is `STUDY.md` (the rationale) plus `testbench/variants.json`
(changes, variants, derived values, selection rule). The method (grids,
thresholds, probes, fixture, NF convention) is the #74 declaration
`../lna-match-tradeoff/testbench/study.json`, pinned by sha256 and executed
by `../lna-match-tradeoff/matchstudy.py`.

## Files

| file | role |
|---|---|
| `STUDY.md` | the declaration's rationale (append-only; never edited after a record) |
| `testbench/variants.json` | the machine-readable declaration: changes, variants, derivations with their values, selection rule |
| `corestudy.py` | pure logic: variant netlists (declared line edits only), device table, derivation scan decks, per-point analysis, variant summaries, selection, reproduction, gate |
| `corecollect.py` | `klt sim` requests (one per variant x supply, 9 units, batch), ingest, local single-point controls, append-only record writer |
| `run.py` | CLI: `plan`, `derive`, `netlists`, `collect` |
| `tests/` | unit tests and the whole collection against the #74 closed-form fake klt (no simulator) |

## Running it

```
python3 sim/lna-core-variants/run.py plan
python3 sim/lna-core-variants/run.py derive          # local single-point scans; values already declared are skipped
python3 -m pytest sim/lna-core-variants/tests -q
python3 sim/lna-core-variants/run.py collect --dry-run
python3 sim/lna-core-variants/run.py collect [--workdir DIR] [--runner-version-check warn] [--no-stage-models]
```

`collect` submits 24 requests (8 variants x 3 supplies) on `--backend batch`.
It then runs two local single-point controls:

- the #74 normalization pad at 27 C;
- the frozen core at the nominal point, compared with the fleet's unit.

It then checks that `core0` reproduces the #74 bound at all 27 points, runs
the gate, and writes one record. A failed batch submit exits non-zero with
no record. It never falls back to a local grid. `--workdir` resumes: any
request whose report already exists is reused.

## klt friction

This is the same gap as #74. `klt sim` has no swept two-port
(S-parameter/noise) acquisition and no per-frequency result channel. So
each body carries its own `.control` block, and the printed tables are
parsed from each unit's `ngspice.log`. It is filed generically as
2AMLogic/klayout-tools#3029.
