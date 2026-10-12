# layout

GDS and DRC/LVS reports.

**The LNA layout does not exist yet** — it waits on the core/sizing decision
(#79). What is here:

- `probe-readiness/` — a non-claiming klt layout-chain readiness probe
  (issue #185): one throwaway cell with an `npn13G2` HBT, a `cmim` MIM cap and
  an `rsil` resistor from the PDK's own primitives, run through
  `klt drc`/`extract`/`lvs`/`ring-check`/`economy` once, with per-tool records
  and the tool gaps found (filed upstream). It is not the LNA layout and
  cites nothing.
- `toolchain.json` — the capability pin for the layout/ verification flow
  (which `klt` commands this directory's runners require, and the exact klt
  commit last verified against this PDK).
