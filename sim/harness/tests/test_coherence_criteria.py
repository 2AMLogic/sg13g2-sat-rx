"""The coherent-bin criterion measurement behind decision record 0009 (issue #266).

Both `sim/` benches decide whether an analysed spectral bin is coherent with
the retained window, and each carries its own private ``coherence_problems``:

- ``coherence_problems`` in ``sim/lna-linearity/linearity.py`` -- relative
  tolerance ``tol=1e-9`` everywhere, Nyquist margin 8 samples per period, plus
  a settling-discard check;
- ``coherence_problems`` in ``sim/mixer-topology-feasibility/mixfeas.py`` --
  absolute ``tol=1e-6`` on the window test (relative on cycles), bare Nyquist
  (2 samples per period), no discard check, and a coherence test on the run
  tones.

Neither convention is ratified anywhere in ``spec/``; every recorded result of
three campaigns (lna-linearity, lna-headroom, mixer-topology-feasibility) is
qualified against one of them. This measurement evaluates BOTH criteria
against the actual window/step/frequency sets that produced the existing
records, read from the committed netlist snapshots -- pure arithmetic, no
simulator, no PDK. It is the evidence table of
``spec/decision-records/0009-coherent-bin-criterion.md``; if an assertion
here disagrees with a number quoted in that record, the record is wrong and
this test is the arbiter.

Cross-evaluation convention: the lna criterion is applied to a mixer run's
union of bin frequencies and run tones (the frequency set the mixer campaign
itself qualifies); the mixfeas criterion is applied to an LNA case's analysis
bins (which already include the tones), with no separate tone list. The
mixfeas transcription is cross-checked against the committed
``mixfeas.coherence_problems`` on a deliberately broken run spec.

Run: python3 -m pytest sim/harness/tests/test_coherence_criteria.py -q
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SIM = Path(__file__).resolve().parents[2]
ROOT = SIM.parent
if str(SIM) not in sys.path:
    sys.path.insert(0, str(SIM))  # the campaign modules import ``harness.rf``

REPO_RECORD = ROOT / "spec" / "decision-records" / "0009-coherent-bin-criterion.md"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclass processing resolves the module namespace
    spec.loader.exec_module(mod)
    return mod


L = _load("criterion_linearity", SIM / "lna-linearity" / "linearity.py")
MF = _load("criterion_mixfeas", SIM / "mixer-topology-feasibility" / "mixfeas.py")

LIN_SNAP = SIM / "lna-linearity" / "netlist-snapshots" / "20261010-174208-0f67eaf"
LIN_RECORD = SIM / "lna-linearity" / "records" / "20261010-174208-0f67eaf.json"
MIX_RECORDS = ("20261010-010744-a10c193", "20261010-025859-2113f00")
MIX_SNAPS = {r: SIM / "mixer-topology-feasibility" / "netlist-snapshots" / r for r in MIX_RECORDS}
HEADROOM_RECORDS = ("20261011-053527-d60e79a", "20261031-222819-864b44f")
HEADROOM_SNAPS = {r: SIM / "lna-headroom" / "netlist-snapshots" / r for r in HEADROOM_RECORDS}

LIN_TOL = 1e-9        # linearity.coherence_problems default (relative everywhere)
MIX_TOL = 1e-6        # mixfeas.coherence_problems default (absolute window test)
LIN_NYQUIST_F_STEP = 1.0 / 8.0   # linearity: reject when f*step > 1/8 (8 samples/period)
MIX_NYQUIST_F_STEP = 0.5         # mixfeas: reject when f >= 0.5/tstep (2 samples/period)

# Numbers the record quotes; the assertions below hold them to the arithmetic.
EXPECTED_REAL_CASES = 27          # 18 LNA (3 placements x 3 variants x 2 kinds) + 9 mixer
EXPECTED_HEADROOM_ROWS = 12       # 2 records x 3 placements x 2 kinds, base variant only
EXPECTED_WORST_F_STEP = 0.0212    # f21p20's RF tone at 21.2 GHz (cross-eval union set), step 1 ps
EXPECTED_WORST_SAMPLES_PER_PERIOD = 1.0 / EXPECTED_WORST_F_STEP  # ~47.2
# Window-gate loosening the record's Consequences section quotes, derived
# from the two tolerances: old bound MIX_TOL absolute vs new LIN_TOL*max(1,n)
# absolute, i.e. MIX_TOL/n relative at n = 2e4 and 8e4 -> 20x and 80x,
# growing linearly with n.
EXPECTED_WINDOW_LOOSENING = {2e4: LIN_TOL * 2e4 / MIX_TOL,   # 20x
                             8e4: LIN_TOL * 8e4 / MIX_TOL}   # 80x


# ---------------------------------------------------------------------------
# the mixfeas criterion, transcribed over plain frequency sets
# ---------------------------------------------------------------------------


def mixfeas_style_problems(bins, tones, window_s, tstep_s, tol=MIX_TOL):
    """mixfeas.coherence_problems restated over plain
    (bins, tones, window, step) so the LNA analysis bins can be evaluated
    under the mixer convention. Transcribed verbatim from the committed
    function; cross-checked against it by
    test_mixfeas_transcription_matches_committed."""
    out = []
    steps = window_s / tstep_s
    if abs(steps - round(steps)) > tol:
        out.append("window")
    for f in bins:
        cycles = f * window_s
        if abs(cycles - round(cycles)) > tol * max(1.0, cycles):
            out.append("cycle")
        if f <= 0 or f >= 0.5 / tstep_s:
            out.append("nyquist")
    for f in tones:
        cycles = f * window_s
        if abs(cycles - round(cycles)) > tol * max(1.0, cycles):
            out.append("tone-cycle")
    return out


# ---------------------------------------------------------------------------
# raw residuals (the "by how much" column the record quotes)
# ---------------------------------------------------------------------------


def window_residual(window_s, step_s):
    n = window_s / step_s
    return abs(n - round(n)), n


def discard_residual(discard_s, step_s):
    d = discard_s / step_s
    return abs(d - round(d)), d


def worst_cycle_residual(freqs, window_s):
    return max((abs(f * window_s - round(f * window_s)) for f in freqs), default=0.0)


def nyquist_extremes(freqs, step_s):
    f_max = max(freqs)
    f_step = f_max * step_s
    return f_max, f_step, 1.0 / f_step


# ---------------------------------------------------------------------------
# real cases from the committed snapshots
# ---------------------------------------------------------------------------


def lna_rows(campaign, record_id, plan, variants):
    """One row per placement x variant x kind, both criteria applied."""
    rows = []
    off = float(plan["extraction"]["floor_probe_offset_hz"])
    for pl in plan["placements"]:
        for variant in variants:
            tm = L.variant_timing(plan, variant)
            for kind in ("two", "one"):
                bins = L.analysis_bins(plan, pl, kind)
                own = L.coherence_problems(bins, tm["window_s"], tm["step_s"],
                                           tm["settle_discard_s"])
                other = mixfeas_style_problems(bins.values(), (), tm["window_s"], tm["step_s"])
                fres, n = window_residual(tm["window_s"], tm["step_s"])
                dres, d = discard_residual(tm["settle_discard_s"], tm["step_s"])
                cres = worst_cycle_residual(bins.values(), tm["window_s"])
                _, f_step, spp = nyquist_extremes(bins.values(), tm["step_s"])
                rows.append(dict(campaign=campaign, record=record_id,
                                 case=f"{pl['name']}/{variant}/{kind}",
                                 bins=bins, window_s=tm["window_s"], step_s=tm["step_s"],
                                 discard_s=tm["settle_discard_s"], n=n, d=d,
                                 own=own, other=other,
                                 window_res=fres, discard_res=dres, cycle_res=cres,
                                 f_step=f_step, spp=spp, off_hz=off))
    return rows


def mixer_rows(record_ids):
    """One row per band x kind from the shared committed tb.json study block."""
    tbs = {rid: json.loads((MIX_SNAPS[rid] / "tb.json").read_text()) for rid in record_ids}
    # every record qualifies against the same timing/bands: assert it, then measure once
    blocks = [tb["study"] for tb in tbs.values()]
    for key in ("if_hz", "timing", "bands", "rf_band_hz"):
        for b in blocks[1:]:
            assert b[key] == blocks[0][key], f"{record_ids}: study.{key} differs across records"
    s = blocks[0]
    if_hz = float(s["if_hz"])
    t = s["timing"]
    rows = []
    for b in s["bands"]:
        rf = float(b["rf_hz"])
        t1, t2 = (float(x) for x in b["two_tone_hz"])
        band = MF.Band(name=str(b["name"]), rf_hz=rf, lo_hz=rf - if_hz,
                       two_tone_hz=(t1, t2), two_tone_lo_hz=(t1 + t2) / 2.0 - if_hz)
        for kind in ("single", "rfoff", "two_tone"):
            run = MF.RunSpec(run_id=f"measure-{band.name}-{kind}", kind=kind, band=band,
                             vlo_dbm=0.0, rf_dbm=None if kind == "rfoff" else 0.0,
                             window_s=float(t["window_two_tone_s"]) if kind == "two_tone"
                             else float(t["window_single_s"]),
                             settle_s=float(t["settle_s"]), tmax_s=float(t["tmax_s"]),
                             tstep_s=float(t["tstep_s"]), if_hz=if_hz)
            own = MF.coherence_problems(run)
            bin_freqs = {name: f for name, (_, f) in run.bins().items()}
            if kind == "two_tone":
                tones = {"tone1": band.two_tone_hz[0], "tone2": band.two_tone_hz[1],
                         "tone_lo": band.two_tone_lo_hz}
            else:
                tones = {"tone_rf": band.rf_hz, "tone_lo": band.lo_hz}
            union = dict(bin_freqs, **tones)
            other = L.coherence_problems(union, run.window_s, run.tstep_s, run.settle_s)
            fres, n = window_residual(run.window_s, run.tstep_s)
            dres, d = discard_residual(run.settle_s, run.tstep_s)
            cres = worst_cycle_residual(union.values(), run.window_s)
            _, f_step, spp = nyquist_extremes(union.values(), run.tstep_s)
            rows.append(dict(campaign="mixer-topology-feasibility",
                             record=", ".join(record_ids),
                             case=f"{band.name}/{kind}", bins=bin_freqs,
                             union_freqs=union,
                             window_s=run.window_s, step_s=run.tstep_s,
                             discard_s=run.settle_s, n=n, d=d,
                             own=own, other=other,
                             window_res=fres, discard_res=dres, cycle_res=cres,
                             f_step=f_step, spp=spp, off_hz=None))
    return rows


def build_real_rows():
    plan = L.load_plan(LIN_SNAP / "plan.json")
    rows = lna_rows("lna-linearity", LIN_RECORD.stem, plan, L.VARIANTS)
    headroom = []
    for rid, snap in HEADROOM_SNAPS.items():
        hp = json.loads((snap / "plan.json").read_text())
        declared = hp["linearity_plan"]["sha256"]
        got = __import__("hashlib").sha256((snap / "linearity-plan-v2.json").read_bytes()).hexdigest()
        assert declared == got, f"{rid}: linearity-plan-v2.json sha256 != the record's declared hash"
        lp = L.load_plan(snap / "linearity-plan-v2.json")
        headroom += lna_rows("lna-headroom", rid, lp, ("base",))
    mix = mixer_rows(list(MIX_RECORDS))
    return rows, headroom, mix


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_record_provenance():
    """The snapshots this measurement reads are the ones the records declare."""
    assert LIN_RECORD.exists(), "lna-linearity record missing"
    rec = json.loads(LIN_RECORD.read_text())
    import hashlib
    got = hashlib.sha256((LIN_SNAP / "plan.json").read_bytes()).hexdigest()
    assert rec["plan"]["sha256"] == got, "lna snapshot plan.json is not the recorded plan"


def test_real_runs_pass_both_criteria():
    """Every recorded run of all three campaigns passes its own criterion AND
    the other campaign's (the record's 27/27 result, plus headroom rows)."""
    lna, headroom, mix = build_real_rows()
    assert len(lna) == 18 and len(mix) == 9
    assert len(lna) + len(mix) == EXPECTED_REAL_CASES
    assert len(headroom) == EXPECTED_HEADROOM_ROWS
    for row in lna + headroom + mix:
        assert row["own"] == [], f"{row['campaign']}/{row['case']}: fails its OWN criterion: {row['own']}"
        assert row["other"] == [], f"{row['campaign']}/{row['case']}: fails the OTHER criterion: {row['other']}"


def test_real_residuals_are_exactly_zero():
    """The real-run table does not discriminate: every window, discard and
    cycle residual is exactly 0.0 (exact binary ratios). This is the fact
    that forces the record's Argument onto per-sub-test margins and the
    synthetic cases."""
    lna, headroom, mix = build_real_rows()
    for row in lna + headroom + mix:
        assert row["window_res"] == 0.0, f"{row['campaign']}/{row['case']}"
        assert row["discard_res"] == 0.0, f"{row['campaign']}/{row['case']}"
        assert row["cycle_res"] == 0.0, f"{row['campaign']}/{row['case']}"


def test_real_nyquist_margins():
    """The only non-degenerate real margin: worst analysed bin sits at
    f*step = 0.0212 (47.2 samples per period), far inside both bounds."""
    lna, headroom, mix = build_real_rows()
    worst = max(lna + headroom + mix, key=lambda r: r["f_step"])
    assert worst["f_step"] == EXPECTED_WORST_F_STEP
    assert worst["spp"] == EXPECTED_WORST_SAMPLES_PER_PERIOD
    assert worst["f_step"] < LIN_NYQUIST_F_STEP / 4.0, "no longer 4x inside the 8/period bound"
    for row in lna + headroom + mix:
        assert row["f_step"] < LIN_NYQUIST_F_STEP, f"{row['case']} outside the proposed bound"
        assert row["f_step"] < MIX_NYQUIST_F_STEP, f"{row['case']} outside bare Nyquist"


def test_real_analysed_frequencies_are_positive():
    """Sub-test 3's `f <= 0` exclusion moves nothing measured: no committed
    plan proposes a non-positive analysed bin or tone (the record's
    Consequences quotes this). The transcription itself rejects what the
    criterion rejects."""
    lna, headroom, mix = build_real_rows()
    for row in lna + headroom + mix:
        for f in row["bins"].values():
            assert f > 0, f"{row['campaign']}/{row['case']}: non-positive bin {f!r}"
    for row in mix:
        for f in row["union_freqs"].values():
            assert f > 0, f"{row['campaign']}/{row['case']}: non-positive tone {f!r}"
    window_s, step_s = 2e-8, 1e-12
    assert mixfeas_style_problems((0.0,), (), window_s, step_s) == ["nyquist"]
    assert mixfeas_style_problems((-1.5e10,), (), window_s, step_s) == ["nyquist"]


def test_headroom_rows_equal_lna_base_rows():
    """lna-headroom qualifies the 'base' variant only, against the same
    placements and timing as lna-linearity: its rows must be numerically
    identical to the LNA base rows (the five-record answer is one answer)."""
    lna, headroom, _ = build_real_rows()
    base = {(r["case"], r["campaign"]): r for r in lna if "/base/" in r["case"]}
    for h in headroom:
        ref = base[(h["case"], "lna-linearity")]
        for key in ("window_s", "step_s", "discard_s", "n", "d", "own", "other",
                    "window_res", "discard_res", "cycle_res", "f_step", "spp"):
            assert h[key] == ref[key], f"headroom {h['record']}/{h['case']}: {key} differs from LNA base"


def test_mixfeas_transcription_matches_committed():
    """The transcription fires exactly where the committed function fires, on
    a deliberately broken run spec (window off-grid by 1e-4 relative, an
    incoherent two-tone) and on a clean one."""
    manifest = json.loads((MIX_SNAPS[MIX_RECORDS[0]] / "tb.json").read_text())
    s = manifest["study"]
    t = s["timing"]
    if_hz = float(s["if_hz"])
    b = s["bands"][0]
    rf, t1, t2 = float(b["rf_hz"]), float(b["two_tone_hz"][0]), float(b["two_tone_hz"][1])
    band = MF.Band(name=str(b["name"]), rf_hz=rf, lo_hz=rf - if_hz,
                   two_tone_hz=(t1, t2), two_tone_lo_hz=(t1 + t2) / 2.0 - if_hz)
    clean = MF.RunSpec(run_id="clean", kind="two_tone", band=band, vlo_dbm=0.0, rf_dbm=0.0,
                       window_s=float(t["window_two_tone_s"]), settle_s=float(t["settle_s"]),
                       tmax_s=float(t["tmax_s"]), tstep_s=float(t["tstep_s"]), if_hz=if_hz)
    broken = MF.RunSpec(run_id="broken", kind="two_tone", band=band, vlo_dbm=0.0, rf_dbm=0.0,
                        window_s=float(t["window_two_tone_s"]) * 1.0001,
                        settle_s=float(t["settle_s"]), tmax_s=float(t["tmax_s"]),
                        tstep_s=float(t["tstep_s"]), if_hz=if_hz)
    bin_freqs = {name: f for name, (_, f) in clean.bins().items()}
    for run in (clean, broken):
        committed = MF.coherence_problems(run)
        kinds = set()
        for p in committed:
            if p.startswith("window"):
                kinds.add("window")
            elif "outside (0, Nyquist)" in p:
                kinds.add("nyquist")
            elif p.startswith("bin"):
                kinds.add("cycle")
            elif p.startswith("tone"):
                kinds.add("tone-cycle")
            else:
                raise AssertionError(f"unclassified committed problem: {p}")
        tones = run.tones  # the exact tone set the committed function tests (RunSpec.tones)
        mine = set(mixfeas_style_problems(bin_freqs.values(), tones, run.window_s, run.tstep_s))
        assert mine == kinds, f"{run.run_id}: transcription {mine} != committed {kinds}"
    assert MF.coherence_problems(clean) == []          # sanity: the clean spec passes
    assert len(MF.coherence_problems(broken)) >= 9     # window + every bin + every tone fires


def test_synthetic_window_discriminates():
    """n = 20000 + 1e-5: residual 1e-5 fails mixfeas's absolute 1e-6, passes
    linearity's relative 2e-5. Neither criterion dominates on the window test."""
    step = 1e-12
    window = (20000 + 1e-5) * step
    res, n = window_residual(window, step)
    lin_fail = res > LIN_TOL * max(1.0, n)
    mix_fail = res > MIX_TOL
    assert not lin_fail and mix_fail
    assert 1e-6 < res < 2e-5, f"residual {res!r} out of the recorded band (1e-6, 2e-5)"


