# sg13g2-sat-rx

A Satellite-band receive front end (LNA + mixer) on the [IHP SG13G2](https://github.com/IHP-GmbH/IHP-Open-PDK) open PDK,
designed by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the open-source
flow — xschem + ngspice, with layout, DRC, and LVS through klayout-tools.

It is the per-element receive chain for an open-source satellite antenna
array: a SiGe HBT low-noise amplifier followed by a downconversion mixer, so
that every antenna element gets its own quiet, linear path from the sky down
to an intermediate frequency where beam steering can happen.

## Status

**Just opened, specification phase.** Nothing is designed yet, nothing has been
taped out, and nothing has been measured.

Deliberately not being built yet:

- **The antenna elements and the array itself.** Those are board-level or
  ceramic objects, not silicon. This repo is the chip behind one element.
- **The analog-to-digital converter and the beamformer.** Which side of the
  mixer the beam steering lives on — RF phase shift per element, LO-phase
  shifting at the mixer, or IF/digital beamforming behind an ADC — is a
  recorded design decision that waits on the LNA and mixer benches. It is not
  a default and nothing here assumes one answer. The three options, what each
  would ask of this chip, and the criteria that will decide it are recorded in
  [`spec/decision-records/0002-beamsteering-partition.md`](spec/decision-records/0002-beamsteering-partition.md)
  (status: *deferred*, deliberately).
- **A ratified receive band.** The draft commits to the Ka-band satellite
  downlink, 17.7–21.2 GHz, because that is where this PDK's SiGe HBTs
  (`npn13g2`: fT min 300 / target 350 GHz, fmax min 400 / target 450 GHz,
  per the PDK process spec §3.1) are decisive. The LNA matching network, the
  mixer's LO range, and the IF plan all follow from that row — and it is the
  one row ratification may still move (to the Ku-band downlink,
  10.7–12.75 GHz) if open-tool EM verification at 20 GHz proves the binding
  constraint. The argument, the Ku fallback, and the explicit trigger that
  would move the band are recorded in
  [`spec/decision-records/0001-band-selection-ka-vs-ku.md`](spec/decision-records/0001-band-selection-ka-vs-ku.md)
  (status: *proposed*, not ratified).

Until the spec is ratified, the only work is testbench methodology: what
ngspice can and cannot measure for S-parameters, noise figure, and
conversion gain on this PDK, stated with every assumption.

## Built agent-native

Every specification, decision record, testbench, and line of documentation in
this repo is produced by AI agents working from a ratified spec and an
append-only evidence trail — not human-authored work that agents merely
assisted with. Verification is the product: every claim traces to a recorded
result. Where the agents hit friction with the open-source tooling — most often
[klayout-tools](https://github.com/2AMLogic/klayout-tools) — that friction gets
filed as a public issue against the tool itself, so the fix benefits everyone
using IHP SG13G2, not just this repo.

## Target specification

**The target spec lives in [`spec/target-spec.md`](spec/target-spec.md).** It
is **DRAFT** — not one row is ratified, and ratification is a separate event
that flows through the two-key mechanism (EE key + market key), recorded as a
decision record under [`spec/decision-records/`](spec/decision-records/).

That document carries the full table (LNA gain / NF / S11 / S22 / stability /
IIP3 / P1dB, mixer conversion gain / SSB NF / IIP3, the cascade rows, LO
range and leakage, IF plan, supply and power, AREA and AREA-EFF), and with it
the things a table alone cannot say: the explicit 50 Ω port convention at
every RF port, what "across band" requires at every corner, the per-row source
citation, the PDK-derived corner set, and an honest `NEEDS-VERIFICATION` flag
on every bound that is an engineering target rather than a traceable
published result.

Alongside it:

- [`spec/porting-plan.md`](spec/porting-plan.md) — what transfers from
  `sg13g2-lna` (S-parameter/NF bench methodology), `sg13g2-vco` (EM-extracted
  passives, the LO/passives half) and `sg13g2-comparator` (the `sim/harness/`
  structure), the exact IHP-Open-PDK model files this block depends on, and
  what is genuinely new: the mixer bench and the 20 GHz passive question.
- [`spec/decision-records/`](spec/decision-records/) — the band record
  (proposed, with the Ku fallback trigger) and the beamsteering-partition
  record (deferred, with its criteria).

## Repo layout

```
design/        schematics (xschem)
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
sim/           analog testbenches + PVT corner results
spec/          target spec (DRAFT) + porting plan + decision records
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
