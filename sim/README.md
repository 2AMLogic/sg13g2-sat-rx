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

## IHP model artifact (immutable pin, verified before every simulation)

`sim/pdk-artifact.json` is the committed pin of the IHP model files the
benches load. It names the upstream revision (IHP-Open-PDK **v0.3.0**, git
commit `5cccb161f7492697cfa52eb14dc03beb00bdca9e` -- a commit id is
content-addressed, unlike a tag or a generated archive), the SHA-256 of every
file in the include closure of `cornerHBT.lib` (4 files: `cornerHBT.lib`,
`sg13g2_hbt_mod.lib`, `sg13g2_hbt_mod_mismatch.lib`, `sg13g2_hbt_stat.lib`),
and the tested ngspice major (46). The closure was measured, not assumed: the
local install's four files were byte-compared against the pinned commit's
tree, and `harness/pdkartifact.py` re-derives the `.include`/`.lib` closure
from the installed `cornerHBT.lib` on every check.

What is checked, and when (`harness/pdkartifact.py`):

- `python3 -m harness.cli verify-pdk [--require-ngspice]` (from `sim/`) is the
  explicit check. `harness.cli run`/`selftest`, the Ka-band bench
  (`run.py`), and `sim/characterize.sh` all run it BEFORE any simulator
  process starts; a failure prints the file and hashes and exits non-zero
  with nothing simulated (`characterize.sh` exits 2).
- Only the file hashes establish a match. The install's `.fetched-version`
  marker is provenance: a missing marker is reported as `unknown` and the
  hashes alone decide; a marker equal to the pin never rescues wrong hashes;
  a marker that disagrees with the pin fails. (This is also why
  `Pdk.version` stays `"unknown"` for IHP -- see above -- and is not used as
  an integrity signal.)
- A model file that is missing, differs, is reachable but not listed, or is
  listed but no longer reachable fails. A missing PDK, a missing manifest or
  (with `--require-ngspice`, which hosted CI sets via
  `SG13G2_REQUIRE_NGSPICE=1`) a missing / different-major ngspice is a failed
  check, never a skip. Without `--require-ngspice` an ngspice major other
  than 46 is only reported, so a local newer ngspice is not blocked.
- There is no override flag for model drift: to use different models, change
  the pin (below) so the change is reviewed, or point
  `SG13G2_PDK_PATH`/`PDK_ROOT` at a verified install.

### Reproducing the hosted `sim-smoke` job locally

1. Fetch exactly the pinned models (about 2 MB, no credentials):
   ```
   git init ihp && cd ihp
   git remote add origin https://github.com/IHP-GmbH/IHP-Open-PDK.git
   git sparse-checkout init --cone
   git sparse-checkout set ihp-sg13g2/libs.tech/ngspice/models
   git fetch --depth 1 --filter=blob:none origin 5cccb161f7492697cfa52eb14dc03beb00bdca9e
   git checkout FETCH_HEAD
   export SG13G2_PDK_PATH=$PWD/ihp-sg13g2
   ```
   (A full IHP-Open-PDK install at that commit, e.g. `~/share/pdk/ihp-sg13g2`,
   works equally; its `.fetched-version` should read `0.3.0`.)
2. Install ngspice **46**: CI builds the SourceForge release tarball
   `ngspice-46.tar.gz` (sha256 in `sim/pdk-artifact.json`) on `ubuntu-24.04`
   with build dependencies `build-essential bison flex libreadline-dev`
   (configure stops with "Couldn't find GNU readline headers" without
   `libreadline-dev`) and `./configure --disable-debug --without-x`. No
   distribution package is assumed to carry 46. The dependency set and the
   configure flags are part of the CI cache key, so changing either rebuilds.
