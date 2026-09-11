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
- **A ratified receive band.** The draft below commits to the Ka-band
  satellite downlink, 17.7–21.2 GHz, because that is where this PDK's SiGe
  HBTs (about 300 GHz fT, 450 GHz fmax) are decisive and a 130 nm CMOS
  open PDK cannot follow. The LNA matching network, the mixer's LO range,
  and the IF plan all follow from that row, so it is the first thing the
  ratification issue settles — and the one row the ratification may still
  move (to the Ku-band downlink, 10.7–12.75 GHz) if open-tool EM
  verification at 20 GHz proves the binding constraint.

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

## Target specification (DRAFT — engineering to ratify, see issue #1)

| Parameter | Target (DRAFT) | Stretch (DRAFT) |
|---|---|---|
| Receive band | Ka-band satellite downlink, 17.7–21.2 GHz (K-band by ITU letter), every row below held across the full band | Fallback if ratification moves it: Ku-band downlink, 10.7–12.75 GHz |
| LNA gain (S21) | ≥ 20 dB across band (two-stage cascode) | ≥ 25 dB |
| LNA noise figure | ≤ 2.5 dB across band, all corners | ≤ 2.0 dB |
| Input match (S11) | ≤ −10 dB across band | ≤ −15 dB |
| Stability | Unconditional (k > 1) across band, all corners | — |
| LNA IIP3 | ≥ −15 dBm | ≥ −10 dBm |
| Mixer conversion gain | ≥ 8 dB (active, Gilbert-cell class) | ≥ 12 dB |
| Mixer noise figure (SSB) | ≤ 12 dB | ≤ 9 dB |
| Mixer IIP3 | ≥ −5 dBm | ≥ 0 dBm |
| LO range / LO-to-RF leakage | 16.7–20.2 GHz (1 GHz IF, low-side) / ≤ −30 dBm at the RF port | LO from an on-PDK LC VCO (sg13g2-vco class) |
| IF bandwidth | ≥ 500 MHz (one LEO broadband channel) | ≥ 1 GHz |
| Supply / power (LNA + mixer) | ≤ 2.5 V rails, HBTs kept inside BVCEO by cascoding; ≤ 40 mW | ≤ 25 mW |
| AREA | Ratified absolute bound — to be set at ratification | — |
| AREA-EFF | Efficiency composite per klayout-tools#1086 (dead margins, bbox tightness, utilization floor, economy review) | — |

All S-parameters, gain, and match figures are defined at 50 Ω reference
impedance at both ports. Every row is DRAFT: values come from published SiGe Ka-band LNA and
active-mixer results and the SG13G2 device menu's static process numbers,
not from any simulation of this PDK. The band and the targets are sized to
exploit the PDK, not to be easy: at 20 GHz the HBTs still have an fT/f
ratio near 15, so gain and noise headroom are real, while on-chip inductors
and transmission lines on the thick top metals are small enough to sit on
the die. That also fixes the array geometry the chip serves: half-wave
element spacing at 20 GHz is about 7.5 mm, so one front end per element is
a natural tiling.

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
