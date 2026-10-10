"""Record tables for the lna_stage1 bench (issue #28).

Pure Python, no simulator. Turns the per-corner scalar measurements (the
``m_*`` lines of each corner log) and the printed wide stability sweep (the
SWEEP_BEGIN/SWEEP_END block of each corner log) into the Markdown sections
appended to an lna-sparam-nf record:

* the per-device, per-grid-cell operating-point table with the row-17 /
  model-box pass/fail columns (failing cells are listed, never dropped; the
  2.75 V supply points are labelled as an EXCURSION above the 2.5 V ceiling);
* the k / |Delta| / mu table in band and over the wide sweep, with
  POTENTIALLY UNSTABLE labelling and MSG-not-gain reporting;
* an independent recomputation of the sweep statistics from the printed
  sweep, compared with the bench's own ``m_sw_*`` scalars.

The limits below are the ratified row 17 and the model-card validity box
(spec/target-spec.md row 17; sim/hbt-kaband-characterization/ box); they are
constants here so a test can pin them, not tunables.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

#: row 17: no single npn13G2 above this V_CE.
VCE_MAX_V = 1.4
#: row 17 / model card: operate inside the card's own vce window.
VCE_WINDOW_V = (0.4, 2.0)
#: model card validity box (sg13g2_hbt_mod.lib header): V_BE window.
VBE_WINDOW_V = (0.65, 0.96)
#: model card validity box: Ic < 3 mA x Nx  (the table reports Ic/(3 mA x Nx)).
ICFRAC_MAX = 1.0
#: band top of the DRAFT band (spec row 1, OPEN): fT must exceed it.
F_BAND_TOP_GHZ = 21.2
#: row 17 rail ceiling; supply points above it are excursions.
RAIL_CEILING_V = 2.5

DEVICES = (("q1", "Q1 (CE)", 8), ("q2", "Q2 (CB)", 8), ("qr", "Qref (mirror)", 1))
BAND_SUFFIX = (("lo", 17.7), ("mid", 19.45), ("hi", 21.2))

_ROW_RE = re.compile(r"^\d+\t(\S+)\t(\S+)\t(\S+)\t(\S+)\t(\S+)\s*$")


def supply_class(vdd: float) -> str:
    return "EXCURSION (above 2.5 V row-17 ceiling)" if vdd > RAIL_CEILING_V + 1e-9 else "within row-17 rail"


def parse_sweep(text: str) -> dict[str, list[float]]:
    """The printed sweep of one corner log: frequency (Hz), k, |Delta|, mu."""
    lo = text.find("SWEEP_BEGIN")
    hi = text.find("SWEEP_END")
    if lo < 0 or hi < lo:
        raise ValueError("log has no SWEEP_BEGIN/SWEEP_END block")
    cols: dict[str, list[float]] = {"f": [], "k": [], "d": [], "mu": []}
    for line in text[lo:hi].splitlines():
        m = _ROW_RE.match(line)
        if m:
            cols["f"].append(float(m.group(2)))
            cols["k"].append(float(m.group(3)))
            cols["d"].append(float(m.group(4)))
            cols["mu"].append(float(m.group(5)))
    return cols


@dataclass
class SweepStats:
    n: int
    f_min_ghz: float
    f_max_ghz: float
    ratio_step: float
    kmin: float
    f_at_kmin_ghz: float
    kmin_above_band: float
    kmin_below_band: float
    dmax: float
    mumin: float
    n_unstable: int


def sweep_stats(cols: dict[str, list[float]]) -> SweepStats:
    f, k, d, mu = cols["f"], cols["k"], cols["d"], cols["mu"]
    if not f:
        raise ValueError("empty sweep")
    i = min(range(len(k)), key=lambda j: k[j])
    above = [x for x, ff in zip(k, f) if ff > 21.2e9]
    below = [x for x, ff in zip(k, f) if ff < 17.7e9]
    unstable = sum(1 for kk, dd in zip(k, d) if kk <= 1.0 or dd >= 1.0)
    return SweepStats(
        n=len(f), f_min_ghz=f[0] / 1e9, f_max_ghz=f[-1] / 1e9,
        ratio_step=f[1] / f[0] if len(f) > 1 else float("nan"),
        kmin=k[i], f_at_kmin_ghz=f[i] / 1e9,
        kmin_above_band=min(above) if above else float("nan"),
        kmin_below_band=min(below) if below else float("nan"),
        dmax=max(d), mumin=min(mu), n_unstable=unstable)


def op_flags(m: dict[str, float], dev: str, f_top_ghz: float = F_BAND_TOP_GHZ) -> dict[str, bool]:
    """Pass/fail of one device in one grid cell against the stated limits."""
    vce, vbe = m[f"{dev}_vce"], m[f"{dev}_vbe"]
    return {
        "vce_le_1v4": vce <= VCE_MAX_V,
        "vce_in_window": VCE_WINDOW_V[0] <= vce <= VCE_WINDOW_V[1],
        "vbe_in_window": VBE_WINDOW_V[0] <= vbe <= VBE_WINDOW_V[1],
        "ic_in_box": m[f"{dev}_icfrac"] < ICFRAC_MAX,
        "ft_above_band": m[f"{dev}_ft"] > f_top_ghz,
    }


FLAG_HEAD = ("VCE<=1.4", "VCE 0.4-2.0", "VBE .65-.96", "Ic<3mA*Nx", "fT>21.2G")
_FLAG_KEYS = ("vce_le_1v4", "vce_in_window", "vbe_in_window", "ic_in_box", "ft_above_band")


def _pf(b: bool) -> str:
    return "pass" if b else "**FAIL**"


def stability_flag(m: dict[str, float]) -> tuple[bool, list[str]]:
    """(unstable?, reasons). Unstable if k <= 1 or |Delta| >= 1 at any in-band
    point or anywhere in the wide sweep."""
    why = []
    for s, f in BAND_SUFFIX:
        if m[f"k_{s}"] <= 1.0:
            why.append(f"k<=1 @{f} GHz")
        if m[f"d_{s}"] >= 1.0:
            why.append(f"|Delta|>=1 @{f} GHz")
    if m["sw_nunst"] > 0.5:
        why.append(f"{m['sw_nunst']:.0f} sweep point(s) with k<=1 or |Delta|>=1")
    return (bool(why), why)


def render(results: dict[str, dict[str, float]], texts: dict[str, str], vdd_of: dict[str, float],
           corner_meta: dict[str, tuple[str, float]]) -> str:
    """Markdown sections for the record. ``results``: corner_id -> measurements;
    ``texts``: corner_id -> log text; ``vdd_of``: corner_id -> supply;
    ``corner_meta``: corner_id -> (process, temp_c)."""
    ids = sorted(results, key=lambda c: (vdd_of[c], corner_meta[c][0], corner_meta[c][1]))
    out: list[str] = [
        "", "## How to read this record", "",
        "- `Status: pass` / `Result: PASS` above mean only that the bench ran every one of the 27 grid points "
        "with finite values and that its two sensitivity-floor checks (proof the PVT grid perturbs the circuit) "
        "held. They are NOT spec verdicts. Claim: ideal-matching feasibility record; no spec row is claimed met; "
        "row 6 (k > 1) is reported, not claimed.",
        "- The matching is ideal lossless L/C sized once at the DRAFT band centre (spec row 1 is OPEN); it is not "
        "re-tuned per corner, so the spread in S11 / S22 / S21 across the grid includes match detuning.",
        "- Rows 2-5 (gain, NF, S11, S22) are compared with nothing here; the Summary above lists the extremes.",
        "- Open operator question, flagged and not decided: is the 2.75 V corner (nominal 2.5 V + 10 %) inside "
        "row 17's scope? Every table below carries the 2.75 V cells as a labelled excursion so either answer "
        "needs no re-run.",
    ]

    # ---- operating points ---------------------------------------------------
    out += ["", "## Operating points per device and grid cell (`.op`, selft=1)", "",
            "One row per transistor per PVT cell. Limits: row 17 (V_CE <= 1.4 V; V_CE inside the card's "
            "0.4-2.0 V window), the card box (V_BE 0.65-0.96 V; I_C < 3 mA x Nx), and fT above the DRAFT "
            f"band top ({F_BAND_TOP_GHZ} GHz). `Ic/box` = I_C / (3 mA x Nx). dTj = self-heating rise from the "
            "thermal node. fT is the small-signal estimate gm / (2 pi (cbe+cbex+cbc+cbcx+cbep+cbcp)) from the "
            "operating-point model parameters (all capacitances incl. parasitics; it reproduces the Ka-band "
            "characterization record's fT at the same J_C to within the model, but is NOT a measured h21 "
            "extrapolation). A failing cell is shown, never removed; the 2.75 V rows are the labelled supply "
            "EXCURSION above the 2.5 V rail ceiling (whether 2.75 V is in or out of row 17's scope is an open "
            "operator question, so both readings can be read off this table without a re-run).", "",
            "| cell | supply class | device | V_CE (V) | V_BE (V) | I_C (mA) | Ic/box | dTj (K) | fT est (GHz) | "
            + " | ".join(FLAG_HEAD) + " |",
            "|---|---|---|---|---|---|---|---|---|" + "---|" * len(FLAG_HEAD)]
    fails: list[str] = []
    fail_exc: list[str] = []
    for cid in ids:
        m = results[cid]
        for dev, label, _nx in DEVICES:
            fl = op_flags(m, dev)
            out.append(
                f"| {cid} | {supply_class(vdd_of[cid])} | {label} | {m[f'{dev}_vce']:.3f} | {m[f'{dev}_vbe']:.3f} | "
                f"{m[f'{dev}_ic'] * 1e3:.3f} | {m[f'{dev}_icfrac']:.3f} | {m[f'{dev}_dtj']:.2f} | "
                f"{m[f'{dev}_ft']:.0f} | " + " | ".join(_pf(fl[k]) for k in _FLAG_KEYS) + " |")
            bad = [h for h, k in zip(FLAG_HEAD, _FLAG_KEYS) if not fl[k]]
            if bad:
                (fail_exc if vdd_of[cid] > RAIL_CEILING_V + 1e-9 else fails).append(
                    f"{cid} {label}: {', '.join(bad)} (V_CE {m[f'{dev}_vce']:.3f} V)")
    out += ["", "### Operating-point verdict", ""]
    n_cells_le = sum(1 for c in ids if vdd_of[c] <= RAIL_CEILING_V + 1e-9)
    out.append(f"- Cells at supply <= 2.5 V: {n_cells_le}; failing device-cells there: **{len(fails)}**."
               + ("" if not fails else " Listed: " + "; ".join(fails) + "."))
    out.append(f"- Cells at the 2.75 V EXCURSION supply: {len(ids) - n_cells_le}; failing device-cells: "
               f"**{len(fail_exc)}**." + ("" if not fail_exc else " Listed: " + "; ".join(fail_exc) + "."))
    for dev, label, _nx in DEVICES:
        for scope, pick in (("<= 2.5 V", lambda c: vdd_of[c] <= RAIL_CEILING_V + 1e-9),
                            ("2.75 V excursion", lambda c: vdd_of[c] > RAIL_CEILING_V + 1e-9)):
            sel = [c for c in ids if pick(c)]
            vmax = max(sel, key=lambda c: results[c][f"{dev}_vce"])
            tmax = max(sel, key=lambda c: results[c][f"{dev}_dtj"])
            ftmin = min(sel, key=lambda c: results[c][f"{dev}_ft"])
            out.append(
                f"- {label}, {scope}: max V_CE {results[vmax][f'{dev}_vce']:.3f} V ({vmax}); "
                f"max dTj {results[tmax][f'{dev}_dtj']:.2f} K ({tmax}); "
                f"min fT est {results[ftmin][f'{dev}_ft']:.0f} GHz ({ftmin}).")
    pd = max(ids, key=lambda c: results[c]["pdc_mw"])
    out.append(f"- Supply current / DC power (whole stage incl. bias): max {results[pd]['idd_ma']:.2f} mA, "
               f"{results[pd]['pdc_mw']:.2f} mW at {pd}.")

    # ---- stability ------------------------------------------------------------
    stats = {c: sweep_stats(parse_sweep(texts[c])) for c in ids}
    s0 = stats[ids[0]]
    out += ["", "## Stability: k, |Delta|, mu (reported, NOT claimed against row 6)", "",
            "k = (1 - |S11|^2 - |S22|^2 + |Delta|^2) / (2 |S12 S21|), Delta = S11 S22 - S12 S21, "
            "mu = (1 - |S11|^2) / (|S22 - Delta S11*| + |S12 S21|), all with the 50 ohm power-wave ports of this "
            f"bench. In band at 17.7 / 19.45 / 21.2 GHz (the 3-point set), plus a wide sweep of **{s0.n} points, "
            f"logarithmic, 100 points per decade (adjacent-point ratio {s0.ratio_step:.4f}, i.e. {100 * (s0.ratio_step - 1):.2f} %), "
            f"{s0.f_min_ghz:g} GHz to {s0.f_max_ghz:g} GHz**, which reaches past row 6's 63.6 GHz (3 x 21.2 GHz) "
            "with a step of about 1.5 GHz there. The sweep does NOT cover below 1 GHz or above 100 GHz. A cell with "
            "k <= 1 or |Delta| >= 1 anywhere in band or in the sweep is labelled `POTENTIALLY UNSTABLE` and its "
            "gain column is MSG (|S21|/|S12|), not S21. Every cell is listed.", "",
            "| cell | verdict | k 17.7/19.45/21.2 | \\|Delta\\| 17.7/19.45/21.2 | mu 17.7/19.45/21.2 | "
            "gain dB 17.7/19.45/21.2 | gain kind | sweep k min (GHz) | k min above band | k min below band | "
            "\\|Delta\\| max | mu min | unstable pts |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    n_unst = 0
    for cid in ids:
        m, st = results[cid], stats[cid]
        unst, why = stability_flag(m)
        n_unst += unst
        kind = "MSG" if unst else "S21"
        gain = [m[f"msg_db_{s}"] if unst else m[f"s21_db_{s}"] for s, _ in BAND_SUFFIX]
        verdict = "**POTENTIALLY UNSTABLE** (" + "; ".join(why) + ")" if unst else "k>1, \\|Delta\\|<1 (reported)"
        out.append(
            f"| {cid} | {verdict} | " + " / ".join(f"{m[f'k_{s}']:.2f}" for s, _ in BAND_SUFFIX)
            + " | " + " / ".join(f"{m[f'd_{s}']:.3f}" for s, _ in BAND_SUFFIX)
            + " | " + " / ".join(f"{m[f'mu_{s}']:.2f}" for s, _ in BAND_SUFFIX)
            + " | " + " / ".join(f"{g:.1f}" for g in gain) + f" | {kind} | "
            f"{st.kmin:.2f} ({st.f_at_kmin_ghz:.1f}) | {st.kmin_above_band:.2f} | {st.kmin_below_band:.2f} | "
            f"{st.dmax:.3f} | {st.mumin:.2f} | {st.n_unstable}/{st.n} |")
    out += ["", f"- Cells labelled POTENTIALLY UNSTABLE: **{n_unst} of {len(ids)}**."]
    worst = min(ids, key=lambda c: stats[c].kmin)
    out.append(f"- Lowest k anywhere in any sweep: {stats[worst].kmin:.3f} at {stats[worst].f_at_kmin_ghz:.1f} GHz "
               f"({worst}); highest |Delta|: {max(s.dmax for s in stats.values()):.3f}; lowest mu: "
               f"{min(s.mumin for s in stats.values()):.3f}.")

    # ---- cross-check ----------------------------------------------------------
    worst_dev = 0.0
    for cid in ids:
        m, st = results[cid], stats[cid]
        for name, mine in (("sw_kmin", st.kmin), ("sw_dmax", st.dmax), ("sw_mumin", st.mumin)):
            theirs = m[name]
            worst_dev = max(worst_dev, abs(theirs - mine) / max(abs(theirs), 1e-30))
        if int(round(m["sw_n"])) != st.n or int(round(m["sw_nunst"])) != st.n_unstable:
            worst_dev = float("inf")
    out += ["", "### Sweep statistics cross-check", "",
            "The `m_sw_*` scalars the bench computes inside ngspice were recomputed in Python from the printed "
            f"sweep in each corner log (point count, unstable-point count, k min, |Delta| max, mu min): max relative "
            f"deviation {worst_dev:.2e} over {len(ids)} cells (printed precision is 10 significant digits)."]
    if not math.isfinite(worst_dev) or worst_dev > 1e-6:
        raise ValueError(f"sweep statistics disagree with the bench scalars (max rel dev {worst_dev})")
    return "\n".join(out) + "\n"
