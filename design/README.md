# design

Schematics (xschem). Sources, netlist export and design notes:

* `lna_stage1.sch` / `.sym` — first LNA stage (npn13G2 cascode, ideal behavioral matching), issue #28.
* `export_netlist.sh` — regenerates `netlist/lna_stage1.spice` from the sources (via `klt netlist --block`) (`--check` verifies).
* `netlist/` — the derived netlist (never edit by hand).
* `lna_stage1.md` — topology argument, bias network, matching derivation, what the evidence shows.

The simulation benches live in `sim/` (`sim/lna-sparam-nf` consumes `netlist/lna_stage1.spice`).
