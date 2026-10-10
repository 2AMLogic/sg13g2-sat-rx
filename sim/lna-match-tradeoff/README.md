# lna-match-tradeoff (issue #74)

This study maps NF against input return loss against gain for ideal lossless
input networks on the frozen `design/lna_stage1` cascode, at the declared PVT
grid.

**IDEAL-ELEMENT FEASIBILITY SCREEN. NO SPEC ROW IS CLAIMED.** Every network
is ideal L/C: no PDK inductor model exists, and spec row 1 (the band) is
OPEN. Each threshold traces to a ratified row (2, 3, 4, 6, 17), but it is
used as a screen, not as compliance. A candidate that passes is optimistic
and conditional. It still depends on real passive loss (#46), the band
decision, and second-stage loading.

The declaration is `STUDY.md` (rationale) plus `testbench/study.json`
(machine-readable: grids, thresholds, tolerances, shortlist rule, the frozen
candidate list, the nominal derivation). It was committed before any record.

## Status: one record, no tested input match meets the joint screen

Record: `records/20261010-042556-dae8519.md`. Reading:
`design/lna_match_tradeoff.md`.

**Screen.** All 51 declared networks ran at the nominal point, as one
local single-unit `klt sim`.

**Corner campaign.** The shortlist (the baseline plus the lowest-NF,
best-S11 and lowest-S11-with-NF<=2.5 candidates) plus 9 probes ran at all
27 PVT points on the batch fleet. The jobs were `klt-sim-ae96e48753bb`,
`klt-sim-3f9d98f926a0` and `klt-sim-f5d0a72c5d2b`. The runner was klt 0.5.0
against client 0.7.0, so the run used `--runner-version-check warn` and
`--no-stage-models`, the known skew documented in
`../mixer-topology-feasibility/README.md`. The fleet's models_lib_sha256
equals this host's, and the fleet-vs-local nominal cross-check is exact.

**Findings.**

- No L-section reaches S11 <= -10 dB. The best is -6.0 dB at nominal.
- The network-independent bound shows that at 8 of 18 in-rail points
  (every 125 C point, and hbt_wcs/27 C) no lossless input network can meet
  NF <= 2.5 dB with S11 <= -10 dB.
- At hbt_wcs/125 C the core's own Fmin exceeds 2.5 dB at the top of the
  band.

**Next decision.** It is a core change, not a network change, and it is
filed as #79.

## Files

| file | role |
|---|---|
| `STUDY.md` | the declaration and its rationale (append-only; never edited after a record) |
| `testbench/study.json` | the machine-readable declaration and frozen candidate list |
| `matchstudy.py` | pure logic: family synthesis, DUT text, deck text, log parsing, extraction, noise-parameter fit, network-independent bound, screen, shortlist, gate, conclusion |
| `localrun.py` | ONE local `ngspice -b` at ONE PVT point (derivation, smoke controls) |
| `matchcollect.py` | `klt sim` requests (screen: single unit, local; corners: 3 x 9 units, batch), ingest, baseline reproduction, cross-check, append-only record writer |
| `run.py` | CLI: `plan`, `derive`, `declare`, `smoke`, `collect` |
| `tests/` | unit tests and a closed-form fake `klt sim` (`matchfakes.py`); no simulator |

The checker support is the `lna-match-tradeoff` adapter in
`.github/scripts/check_evidence_formats.py`. Its negative controls are in
`.github/scripts/tests/test_check_lnamatch_adapter.py`.

## Running it

```
python3 sim/lna-match-tradeoff/run.py plan
python3 sim/lna-match-tradeoff/run.py smoke     # local, single points, records nothing
python3 -m pytest sim/lna-match-tradeoff/tests -q
python3 sim/lna-match-tradeoff/run.py collect --dry-run
python3 sim/lna-match-tradeoff/run.py collect [--workdir DIR] [--runner-version-check warn] [--no-stage-models]
```

`collect` runs two phases:

- **Screen.** One single-unit `klt sim` at the nominal point with every
  declared network, using `--screen-backend local`.
- **Corners.** The declared shortlist plus the probes, one request per
  supply with 9 units each, on `--backend batch`.

A failed batch submit makes `collect` exit non-zero without a record, and it
never falls back to a local grid. `--workdir` resumes: any request whose
report already exists is reused.

## What the smoke checks

The smoke runs single local points:

- **Pad control.** A matched 6.02 dB pad at 27 C and at -40 C, checked
  against the closed form F = 1 + (2L - 1) T/T0. This is the bench's
  noisy-load convention.
- **Baseline reproduction.** The baseline against
  `sim/lna-sparam-nf/records/20261010-012923-6cad7fc` at the nominal point.
- **Bound and model check.** The network-independent bound, with its
  model-consistency check.
- **Cross-check and op invariance.** The alterparam deck against a deck
  with literal values, and the operating point's invariance to the input
  network.
- **Process sensitivity.** hbt_wcs must move the baseline.

## klt friction

`klt sim` has no swept two-port (S-parameter/noise) acquisition and no
per-frequency result channel. Each request therefore works around it:

- it carries its own body-level `.control` block;
- a sentinel `tran` `.meas` keeps the request valid;
- `matchcollect.py` parses the printed tables out of each unit's
  `ngspice.log`.

`matchstudy.parse_log` refuses a unit whose blocks are missing, and the gate
needs every declared cell, so a silently failed body cannot pass. Filed
generically as 2AMLogic/klayout-tools#3029. The fleet runner/client version
skew is already tracked upstream (klayout-tools#2851, #2877, #2901).
