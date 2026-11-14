# Roadmap

sg13g2-sat-rx is a satellite-band receive front end (SiGe HBT LNA + downconversion
mixer) on the IHP SG13G2 open PDK, built to exercise the open flow and
[klayout-tools](https://github.com/2AMLogic/klayout-tools) end to end.

Status as of 2026-11-13, `main` @ `1f7f7c3`. The label-generated queue view is
[`WORK_PLAN.md`](../WORK_PLAN.md); merged work is in [`WORK_LOG.md`](../WORK_LOG.md).

## Where it stands

**Stage: schematic feasibility and testbench methodology.** Nothing is laid out,
no spec row is claimed met, nothing has been taped out.

Machine-graded verdict ([`signoff/tier-report.json`](../signoff/tier-report.json),
klt 0.8.0, re-graded by `signoff.yml`): **tier none, T1 3/11 items met.**

| T1 item | Verdict | What backs it / what is missing |
|---|---|---|
| 1 Design sources | met | `design/lna_stage1.sch` + derived netlist, LNA first stage only; the mixer has no design source (`signoff/block-coverage.json`) |
| 2 Layout | unmet | no LNA layout; waits on #79, tracked in #198 |
| 3 DRC clean | unmet | as item 2; the probe cell is DRC clean but cites nothing |
| 4 LVS clean | unmet | as item 2; `npn13G2` extraction not yet confirmed on a release (see Now 2) |
| 5 Corner verification vs ratified spec | unmet | every row in `spec/row-coverage.json` is `placeholder_circuit`, `method_absent` or `no_bench` |
| 6 Monte Carlo evidence | unmet | method qualified (`sim/hbt-mismatch-pair`, `MC_METHOD_WORKS`); row 15 is the one statistical row (DR-0007, proposed) and has no mixer to sample |
| 7 Post-layout verification | unmet | needs items 2-4 |
| 8 Characterization report | unmet | needs item 5 |
| 9 Testbenches shipped | met | `signoff/inventories/item9.json` |
| 10 Repo hygiene | met | `signoff/inventories/item10.json` |
| 11 Power delivery (structural) | unmet | needs the layout (#198) |

Spec ([`spec/target-spec.md`](../spec/target-spec.md)): eleven rows ratified as
targets by DR-0003 (2, 3, 4, 6-11, 17, 18); nine open (1, 5, 12-16, 19, 20).
Decision records 0001, 0004, 0006, 0007 and 0008 are *proposed*; 0002 and 0005
are *deferred*.

Evidence on `main` (all append-only records under `sim/*/records/`):

- **LNA first stage** (`design/lna_stage1`, one cascode, ideal lossless matching):
  S-parameter/NF PVT records, nominal two-tone IIP3 and P1dB method
  (`sim/lna-linearity`), and the input-match study (`sim/lna-match-tradeoff`),
  which found that no lossless input network reaches NF <= 2.5 dB with
  S11 <= -10 dB at 8 of 18 in-rail PVT points. That finding is why #79 exists.
- **LNA headroom** (`sim/lna-headroom`, stages 1 and 2, PR #242): variant C08
  buys +10 dB input-referred stress-free headroom for 4.4 dB gain and about
  0.06 dB NF; single-tone P1dB is still a one-sided bound, so row 8 is undetermined.
- **Mixer**: placeholder circuit only. Topology study: all candidates
  `no acceptable drive in declared sweep`. NF method: `MODEL_ABSENT`
  (no intrinsic device noise in `.tran`). Pumped-admittance and
  conversion-matrix interface probes are method feasibility only.
- **Passives** (`sim/passive-p1`): analysis chain and synthetic controls pass;
  the EM solves are `CAPABILITY_UNAVAILABLE` (no openEMS runner).
- **Layout chain** (`layout/probe-readiness`, klt dev build of 2026-10-17): probe
  cell DRC clean, `cmim` and `rsil` match in LVS, `npn13G2` extracted as no device.

## Now

1. **Finish the first-stage core-variant collection (#79).** Choose the core
   change (emitter degeneration, device size / current density, bias-feed
   noise) that lets NF and input match close together. Work is on branch
   `feature/issue-79` (`sim/lna-core-variants`); 3 of 24 batch requests have
   completed. *Done when:* a `sim/lna-core-variants` record is merged, the
   `sim/lna-match-tradeoff` bound is re-run on the chosen core, and the issue
   names the core that `design/lna_stage1.sch` should adopt. *Blocks:* batch
   simulation capacity; the issue carries a transient capacity park and is
   re-queued automatically when it expires.
2. **Re-run the layout-chain readiness probe at the pinned release, klt 0.8.0**
   (#246). The upstream gap behind the HBT result,
   [klayout-tools#3137](https://github.com/2AMLogic/klayout-tools/issues/3137),
   closed on 2026-10-18, and `layout/toolchain.json` already says a 0.8.0
   re-run "would be a separate, later record". *Done when:*
   `layout/probe-readiness/runs/klt-0.8.0/` holds the per-command records, the
   README gains a dated section stating whether `npn13G2` extracts and whether
   the full-reference LVS matches, and any remaining gap is filed upstream.
   Non-claiming: `signoff/` does not change.
3. **Bring the README repo-layout block up to date** (#247). It lists five
   directories and omits `signoff/`, `manifests/`,
   `ratification/` and `docs/`. *Done when:* the block names every top-level
   content directory and links this roadmap.

## Next

- **LNA stage-1 schematic update to the chosen core.** *Done when:*
  `design/lna_stage1.sch` and its netlist are re-exported and
  `klt signoff --attest 1 --check` passes. Unblocked by Now 1.
- **LNA stage-1 layout with DRC, LVS and ERC supply evidence (#198; T1 items
  2, 3, 4, 11).** *Done when:* the #198 acceptance criteria hold and
  `signoff/tier-report.json` moves those items. Unblocked by Now 1 and by the
  HBT extracting in Now 2.
- **Post-layout re-simulation (T1 item 7)** and the **AREA / AREA-EFF rows
  (19, 20)** via `klt economy`. Unblocked by #198.
- **Live-verify the first stored harness manifest (#230).** `manifests/artifacts/`
  holds no manifest yet. Unblocked by the first new harness-native record.
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

As read today no open issue carries `loom:issue`. #79 returns to the queue
when its capacity park expires; Now 2 and Now 3 are filed as #246 and #247.

## Not planned

- The antenna elements, the array, the ADC and the beamformer (`CLAUDE.md`
  scope rule; DR-0002 is deferred on purpose).
- Relaxing a ratified row to make a result pass; a row changes only through a
  superseding decision record.
