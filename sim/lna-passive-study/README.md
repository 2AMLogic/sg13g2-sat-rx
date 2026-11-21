# lna-passive-study (issue #340)

**NON-CLAIMING substituted-primitive study** of `design/lna_stage1`, feeding the
proposed decision record DR-0011 (`spec/decision-records/0011-lna-stage1-passive-realization.md`):
at most four candidate sets that replace the stage's generic `res.sym`/`capa.sym`
elements with PDK-modelled primitives (`rsil`/`rppd`/`rhigh`, `cap_cmim`/`cap_rfcmim`),
measured with the **reused lna-sparam-nf method** (fixture and whole `.control`
block pinned by sha256 in `testbench/plan.json`) as **comparative deltas only**
against a same-deck control (the committed ideal-passive DUT) at the bound corners
of ratified rows 2, 3, 4 and 6.

**Inductors (`Lin`, `Lfeed`, `Le1`) stay IDEAL in every variant and every
record** — the inductor half of passive realization is #110 / DR-0005 and is out
of scope here. **No spec row is claimed met or missed**: row 4's own note says
S11 is not simulatable as a claim until EM extraction lands, so every delta is a
design input for the operator's realization call, not compliance evidence.
Selecting a primitive set, editing `design/lna_stage1.sch`, and relaxing any
ratified row are all outside this study.

The per-element sizings come from `layout/lna_stage1/passive_sizing.json`
(issue #340 part 1): PDK models, not `R = rsh*L/W` — the `r3_cmc` resistor
model's drawn-to-electrical width correction and end/contact resistance and the
MIM models' area + perimeter capacitance are included, verified against the
instanced models on the batch fleet. The `r3_cmc` model needs OSDI support this
host's ngspice does not have, so **every simulation here runs on the `klt sim`
batch fleet** (`--backend batch`, `--wait-for-capacity 600` per the host rules);
there is no local fallback. klayout-tools friction met: `options.osdi_preload`
has no PDK-relative form the way per-section corner libraries do (the request
must hard-code the runner's `$PDK_ROOT/<variant>/...` layout) — filed as
[2AMLogic/klayout-tools#7039](https://github.com/2AMLogic/klayout-tools/issues/7039);
meanwhile the requests stage the OSDI file so the report hashes the exact bytes.

## Cold start

```bash
python3 -m pytest sim/lna-passive-study/tests -q   # no simulator needed
python3 sim/lna-passive-study/run.py check-plan    # plan vs sizing table vs DUT
python3 sim/lna-passive-study/run.py variants --check
python3 sim/lna-passive-study/run.py prematch --dry-run   # V04's re-match probe + grid requests
python3 sim/lna-passive-study/run.py prematch       # submits both, writes testbench/prematch.json
python3 sim/lna-passive-study/run.py build          # bodies/requests under _build/
python3 sim/lna-passive-study/run.py collect        # batch-set the grid, write ONE record
python3 sim/lna-passive-study/run.py verify         # re-derive verdicts from the sidecars
```

`collect` needs the plan, the sizing table, the variant decks and the prematch
outcome committed (it refuses a dirty tree of those inputs) and stores the raw
evidence bytes in the fleet artifact store (issue #226); git keeps the record,
its JSON sidecar and the manifest. Evidence under `records/` is append-only.

## Method

Everything about the measurement is the committed `sim/lna-sparam-nf` method,
reused unchanged and pinned by hash: the two-port fixture (Thevenin Z0 = 50 ohm
sources, forward/reverse by `alterparam`+`reset`), the corrected issue-#22 NF
convention (noiseless `Rs1`, analytic source noise at T0 = 300.15 K), the
3-point DRAFT-band set (17.7 / 19.45 / 21.2 GHz; row 1 is OPEN), the 1–100 GHz
stability sweep for k / |Delta| / mu (row 6), and the per-device operating-point
lines (row 17 context; 2.75 V cells stay labelled excursions).

What this study adds, all frozen in `testbench/plan.json` **before** collection:

* **Corner axis.** Seven named process bundles, each one `.lib` section per model
  family (klt per-section corner libraries): `typ`, `hbt_wcs`, `hbt_bcs`, and the
  four row-4 passive extremes `res_bcs__cap_bcs`, `res_wcs__cap_wcs`,
  `res_bcs__cap_wcs`, `res_wcs__cap_bcs` — crossed with -40/27/125 C and
  2.25/2.50/2.75 V (63 cells per deck). The post-#79 record covers the hbt half
  of every cell; for the ideal control DUT the passive sections are provably
  inert (it instances no such device), which the record's negative control checks.
* **Candidate sets (4) + control.** V00 = the committed ideal-passive DUT
  (selects nothing; the deltas' baseline under this deck). V01 = `rppd` bias
  ladder + `rsil` RF path + `cmim` caps + `Cb2` as two parallel `cmim` +
  `Cblk_in` OFF-CHIP (its designed 1 nF value kept as an IDEAL element: no
  on-chip area, no pad/bond/PCB parasitics — a stated omission). V02 = V01's
  capacitors with the `rhigh` bias ladder
  (minimum area, widest `res_*` spread) — isolates the resistor-flavour delta.
  V03 = V01's resistors with the `rfcmim` route (substrate nodes admitted) and
  `Cblk_in` as an on-chip 1 nF `rfcmim` array — isolates the cap-primitive and
  on-chip-`Cblk_in` delta. V04 = V01 with the **smallest on-chip `cmim`
  `Cblk_in` that still closes the input match**, re-matched (DR-0011 option b).
* **V04's bounded re-match iteration** (`testbench/prematch.json`, committed
  before the collection): a one-corner probe of the substituted core's base
  impedance at 19.45 GHz by the design's own methodology (measured:
  48.17 − j143.38 ohm), an L-section re-match per grid value
  {0.5, 1, 2, 5, 10} pF, a four-corner-cell S11 grid, and the selection rule
  "smallest value holding S11 ≤ −10 dB at all three band points at every cell"
  (row 4's ratified target, used here as a design-iteration rule, NOT a claim).
  Measured outcome: 1 pF closes (worst −10.15 dB) at 664 um² of plate — about
  1000x less plate than the 1 nF array; 0.5 pF does not (−9.90 dB at one cell).
* **Gates.** The control must agree with the post-#79 record's published
  per-cell operating points at every 2.5 V hbt x temperature cell (10 mV / 2 %),
  sit inside its published per-measure envelopes, be inert to the passive corner
  sections (1e-6 relative), and every cell of every deck must be finite.
  A failing gate is `CONTROLS_FAILED`: no delta is published as a conclusion.
* **Deltas.** Per variant cell, variant minus control at the same hbt section,
  temperature and supply, for S21 / NF / S11 / k (band points and sweep
  minimum) — reported at the row 2/3, row 4 and row 6 bound cells. A degraded
  margin is recorded as measured, with the bounded iteration that would recover it.

## Files

| file | role |
|---|---|
| `testbench/plan.json` | frozen declaration: scope, corner axis, candidate sets, prematch rule, gates |
| `testbench/prematch.json` | frozen V04 re-match outcome (probe, grid, selection) |
| `testbench/variants/*.spice` | frozen variant DUT decks (generated; checked by `variants --check` and the tests) |
| `passive.py` | pure logic: plan validation, deck/body/request generation, deltas, L-section re-match |
| `run.py` | CLI: `check-plan`, `variants`, `prematch`, `build`, `collect`, `verify` |
| `tests/` | closed-form qualification (no simulator, no fleet) |
| `records/`, `manifests/artifacts/lna-passive-study-*` | append-only evidence (md + json sidecar in git; bytes in the artifact store) |
