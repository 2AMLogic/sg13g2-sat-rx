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
instanced models. Collection and the input-match screen default to batch.
Both can run locally on an OSDI-capable ngspice installation with
the pinned IHP model files and compiled resistor model. The upstream issue
tracks support for PDK-relative OSDI paths. [klayout-tools #7039](https://github.com/2AMLogic/klayout-tools/issues/7039)

## Cold start

```bash
python3 -m pytest sim/lna-passive-study/tests -q   # no simulator needed
python3 sim/lna-passive-study/run.py check-plan    # plan vs sizing table vs DUT
python3 sim/lna-passive-study/run.py variants --check
python3 sim/lna-passive-study/run.py prematch --dry-run   # V04's re-match probe + grid requests
python3 sim/lna-passive-study/run.py prematch       # probe, screen, then selected circuit and control
# To reproduce the bounded screen on a workstation with ngspice 47 and OSDI:
python3 sim/lna-passive-study/run.py prematch --backend local
python3 sim/lna-passive-study/run.py variants       # regenerate current decks after prematch
python3 sim/lna-passive-study/run.py build          # bodies/requests under _build/
python3 sim/lna-passive-study/run.py collect        # batch grid and stored record
# On a simulation workstation, use collect --backend local for the same grid.
python3 sim/lna-passive-study/run.py verify         # check grids, deck identities and summaries
```

`collect` needs the plan, the sizing table, the variant decks and the prematch
outcome frozen. It checks the generated decks against the plan and stores the raw
evidence bytes in the fleet artifact store (issue #226); git keeps the record,
its JSON sidecar and the manifest. Evidence under `records/` is append-only.
To repeat the four gates and every subtraction on archived measurements,
use `verify RECORD_ID --cells BUNDLE.json.gz`. The historical erratum gives
the corresponding fetch command.

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
  on-chip-`Cblk_in` delta as a combined set. The nominal probe repeats each RF
  substitution individually and compares the three-terminal `m=119` instance
  with 119 explicit units under the same load and substrate connection.
* **V04 input match.** The base probe gives 48.17 − j143.38 Ω at 19.45 GHz.
  Version 2 sizes both the blocking and shunt capacitors as `cap_cmim`. It
  screens 0.5, 1, 2, 5 and 10 pF at three frequencies, four resistor/capacitor
  corner pairs and two temperatures at 2.5 V. The 10 pF point uses two plates.
  The smallest passing tested value is **2 pF** with a 4.56 µm square shunt.
  At 17.7 GHz, `res_wcs / cap_wcs` and 125 °C, S11 is −10.0086 dB. The
  1 pF option reaches −9.7526 dB. The selected circuit and V00 are then
  measured with the original two-port and NF method at the same eight cells.
  Per-frequency S11, gain and NF comparisons, body hashes and the nominal RF
  substitution probe are in [prematch.json](testbench/prematch.json).
* **Historical record.** The append-only 63-cell-per-deck record used a
  four-cell selection grid and an ideal 31.89 fF shunt for its 1 pF V04.
  Its original deck is [v1/V04.spice](testbench/variants/v1/V04.spice).
  DR-0011 supersedes the record's initial V03 inductance explanation and
  input-block recommendation. The [historical erratum](errata/20261121-044750-495011a.md)
  rechecks all four gates, corrects the noise-figure legend and gives whole-grid
  stability extrema. The [revised 2 pF record](records/20261121-101130-e6a7e3e.md)
  includes 63 cells each for the control and all four current candidate decks.
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
