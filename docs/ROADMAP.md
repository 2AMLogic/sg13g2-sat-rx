# Roadmap

sg13g2-sat-rx is a satellite-band receive front end (SiGe HBT LNA + downconversion
mixer) on the IHP SG13G2 open PDK, built to exercise the open flow and
[klayout-tools](https://github.com/2AMLogic/klayout-tools) end to end.

Status as of 2026-11-15, `main` @ `b11e09c`. The label-generated queue view is
[`WORK_PLAN.md`](../WORK_PLAN.md); merged work is in [`WORK_LOG.md`](../WORK_LOG.md).

## Where it stands

**Stage: schematic feasibility and testbench methodology.** Nothing is laid out,
no spec row is claimed met, nothing has been taped out.

Machine-graded verdict ([`signoff/tier-report.json`](../signoff/tier-report.json),
klt 0.8.0, re-graded by `signoff.yml`): **tier none, T1 3/11 items met.**

| T1 item | Verdict | What backs it / what is missing |
|---|---|---|
| 1 Design sources | met | `design/lna_stage1.sch` + derived netlist, LNA first stage only; the mixer has no design source (`signoff/block-coverage.json`) |
| 2 Layout | unmet | `layout/lna_stage1` (#198) records why it does not claim: 1 of 18 stage elements is drawable at its designed value; the gate is a `spec/` decision record on passive realization |
| 3 DRC clean | unmet | as item 2; the probe cell and the #198 device-group GDS both run DRC clean but cite nothing |
| 4 LVS clean | unmet | `npn13G2` does not extract at the pinned release (klt 0.8.0, #246); the curated-deck route is declined by ruling, the runset route is #260 |
| 5 Corner verification vs ratified spec | unmet | every row in `spec/row-coverage.json` is `placeholder_circuit`, `method_absent` or `no_bench` |
| 6 Monte Carlo evidence | unmet | method qualified (`sim/hbt-mismatch-pair`, `MC_METHOD_WORKS`); row 15 is the one statistical row (DR-0007, proposed) and has no mixer to sample |
| 7 Post-layout verification | unmet | needs items 2-4 |
| 8 Characterization report | unmet | needs item 5 |
| 9 Testbenches shipped | met | `signoff/inventories/item9.json` |
| 10 Repo hygiene | met | `signoff/inventories/item10.json` |
| 11 Power delivery (structural) | unmet | needs the layout; the #198 study's `vdd` rail is deliberately unloaded |

Spec ([`spec/target-spec.md`](../spec/target-spec.md)): eleven rows ratified as
targets by DR-0003 (2, 3, 4, 6-11, 17, 18); nine open (1, 5, 12-16, 19, 20).
Decision records 0001, 0004, 0006, 0007 and 0008 are *proposed*; 0002 and 0005
are *deferred*.

Evidence on `main` (all append-only records under `sim/*/records/`):

- **LNA first stage** (`design/lna_stage1`, one cascode, ideal lossless matching):
  the input-match study (`sim/lna-match-tradeoff`) found that no lossless input
  network reaches NF <= 2.5 dB with S11 <= -10 dB at 8 of 18 in-rail PVT points
  on the original core, and #79 closed that finding: the chosen core change
  `ac` — 67 pH of emitter degeneration and a 10 k bias feed with base-current
  compensation, adopted in the schematic — re-runs the same bound screen at
  0/18 jointly-infeasible in-rail points, worst bound 2.459 dB (`hbt_wcs`,
  125 °C, 2.25 V), margin +0.041 dB, an ideal-element screen claiming no spec
  row (`sim/lna-core-variants/records/20261114-031930-fbdf13c.md`). The
  small-signal bench has been re-run on the post-#79 core
  (`sim/lna-sparam-nf/records/20261114-211735-8a92c6e.md`, #250); the
  linearity, headroom and match-tradeoff records still describe the pre-#79
  core by recorded disposition (`design/lna_stage1.md`), with the linearity
  re-run filed as #273.
- **LNA headroom** (`sim/lna-headroom`, stages 1 and 2, PR #242): variant C08
  buys +10 dB input-referred stress-free headroom for 4.4 dB gain and about
  0.06 dB NF; single-tone P1dB is still a one-sided bound, so row 8 is
  undetermined. (Pre-#79 core; the post-#79 small-signal record confirms the
  operating point is unmoved — max Q1 V_CE 1.340 V at 2.5 V vs 1.342 V before.)
- **Mixer**: placeholder circuit only. Topology study: all candidates
  `no acceptable drive in declared sweep`. NF method: `MODEL_ABSENT`
  (no intrinsic device noise in `.tran`). Pumped-admittance and
  conversion-matrix interface probes are method feasibility only.
- **Passives** (`sim/passive-p1`): analysis chain and synthetic controls pass;
  the EM solves are `CAPABILITY_UNAVAILABLE` (no openEMS runner).
- **Layout chain** (`layout/probe-readiness`, re-run at the pinned release
  klt 0.8.0, #246): probe cell DRC clean, `cmim` and `rsil` match in LVS, and
  `npn13G2` still extracts as no device. The curated-deck bipolar gap (G1) is
  **declined by ruling**, so the curated-deck route to an LVS-clean bipolar
  flow in this repo is closed — a later reader should not wait on it. The
  accepted route is the PDK's own runset, reachable once the klt pin moves to
  0.9.0 (#260). New gap from the same run: `klt ring-check` records carry no
  provenance block
  ([klayout-tools#5650](https://github.com/2AMLogic/klayout-tools/issues/5650)).
- **LNA stage-1 layout study** (`layout/lna_stage1`, #198): non-claiming
  realizability study. Of the stage's 18 elements only one (`Xqr`) is drawable
  at its designed value: 8 resistors and 4 capacitors have no PDK primitive
  selected in the schematic, and the 3 inductors have no PDK model at all.
  The device-group GDS (17 `npn13G2` instances and a substrate guard ring)
  runs DRC and the ERC supply checks clean. T1 item 2's gate is therefore a
  `spec/` decision record on passive realization — an operator call, not an
  agent's.

## Now

1. **Verify runset-backed LVS recognises `npn13G2` at klt 0.9.0** (#260, in
   progress; the T1 item 4 route). The 0.8.0 pin's runset allowlist is empty,
   so item 4 has been unreachable by allowlist, not only by the declined
   curated deck; 0.9.0 is the earliest release carrying the `ihp-sg13g2`
   entry. *Done when:* a runset-backed LVS record exists under `layout/`
   stating whether the PDK's own runset recognises the device; `signoff/`
   does not change unless it matches. Non-claiming until then.
2. **Re-run `sim/lna-linearity` on the post-#79 core** (#273). The bench has
   no DUT pin, so its existing record froze the pre-#79 deck as the DUT
   identity and is no longer reproducible from the live tree. *Done when:* a
   new declaration pinned to the post-#79 netlist hash and one campaign
   record are merged.

## Next

- **Stage-1 layout with DRC, LVS and ERC supply evidence (T1 items 2, 3,
  11).** The realizability study (#198) names the three-part decision:
  which PDK resistor flavour realizes each resistor, which MIM primitive
  realizes each capacitor (two, `Cb2` and `Cblk_in`, exceed the declared
  `cmim` maximum as drawn), and how the three inductors are realized.
  *First:* the `spec/` decision record on passive realization (see
  Blocked and waiting).
- **Post-layout re-simulation (T1 item 7)** and the **AREA / AREA-EFF rows
  (19, 20)** via `klt economy`. Unblocked by the layout.
- **Live-verify the stored harness manifest (#230).** The event gate is met:
  `manifests/artifacts/` holds its first manifest
  (`lna-sparam-nf-20261114-211735-8a92c6e.manifest.json`). What remains is
  the live fleet-worker `klt artifact verify` and its evidence record.
- **Headroom table below Rd = 200 ohm.** Needs its own frozen plan version
  (`design/lna_headroom_study.md`), and should be drawn on the post-#79 core.

## Later

- **Second LNA stage.** Row 2 assumes two stages. *First:* does the chosen
  first-stage core leave gain and power budget (rows 2, 18) for it?
- **Real matching passives and band ratification (row 1, DR-0001).** *First:*
  does the p1 inductor qualify in EM at the draft band (#110, DR-0005)?
- **A mixer design source.** *First:* which LO-drive path survives (DR-0008),
  given no candidate has an acceptable drive at the declared sizings?
- **Mixer noise figure (rows 10, 12).** *First:* can a conversion-matrix
  solver be built on the interfaces `sim/mixer-cm-interface-probe` found
  reachable, since ngspice has no pnoise and `.tran` carries no device noise?
- **Cascade rows 12 and 13.** *First:* the LNA-to-mixer interface convention
  (DR-0004).

## Blocked and waiting

| What | Waiting on |
|---|---|
| #110 p1 EM campaign | a provisioned openEMS runner; the operator decision is recorded on the issue |
| DR-0001, 0004, 0006, 0007, 0008 | two-key ratification; no key has been turned on any of them |
| DR-0008 validation plan | separate authorization of simulation spend, which the record does not grant |
| #38 auditor Python runtime | operator hold |
| #4 T1 tracker | an operator decision on how the tracker leaves the triage queue; its body still quotes an older grade, and `signoff/tier-report.json` is the verdict |
| LNA stage-1 passive realization — the T1 item 2/3 gate | a `spec/` decision record; operator call per the #198 realizability study, since every option changes the circuit and would invalidate the post-#79 characterization |

As read today no open issue carries `loom:issue` — the last two that did
(#259, #261) have moved to `loom:building`. The filed next items are #260
(in progress) and #273 (triage).

## Not planned

- The antenna elements, the array, the ADC and the beamformer (`CLAUDE.md`
  scope rule; DR-0002 is deferred on purpose).
- Relaxing a ratified row to make a result pass; a row changes only through a
  superseding decision record.
