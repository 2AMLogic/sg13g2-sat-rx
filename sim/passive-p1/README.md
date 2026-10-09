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

Run `sim/passive-p1/run_extraction.sh` on a host that has openEMS (below) to
produce the real record; it appends a new record and never edits an old one.

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

Host provisioning is out of scope; the script installs nothing. On a host without
numpy use a throwaway environment (for example `uv venv /tmp/venv && uv pip install
--python /tmp/venv/bin/python numpy scipy`, then `FIT_PYTHON=/tmp/venv/bin/python`).
Use `EM_THREADS` (default 2) to keep a shared host usable.

The solver is single-process FDTD; the three solves (baseline, mesh 0.5 µm,
margin 400 µm) take on the order of minutes to tens of minutes each in the sibling
log (the 0.5 µm mesh ~10 minutes there). That wall time is the sibling's, a
planning figure only.

Controls (no EM solver, a few seconds, one local `ngspice -b` per check):

```
python3 sim/passive-p1/scripts/controls.py all [--write-record]      # needs numpy
python3 sim/passive-p1/scripts/hash_inputs.py --check
```

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

## klayout-tools friction

No klayout-tools gap was hit by this campaign: it uses `klayout` headless directly
for geometry and `ngspice -b` for the model comparison, not `klt`. The standing
gap (`klt mom` cannot extract spirals / export Touchstone,
[klayout-tools#1517](https://github.com/2AMLogic/klayout-tools/issues/1517)) is the
reason this route exists and is already filed; it is not re-filed.
