# sim/passive-p1 — bounded p1-only single-turn spiral campaign

Issue [#25](https://github.com/2AMLogic/sg13g2-sat-rx/issues/25) (revised
2026-10-09). **Feasibility evidence for one geometry, nothing more.** It does
not close the 20 GHz passive question (`spec/target-spec.md` open item 3), does
not choose a passive family, sizes no matching network, and edits no ratified
spec value. Transmission lines, MIM capacitors, other geometries and validated
process/temperature corners are follow-on work.

## Current state (read this first)

| Item | State |
|---|---|
| Analysis chain (strict Touchstone parse, S→Z/Y, L/Q/SRF, ngspice two-port comparison, record/verdict) | implemented; controls pass (`records/*-CONTROLS-PASS.md`) |
| Synthetic lossless-L known-answer, wrong-value, malformed-data controls | pass (the sabotage controls pass by being **rejected**) |
| Pipeline plumbing on generated 2-π data (success / exceeded-limit / wrong-fit / unavailable / re-run digest) | pass, records labelled `SYNTHETIC-*`, kept out of `records/` |
| Geometry stage (PDK PCell → GDS, compared with pinned GDS) | ran on the authoring host: per-layer XOR area 0 for all four layers |
| **openEMS stages (`em`, `convergence`)** | **`CAPABILITY_UNAVAILABLE`** on the authoring host — `openEMS` not on PATH, no openEMS python, `import CSXCAD` fails. See `records/*-CAPABILITY_UNAVAILABLE.md`. |
| L/Q/SRF at 17.7 / 19.45 / 21.2 GHz, mesh and margin deltas, fit residuals | **not established** — no solver ran; no number from any other source is substituted |
| Qualified p1 model | **none** |
| Reproducible openEMS runner + real solver smoke control (issue [#46](https://github.com/2AMLogic/sg13g2-sat-rx/issues/46)) | **prepared**; see "Reproducible runner" below. A passing smoke control is capability evidence only. **p1 remains unqualified and DR-0005 remains deferred.** |

Run `sim/passive-p1/run_extraction.sh` on a host that has openEMS (below) to
produce the real record; it appends a new record and never edits an old one.

## Reproducible runner (issue #46): bootstrap, probe, smoke, cleanup

`runner/` builds, from public sources at pinned commits and with no root, secrets, paid
service or container daemon, a user-owned prefix that satisfies the prerequisites of
`run_extraction.sh`, and proves with a real solver run that the prefix works. It does **not**
run the p1 campaign, choose a passive family, relax any spec value or touch the PDK tree.

```
R=sim/passive-p1/runner
$R/bootstrap.sh build /path/outside/repo/p1-prefix      # build (cold, 2 jobs)   [--skip-ngspice] [--skip-pdk]
source /path/outside/repo/p1-prefix/activate.sh         # OPENEMS_PYTHON FIT_PYTHON IHP_PDK_ROOT PATH LD_LIBRARY_PATH EM_THREADS
$R/probe.sh                                             # every executable/import/path run_extraction.sh uses; exit 1 + exact list if any is missing
$R/smoke.sh                                             # real openEMS known-answer solve under enforced limits
$R/negative_controls.sh                                 # 1 baseline + 9 sabotaged runs (7 smoke, 2 probe), each must be rejected with its own status
python3 sim/passive-p1/scripts/controls.py all          # existing synthetic controls (needs ngspice + numpy/scipy from the prefix)
python3 sim/passive-p1/scripts/hash_inputs.py --check
$R/bootstrap.sh clean /path/outside/repo/p1-prefix [--caches]   # remove everything (or only src/tmp/dl)
```

Paths with spaces are supported (the verification below used one). `probe.sh --build` checks the
system build prerequisites without network.

**What gets installed** (all under the prefix; `provenance.json` records versions, commits, sha256s):
isolated venv with hash-pinned wheels (`runner/requirements-lock.txt`, generated from
`requirements.in` with `uv pip compile --generate-hashes`, installed with `--require-hashes`;
`gdspy` is sdist-only and is built from its hash-pinned sdist, `requirements-sdist-lock.txt`),
openEMS v0.37.0-rc2 / CSXCAD 0.7.0rc2 (openEMS-Project commit and its three submodule gitlinks
verified), `gds2openEMS` 0.3.0 (IHP helper commit, `--no-deps`: its declared PySide6 GUI dependency is
never imported by the driver), ngspice 46 (same tarball and sha256 as the CI `sim-smoke` job), and a sparse
checkout of IHP-Open-PDK v0.3.0 (`libs.tech/klayout`, `libs.tech/ngspice/models`; the pycell submodules the
tarball omits are still supplied per run by `scripts/setup_pdk_overlay.sh`, unchanged). All pins live in
`runner/LOCK.env`. **Headless KLayout is the system `klayout` binary** (apt `klayout`), checked by the probe and
version-recorded but not built: a Qt-less source build is outside the preparation limits. If a worker lacks it the
probe/bootstrap name it as the missing prerequisite (a worker-spec item, never installed by the runner). Other system
prerequisites (compilers, cmake, hdf5/vtk/CGAL/boost/tinyxml headers, python3-venv, bison/flex) are likewise only
checked, and named when absent.

**Environment variables** exported by `activate.sh` and consumed by `run_extraction.sh`: `OPENEMS_PYTHON`,
`FIT_PYTHON` (both the prefix venv), `IHP_PDK_ROOT`, `PATH` (venv python3 first: `run_extraction.sh` also runs
`python3 -I -c 'import CSXCAD'`, and `-I` ignores `PYTHONPATH`), `LD_LIBRARY_PATH`, `EM_THREADS` (default 2).

**Declared preparation limits** (`runner/LIMITS.env`; the environment or flags may only lower them; they are
preparation limits chosen by the Builder, **not** an estimate for the full p1 campaign, which must establish its own
bounds before launch): solver threads 2 (`--numThreads=2`, `OMP_NUM_THREADS`), make jobs 2, free disk >= 6 GiB before
launch and prefix <= 3 GiB, whole bootstrap wall limit 1800 s (each phase gets the remaining budget, tree killed on
expiry), smoke wall limit 60 s and process-tree RSS <= 1024 MB (`limited_run.py` samples `/proc` and kills the tree
on breach). Each limit is at least 3x the measured cost below.

**The known-answer control** (`runner/smoke_cavity.py`): a closed 30 x 20 x 25 mm PEC box, 1 mm cells, Gaussian
soft source, 20 000 FDTD steps, run with the real `openEMS` executable. The lowest four spectral peaks of the recorded probe
voltage (found from the spectrum alone) must match the closed-form `f_mnp = (c0/2) sqrt((m/a)^2+(n/b)^2+(p/d)^2)` for
(1,0,1), (1,1,1), (2,0,1), (1,0,2) within a declared **0.5 %**. The check also requires the solver log to report all
iterations, the probe record to span them and every value to be finite. Import-only checks, mocks and the synthetic L
controls cannot pass it. The merged `smoke_log.json` (written outside the repo, also on failure) records openEMS/python/numpy
versions, sha256 of the XML solver input and the script, the exact command, threads, enforced limits, measured wall
time and peak memory.

**Negative controls** (`runner/negative_controls.sh`) pass only when the smoke is rejected with a distinct status:
missing python binding 14, missing executable 10, solver failure 11 (stub solver; truncated input XML), numerical
mismatch 13 (analytic values scaled by 1.02), timeout 124, memory limit 125; and `probe.sh` must exit 1 naming a missing binding
or executable. It also checks that no solver process is
left running and that the repository work tree is unchanged.

### Verification record (preparation host, 2026-10-10)

Cold build in a fresh prefix whose path contains spaces, from a clean environment (`env -i`), then probe, smoke,
negative controls, synthetic controls and hash checks all green. Measured: **build wall 330 s, peak process-tree RSS
784 MB (single `/usr/bin/time` max 626 MB), prefix 0.68 GiB, 2 make jobs**; **smoke wall 2.0 s (solver 1.7 s, 20 000
iterations, 2 threads), peak RSS 107 MB**; worst relative frequency error 0.13 % against the 0.5 % tolerance for
7.8033 / 10.8199 / 11.6458 / 12.9743 GHz. Host: Ubuntu 24.04, gcc 13, KLayout 0.28.16 (system). This is evidence
that the toolchain runs and reproduces a closed-form answer; it is **not** an EM result for p1 and measures nothing
about the campaign's three solves, whose cost is unknown until they are run.

### Launching and retrieving the full campaign with this environment

The campaign itself is separate follow-on work and is **not** run or claimed by this preparation. Once its resource
bounds have been established and recorded:

```
source /path/outside/repo/p1-prefix/activate.sh && sim/passive-p1/runner/probe.sh        # must exit 0
sim/passive-p1/run_extraction.sh                          # geometry, em, convergence, post, fit, compare
# retrieve: records/<id>-<STATUS>.{md,json} and solver-artifacts/<id>/ are the only tracked outputs (append-only);
# results/ fit/ run_log/ are scratch. Commit the new record + package; never edit an old one.
```

If a solve fails, the script writes a new `CAPABILITY_UNAVAILABLE` record as before. A passing runner smoke control
cannot stand in for `QUALIFIED`, `UNCONVERGED` or `FIT_FAILED`. **p1 qualification stays pending, DR-0005 stays deferred**
until its measured-evidence and band-ratification gates are met; no matching-network or compliance claim follows.

## Geometry, ports, definitions

PDK `inductor2` (SG13_dev), `w=8.22 µm, s=3.29 µm, d=47.65 µm, nr_r=1`
(`gds/inductor_p1.json`). Port 1 = LA, port 2 = LB, each a lumped z-port
referenced to a local substrate ground patch (the model's `sub` node); Touchstone
z0 = 50 Ω. De-embedding subtracts the lumped-port series inductance (Terman
flat ribbon, from `port_information.json`) from the diagonal of **Z**.

- `Z_se = Z11 − Z12·Z21/Z22` (= 1/Y11): LA driven, LB and `sub` grounded — the
  quantity the ngspice fixture measures and the one the limits gate.
- `Z_diff = Z11 − Z12 − Z21 + Z22`: reported alongside, not gated.
- `L = Im(Z)/ω`, `Q = Im(Z)/Re(Z)` (reported as **infinite** where `Re Z` is
  numerically zero; no division error), `SRF` = first downward zero crossing of
  `Im Z_se`; **no crossing below the 30 GHz search ceiling is reported as a lower
  bound, never as a number.**
- Sweep: 0–30 GHz, 601 samples (the DC point is dropped from L/Q).

## Declared limits (proposed acceptance limits for this campaign — not accuracy claims)

(`scripts/limits.py`)

- Mesh 1.0 µm vs 0.5 µm (margin 200 µm fixed) and, independently, margin 200 µm vs
  400 µm (mesh 1.0 µm fixed): at each of 17.7 / 19.45 / 21.2 GHz, ΔL ≤ 5 %, ΔQ ≤ 10 %,
  denominator = the finer-mesh / larger-domain result; a nonpositive or near-zero
  denominator invalidates the comparison. Exceeding a limit stops the campaign as
  `UNCONVERGED`. Gated on single-ended L/Q; differential is reported.
- Fit: `|Zfit − ZEM|/|ZEM| ≤ 5 %` at each band frequency; RMS/max over 17.7–21.2 GHz
  and two-port |S| residuals are reported (no limit on S). The model is qualified
  only inside the tested band and for this exact geometry.
- Control: synthetic lossless L recovered within 1 % in L and complex Z.
- Process/temperature: nominal published stackup point only. Spread, temperature
  coefficients and Monte Carlo are **unsupported**; no invented ±% sweep, no
  inherited HBT corner labels. Stackup source: `stackup/SG13G2.xml` (hash in
  `INPUTS.json`; metal thickness, dielectric and conductivity are read from it by
  `run_openems.py`).

Outcomes (the `STATUS` line of a record): `QUALIFIED`, `UNCONVERGED`,
`FIT_FAILED`, `CAPABILITY_UNAVAILABLE`.

## Provenance and hashes

Method source: `2AMLogic/sg13g2-vco` @ `ee69f8529df347b871f52067f6f054821ac75b32`,
`sim/inductor-model/em-extraction/` (read with `git show <commit>:<path>`; the
sibling working tree on the authoring host was at a later commit, which is
irrelevant to the pinned blobs). `INPUTS.json` lists every file with its role and
sha256: `verbatim` (byte-identical to the pinned blob: GDS/JSON, stackup,
`emlib.py`, `gen_geometry.py`, `run_openems.py`, `setup_pdk_overlay.sh`),
`original` (unmodified source of an adapted file, kept in `upstream/` for diffing),
`adapted` (`run_extraction.sh`, `postprocess_p1.py`, `fit_p1.py`, `compare_p1.py`),
`new`. Check with `python3 scripts/hash_inputs.py --check`. Every record embeds the
current hashes and whether each verbatim file still equals its source.

No sibling result is copied. The sibling's p1 numbers (cited in
`spec/porting-plan.md` §4.2) are historical comparison only, to be compared
against this campaign's own output after it exists; the fit's optimiser seeds are
order-of-magnitude heuristics, never results.

## Stages and commands

```
sim/passive-p1/run_extraction.sh                                   # all stages
EM_STAGES="post fit compare" sim/passive-p1/run_extraction.sh      # from saved outputs
```

`EM_STAGES` ⊆ `geometry em convergence post fit compare` (see the header of
`run_extraction.sh`). Prerequisites are checked up front and a missing one ends in
a `CAPABILITY_UNAVAILABLE` record (exit 3):

- openEMS on PATH and `$OPENEMS_PYTHON` (default `~/opt/openEMS/venv/bin/python`)
  importing `openEMS, CSXCAD, gds2openEMS`;
- `klayout`, git and network for the geometry stage (two pinned IHP helper repos are
  cloned to `$TMPDIR`; the PDK tree is not modified);
- `$FIT_PYTHON` (default `python3`) with numpy and scipy; ngspice for `compare`;
- an IHP-Open-PDK v0.3.0 tree (`$IHP_PDK_ROOT`, `$PDK_ROOT/ihp-sg13g2`, or
  `~/share/pdk/ihp-sg13g2`).

`run_extraction.sh` itself installs nothing; a user-owned toolchain that satisfies every
prerequisite above is built by `runner/` (next section). On a host without
numpy use a throwaway environment (for example `uv venv /tmp/venv && uv pip install
--python /tmp/venv/bin/python numpy scipy`, then `FIT_PYTHON=/tmp/venv/bin/python`).
Use `EM_THREADS` (default 2) to keep a shared host usable.

The solver is single-process FDTD; the three solves (baseline, mesh 0.5 µm,
margin 400 µm) take on the order of minutes to tens of minutes each in the sibling
log (the 0.5 µm mesh ~10 minutes there). That wall time is the sibling's, a
planning figure only.

Controls (no EM solver, a few seconds, one local `ngspice -b` per check):

```
python3 sim/passive-p1/scripts/controls.py all [--write-record]      # needs ngspice, numpy, scipy (requirements-sim.txt)
python3 sim/passive-p1/scripts/hash_inputs.py --check
```

CI (job `sim-smoke`, pinned ngspice 46) runs `controls.py all` **without**
`--write-record` after `pip install -r requirements-sim.txt` (numpy + scipy with
version bounds; `requirements-test.txt` stays simulator-free). A missing
dependency, crash or failed control fails the job, and the job's clean-tree gate
confirms nothing was written. This is an automated check of the *synthetic
numerical controls only*. A pass does **not** establish EM convergence, does not
exercise openEMS, and does **not** qualify p1; the EM campaign remains pending.
It is also distinct from the evidence-format checks (`evidence-formats` job),
which validate record structure and hash integrity, not numerical correctness.

## Layout

```
INPUTS.json        pinned source commit + sha256 of every copied/adapted/new input
run_extraction.sh  stage driver (adapted)          upstream/   unmodified originals of adapted files
scripts/           emlib, gen_geometry, run_openems, setup_pdk_overlay (verbatim);
                   postprocess_p1, fit_p1, compare_p1 (adapted); p1chain, limits,
                   make_record, controls, make_synthetic, hash_inputs, gds_xor (new)
gds/ stackup/      pinned geometry and IHP's openEMS stackup
fixtures/          synthetic lossless-L Touchstone (known answer; NOT an EM result)
results/           solver outputs and derived metrics (see below)
fit/               fit parameters and the candidate .spice
records/           append-only: one new file pair per run, never edited
solver-artifacts/  append-only: one frozen, hashed package per new record (see below)
run_log/           stage logs
```

`results/geometry_regen/` and `run_log/` hold the geometry-stage output. Large
disposable solver files (`sub-*/et`, `sub-*/ht`, regenerable excitation traces,
~2.5 MB each) are deleted by the script after each solve and are **not**
tracked; the port voltage/current probes the S-parameters are computed from, the
`.s2p`, `port_information.json` and `run_meta.json` are kept. A fitted `.spice`
becomes a model only if a record says `QUALIFIED`; until then `fit/p1_fit_candidate.spice`
is a candidate, labelled as such in its header.

## Records

Records are append-only (`make_record.py` opens files exclusively). A re-run from
saved outputs writes a **new** record whose `numerical_digest` must equal the
earlier one if nothing changed; it never modifies the earlier record. The
`git_commit` inside a record is the repository HEAD when it ran (the PR's base
commit if run before committing); the input hashes identify the exact scripts.

## Frozen solver-artifact packages (issue #58)

`results/`, `fit/` and `run_log/` are reused scratch: the next run overwrites them.
A record that only named those paths could therefore be orphaned from the bytes it
was derived from. Every **new** record (`"record_schema": 2`) is instead preceded by
a frozen copy of the artifacts the outcome consumed:

```
solver-artifacts/<YYYYMMDD>-<HHMMSS>-<git-sha>/     (same id as the record, without the status)
    manifest.json   schema, run_id, status, stages, files[] = {path, sha256, bytes}
    settings.json   stages, commands, failed command, EM_* solver settings
    results/ fit/ run_log/   byte copies, same relative layout as the working tree
```

The record names the package path and the sha256 of `manifest.json`
(`artifact_package`), and derives its numbers from the **frozen** bytes.
Publication (`scripts/freeze_package.py`, called by `make_record.py`):

- the run directory is created with `mkdir`; an existing id (complete or interrupted) is
  refused, never merged or reused;
- required files depend on the outcome (`required_paths()`): `QUALIFIED` needs the three
  `.s2p` + `port_information.json` + `run_meta.json`, the post-processing outputs, the fit
  files, `p1_compare.json` and the logs of the requested stages; `UNCONVERGED` stops after the
  post-processing outputs; `FIT_FAILED` adds the fit log (and fit/compare files when they
  exist for it); `CAPABILITY_UNAVAILABLE` keeps whatever diagnostics (logs) exist and invents
  no solver data. Files from an earlier run that the outcome did not consume (for example a
  stale `p1_compare.json` beside an `UNCONVERGED` record) are not frozen. Raw FDTD field dumps
  are not stored;
- a missing required file refuses publication **before** anything is created (exit 2, no
  record); `.INCOMPLETE` marks the directory until `manifest.json` is written last; any
  failure removes the directory this call created; a failed record write removes the package;
- legacy records (the two committed before #58) are neither edited nor given invented
  artifacts; they remain valid under their stated existence-only limitation.

CI (`check_evidence_formats.py`) fails a package with a missing or unlisted file, a
sha256/size mismatch, an absolute, `..`, symlinked or dot-file path, a missing required output,
a leftover `.INCOMPLETE`, an orphan package, a manifest hash that differs from the record's, or
record `metrics`/`compare` that differ from the packaged JSON; and the append-only check fails
any modification, deletion, rename or **addition** under a committed run id.

**Hash integrity is not numerical qualification.** A passing check means the bytes in the
package are the bytes the record names. It does not say the solver result is converged, the fit
is good, or the model qualified: that is the record's status, produced by the analysis against
the declared limits, and CI never re-derives it.

### Re-analysing a frozen package

```
python3 sim/passive-p1/scripts/reanalyze_frozen.py \
    sim/passive-p1/solver-artifacts/<id> --out /tmp/p1-reanalysis-<id> \
    --python /path/to/python-with-numpy-scipy          # [--dry-run] [--stages "post fit compare"]
```

It verifies the manifest first, copies only the solver numerical artifacts into a fresh
`--out/work`, re-runs `postprocess_p1.py`, `fit_p1.py` and `compare_p1.py` there, and writes
`--out/reanalysis.json` (exit codes, sha256 of every output, and whether the re-derived
metrics/compare JSON equal the frozen ones). It writes no record, refuses `--out` inside the
package, `records/` or `solver-artifacts/` or into a non-empty directory, and never edits the
original record or package. A reanalysis that changes the picture is a reason to publish a
**new** record that says why, not to edit the old one.

## klayout-tools friction

No klayout-tools gap was hit by this campaign: it uses `klayout` headless directly
for geometry and `ngspice -b` for the model comparison, not `klt`. The standing
gap (`klt mom` cannot extract spirals / export Touchstone,
[klayout-tools#1517](https://github.com/2AMLogic/klayout-tools/issues/1517)) is the
reason this route exists and is already filed; it is not re-filed.

## CI coverage

The permanent evidence package is `records/<id>-<STATUS>.md` + `.json`, the
input files named by the record's `input_hashes` (existence checked) and, for
`record_schema` 2 records, the frozen `solver-artifacts/<id>/` package (hash-checked
and history-protected; see above) --
`.github/scripts/check_evidence_formats.py` validates and history-protects the
records and packages. `results/`, `run_log/` and `fit/` are mutable working output and are
not protected. `SYNTHETIC-*` pipeline-smoke records must stay out of `records/`
(the checker rejects them there). See the top-level README.
