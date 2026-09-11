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
| `report.py` | Record-id minting (`<YYYYMMDD>-<HHMMSS>-<short-sha>`), grid summaries, per-axis sensitivity, spec-check evaluation, and an append-only Markdown writer. |
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
  "ngspice_min_major": N, "python_min": "3.11"}`. Absent means "nothing
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