def test_synthetic_nyquist_discriminates():
    """4 samples per period: inside mixfeas's bare Nyquist, outside
    linearity's 8 samples per period."""
    f, step = 2.5e11, 1e-12
    f_step = f * step
    lin_fail = f_step > LIN_NYQUIST_F_STEP
    mix_fail = f <= 0 or f >= 0.5 / step
    assert lin_fail and not mix_fail
    assert 3.9 < 1.0 / f_step < 4.1, f"expected ~4 samples/period, got {1.0 / f_step}"


def test_synthetic_discard_discriminates():
    """A settle discard half a step off a sample: linearity's criterion fires,
    mixfeas has no such test (so it passes vacuously)."""
    step = 1e-12
    discard = 4e-8 + 0.5 * step
    res, d = discard_residual(discard, step)
    lin_fail = res > LIN_TOL * max(1.0, d)
    assert lin_fail
    assert res == 0.5
    mix_has_discard_test = any("discard" in p or "settle" in p
                               for p in mixfeas_style_problems((), (), 2e-8, step))
    assert not mix_has_discard_test, "transcription grew a discard test; update the record"


def test_synthetic_both_reject_control():
    """A grossly off-grid window (n = 20000.5) is rejected by BOTH criteria:
    the table distinguishes 'both accept' from 'the criteria are
    indistinguishable'."""
    step = 1e-12
    window = 20000.5 * step
    res, n = window_residual(window, step)
    assert res > LIN_TOL * max(1.0, n), "linearity accepted a half-sample-off window"
    assert res > MIX_TOL, "mixfeas accepted a half-sample-off window"


