# 0009: coherent-bin criterion — one convention for every analysed bin

- **Status**: proposed
- **Date**: 2026-11-15
- **Decided by**: Builder (authored from the measurement in
  `sim/harness/tests/test_coherence_criteria.py`; issue #266, split D of #257)
- **Ratification**: two-key (EE key + market key) — **neither key has been
  turned.** Until both are, design work may read this record but no claim may
  cite it as settled.

## Context

Two functions named `coherence_problems`, in two benches, both decide whether
an analysed spectral bin is coherent with the retained window, and they
disagree: **1000x in tolerance** (`tol=1e-6` vs `tol=1e-9`) and **4x in
Nyquist margin** (2 vs 8 samples per period). Verified at commit `c498b96`,
the base at which these criteria were transcribed; both functions are
unchanged at this PR's head:

- `sim/mixer-topology-feasibility/mixfeas.py:465` — `coherence_problems(run, tol=1e-6)`:
  window-integer-steps test **absolute** (`abs(steps - round(steps)) > 1e-6`),
  per-bin cycle test relative, bare Nyquist guard `f <= 0 or f >= 0.5/tstep_s`
  (2 samples per period), a coherence test on `run.tones`, **no** settling-discard check.
- `sim/lna-linearity/linearity.py:121` — `coherence_problems(freqs, window_s, step_s,
  settle_discard_s=0.0, tol=1e-9)`: window test **relative**
  (`> tol * max(1, n)`), per-bin cycle test relative with the same `tol`,
  Nyquist guard `f * step_s > 1.0/8.0` (8 samples per period), and a
  settling-discard-lands-on-a-sample check the mixer bench lacks.

The tolerance-mode split applies **only** to the window test; both per-bin
cycle tests are relative (they differ in value, also 1000x: `1e-6` vs `1e-9`
relative).

A third campaign consumes the lna-linearity criterion:
`sim/lna-headroom/headroom.py:170` calls `linearity.placement_coherence`
(→ `linearity.py:157`) for the `base` variant only.

**Neither convention is ratified.** `grep -rniE "coheren" spec/ docs/
ratification/ README.md` returns nothing (re-verified 2026-11-15). Five
recorded results across the three campaigns are each qualified against a
private definition of a coherent bin:

- `sim/lna-linearity/records/20261010-174208-0f67eaf.json`
- `sim/lna-headroom/records/20261011-053527-d60e79a.json`
- `sim/lna-headroom/records/20261031-222819-864b44f.json`
- `sim/mixer-topology-feasibility/records/20261010-010744-a10c193.json`
- `sim/mixer-topology-feasibility/records/20261010-025859-2113f00.json`

Champion gated this piece explicitly: *"**D — coherence** (group 2): **gated
on a decision record in `spec/`** fixing the tolerance mode and the Nyquist
margin for this block, filed as its own decision issue. Do not land D as a
parameterised shim carrying both policies."* This record is that gate. It
changes no code; unifying the two functions rests on a *ratified* record and
is explicitly out of scope here.

## Decision

The coherent-bin criterion for this block, stated per sub-test so design work
can lock to it without interpretation. Every check applies to **every
analysed frequency** of a run (bins, and tones where the caller analyses
tones as separate quantities), with one tolerance value `tol = 1e-9`:

1. **Window-integer-steps — relative mode, `tol = 1e-9`.** Reject when
   `abs(n - round(n)) > 1e-9 * max(1, n)`, where `n = window_s / step_s`.
   (This is the **looser** of the two existing window bounds at the current
   operating point — see Argument; the mode is chosen for scale-invariance,
   not strictness.)
2. **Per-bin cycle count — relative, `tol = 1e-9`.** Reject when
   `abs(c - round(c)) > 1e-9 * max(1, c)`, where `c = f * window_s`. Both
   existing conventions are already relative here; the value follows the
   single-tolerance rule below.
3. **Nyquist margin — 8 samples per period, positive frequencies only.**
   Reject when `f <= 0` or `f * step_s > 1.0 / 8.0`. The `f <= 0` exclusion is
   mixfeas's lower guard, retained verbatim (linearity's criterion has no such
   test today — see Consequences).
4. **Settling discard — part of the criterion.** Reject when
   `abs(d - round(d)) > 1e-9 * max(1, d)`, where `d = settle_discard_s /
   step_s`, for any campaign that discards a settling prefix before the
   retained window.

One tolerance value (`1e-9`, relative) for all three relative tests: one
number to lock to, one number to revisit. This is a per-sub-test resolution,
**not** "adopt the stricter campaign" — sub-test 1 adopts the looser window
bound on its own argument (mode scaling), sub-tests 3 and 4 adopt the
stricter bounds the mixer bench lacks.

## Argument

### The measurement