3. From `sim/`: `python3 -m harness.cli verify-pdk --require-ngspice`, then
   `SG13G2_REQUIRE_NGSPICE=1 ./characterize.sh smoke` and
   `SG13G2_REQUIRE_NGSPICE=1 ./characterize.sh selftest`.
   The job also checks that a tampered copy of a model file makes
   `characterize.sh` exit 2 before simulating, and that the working tree is
   unchanged afterwards. Smoke and selftest write no evidence (`--no-write`,
   `run.py smoke`'s "nothing recorded"); the job uploads and commits nothing.
   The full PVT campaign (`characterize`) is deliberately not run in CI; it
   stays on the Spot batch fleet.

### Drift behaviour

Any hash mismatch, missing/extra closure file, or conflicting marker stops the
run (see above) and CI goes red. Do not edit the manifest to make a red run
green: the cause is either a wrong install (reinstall the pinned commit) or a
deliberate pin change (next section).

### Deliberately updating the pin

1. Pick the new upstream commit (full 40-hex id), fetch it as in step 1, and
   run the benches against it with `SG13G2_PDK_PATH` set; a failing verify is
   expected at this point.
2. Update in ONE change: `upstream.*`, `install_marker.value`, and each
   `files` hash in `sim/pdk-artifact.json` (`sha256sum` the closure; add or
   drop files if the closure changed), plus `IHP_PDK_COMMIT` in
   `.github/workflows/ci.yml` (`harness/tests/test_ci_pins.py` fails if the
   two disagree). The same procedure applies to ngspice
   (`ngspice.*` in the manifest and `NGSPICE_*` in the workflow, and bump the
   cache key's `-v2` suffix).
3. Existing records under `sim/*/records/` are append-only evidence taken
   against the old pin and are not edited. New records state the new
   `environment.pdk` provenance; if a number changes, add a later record that
   says why rather than superseding by deletion.
4. A pin change that alters measured values is a spec-adjacent event: it must
   not be used to relax the ratified spec (`spec/` decision records govern).

## Benches

| Experiment | What it measures | Status |
|---|---|---|
| `lna-sparam-nf` | S11/S21/S22/S12, k-factor (stability), noise figure | placeholder circuit — see below |
| `mixer-conversion-iip3` | Conversion gain, LO-to-RF leakage, two-tone IIP3 | placeholder circuit — see below |
| `hbt-kaband-characterization` | Bare `npn13G2` at 17.7/19.45/21.2 GHz: two-port noise parameters (NFmin, Zopt, Rn), NF₅₀, fT, K/\|Δ\| and MAG-or-MSG, DC power, over Nx × VCE × J_C inside every PVT point | **device-level evidence, not a matched-amplifier result** — see below |
| `mixer-nf-method` | Feasibility of a mixer SSB-NF method without pnoise (issue #27): ngspice noise-capability inventory, SSB/image estimator and status gates | **`MODEL_ABSENT`** — no intrinsic device noise in `.tran`; no mixer NF number — see below |
| `mixer-topology-feasibility` | Mixer-core topology comparison under row 17 (issue #35): stacked Gilbert vs folded single-balanced vs the placeholder floor; per-device V_CE/V_BE/Ic stress, gain into a physical 50 Ω IF load, LO-drive selection rule, DC power, mismatch-card leakage, swept-region IIP3 | **part 1 only: fixtures + validated extraction, no record yet** — see below |

**The first two benches instantiate a PLACEHOLDER circuit, not a design candidate.**
`design/` has no schematic yet — each bench's `testbench/*.spice` fragment is a
single, minimally-sized `npn13G2` HBT stage sized only well enough to bias
sanely, built solely to prove each bench's ngspice methodology end to end
against the real device model. Every record these benches write states this
in its `claim` line and `## Evidence` notes; **no number in either bench's
records should be compared against any row of the target spec
(`spec/target-spec.md`)**, because they come from placeholder circuits, not
a design candidate. The spec itself is partially ratified per
[DR-0003](../spec/decision-records/0003-target-spec-first-ratification.md):
eleven rows are binding targets and nine stay explicitly open (the band,
row 1, among them — hence the "DRAFT band" wording below). Comparison against
the binding rows becomes meaningful only once these `tb.json` files are
re-pointed at a real schematic, which is the follow-up tracked in
[#28](https://github.com/2AMLogic/sg13g2-sat-rx/issues/28).

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

**Noise-figure reference (corrected, issue #22).** The reference source Rs1
is **noiseless** (`noisy=0`, no instance `TEMP=`) and its thermal noise is
added analytically at an explicit T0 = 300.15 K:
`F = 1 + inoise_spectrum^2 / (4 k T0 Z0)`, `NF = 10 log10 F`. The output load
Rs2 and bias resistor stay noisy at each corner's temperature (unchanged).
The first record, `lna-sparam-nf/records/20260912-034726-9204518.md`, used
`Rs1 ... TEMP=27` and believed it pinned the source at 300.15 K; in
ngspice-46 it generates noise at 327.15 K (see `hbt-kaband-characterization`'s
probe), so **every `nf_db_*` in that record is high by 27/300.15 = 0.0900 in
linear F** (not a constant dB offset). It is left untouched; do not quote its
NF numbers. The current record is
`lna-sparam-nf/records/20261009-134024-57e1898.md` (supersedes it; a fresh
27-point simulation whose NF equals `10^(NF_old/10) - 27/300.15` to 4e-7 in F,
S-parameters and k bit-identical). The instance-`temp=` behaviour is an
observation on ngspice-46: on ngspice-42 a one-corner local check shows the old
and new fixtures agreeing, so the correction cannot be reproduced on that
version. Normalization and its negative controls:
`lna-sparam-nf/lna_nf.py`, tests `python3 -m pytest sim/lna-sparam-nf/tests -q`.

To reproduce the campaign on a shared dispatch host (the 27 points go to the
`klt sim` batch fleet, not a local `ngspice -b` loop):

```
python3 sim/lna-sparam-nf/run.py characterize --no-stage-models --runner-version-check warn \
    --supersedes <previous-record-id> --claim '...'
```

(`--no-stage-models --runner-version-check warn` are the same fleet/client
version-skew workarounds as `hbt-kaband-characterization/README.md` documents;
drop them once the runner image is updated.) The driver ingests the returned
logs into the usual native layout and refuses to write unless all 27 points
carry finite values and, with `--supersedes`, agree with that record's logs.

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

### `mixer-topology-feasibility`: which mixer core to draw first (issue #35)

[`mixer-topology-feasibility/`](mixer-topology-feasibility/README.md) compares
a classic stacked Gilbert cell, a folded single-balanced alternative and the
placeholder (a labelled floor). All three use bit-identical port conventions:
a 50 Ω RF port, a 100 Ω differential LO port quoted as total available power,
and a physical 50 Ω IF load. Ideal baluns and passives keep it a
**device-level topology study, not a design**; it claims no spec row.

- **Status: part 1 of 2.** Part 1 has the fixtures, the study declaration,
  the extraction/selection/IIP3/stress/acceptance-gate logic with unit tests,
  and local single-corner `smoke`, `selftest` and `converge` modes. **No
  record exists yet.** The 837-cell comparison is a multi-corner campaign
  for `klt sim` batch submission (part 2).
- **Limitations.** The supply axis is an exploratory 2.25 V ± 10 %, wholly
  below the 2.5 V ceiling; it ratifies no rail. The LO-selection and IIP3
  sweeps are reduced to `hbt_typ`/27 °C/2.25 V. Leakage uses the
  `*_mismatch` cards at one fixed seed, which is deterministic card coverage,
  not yield evidence. There is no MOS/capacitor/resistor or passive/EM
  corner axis, and SSB NF is out of scope.

### `mixer-nf-method`: SSB NF without pnoise (issue #27)

[`mixer-nf-method/`](mixer-nf-method/README.md) tests whether a transient-noise method
could fill the gap above. **The outcome is `MODEL_ABSENT`.**

- The test is one local `ngspice -b` capability probe of the placeholder at
  `hbt_typ`/27 °C/2.50 V. Its findings are backed by the ngspice-46 manual and source.
- ngspice-46 generates no intrinsic HBT noise (shot, terminal-resistance thermal or
  flicker) and no resistor thermal noise during `.tran`. Only explicit `TRNOISE`
  sources are stochastic there.
- PSS/pnoise does not exist.
- The active-mixer path therefore stops at the issue's coverage gate. No NF number for
  the placeholder is reported, and nothing there bears on row 10 or row 12.
- The SSB/image, T0 = 300.15 K, PSD/ENBW and uncertainty conventions, and the status
  gates, are defined and tested on analytic fixtures. They are ready for a simulator
  that has the capability.
- The `klt sim` disclosure gap is filed as 2AMLogic/klayout-tools#2985.

### `hbt-kaband-characterization`

Issue #17, `spec/porting-plan.md` §5 step 3. **Device-level evidence, not a
matched-amplifier result**: one bare `npn13G2` behind ideal bias tees with
ideal noiseless terminations. NFmin is a lower bound for a circuit built
around the device *before* matching loss and second-stage noise; MAG/MSG is
device gain. Its records' row-3 comparison is a feasibility screen, never a
compliance claim.

The generic `harness.cli` interface (scalar `measure` per PVT point) cannot
express its Nx × VCE × VBE sweep inside each PVT point, so it has a
bench-local driver, `hbt-kaband-characterization/run.py`, built on the
harness's deck composition, corner, sabotage and record-id helpers. Its
noise figures use a **noiseless** source with the source noise added
analytically at an explicit T0 (290 K and 300.15 K); the bench's
resistor-noise probe shows that the per-instance resistor `temp=` convention
used by `lna-sparam-nf`'s fixture does not do what that fixture says in
ngspice-46 (a `temp=27` resistor generates noise at 327.15 K at every
analysis temperature) — existing `lna-sparam-nf` records are left as they
are; see the bench README. Full method, sweep, checks and reproduction:
`hbt-kaband-characterization/README.md`.

The full 27-point grid is submitted as `klt sim` requests (off-host batch by
default) and ingested into one append-only record with full per-point
sidecars; smoke and selftest run one local PVT point at a time on a reduced
bias sweep.

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

### `passive-p1` — bounded EM campaign for one inductor (issue #25)

[`passive-p1/`](passive-p1/README.md) is a reproducible, **p1-only** (single-turn
`inductor2`, w=8.22 µm, s=3.29 µm, d=47.65 µm) openEMS → de-embed → Touchstone →
lumped fit → ngspice campaign, adapted from the pinned `sg13g2-vco` flow, with
declared mesh/margin/fit limits and an append-only record whose status is one of
`QUALIFIED` / `UNCONVERGED` / `FIT_FAILED` / `CAPABILITY_UNAVAILABLE`.
**State at merge: the openEMS stages are `CAPABILITY_UNAVAILABLE` on the build host,
so there is no p1 L/Q/SRF, convergence or fit result, and no qualified model.** The
analysis chain (strict Touchstone parsing, impedance, L/Q/SRF, ngspice comparison)
is validated only on generated data (synthetic lossless-L known answer plus
wrong-value and malformed-data rejections). The passive question
(`spec/target-spec.md` open item 3) is **not** resolved by this; feasibility is
deferred in [DR-0005](../spec/decision-records/0005-passive-p1-feasibility.md).
No process/temperature spread is supported; nothing here is a design stand-in yet,
and the benches above still contain no inductor.

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

One command runs every bench (from the repo root):

```
sim/characterize.sh smoke          # hbt_typ only, no evidence written; fails on any simulator/measurement failure
sim/characterize.sh characterize   # full HBT x T x V grid, writes a record per bench
sim/characterize.sh selftest       # negative-control self-test per bench
```

For the Ka-band bench, `characterize` submits `klt sim` requests (backend
from `$KABAND_BACKEND`, default `batch`); see
`hbt-kaband-characterization/README.md` "Running the full grid".

Or drive `harness.cli` directly (from `sim/`), always naming the `hbt`
corner set explicitly:

```
python3 -m harness.cli list
python3 -m harness.cli run lna-sparam-nf --corners hbt   # local ngspice loop: workstation only; on a shared host use lna-sparam-nf/run.py
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
harness bootstrap. Later, `mixer-nf-method` (issue #27) filed
2AMLogic/klayout-tools#2985. The `klt sim` contract does not disclose that ngspice
transients carry no device or resistor noise. The missing noise itself is an ngspice
capability gap, not a klt one.
