# sg13g2-sat-rx

A Satellite-band receive front end (LNA + mixer) on the [IHP SG13G2](https://github.com/IHP-GmbH/IHP-Open-PDK) open PDK,
designed by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the open-source
flow — xschem + ngspice, with layout, DRC, and LVS through klayout-tools.

It is the per-element receive chain for an open-source satellite antenna
array: a SiGe HBT low-noise amplifier followed by a downconversion mixer, so
that every antenna element gets its own quiet, linear path from the sky down
to an intermediate frequency where beam steering can happen.

## Status

**Just opened, specification phase.** Nothing is designed yet, nothing has been
taped out, and nothing has been measured.

Deliberately not being built yet:

- **The antenna elements and the array itself.** Those are board-level or
  ceramic objects, not silicon. This repo is the chip behind one element.
- **The analog-to-digital converter and the beamformer.** Which side of the
  mixer the beam steering lives on — RF phase shift per element, LO-phase
  shifting at the mixer, or IF/digital beamforming behind an ADC — is a
  recorded design decision that waits on the LNA and mixer benches. It is not
  a default and nothing here assumes one answer. The three options, what each
  would ask of this chip, and the criteria that will decide it are recorded in
  [`spec/decision-records/0002-beamsteering-partition.md`](spec/decision-records/0002-beamsteering-partition.md)
  (status: *deferred*, deliberately).
- **A ratified receive band.** The draft commits to the Ka-band satellite
  downlink, 17.7–21.2 GHz, because that is where this PDK's SiGe HBTs
  (`npn13g2`: fT min 300 / target 350 GHz, fmax min 400 / target 450 GHz,
  per the PDK process spec §3.1) are decisive. The LNA matching network, the
  mixer's LO range, and the IF plan all follow from that row — and it is the
  one row ratification may still move (to the Ku-band downlink,
  10.7–12.75 GHz) if open-tool EM verification at 20 GHz proves the binding
  constraint. The argument, the Ku fallback, and the explicit trigger that
  would move the band are recorded in
  [`spec/decision-records/0001-band-selection-ka-vs-ku.md`](spec/decision-records/0001-band-selection-ka-vs-ku.md)
  (status: *proposed*, not ratified).

The spec's [first ratification pass](spec/decision-records/0003-target-spec-first-ratification.md)
(merged via the ratification-via-PR two-key path) binds **eleven rows as
targets**; nine — including the band row itself, still gated on DR-0001 and
allocation-edge verification — stay explicitly open. Until benches exist
nothing can be claimed *met*, so the near-term work is still testbench
methodology: what ngspice can and cannot measure for S-parameters, noise
figure, and conversion gain on this PDK, stated with every assumption.

## Built agent-native

Every specification, decision record, testbench, and line of documentation in
this repo is produced by AI agents working from a ratified spec and an
append-only evidence trail — not human-authored work that agents merely
assisted with. Verification is the product: every claim traces to a recorded
result. Where the agents hit friction with the open-source tooling — most often
[klayout-tools](https://github.com/2AMLogic/klayout-tools) — that friction gets
filed as a public issue against the tool itself, so the fix benefits everyone
using IHP SG13G2, not just this repo.

## Target specification

**The target spec lives in [`spec/target-spec.md`](spec/target-spec.md).** It
is **partially ratified — targets, not compliance**: eleven of its twenty
rows are [RATIFIED (target)](spec/decision-records/0003-target-spec-first-ratification.md)
by the first ratification pass, nine are explicitly OPEN each with its gate
recorded, and **no row is ratified as met** — no measurement of this block
exists. Ratification flowed through the two-key mechanism (Judge review +
Champion/operator merge, per the ratification-via-PR standing path), and any
row change now requires a superseding decision record argued on evidence.

That document carries the full table (LNA gain / NF / S11 / S22 / stability /
IIP3 / P1dB, mixer conversion gain / SSB NF / IIP3, the cascade rows, LO
range and leakage, IF plan, supply and power, AREA and AREA-EFF), and with it
the things a table alone cannot say: the explicit 50 Ω port convention at
every RF port, what "across band" requires at every corner, the per-row source
citation, the PDK-derived corner set, and an honest `NEEDS-VERIFICATION` flag
on every bound that is an engineering target rather than a traceable
published result.

Alongside it:

- [`spec/porting-plan.md`](spec/porting-plan.md) — what transfers from
  `sg13g2-lna` (S-parameter/NF bench methodology), `sg13g2-vco` (EM-extracted
  passives, the LO/passives half) and `sg13g2-comparator` (the `sim/harness/`
  structure), the exact IHP-Open-PDK model files this block depends on, and
  what is genuinely new: the mixer bench and the 20 GHz passive question.
- [`spec/decision-records/`](spec/decision-records/) — the band record
  (proposed, with the Ku fallback trigger), the beamsteering-partition
  record (deferred, with its criteria), and the first-ratification-pass
  record (eleven rows RATIFIED as targets, nine OPEN, each with its gate).

## Repo layout

```
design/        schematics (xschem)
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
sim/           analog testbenches + PVT corner results
spec/          target spec (partially ratified, DR-0003) + porting plan
               + decision records
```

## Reproduce

Everything is driven from `sim/`; benches, harness and record conventions are
described in [`sim/README.md`](sim/README.md), [`sim/harness/README.md`](sim/harness/README.md)
and [`sim/hbt-kaband-characterization/README.md`](sim/hbt-kaband-characterization/README.md).
These need ngspice and the IHP SG13G2 PDK:

```
sim/characterize.sh smoke         # hbt_typ only, no evidence written; seconds
sim/characterize.sh selftest      # negative controls (sabotaged corners must fail, bad deck must be rejected)
sim/characterize.sh characterize  # full 27-point PVT campaign; mints a NEW append-only record per bench
```

The wrapper does not cover `mixer-topology-feasibility`; its controls are separate
(`python3 sim/mixer-topology-feasibility/run.py smoke` and `... selftest`, no evidence written) and
the `sim-smoke` CI job runs them after `characterize.sh smoke`/`selftest`.

Checks that need neither a PDK nor a simulator (Python 3, plus `pytest` and `numpy` from `requirements-test.txt`) are
what CI runs on every push and pull request (`.github/workflows/ci.yml`):

```
pip install -r requirements-test.txt
python -m compileall -q sim .github/scripts
python -m pytest sim/harness/tests sim/hbt-kaband-characterization/tests -q      # job: harness-tests
python -m pytest sim/mixer-nf-method/tests/test_nfmethod.py -v                    # job: harness-tests (mixer noise-method analytic fixtures; methodology only)
python -m pytest .github/scripts/tests -q                                         # job: evidence-formats (checker negative controls)
python .github/scripts/check_evidence_formats.py --base origin/main               # job: evidence-formats
```

The evidence checker validates the format of every `sim/*/records/*.md` and
its `corners/` and `netlist-snapshots/` artifacts (both the harness-native and
the Ka-band layout) and fails if a pull request modifies, deletes or renames
committed evidence; adding a new record is always allowed. Two campaigns
without a PVT testbench manifest are registered explicitly (`ADAPTERS` in the
checker) rather than skipped: `sim/passive-p1` (paired `records/<id>-<STATUS>.md/.json`:
record identity, allowed status incl. `CAPABILITY_UNAVAILABLE` and
`CONTROLS-PASS/FAIL`, Markdown/JSON agreement, provenance, declared input and
`run_log/` files exist; `SYNTHETIC-*` smoke output is rejected inside `records/`) and
`sim/mixer-nf-method` (same pairing for `MODEL_ABSENT` etc., plus the frozen
`probe-logs/<id>/{deck.spice,stdout.txt,stderr.txt,inventory.json}` package the
record names, which must agree with the record's inventory). Any other `sim/<dir>`
with `records/`, `corners/`, `netlist-snapshots/` or `probe-logs/` fails as an
unrecognised layout. Append-only history additionally protects `sim/*/probe-logs/`
(no modify/delete/rename, nothing added to a committed run id; a complete new run
is fine). New passive records (`record_schema` 2, issue #58) also name a frozen
`sim/passive-p1/solver-artifacts/<id>/` package with a SHA-256 `manifest.json`;
the checker verifies completeness for the recorded outcome, safe relative paths,
actual hash agreement and record/package agreement, and the append-only check
protects it like `probe-logs/`. This is hash integrity, not numerical
qualification. The passive solver working outputs (`results/`, `run_log/`, `fit/`)
stay mutable on purpose; the permanent evidence there is the record pair, the
hashed inputs it names and (for new records) the frozen package. The checks validate structure and provenance only, never
a historical numerical claim, and need no simulator or PDK. Adapter tests:
`python -m pytest .github/scripts/tests/test_check_evidence_adapters.py -q`
(also runs under `python -m unittest`). The simulator-backed
`sim-smoke` job (pinned ngspice 46 and IHP models) also runs the passive-p1
synthetic numerical controls (`python3 sim/passive-p1/scripts/controls.py all`,
no `--write-record`; extra dependencies in `requirements-sim.txt`, numpy + scipy).
These controls check the analysis chain on synthetic data only: a pass does **not**
establish EM convergence and does **not** qualify p1, and it is separate from the
evidence-format checks above. `signoff.yml` separately re-grades the
committed tier report.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
