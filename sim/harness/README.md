# sim-harness-core

The generic ~40% of an analog canary's `sim/` harness — PDK resolution, the
classic five-corner MOS sweep, fragment-based ngspice deck composition, and
append-only evidence recording. Scaffolded by `everyblock/scaffold.sh` into
`sim/harness/` for the `analog` and `mixed-signal` variants (block and chip
kind alike), so a new canary starts from working generic mechanics instead
of re-deriving the split between generic and block-specific by hand-reading
an existing canary's `sim/harness/` package end to end.

**Do not fork or vendor a sibling canary's harness wholesale.** Read one for
reference — `2AMLogic/gf180-sar-adc`'s `sim/harness/` is the implementation
this package was distilled from — but this package *is* the generic core
already extracted from that reading. Extend it in place per block; don't
re-derive it.

## What's here

| Module | Generic core covers |
|---|---|
| `pdk.py` | PDK discovery: env var / `PDK_ROOT` / `sim/pdk.local.json` / `sim/pdk.json` / built-in search-root resolution order. PDK name, variant scheme, and model-file paths come from `sim/pdk.json` (block-authored config, not part of this package) rather than being hardcoded. |
| `corners.py` | The classic five MOS process corners (`tt`/`ff`/`ss`/`fs`/`sf`) as the default corner set, plus the PVT-grid arithmetic (`Corner`, `PvtPoint`, `build_grid`, `supply_points`, `resolve_corners`) and the `sabotage()` negative control. |
| `toolchain.py` | Toolchain pin/drift checking against `sim/toolchain.json` (PDK version, ngspice floor, Python floor). Fully generic already — no block-specific content. |
| `testbench.py` | The `tb.json` manifest schema: netlist-fragment discipline (forbidden directives the harness owns), `checks` validation, `netlist_provenance` semantics. Fully generic already. |
| `runner.py` | `compose_deck()` — assembles one complete ngspice deck from a testbench fragment, the resolved PDK's models, and one PVT point's corner sections. `run_point()` / `run_grid()` execute it and parse measurements. |
| `evidence.py` | `BaseExtensions` — an open, unstructured evidence-record extension slot (`extra` dict + `notes`), so a fresh block has a working evidence path before it has ratified its own schema. |
| `report.py` | Record-id minting (`<YYYYMMDD>-<HHMMSS>-<short-sha>`), grid summaries, per-axis sensitivity, spec-check evaluation, frozen netlist + manifest snapshots, and an append-only Markdown writer. |
| `cli.py` | `list` / `run` / `selftest` subcommands wiring the above together. |

Every module's docstring opens with a `GENERIC CORE` paragraph (what it is
safe to use unmodified) and, where one exists, an `EXTENSION POINT`
paragraph (what a block is expected to add, and how). Read those before
editing — they say which changes belong in *this* package versus which
belong in a block-specific replacement or subclass.

## Extension points — what a block layers on top

This core deliberately does not know:

- **This PDK's device model section names**, beyond the assumption that a
  `tt`/`ff`/`ss`/`fs`/`sf` sweep is the useful default (`corners.py`). Most
  open PDKs' ngspice model libraries use exactly these section names for the
  MOS family; if this PDK's do not, edit the `sections` tuples on
  `corners.CORNERS`' built-in entries — that is the one PDK-specific edit
  most blocks need before their first run.
- **Block-specific corners.** A capacitor-dominated block (e.g. a SAR ADC's
  CDAC) or a resistor/BJT-dominated one (e.g. a bandgap) needs corners this
  core does not define. Call `corners.register_corner()` /
  `register_corner_set()` to add them without editing the built-in set.