Committed as `sim/harness/tests/test_coherence_criteria.py`; run with
`python3 -m pytest sim/harness/tests/test_coherence_criteria.py -q`. It
evaluates **both** existing criteria against the actual window/step/frequency
sets that produced the five records, read from the committed netlist
snapshots (pure arithmetic — no `klt sim`, no `ngspice`). Input provenance is
checked by the test: the lna-linearity snapshot `plan.json` carries the
sha256 the record declares (`61291b0e…`); both `lna-headroom` snapshots'
`linearity-plan-v2.json` carry the sha256 their headroom plans declare
(`26ad9db8…`); the two mixer snapshots' `tb.json` study blocks (timing,
bands, `if_hz`) are identical, so the nine mixer cases qualify both mixer
records.

**The real-run table does not discriminate.** All 27 distinct real cases
(18 LNA: 3 placements × 3 variants × 2 run kinds; 9 mixer: 3 bands ×
`single`/`rfoff`/`two_tone`) pass **their own** criterion **and** the other
campaign's. Every window residual `abs(n - round(n))`, every discard residual
and every per-bin cycle residual is **exactly `0.0`** — these window/step/
discard ratios are exact in binary floating point and the cycle counts are
exact integers. A uniformly PASS/PASS table cannot choose a tolerance; the
decision below therefore rests on per-sub-test margins and robustness, not on
what the existing records require. (Both `lna-headroom` records qualify the
`base` variant only, against the same placements and timing as
lna-linearity: the test asserts their 12 rows are numerically identical to
the LNA base rows, so the five-record answer is this one answer.)

Summary of the 27 distinct cases (full table reproduced by
`python3 sim/harness/tests/test_coherence_criteria.py`):

| quantity | lna-linearity / lna-headroom | mixer-topology-feasibility |
|---|---|---|
| `n = window_s/step_s` | 20000 (base), 40000 (half_step, double_window) | 20000 (`single`/`rfoff`), 80000 (`two_tone`) |
| `d = discard_s/step_s` | 40000 (80000 for half_step) | 20000 (`settle_s`) |
| window residual | 0.0 | 0.0 |
| discard residual | 0.0 | 0.0 |
| worst cycle residual | 0.0 | 0.0 |
| worst analysed `f*step_s` | 0.02115 (high placement, base step) | 0.0212 |
| worst samples-per-period | 47.3 | 47.2 |
| own criterion | PASS (18/18) | PASS (9/9) |
| other criterion | PASS (18/18) | PASS (9/9) |

The worst analysed frequency across all three campaigns is the `f21p20`
band's RF tone at 21.2 GHz with `tstep_s = 1 ps`: `f*step = 0.0212`, i.e.
**47.2 samples per period** — **5.9x** inside the proposed 8-samples-per-period
bound (`f*step = 0.125`) and **23.6x** inside mixfeas's bare Nyquist bound
(`f*step = 0.5`). The worst LNA bin (`fl_hi = 21.15 GHz`, the high placement's
upper floor probe) sits at `f*step = 0.02115` — 47.3 samples per period.
Nyquist headroom is the only sub-test with a non-degenerate real margin.

### Why relative `1e-9` on the window test (the looser bound here)

At the real `n` of 20000–80000, mixfeas's absolute `1e-6` is the **tighter**
window bound by **20x–80x** (relative `1e-9 * n` = `2e-5…8e-5`). Adopting
relative `1e-9` is nonetheless the right call, on three measured/derivable
grounds:

- **Mode must scale with the quantity.** The window residual of a
  correctly-specified integer ratio is floating-point noise and noise is
  *relative* (≈1e-16 per operation, realistically ≤1e-14 through the handful
  of intermediate expressions a plan value passes through —
  `variant_timing` multiplies `step_s` by `timestep_factor` and `window_s`
  by `duration_factor`). The smallest *real* mis-specification — a decimal
  typo like 20.001 ns instead of 20 ns — is ≥ ~1e-6 relative. `1e-9`
  relative keeps ≥5 decades above the noise floor and ≥3 decades below typo
  granularity **at every `n`**. An absolute bound changes meaning with `n`:
  tighter than `1e-9`-relative above `n = 1000`, looser below it.
- **The absolute bound has a failure mode at large `n`.** Its tolerated
  residual (`1e-6`) is a fixed absolute quantity while fp noise grows as
  ~`1e-15 * n`; they cross near `n ≈ 1e9` — a 1 ms window at 1 fs step, a
  plausible long-settling campaign. Correctly-specified runs would start
  failing there. The relative bound never fails a correct ratio.
- **Measured cost today is zero.** Every real window residual is exactly
  `0.0`; no recorded run moves. The one behavioural consequence is stated
  under Consequences: the mixer campaign's gate loosens by 20x at
  `n = 2e4` and 80x at `n = 8e4` in a physically meaningless band (see
  below).

