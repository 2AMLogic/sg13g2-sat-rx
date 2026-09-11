# sg13g2-sat-rx — agent instructions

Open-source canary block: a Satellite-band receive front end (LNA + mixer) on the IHP SG13G2 PDK,
designed and verified by AI agents — an **analog** block.

- **PDK**: IHP SG13G2 (open PDK).
  Schematics in xschem, simulation in ngspice.
  Layout, DRC, and LVS go through klayout-tools (`klt`).
- **Friction protocol (the canary's job)**: every time klayout-tools is
  awkward, missing a capability, or wrong for what you need, file an issue at
  `2AMLogic/klayout-tools` describing the tool gap generically — that tracker is
  scoped to the tool, so keep design-specific detail (spec values, this repo's
  content) out of it and describe the gap, not the design.
- **Verification is the product**: no claim without a testbench. Recorded
  results are append-only evidence; a result is not superseded by deletion, it
  is superseded by a later record that says why.
- Spec changes go through `spec/` with a decision record. Agents do not relax
  the ratified spec to make a result pass.

- **Scope is the per-element chain, nothing wider**: this repo builds an
  LNA and a mixer. The antenna elements, the array, the ADC, and the
  beamformer are out of scope until a decision record in `spec/` admits a
  piece of them — do not let the array ambition pull board-level or digital
  work into the block. The draft band is the Ka-band downlink (17.7–21.2 GHz) and it is
  ratified before it is designed to: do not size a matching network for a
  band nobody has ratified, and do not
  call a design "wideband" unless every spec row holds across the whole
  ratified band at every corner, not at one center frequency.

## Harness bootstrap

Copy `sg13g2-lna` for the small-signal half — its S-parameter and
noise-figure bench methodology (50 Ω port convention, each ngspice analysis
stated beside its number) is the LNA path here, and its porting plan already
records which SG13G2 HBT and passive model files exist and which (inductors)
do not. Copy `sg13g2-vco` for the LO/passives half — its inductor and
varactor characterization is what the mixer's LO port and any on-chip
matching inductors depend on. Copy `sg13g2-comparator` for the `sim/harness/`
corner and evidence structure, which this repo's generated harness already
mirrors. Coordinate through klayout-tools issues; never copy a number across
repos without its derivation.

<!-- BEGIN LOOM ORCHESTRATION -->
This repository uses [Loom](https://github.com/rjwalters/loom) for AI-powered development orchestration — see the Loom repository for the full guide (roles, labels, worktrees, configuration). When installed, Loom also writes a locally-substituted copy of that guide to `.loom/CLAUDE.md`.
<!-- END LOOM ORCHESTRATION -->