- **Block-specific evidence-schema fields.** Once a block has ratified its
  own evidence convention (which fields every record must carry — FFT
  metadata, linearity methodology, Monte Carlo convention, whatever this
  block's spec doc names), replace `evidence.BaseExtensions` with a subclass
  or a fresh dataclass carrying named, *validated* fields instead of routing
  everything through the generic `extra` bag. See
  `2AMLogic/gf180-sar-adc`'s `sim/harness/evidence.py` for a worked example:
  five named extension groups, each with its own required-field and
  allowed-value validation.
- **Block-specific netlist injection ahead of the testbench.** A block
  needing PDK-variant-bound subckt aliases (the SAR-ADC reference's MIM
  capacitor wrapper is the worked example) passes an `extra_subckts`
  callable to `runner.compose_deck()` / `run_point()` / `run_grid()` rather
  than editing `compose_deck()` itself.
- **A rendered Markdown record layout beyond the plain one in
  `report.render_markdown()`.** `report.build_record()` already returns
  everything a richer renderer needs (grid, summary, sensitivity,
  evidence, environment); replace only the rendering function once a
  block's evidence convention wants a specific layout (a toolchain-drift
  banner, a rendered per-axis sensitivity table, etc.).

## Configuration this core reads (block-authored, not shipped here)

- `sim/pdk.json` — required. `{"name": ..., "default_variant": ...,
  "model_lib": "path/relative/to/variant/dir", "design_include": "...",
  "search_roots": [...]}`. See `pdk.py`'s module docstring for the full
  shape.
- `sim/pdk.local.json` — optional, git-ignored, same shape, overrides
  `pdk.json` per-machine.
- `sim/toolchain.json` — optional. `{"pdk_version": "...",
  "ngspice_min_major": N, "python_min": "3.11"}`. `pdk_version` is compared
  exactly against `Pdk.version`: the install's `.fetched-version` first line,
  else the first line of `SOURCES`, else `unknown` (a drift when a pin is set). Absent means "nothing
  pinned" (reported, not a failure).
- `sim/<experiment-slug>/testbench/tb.json` — one per experiment. See
  `testbench.py`'s module docstring for the manifest schema.

## Running it

From `sim/`:

```
python3 -m harness.cli list
python3 -m harness.cli run <experiment-slug> --corners mos
python3 -m harness.cli selftest <experiment-slug>
```

### Where `run` simulates (`--backend`)

