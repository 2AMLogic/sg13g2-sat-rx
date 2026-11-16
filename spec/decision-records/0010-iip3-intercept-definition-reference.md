# 0010: Which IIP3 intercept definition is the published reference (#299) — proposal, nothing selected

- **Status**: **proposed**. Written and argued, **not ratified**, and it **selects nothing**: it recommends a reference definition and the separate changes adopting it would take, and names the evidence it rests on and the widening that would settle it. Design work may read it; no claim may cite it as settled.
- **Date**: 2026-11-16
- **Decided by**: Builder agent, issue #299 (proposing only; per [`spec/README.md`](../README.md) an agent turns neither key)
- **Ratification**: two-key (EE key + market key) via the ratification-via-PR path DR-0003 used. **Neither key has been turned.** EE review outcome: **pending**. Market review outcome: **pending**.
- **Related**: [#299](https://github.com/2AMLogic/sg13g2-sat-rx/issues/299), [#276](https://github.com/2AMLogic/sg13g2-sat-rx/issues/276) / PR #293 (single-sourced the estimator; deliberately picked no definition), [#181](https://github.com/2AMLogic/sg13g2-sat-rx/issues/181) (the ranking evidence), [#273](https://github.com/2AMLogic/sg13g2-sat-rx/issues/273) (owns any `sim/lna-linearity` re-run), [DR-0007](0007-statistical-row-classification.md), [DR-0008](0008-lo-drive-path-after-no-acceptable-drive.md) (closest in shape).

**What this record edits:** no target-spec row, no fitter, no testbench manifest, no plan and no committed record. Row 7 (IIP3) is *not* shown met by anything here.

---

## Context

PR #293 moved the two-tone IIP3 estimator into `sim/harness/iip3.py`, which computes three intercepts per selected run (`INTERCEPT_KEYS = ("iip3_free_slope_dbm", "iip3_ideal_slope_dbm", "iip3_topfit_dbm")`, `sim/harness/iip3.py:87`). It did not choose among them, so the tree has one implementation and **three published headline definitions**:

| home | published `iip3_dbm` is | source |
|---|---|---|
| `mixfeas.fit_iip3` (`sim/mixer-topology-feasibility`) | free-slope line intersection, lower of the two sidebands | `mixfeas.py:905-925` docstring ("intersection of the two fitted lines") |
| `linearity.fit_iip3` (`sim/lna-linearity`, reused by `sim/lna-headroom` via `headroom.py:624`) | ideal-slope window centroid, `mean(pin + (Pfund - Pim3)/2)` over the run | `linearity.py:650-668` docstring |
| `sim/mixer-conversion-iip3` in-deck bench | `iip3t`, slope-3-constrained read at the top-of-fit drive, `Pin + (Pfund - Pim3)/2` | `testbench/tb.json:164` (`"iip3_dbm": "iip3t"`), `tb.json:152` |

The engine's `iip3_topfit_dbm` is the same formula as the deck's `iip3t` (`xs[j-1] + (fund_ys[j-1] - im3_ys[j-1]) / 2.0` at `iip3.py:146`; deck at `tb.json:152`). **This equivalence was read off the two expressions, not run.**

Consequence on the current tree: `test_case_d_both_wrappers_publish_their_own_headlines_measurably_apart` (`sim/harness/tests/test_iip3.py`) pins that on one set of rows every gate in both campaigns accepts while the two Python headlines disagree, each reporting "ok". #276 deferred the choice here: choosing changes published numbers, so it belongs in a decision record.

A second constraint shapes what adopting any choice costs. `sim/lna-linearity/run.py:519` checks committed records with `json.loads(json.dumps(A_roundtrip(res["placements"]))) != rec["placements"]`: plain dict equality, insensitive to key *order* and sensitive to the key *set*. So a change to a published key set, like a change to a published headline value, stops a committed record reproducing from its frozen logs. This is why #293 put the full three-intercept shape behind an opt-in `diagnostics=True`. (The issue body reports this was shown by flipping that filter in a throwaway copy of the tree; that run was **not repeated for this record** and the constraint rests on the `run.py:519` line itself.)

## Decision

**Proposed, not selected.** If ratified, the reference definition for the **published** `iip3_dbm` in the Python fitters (`mixfeas.fit_iip3`, `linearity.fit_iip3`) would be **`iip3t`** (top-of-fit, slope-3 constrained; the engine's `iip3_topfit_dbm`), the same headline the in-deck bench already publishes. The other two intercepts would remain published as **named diagnostics**, as the deck does at `tb.json:165-166` (`iip3_free_intersection_dbm`, `iip3_window_centroid_dbm`).

1. **Do the three homes agree?** On the **headline, yes**: all three publish `iip3t` as `iip3_dbm`. They may differ in their diagnostics and gates, because the diagnostics are where the disagreement is carried, not hidden.
2. **The cross-check stays a hard reject.** `free_fixed_tol_db` (live `1.0` dB, `sim/lna-linearity/testbench/plan.json:91`; the evidence checker defaults to the same 1.0, `.github/scripts/evidence_checks/lna_linearity.py:118`) keeps rejecting an interval (`linearity.py:702-703` injects the cross-check as a campaign gate; `sim/harness/iip3.py:150-151` appends to `rejected` and `continue`s; `linearity.py:713` publishes `rejected_intervals`) where the free-slope and ideal-slope reads differ by more than it. With `iip3t` as the headline, the free-slope read's job becomes exactly that guard. When the two disagree, interval selection is unchanged: that interval is discarded and the next candidate run is tried; if none passes the result is `unavailable` with the reason.
3. **Headline move and key-set adoption are one migration, not two** (see Consequences). Neither is performed by this record.
4. **Evidence scope.** This record rests on the #181 measurement as it stands: **one corner (hbt_typ / 27 C / 2.50 V), one bench (`mixer-conversion-iip3`), one 5-point window (`fit_n = 5`)**. It does not widen it. It must not be read as validated across the ratified band or across corners. Widening is the revisit trigger below, not work done here.

If the reviewers judge single-corner evidence too thin to rest a headline move on, the equally complete outcome is to leave this record `deferred` on the criteria under "Trigger to revisit", which is DR-0008's disposition.

## Argument

The #181 resolution ranks the three definitions on **measured local-vs-batch (ngspice-42 vs ngspice-46) reproducibility** (`sim/mixer-conversion-iip3/README.md:47-56`):

| definition | measured backend bound | status in that bench |
|---|---|---|
| `iip3t` top-of-fit, slope-3 constrained | **0.0492 dB** (ngspice-42 +3.8513 vs ngspice-46 +3.8021) | headline |
| `iip3c` window centroid (= `linearity`'s headline) | ~0.27 dB | diagnostic |
| `iip3x` free intersection (= `mixfeas`'s headline) | ~1.4 dB | diagnostic |

Pinned executably by `sim/harness/tests/test_testbench.py:226-307` (`test_iip3_headline_is_topfit_slope3_read_with_published_diagnostics`, `test_issue181_slope_region_and_floor_gates_not_loosened`, `test_iip3_topfit_read_holds_while_free_intersection_swings`). Criterion: #135's 0.1 dB backend-agreement criterion, as cited in that README. Only `iip3t` meets it.

The README also gives the **mechanism**, which is what lifts this above a ranking of three numbers: the free intersection "rotates with the fitted IM3 slope the two ngspice builds agree to only ~0.10". A fitted-slope intercept inherits slope error; the slope-3-constrained read removes the fitted slope from the headline. A headline that moves ~1.4 dB between two builds of the same simulator does not meet this repo's reproducibility convention, whatever its other merits. The centroid is better but still about 5x the constrained read (0.27 / 0.0492 ~ 5.5; derived here from the two quoted bounds), and adopting it would still force a re-recording, buying a migration without buying reproducibility.

**What the evidence does not establish**, stated so the record is not read as stronger than it is:

- The ranking is one corner on one bench's data. The Python benches (`lna-linearity`, `mixfeas`) run different DUTs and different windows; nothing here measures the three definitions on *their* data. The mechanism argument (slope error leaks into a fitted-slope intercept) suggests the ordering generalises, but that is an argument, not a measurement.
- Two follow-ups recorded in the same README stand and bear directly on the choice: the low-drive IM3 reads are **not tolerance-converged** (reltol alone fails the slope gate), and at **6 of 27 PVT corners** the static fit window contains no valid 1:3 region (hot corners compress inside it), so no IIP3 is published there. A top-of-fit read depends on where the window's top lies, and compression inside the window is exactly the regime where the top point is least representative. `iip3t` is the best-reproducing of the three at one corner; it is not shown best where the window is compressing.
- The deck's `iip3t` and the engine's `iip3_topfit_dbm` are the same expression (above) but have not been run against each other on common rows.

On **question 2**: the cross-check is the only live guard that catches a window where the two definitions disagree. Loosening a gate in the same record that moves a headline would change two things at once, and this repo's rule is that agents do not relax a gate to make a result pass. Demoting it to a diagnostic would need its own evidence of a case where the reject is wrong, and none is cited here.

## Alternatives considered

- **Adopt the free intersection** (what `mixfeas` publishes today) — ~1.4 dB local-vs-batch bound fails #135's 0.1 dB criterion; it is the definition #181 explicitly demoted, on measurement (`README.md:47-56`).
- **Adopt the window centroid** (what `linearity` publishes today) — ~0.27 dB, still above 0.1 dB and ~5x the constrained read; and because `linearity` would still have to adopt the diagnostics key set, it needs the re-recording anyway.
- **Let each home keep its own headline and document the divergence** — today's state, which `test_case_d_...` pins as two campaigns both reporting "ok" with disagreeing headlines. Not chosen: a reader cannot tell which "IIP3" a row-7 figure is.
- **Demote `free_fixed_tol_db` to a recorded diagnostic** — see Argument; no evidence of a wrongly rejected interval, and it would loosen a gate and move a headline in one step.
- **Change the fitters in this issue** — a `proposed` record is not ratified; acting on it before ratification is what CLAUDE.md forbids.
- **Widen the #181 measurement first (more corners, the Python benches' data)** — the stronger evidence, but needs SPICE on the batch fleet and is out of scope for a record-only issue. It is the revisit trigger below.

## Trigger to revisit / what will decide this

This record is superseded (by a higher-numbered record that ratifies, amends or rejects its recommendation) when **either** holds, both checkable:

1. A measurement of the three intercepts' local-vs-batch bound exists, on a committed record, at **at least the corners where `sim/mixer-conversion-iip3` publishes an IIP3** (i.e. excluding the 6 of 27 PVT corners with no valid 1:3 region) **and** on at least one of the Python benches' own data. The record that follows states whether `iip3t` still meets #135's 0.1 dB criterion there. If it does not at some corner, this proposal is rejected or narrowed for that corner.
2. The EE and market reviewers rule on this record as written, resting on the single-corner evidence, via the PR path (merge is the second key).

A follow-up issue for the widening measurement in (1) is **not filed by this PR**; the issue's Out of Scope reserves it. If reviewers want it, it is a new issue with its compute going to the batch fleet.

## Consequences

If ratified and then acted on (none of this is done by this record):

- **Headline move changes published `iip3_dbm`** in `mixfeas` (free -> top-of-fit) and `linearity` (centroid -> top-of-fit). `iip3t` at the top of the window will generally differ from the centroid and the free intersection; the size of the shift on any given record is **not estimated here**.
- **Adopting the three-intercept key set is the same migration as the headline move, not a separate one.** Per `sim/lna-linearity/run.py:519`, a change to the published `placements` key set makes committed records fail "placements (fits, convergence, verdicts) do not reproduce from the frozen logs", exactly as a headline value change does. So it is one re-recording, and #293's opt-in `diagnostics=True` filter would be turned on permanently at the same time.
- **Committed records that embed these fitters and would stop reproducing** (found by grepping for `fit_iip3` / `iip3_dbm` in `sim/` and `.github/`):
  - `sim/lna-linearity/records/20261010-174208-0f67eaf` (the record guarded at `run.py:519`; re-running is #273's territory).
  - `sim/lna-headroom/records/20261011-053527-d60e79a` and `20261031-222819-864b44f` (headroom calls `L.fit_iip3`, `headroom.py:624`, with a snapshotted `linearity-plan-v2.json` for the latter, `run.py:492,554,576`).
  - `sim/mixer-topology-feasibility/records/20261010-010744-a10c193` and `20261010-025859-2113f00` (`mixfeas.fit_iip3` via `collect.py:314`; both contain `iip3` fits).
  - `sim/mixer-conversion-iip3` is **not** affected on the headline (it already publishes `iip3t`); only if its diagnostics were renamed would it be.

  Append-only convention applies: each is superseded by a later record that says why, never edited or deleted. Whether each of these is re-recorded or left as a superseded historical record is a ratification-time question; this record does not decide it.
- **Bad consequences.** Moving the headline makes every previously published Python IIP3 figure non-comparable with later ones until re-recorded; adoption rests on one corner of evidence unless widened first; and `iip3t` is the least-validated of the three where a window compresses (the 6 of 27 corners), so the choice could shift risk into exactly those corners.
- **Unchanged by this record:** `sim/harness/iip3.py`'s arithmetic, every fitter, plan and manifest, the `free_fixed_tol_db` value, and all committed records.
