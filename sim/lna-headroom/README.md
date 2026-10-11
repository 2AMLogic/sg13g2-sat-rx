# lna-headroom (issue #123)

Bounded **headroom feasibility study** for the committed `design/lna_stage1` cascode: can the Q2 base
divider ratio and the collector damping resistor `Rd` alone buy output-swing headroom under the
**unchanged** ratified limits (row 17, V_CE <= 1.4 V) so that a *stress-valid* single-tone P1dB
(row 8, target >= -25 dBm) can be determined? The baseline campaign
(`sim/lna-linearity/records/20261010-174208-0f67eaf`) could not: Q2 V_CE broke 1.4 V from -36 dBm.

**Study variants only.** The production schematic and netlist (`design/lna_stage1*`) are not
changed; adoption of any variant would be a later, reviewed change. DUT passives are IDEAL lossless
L/C, the band (row 1) is a draft, scope is nominal corner only (hbt_typ, 27 C, 2.5 V). Nothing here
relaxes a limit or target, and nothing is compliance. A no-feasible-candidate outcome is a valid result.

## Cold start

```bash
python3 -m pytest sim/lna-headroom/tests -q        # method qualification, no simulator
python3 sim/lna-headroom/run.py check-plan         # plan coherence, band, DUT hash, baseline = committed DUT
python3 sim/lna-headroom/run.py variants --check   # frozen variant decks regenerate from DUT + plan
python3 sim/lna-headroom/run.py collect --dry-run  # write the klt bodies/requests only
python3 sim/lna-headroom/run.py collect \
    --runner-version-check warn --no-stage-models  # submit to the Spot batch fleet, write ONE record
python3 sim/lna-headroom/run.py verify             # re-derive every verdict from the frozen logs
```

`collect` needs the plan, bench and DUT committed (it refuses a dirty tree) and uses an explicit
`--backend batch` for every request. A failed submit stops the collection, writes nothing and does
not fall back to a local run. The two flags are the documented client/runner skew
(`../lna-linearity/README.md`). Caveat: the record's requests all carry `runner_compatibility: mismatch`
(runner klt 0.5.0 vs client 0.7.0); see `design/lna_headroom_study.md`.

## Method

Everything about the measurement is the committed `sim/lna-linearity` method, reused unchanged and
pinned by hash (`testbench/plan.json` -> `linearity_plan`): per-tone available-power axis behind
50 ohm, three in-band placements, the single-tone sweep -56..-16 dBm (2 dB), the P1dB extractor,
the V_CE/V_BE operating limits, and the versioned collector-current diagnostics
(`plan-v2`: applicability **unresolved**, `complete_envelope: false`, missing or non-finite
diagnostics reject a point; no instantaneous current rating is invented). Points that break a limit
are classified and excluded, never fitted through; a sweep that is cut off before the crossing yields a
one-sided `bounded` result.

What this study adds, all declared in `testbench/plan.json` **before** collection:

* **Candidate table (12).** `R1b + R2b = 8.5 kohm` held, `R2b` in {7.0, 7.15, 7.3, 7.45} kohm (Q1/Q2
  DC split moves; beyond ~7.5 kohm Q1's DC V_CE alone exceeds 1.4 V) crossed with `Rd` in
  {465 (committed), 300, 200} ohm. C00 is the committed DUT. Q1, Q2, `Re1`, the input network, `Lfeed`,
  `Cm`, `Cb2` and the supply are fixed.
* **Baseline reproduction.** C00 must reproduce the historical stress cutoff (same limit identity, first
  violation within one 2 dB grid step, Q2 V_CE peak within 5 mV and delivered power within 0.05 dB at
  every swept power). If not, no candidate is ranked.
* **Gates** (a failing candidate stays visible, only excluded from ranking): DC V_CE of Q1/Q2 inside
  [0.4, 1.37] V; baseline gain at every placement within 6 dB of C00's (a heavily attenuated variant is not
  a receive-chain solution); a usable gain baseline.
* **Metrics and ranking.** Per placement: stress-free power (last point before the first violation),
  limit identity, gain drop there, P1dB number or bound, DC allocation. Ranked by worst-placement
  stress-free power, then minimum gain. *Net output headroom* subtracts the gain given away, so a
  candidate that merely attenuates scores <= 0.
* **Shortlist / outcome.** Top-2 ranked candidates with >= 4 dB input-referred headroom gain and positive
  net output headroom are shortlisted for refinement (timestep/window controls, two-tone IIP3, small-signal
  gain/NF/stability against C00); otherwise the screening outcome (`no_feasible_candidate` etc.) stands.

## Files

| file | role |
|---|---|
| `testbench/plan.json` | frozen declaration: candidate table, gates, ranking, shortlist, outcome classes |
| `variants/C*.spice` | frozen variant decks (generated, checked by `variants --check` and the tests) |
| `headroom.py` | pure logic: variants, bodies, parsing, gates, ranking, baseline reproduction |
| `run.py` | CLI: `check-plan`, `variants`, `build`, `collect`, `verify` |
| `tests/` | closed-form fake-log qualification (no simulator) |
| `records/`, `corners/`, `netlist-snapshots/` | append-only evidence (adapter `lna-headroom` in `.github/scripts/check_evidence_formats.py`) |

## Status

One record, stage 1 (screening): `records/20261011-053527-d60e79a.md`, all 13 klt requests on the batch
fleet, control passing, baseline C00 reproducing the historical cutoff exactly. Outcome class
`headroom_improved_p1db_undetermined`: the best candidate (C08) moves the first Q2 V_CE violation up by
10 dB input-referred (5.6 dB net of 4.4 dB lost gain) but P1dB stays a one-sided bound 1-3 dB short of the
unchanged -25 dBm target. Refinement of the shortlist (convergence controls, two-tone IIP3, gain/NF/stability
vs C00) is **not done**; see `design/lna_headroom_study.md`.