The synthetic window case (`n = 20000 + 1e-5`, residual ≈ `1e-5`) is the
checkable demonstration that neither window bound dominates: it fails the
absolute `1e-6` and passes relative `2e-5`.

### Why 8 samples per period

The analysed quantities are single-bin DFT amplitudes over the retained
window on the resampled grid. A bare Nyquist guard (2 samples per period)
only excludes `f >= Nyquist` and `f <= 0`; it gives the extraction no margin
against neighbouring products folding into the analysed bin or against
resampler artifacts as a bin approaches Nyquist. The guard's lower half is
kept — sub-test 3 rejects `f <= 0` outright, because a non-positive analysed
bin completes an integer number of cycles and the window and cycle tests
cannot catch it — while the upper bound is tightened from 2 to 8 samples per
period, the margin the LNA benches already apply. Measured cost: none — the worst real
bin sits 5.9x inside the bound, and no campaign proposes a bin within 2x of
it (the revisit trigger below names the exact limit). The synthetic Nyquist
case (4 samples per period: `f*step = 0.25`) is the checkable demonstration
of the 4x margin split — it passes bare Nyquist and fails the 8-bound.

### Why the settling-discard check is in the criterion

Every campaign here discards a settling prefix before the retained window
(LNA `settle_discard_s = 4e-8` → `d = 40000`; mixer `settle_s = 2e-8` →
`d = 20000`), and the retained window starts at `t = settle_s`. If the prefix
is not an integer number of steps, every retained sample sits off the
resample grid and coherence breaks for **all** bins at once — the check is
the same integer-ratio requirement as the window test and belongs in the
criterion. mixfeas's omission is a gap, not a choice: its own
`tstop = settle_s + window_s` structure presumes grid alignment without
checking it, and the mixer campaign's recorded `d` is exactly 20000.0
(residual `0.0`), so adding the check moves nothing measured. The synthetic
discard case (`d = 40000.5`, residual exactly `0.5`) shows the asymmetry:
linearity's criterion fires, mixfeas's has no such test to fire.

### Re-qualification: no existing record is invalidated

**No recorded result is invalidated or requires re-qualification under either
convention, for all five records.** All 27 distinct real cases pass both
criteria with every residual exactly `0.0`; the two `lna-headroom` records
are covered by the asserted-equal base rows. The comparability question the
Problem Statement raised is answered: the five records *are* comparable.
This record is still required — the criterion is unratified and the code
still diverges — but the choice carries no re-qualification burden.

## Alternatives considered

- **The mixer convention as-is** (absolute `1e-6` window, relative `1e-6`
  cycles, bare Nyquist, tone-coherence test, no discard check) — rejected per
  sub-test: the window mode does not scale with `n` (failure mode near
  `n ≈ 1e9`, meaning drift below `n = 1000`); bare Nyquist gives the
  single-bin DFT extraction no margin — its upper bound is replaced by the
  8-samples-per-period test and its `f <= 0` lower exclusion is kept in
  sub-test 3; the missing discard check leaves an
  off-grid settle prefix undetected in the campaign that actually discards
  one. Its tone-coherence test is kept: the criterion applies to every
  analysed frequency, and the mixer caller passes its tones into the same
  set.
- **The lna-linearity convention as-is, adopted wholesale** — the landing
  point, but justified per sub-test above rather than adopted as "the
  stricter campaign": its window bound is the *looser* of the two at the
  real `n` (absolute `1e-6` is 20x–80x tighter there), so the blanket
  strictness argument is not only unavailable, it is false. Only its Nyquist
  margin and discard check are stricter; the window mode/value stands on the
  scale-invariance argument.
- **A hybrid** (absolute `1e-6` window + 8 samples per period + discard
  check) — rejected: it keeps the absolute mode's `n`-scaling failure mode
  while the measured evidence gives it no advantage (every residual is
  exactly `0.0` under both modes).
- **A tighter relative tolerance** (`1e-12`) — rejected: buys nothing
  measured (all residuals exactly `0.0`) and spends most of its margin
  against fp noise through intermediate plan expressions
  (`timestep_factor`/`duration_factor` products), exactly where a future
  correct plan would trip it.
- **A looser relative tolerance** (`1e-6` relative) — rejected: within one
  decade of decimal-typo granularity (~1e-6 relative); a window mistyped by
  one part in 1e6 would pass.
- **`Status: deferred`** — rejected: TEMPLATE allows deferral when the
  deciding criteria are unavailable; here the deciding measurement is cheap
  and available from committed artifacts, and this record carries it.

## Trigger to revisit

Checkable conditions, each independently sufficient:

