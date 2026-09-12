# sim

Testbenches and PVT corner results (ngspice), built on the generic
`sim/harness/` scaffold (see `harness/README.md`). Per CLAUDE.md's
"Verification is the product": every claim in this repo traces to one of the
append-only records under `sim/<experiment>/records/`.

## PDK pin

`sim/pdk.json` names the PDK and the model-library file this harness's
corner sweeps read (`libs.tech/ngspice/models/cornerHBT.lib`). Confirmed
against an installed IHP-Open-PDK **v0.3.0** checkout (its own
`.fetched-version` file, 2026-09-12) — see `sim/pdk.json`'s
`_local_install_verified` note for exactly what was checked and why this
repo does not itself carry a `release_tag`/`tarball_sha256` pin the way
`sg13g2-lna`/`sg13g2-vco`/`sg13g2-comparator`'s `sim/pdk.json` fact-sheets do
(those fields are read by nothing in this generic harness core; each record's
own `environment.pdk` block is the self-describing provenance instead).

The PDK's own version marker (`Pdk.version` in `sim/harness/pdk.py`) reads
the SOURCES file convention some other PDK distributions use; IHP-Open-PDK
ships `.fetched-version` instead, so every record's `environment.pdk.version`
currently reads `"unknown"` — a known, documented gap in the generic core's
version-detection convention for this specific PDK, not a broken install
(confirmed working: `sim/pdk.json`'s model_lib resolves and every bench below
runs against real device data).

## Benches

| Experiment | What it measures | Status |
|---|---|---|
| `lna-sparam-nf` | S11/S21/S22/S12, k-factor (stability), noise figure | placeholder circuit — see below |
| `mixer-conversion-iip3` | Conversion gain, LO-to-RF leakage, two-tone IIP3 | placeholder circuit — see below |

**Both benches instantiate a PLACEHOLDER circuit, not a design candidate.**
`design/` has no ratified schematic yet (issue #1, the spec-ratification
issue, is still open) — each bench's `testbench/*.spice` fragment is a
single, minimally-sized `npn13G2` HBT stage sized only well enough to bias
sanely, built solely to prove each bench's ngspice methodology end to end
against the real device model. Every record these benches write states this
in its `claim` line and `## Evidence` notes; **no number in either bench's
records should be compared against the DRAFT target spec
(`spec/target-spec.md`, still `Status: DRAFT` as of this writing — not yet
ratified)** until a real design exists in `design/` and these `tb.json` files
are re-pointed at it (issue #1 → a follow-up design issue).

### `lna-sparam-nf`

S-parameters via power-wave injection (ngspice has no native S-parameter
analysis): a Thevenin Z0=50 Ω source per port, toggled forward/reverse via
`alterparam`+`reset` between two `.ac` calls in one deck. Noise figure via
`.noise`'s per-frequency `inoise_spectrum` vector (**not** the aggregate
`inoise_total`, which is bandwidth-integrated across the whole sweep — a real
trap found while building this bench, documented in the testbench header and
every record's evidence notes). Swept at three points across the Ka-band
downlink DRAFT band (17.7 / 19.45 / 21.2 GHz). Full derivation:
`lna-sparam-nf/testbench/lna_ce_placeholder.spice`'s header comment.

### `mixer-conversion-iip3`

Conversion gain, LO-to-RF leakage, and two-tone IIP3 via one transient run's
coherent-bin FFT (two RF tones at 19.4375/19.4625 GHz, LO at 18.45 GHz —
low-side, 1 GHz IF per the DRAFT LO-range row). **SSB noise figure is not
measured by this bench at all**: ngspice has no periodic-steady-state /
periodic-noise (pnoise) analysis, so there is no valid way to linearize noise
about a mixer's LO-pumped operating point with ngspice's plain `.noise`
(which only applies around a fixed DC bias point) — a real ngspice tooling
gap, not a klayout-tools one (klayout-tools does no simulation and is not
invoked by either bench in this repo). Full derivation:
`mixer-conversion-iip3/testbench/mixer_ce_placeholder.spice`'s header
comment.

### Passive/EM model provenance

**No PDK inductor model exists for SG13G2** — confirmed absent from
IHP-Open-PDK (ships layout PCells, LVS rules, and xschem/Qucs-S symbols for
`inductor`/`inductor2`/`inductor3`, but no `.subckt`/`.model` an ngspice
`.include`/`.lib` can load; `sg13g2-vco`'s `known_model_gaps` note documents
the same absence and its own analytic/EM-fitted stand-ins for a real design's
matching inductors). Both benches in this repo sidestep the gap entirely
rather than substitute an unvalidated model: **no inductor of any kind — PDK,
analytic, or EM-derived — appears anywhere in either fixture.** Every
S-parameter, gain, NF, leakage, and IIP3 number recorded under `sim/` so far
is for a purely resistive/capacitive port and bias network; this is stated
explicitly in each bench's evidence notes on every record. A real design's
matching/LO-port inductors (once a topology is ratified) will need
`sg13g2-vco`'s analytic-or-EM-fitted model route — do not invent a new one
here without re-deriving it per CLAUDE.md's "never copy a number across
repos without its derivation."

## HBT process corners

`sim/harness/corners.py`'s built-in five-corner MOS sweep (`tt`/`ff`/`ss`/
`fs`/`sf`) does not apply here — neither bench instantiates a MOS device, and
`cornerHBT.lib` (this repo's `model_lib`) does not define those section
names at all. This repo registers its own corner set, `hbt` (`hbt_typ` /
`hbt_bcs` / `hbt_wcs` — typical / best-case-speed / worst-case-speed, per
`cornerHBT.lib`'s own three non-mismatch `.LIB` sections), via
`corners.register_corner()`/`register_corner_set()` — the documented
extension point, not an edit to the generic five-MOS-corner default (which
stays intact for a future MOS-instantiating bench). Every bench's `tb.json`
names `"corners": ["hbt"]` explicitly; pass `--corners hbt` on the command
line too (see below) since `harness.cli run`/`selftest` do not read a
testbench's own `corners` field automatically.

## Running it

One command runs both benches (from the repo root):

```
sim/characterize.sh smoke          # one nominal point per bench, no evidence written
sim/characterize.sh characterize   # full HBT x T x V grid, writes a record per bench
sim/characterize.sh selftest       # negative-control self-test per bench
```

Or drive `harness.cli` directly (from `sim/`), always naming the `hbt`
corner set explicitly:

```
python3 -m harness.cli list
python3 -m harness.cli run lna-sparam-nf --corners hbt
python3 -m harness.cli run mixer-conversion-iip3 --corners hbt
python3 -m harness.cli selftest lna-sparam-nf --corners hbt
python3 -m harness.cli selftest mixer-conversion-iip3 --corners hbt
```

`sim/*/corners/<record-id>/*.log` (the raw ngspice output per PVT point) is
committed evidence alongside each Markdown record — `.gitignore` carves an
exception for it out of the general `*.log` rule. `sim/*/_build/` and
`sim/*/_selftest/` are disposable scratch directories (generated decks,
`--no-write`/self-test scratch runs) and are `.gitignore`d.

## klayout-tools

Neither bench in this repo invokes `klayout-tools` (`klt`) — both are
pre-layout ngspice testbenches; layout/DRC/LVS work has not started (`design/`
has no schematic yet). No klayout-tools friction was hit building this
harness bootstrap.
