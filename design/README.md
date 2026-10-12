# design

Schematics (xschem). Sources, netlist export and design notes:

* `lna_stage1.sch` / `.sym` — first LNA stage (npn13G2 cascode, ideal behavioral matching), issue #28.
* `export_netlist.sh` — regenerates `netlist/lna_stage1.spice` from the sources (via `klt netlist --block`) (`--check` verifies).
* `netlist/` — the derived netlist (never edit by hand).
* `lna_stage1.md` — topology argument, bias network, matching derivation, what the evidence shows.
* `lna_match_tradeoff.md` — first-stage NF vs input-match feasibility (issue #74): ideal input networks on the frozen stage cannot close the gap; next decision filed as #79. No spec row claimed.

Item 1 currently attests the LNA first stage only; the mixer has no committed design source. (`signoff/evidence/item1-design-sources.json` `block_coverage`; checked by `.github/scripts/evidence_checks/block_coverage.py`.)

The simulation benches live in `sim/` (`sim/lna-sparam-nf` consumes `netlist/lna_stage1.spice`).