- A committed plan or run spec **fails** this criterion on a new row (the
  committed test goes red). If the failing raw residual is ≥ ~1e-6 relative,
  the criterion did its job — fix the plan. If it lies between ~1e-14 and
  1e-9 relative — floating-point noise from a correctly-specified run — the
  tolerance value is wrong for that arithmetic path: supersede with a
  re-derived value.
- A proposed timing reaches `n >= 1e8`, or any analysed bin reaches
  `f * step_s >= 1/16` (within 2x of the 8-samples-per-period bound): re-run
  the margin argument in a superseding record **before** committing the plan.
- After ratification, the code-consolidation follow-up must reproduce this
  record's committed measurement exactly; a disagreement between the unified
  implementation and `test_coherence_criteria.py` is a finding against the
  implementation — never a reason to relax either side.
- A campaign needs a sub-test this criterion lacks (non-uniform resampling,
  chirped or stitched analyses, multi-window runs): supersede with a new
  record extending the criterion.

## Consequences

- **Possible now**: one citable, fully-specified criterion for all three
  campaigns; the consolidation follow-up (to be filed only once this record
  is *ratified*, per issue #266's Out of Scope) has a concrete target.
- **Unchanged until ratification**: the two `coherence_problems` functions
  keep their private conventions; every bench file and every recorded number
  stays as it is. Interim records are still qualified against a private
  criterion while this record states what it should be — that tension is the
  cost of the two-key gate, not a licence to consolidate early.
- **The mixer campaign's window gate loosens by 20x at `n = 2e4` and 80x at
  `n = 8e4`** (from absolute `1e-6` to relative `1e-9`: the absolute bound is
  `1e-6/n` — `5e-11` relative at `n = 2e4`, `1.25e-11` relative at
  `n = 8e4` — so the loosening grows linearly with `n`). The newly-admitted
  band — window ratios off-grid by between `5e-11` and `1e-9` relative at
  `n = 2e4`, or between `1.25e-11` and `1e-9` relative at `n = 8e4` — sits
  3–4 decades above fp noise and ≥3 decades below the smallest meaningful
  decimal typo: physically meaningless territory, but stated plainly because
  it is a real loosening.
- **The mixer campaign's per-bin cycle test tightens by 1000x** (relative
  `1e-6` → relative `1e-9`), the counterpart of the window loosening above:
  both conventions were already relative here, so the single-tolerance rule
  moves the mixer side only. A tightening cannot admit a bin the mixer
  campaign previously rejected; measured cost today is zero — every cycle
  residual in the committed table is exactly `0.0`.
- **The mixer campaign's non-positive-frequency exclusion is retained — and
  generalised**: sub-test 3 keeps mixfeas's `f <= 0` bin guard verbatim and
  applies it to every analysed frequency, tones included. mixfeas tests bins
  only, and linearity's criterion has no positive-frequency requirement at
  all — a non-positive bin completes an integer number of cycles, so its
  window and cycle tests are silent. Measured cost: zero — no committed plan
  proposes a non-positive analysed bin or tone (asserted by the measurement).
- **New plans are bounded**: an 8-samples-per-period margin, a grid-aligned
  discard and positive analysed frequencies are now plan-validation
  requirements (Trigger names
  the exact limits), which constrains future timing choices — e.g. a
  long-settling 1 ms/1 fs window (`n = 1e9`) is admissible under the relative
  bound but must clear the margin re-derivation first.

## Sources

- Measurement: `sim/harness/tests/test_coherence_criteria.py` (committed with
  this record; `python3 -m pytest sim/harness/tests/test_coherence_criteria.py -q`).
- Snapshots measured: `sim/lna-linearity/netlist-snapshots/20261010-174208-0f67eaf/plan.json`,
  `sim/lna-headroom/netlist-snapshots/{20261011-053527-d60e79a,20261031-222819-864b44f}/linearity-plan-v2.json`,
  `sim/mixer-topology-feasibility/netlist-snapshots/{20261010-010744-a10c193,20261010-025859-2113f00}/tb.json`.
- Criteria transcribed/applied from: `sim/lna-linearity/linearity.py:121`,
  `sim/lna-linearity/linearity.py:157`, `sim/mixer-topology-feasibility/mixfeas.py:465`
  (parse-time gate `mixfeas.py:342`; `RunSpec` `mixfeas.py:361`), third
  consumer `sim/lna-headroom/headroom.py:170` — at commit `c498b96`, where
  these criteria were transcribed (unchanged at this PR's head).
- Numbering: highest existing record on `main` was `0008` at `c498b96`;
  `0009` chosen per `TEMPLATE.md`'s numbering rule and re-checked at PR time
  (asserted by `test_decision_record_matches_measurement`).
- Issue: #266 (split D of #257). Sibling splits #262 (split A), #263 (B),
  #264 (C) and #268 (E) are disjoint: none of them concerns what qualifies a
  bin as coherent.