def test_decision_record_matches_measurement():
    """The record's quoted numbers come from this measurement (and nowhere
    else); the record carries Status: proposed and neither ratification key."""
    assert REPO_RECORD.exists(), "spec/decision-records/0009-coherent-bin-criterion.md missing"
    text = REPO_RECORD.read_text()
    assert "Status**: proposed" in text, "record must be proposed, not ratified"
    for quoted in ("27", "0.0212", "1e-9", "8 samples per period", "47.2", "f <= 0"):
        assert quoted in text, f"record does not quote {quoted!r}"
    # sub-test 3 must rule on the non-positive-frequency exclusion, not omit
    # it: pin the two-sided reject clause as it appears in the Decision (the
    # bare "f <= 0" also occurs in the Context quoting mixfeas's old guard).
    assert "`f <= 0` or `f * step_s > 1.0 / 8.0`" in text, (
        "Decision sub-test 3 must reject `f <= 0` alongside the "
        "8-samples-per-period bound")
    # the Consequences section's window-gate loosening, derived from the two
    # tolerances so record and measurement cannot drift: 20x at n = 2e4,
    # 80x at n = 8e4, with the old bound quoted in relative terms
    for n, factor in EXPECTED_WINDOW_LOOSENING.items():
        assert f"{factor:g}x" in text, (
            f"record does not quote the {factor:g}x window-gate loosening (n={n:g})")
        assert f"{MIX_TOL / n:g}" in text, (
            f"record does not quote the {MIX_TOL / n:g} old relative window bound")
    # numbering: 0009 follows its predecessor 0008; records added after 0009
    # are the numbering rule working, not drift, and are free to exceed it
    nums = sorted(int(p.name[:4]) for p in (ROOT / "spec" / "decision-records").glob("*.md")
                  if p.name[:4].isdigit())
    assert 9 in nums and 8 in nums, f"decision-record numbering drifted (0008/0009 missing): {nums}"


# ---------------------------------------------------------------------------
# table printer (the record's tables are generated from this)
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    lna, headroom, mix = build_real_rows()
    print(f"| campaign | record | case | window_s | step_s | n | discard_s | d | "
          f"own | other | win res | cyc res | worst f*step | samples/period |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in lna + headroom + mix:
        print(f"| {r['campaign']} | {r['record']} | {r['case']} | {r['window_s']:g} | "
              f"{r['step_s']:g} | {r['n']:.0f} | {r['discard_s']:g} | {r['d']:.0f} | "
              f"{'PASS' if not r['own'] else 'FAIL'} | {'PASS' if not r['other'] else 'FAIL'} | "
              f"{r['window_res']:g} | {r['cycle_res']:g} | {r['f_step']:.4g} | {r['spp']:.1f} |")
    worst = max(lna + headroom + mix, key=lambda r: r["f_step"])
    print(f"\nworst f*step = {worst['f_step']:g} ({worst['spp']:.2f} samples/period); "
          f"{LIN_NYQUIST_F_STEP / worst['f_step']:.1f}x inside the 8/period bound, "
          f"{MIX_NYQUIST_F_STEP / worst['f_step']:.1f}x inside bare Nyquist")