`run` picks an execution backend from the size of the grid (issue #134):

| Points | Default | What happens |
|---|---|---|
| more than one | `batch` | `klt_driver.run_grid_klt` writes one `klt sim` body + request per supply value (per supply x temperature if the deck reads `temp_c`), every process x temperature corner in each, with `options.stage_model_inputs`. The requests are submitted with `klt sim --backend batch`; the returned per-corner logs are parsed into the same `PointResult`s and written to `corners/<record-id>/<corner-id>.log`. |
| exactly one | `local` | `runner.run_grid` runs one `ngspice -b` on this host (a debug probe). |

- `--backend local` forces the local path for any grid. `--jobs`/`--num-threads` apply to the local path only, and a multi-point local grid refuses `--jobs` above 2.
- A request that returns no usable report (klt exit 1/2, missing credentials, ...) stops the run with exit 1: nothing is recorded and nothing is re-run locally. Bodies, requests and any reports stay under `<workdir>/klt-<timestamp>/`.
- A point the reports do not cover, a corner klt graded `error`, a missing log, or a missing measurement is an explicit `error`/`failed` point, so the record's status is `error`. It is never dropped.
- Every requested PVT identity must come back exactly once (issue #139): a process x temperature x supply returned twice -- inside one report or across two jobs -- is an explicit ambiguous `error` point naming the reports and their statuses, never a first/last-wins pick, so entry order cannot change the verdict. A returned corner whose `temperature_c` does not parse as a finite number is a collection error (exit 1, nothing recorded, no local fallback), and a corner naming a process the request never asked for is named on the points it left uncovered instead of being silently ignored.
- An evidence-writing batch run takes its PDK artifact identity from the reports (`pdkartifact.offhost_identity`: staged model hashes and runner/client klt match). If that check fails, exit 3 before any log is copied. The local install is still verified before anything is submitted.
- The record keeps the existing schema. `environment.execution` holds the backend and each request's remote job id, status, engine and runner klt version, and the Markdown Environment section shows them on a `- Execution:` line. The `ngspice` field names the off-host engine (`ngspice-46 via klt sim batch (recording host: ...)`).
- Corners must each select exactly one `.lib` section, and no two corners may share a section. A `--sabotage` set fails this check, so run it with `--backend local`. `selftest` is local-only.
- `--runner-version-check warn` passes klt's runner/client skew policy through to the requests. A skewed runner then runs the grid, but `offhost_identity` refuses to record its results, so use it only with `--no-write` (method checks).
- `--no-stage-models` (requires `--no-write`) leaves the models out of the requests, so the runner uses its own image's models. A skewed runner that ignores `stage_model_inputs` needs it (klayout-tools#2877, #2901). Those models are not hashed, so the run is a method check only.
- `--temperatures` / `--supplies` narrow the grid to a subset of the testbench's own declared levels (an undeclared level is refused, exit 2). Combined with a single `--corners` entry this records one local point. An evidence-writing subset run needs `--subset-reason`, which the record prints as the subset Justification. The record is a declared subset, and its checks are still evaluated, so a sensitivity check over an axis the subset does not sweep makes the status `fail`.
- `--klt-cmd` picks the klt client (e.g. `uvx --from klayout-tools==X.Y.Z klt`). `--timeout-s` is the per-corner timeout (default 1800 s for klt, 300 s local).

### Frozen inputs: what a record freezes and how to read it back

An evidence-writing `run` freezes both of a record's inputs next to the
record, under `sim/<experiment-slug>/netlist-snapshots/`:

- `<record-id>.spice` — the DUT netlist fragment, verbatim (issue #93).
- `<record-id>.tb.json` — the testbench manifest, byte-identical to the
  `tb.json` the run was loaded from (issue #141): the analyses, measurement
  expressions, simulator options, parameters, checks and claim the record's
  numbers were produced *by*. The record's `**Manifest**:` header line names
  this file and its SHA-256; records without that line are legacy and carry
  no manifest artifact.

To recover a historical run's settings, read the frozen package: verify
`sha256(netlist-snapshots/<id>.tb.json)` against the digest declared on the
record's `**Manifest**:` line, then read the JSON fields directly
(`analyses`, `measure`, `params`, `options`, `checks`, `claim`, ...). Those
fields are the complete deck inputs — re-deriving the ngspice deck from them
is exactly what `runner.compose_deck()` does with a manifest's fields, so a
later working-manifest edit can neither change the frozen package nor the
interpretation of the record's settings. (This recovers the *inputs*; it is
not a bitwise-numerical-replay promise — simulator version and PDK state are
separately recorded in the record's Environment section.)

Publication refuses (`exit 1`, nothing written) if the working manifest or
netlist fragment changed — or vanished — between load and publication: the
grid is simulated from the state captured at load, so a package frozen
afterwards would not describe the state the numbers came from. The refusal
also removes the run's own `corners/<record-id>/` log directory — minted by
that run, never evidence — so a refused run leaves no orphan log package the
evidence checker would flag. (`run.py` drivers that ingest klt reports
published by an earlier `characterize` enforce the same rule at ingest by
refusing unless each report's generated body deck still matches the reloaded
testbench inputs.)

`harness/` needs no third-party dependencies — everything above is Python
standard library, so it runs the same way in a fresh agent container as on a
developer box, once `sim/pdk.json` points it at an installed PDK and
`ngspice` is on `PATH`.

## Why extend in place rather than fork this package per block

The five/eight-corner sweep, the deck-composition mechanics, the
toolchain-drift guard, and the append-only record writer are identical work
across every open-PDK analog canary this scaffold produces. A block that
forks this package and diverges immediately loses the ability to pull a
future core fix (a corrected `sabotage()` self-test, a `toolchain.py` bug
fix) without a manual merge. Extending through the documented extension
points — subclassing, registration functions, injected callables — keeps
that path open.
