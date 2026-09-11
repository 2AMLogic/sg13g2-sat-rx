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
  recorded design decision that waits on the ratified spec. It is not a
  default and nothing here assumes one answer.
- **A chosen receive band.** The band is the first row the ratification
  issue has to settle, because the LNA matching network, the mixer's LO
  range, and the IF plan all follow from it. Candidates are listed in the
  draft table below; none is ratified.

Until the band is ratified, the only work is testbench methodology: what
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

## Target specification (DRAFT — engineering to ratify, see issue #1)

| Parameter | Target (DRAFT) | Stretch (DRAFT) |
|---|---|---|
| Receive band | Candidates: L/S-band 1–4 GHz (GNSS, LEO IoT, S-band TT&C) or Ku-band 10.7–12.75 GHz downlink — ratification picks one | Ku-band if L/S is ratified first |
| LNA gain (S21) | ≥ 15 dB across the ratified band | ≥ 20 dB |
| LNA noise figure | ≤ 1.5 dB across band, all corners | ≤ 1.0 dB |
| Input match (S11) | ≤ −10 dB across band | ≤ −15 dB |
| Stability | Unconditional (k > 1) across band, all corners | — |
| LNA IIP3 | ≥ −10 dBm | ≥ −5 dBm |
| Mixer conversion gain | ≥ 5 dB | ≥ 10 dB |
| Mixer noise figure (SSB) | ≤ 12 dB | ≤ 8 dB |
| Mixer IIP3 | ≥ 0 dBm | — |
| LO-to-RF leakage | ≤ −30 dBm at the RF port | — |
| IF bandwidth | ≥ 100 MHz | ≥ 500 MHz |
| Supply / power (LNA + mixer) | 1.2–2.5 V, ≤ 30 mW | ≤ 15 mW |
| AREA | Ratified absolute bound — to be set at ratification | — |
| AREA-EFF | Efficiency composite per klayout-tools#1086 (dead margins, bbox tightness, utilization floor, economy review) | — |

All S-parameters, gain, and match figures are defined at 50 Ω reference
impedance at both ports. Every row is DRAFT: values come from general SiGe
LNA and active-mixer literature, not from any simulation of this PDK.

## Repo layout

```
design/        schematics (xschem)
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
sim/           analog testbenches + PVT corner results
spec/          ratified spec + decision records
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
