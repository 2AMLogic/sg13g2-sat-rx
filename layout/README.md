# layout

GDS and DRC/LVS reports.

**The LNA layout does not exist yet.** #79 (the core/sizing decision) has
closed, but the layout is now gated on something further out: **15 of the
stage's 18 elements have no PDK primitive selected in the design**, and the
decision that would select them is not in `spec/`. The derivation is in
`lna_stage1/README.md`; the short version is that `design/lna_stage1.sch` uses
xschem's generic `res.sym`/`capa.sym`/`ind.sym` for every resistor, capacitor
and inductor, so the netlist carries values and no devices — and two of those
values (`Cb2` 10 pF, `Cblk_in` 1 nF) are outside the declared range of the
PDK's own 2-terminal MIM device. **No T1 item 2/3/4/11 citation exists in
`signoff/block-manifest.json` from anything in this directory.**

What is here:

- `probe-readiness/` — a non-claiming klt layout-chain readiness probe
  (issue #185, re-run at the 0.8.0 pin in #246): one throwaway cell with an
  `npn13G2` HBT, a `cmim` MIM cap and an `rsil` resistor from the PDK's own
  primitives, run through
  `klt drc`/`extract`/`lvs`/`ring-check`/`economy` once, with per-tool records
  and the tool gaps found (filed upstream). It is not the LNA layout and
  cites nothing.
- `lna_stage1/` — a non-claiming **device-group layout study** of the LNA
  first stage (issue #198): the 3 `npn13G2` devices and the substrate guard
  ring — the only elements of the stage that resolve to a PDK primitive —
  drawn deterministically, with the whole chain run over them at the pinned
  klt (`drc` **clean**, `erc` supply half **clean**, `ring-check`
  **continuous** on three layers, `economy`, plus the expected `lvs`
  `mismatch`). Its main product is the recorded, machine-regenerable
  derivation of **why items 2 and 3 are not claimed** and what `spec/`
  decision would unblock them. It is not the LNA layout and cites nothing.
- `toolchain.json` — the capability pin for the layout/ verification flow
  (which `klt` commands this directory's runners require, and the exact klt
  commit last verified against this PDK). Append-only comment block: each pin
  bump, re-run and correction is a new paragraph.
- `toolchain_pin.py` — the **one shared** implementation of that pin check,
  which `toolchain.json`'s own comment block asks every runner to import
  rather than re-derive: the required-command check, the PDK-primitive-cell
  check, and PDK resolution. Also runnable directly:
  `python3 layout/toolchain_pin.py --check --klt <path>`.
