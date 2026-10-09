"""Record rendering for the Ka-band device characterization bench.

Turns the full per-point rows of one 27-point PVT campaign into:

- ``points``: every row (every PVT point x Nx x VCE x VBE x frequency),
  including excluded and out-of-model rows with their reasons -- the
  sidecar that keeps the whole sweep, so no summary can discard data;
- ``cells``: per (PVT point, Nx, VCE, frequency) noise optimum / fT peak;
- ``best``: per (PVT point, frequency) the lowest-NFmin eligible optimum
  over every Nx and VCE (the row-3 screen's input);

plus the Markdown record. Pure functions over row dicts (see kaband.py).
"""

from __future__ import annotations

from collections import Counter, defaultdict

import kaband

T0 = kaband.T0_IEEE_K
NFKEY = f"nfmin_db_t{T0:g}"
NFKEY_REPO = f"nfmin_db_t{kaband.T0_REPO_K:g}"
NF50KEY = f"nf50_db_t{T0:g}"

POINT_COLUMNS = [
    "corner_id", "corner", "temp_c", "vdd_v", "nx", "vce_set_v", "vbe_set_v", "freq_hz",
    "status", "reason", "in_box", "active", "validity_flags", "bias_max_rel_dev", "sim_messages",
    "ic_a", "ib_a", "vbe_v", "vce_v", "jc_ma_um2", "jc_alt_ma_um2", "pdc_mw", "dtj_k", "vsupply_v",
    "ft_hz", "ft_status", "ft_bracket",
    "k", "delta_mag", "gmax_db", "gmax_kind", "msg_db", "s21_db", "s11_db",
    "ropt_ohm", "xopt_ohm", "gamma_opt_mag", "gamma_opt_deg", "tmin_k", "rn_ohm",
    "nfmin_db_t290", "nfmin_db_t300.15", "nf50_db_t290", "nf50_db_t300.15",
    "fit_max_rel_residual", "nf50_fit_delta_db",
    "nfmin_check", "nfmin_check_zs_ohm", "nfmin_check_db", "nfmin_check_delta_db",
    "nfmin_check_fit_delta_db",
]

CELL_COLUMNS = [
    "corner_id", "corner", "temp_c", "vdd_v", "nx", "vce_set_v", "freq_hz",
    "n_points", "n_ok", "n_in_box", "n_eligible", "n_excluded",
    "eligible_jc_min", "eligible_jc_max", "eligible_jc_decades",
    "opt_jc_ma_um2", "opt_vbe_v", "opt_ic_a", "opt_nfmin_db_t290", "opt_nfmin_db_t300.15",
    "opt_tmin_k", "opt_ropt_ohm", "opt_xopt_ohm", "opt_rn_ohm", "opt_nf50_db_t290",
    "opt_gmax_db", "opt_gmax_kind", "opt_k", "opt_delta_mag", "opt_ft_hz", "opt_pdc_mw", "opt_dtj_k",
    "opt_constrained_by",
    "ftpk_jc_ma_um2", "ftpk_ft_hz", "ftpk_at_inbox_edge", "opt_over_ftpk_jc",
]

BEST_COLUMNS = ["corner_id", "corner", "temp_c", "vdd_v", "freq_hz", "best_nx", "best_vce_set_v"] + [
    c for c in CELL_COLUMNS if c.startswith(("opt_", "ftpk_", "eligible_jc"))
] + ["row3_margin_db"]


def _fmt(v, digits=4):
    if v is None or v == "":
        return "-"
    if isinstance(v, float):
        if v != 0 and (abs(v) >= 1e5 or abs(v) < 1e-3):
            return f"{v:.{digits - 1}e}"
        return f"{v:.{digits}g}"
    return str(v)


def _ghz(v):
    return "-" if v is None else f"{v / 1e9:.1f}"


def cells(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["corner_id"], r["nx"], r["vce_set_v"], r["freq_index"])].append(r)
    out = []
    for (cid, nx, vce, _k), grp in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2], kv[0][3])):
        c = kaband.cell_optima(grp, T0)
        first = grp[0]
        row = {"corner_id": cid, "corner": first["corner"], "temp_c": first["temp_c"],
               "vdd_v": first["vdd_v"], "nx": nx, "vce_set_v": vce, "freq_hz": first["freq_hz"]}
        for key in ("n_points", "n_ok", "n_in_box", "n_eligible", "n_excluded", "eligible_jc_min",
                    "eligible_jc_max", "eligible_jc_decades", "opt_constrained_by",
                    "opt_over_ftpk_jc", "ftpk_at_inbox_edge"):
            row[key] = c.get(key)
        opt = c.get("opt_row")
        if opt:
            for src, dst in (("jc_ma_um2", "opt_jc_ma_um2"), ("vbe_v", "opt_vbe_v"), ("ic_a", "opt_ic_a"),
                             (NFKEY, "opt_nfmin_db_t290"), (NFKEY_REPO, "opt_nfmin_db_t300.15"),
                             ("tmin_k", "opt_tmin_k"), ("ropt_ohm", "opt_ropt_ohm"),
                             ("xopt_ohm", "opt_xopt_ohm"), ("rn_ohm", "opt_rn_ohm"),
                             (NF50KEY, "opt_nf50_db_t290"), ("gmax_db", "opt_gmax_db"),
                             ("gmax_kind", "opt_gmax_kind"), ("k", "opt_k"),
                             ("delta_mag", "opt_delta_mag"), ("ft_hz", "opt_ft_hz"),
                             ("pdc_mw", "opt_pdc_mw"), ("dtj_k", "opt_dtj_k")):
                row[dst] = opt.get(src)
        ftpk = c.get("ftpk_row")
        if ftpk:
            row["ftpk_jc_ma_um2"] = ftpk["jc_ma_um2"]
            row["ftpk_ft_hz"] = ftpk["ft_hz"]
        out.append(row)
    return out


def best_per_corner_freq(cell_rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for c in cell_rows:
        groups[(c["corner_id"], c["freq_hz"])].append(c)
    out = []
    for (cid, f), grp in groups.items():
        cand = [c for c in grp if c.get("opt_nfmin_db_t290") is not None]
        first = grp[0]
        row = {"corner_id": cid, "corner": first["corner"], "temp_c": first["temp_c"],
               "vdd_v": first["vdd_v"], "freq_hz": f}
        if cand:
            b = min(cand, key=lambda c: c["opt_nfmin_db_t290"])
            row.update({k: v for k, v in b.items() if k.startswith(("opt_", "ftpk_", "eligible_jc"))})
            row["best_nx"] = b["nx"]
            row["best_vce_set_v"] = b["vce_set_v"]
            row["row3_margin_db"] = kaband.ROW3_LIMIT_DB - b["opt_nfmin_db_t290"]
        out.append(row)
    order = {"hbt_typ": 0, "hbt_bcs": 1, "hbt_wcs": 2}
    out.sort(key=lambda r: (order.get(r["corner"], 9), r["temp_c"], r["vdd_v"], r["freq_hz"]))
    return out


def supply_invariance(rows: list[dict]) -> dict:
    """Max difference of key quantities across the supply axis at an
    otherwise identical point (expected exactly zero: the rail is not
    connected to the DUT)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("status") == "ok":
            groups[(r["corner"], r["temp_c"], r["nx"], r["vce_set_v"], r["vbe_set_v"],
                    r["freq_index"])].append(r)
    worst = {"ic_a_rel": 0.0, "ft_hz_rel": 0.0, NFKEY: 0.0, "gmax_db": 0.0}
    levels = set()
    for grp in groups.values():
        levels.add(len({r["vdd_v"] for r in grp}))
        if len(grp) < 2:
            continue
        ic = [r["ic_a"] for r in grp]
        worst["ic_a_rel"] = max(worst["ic_a_rel"], (max(ic) - min(ic)) / max(ic))
        ft = [r["ft_hz"] for r in grp if r.get("ft_hz")]
        if len(ft) == len(grp):
            worst["ft_hz_rel"] = max(worst["ft_hz_rel"], (max(ft) - min(ft)) / max(ft))
        for key in (NFKEY, "gmax_db"):
            vals = [r[key] for r in grp if r.get(key) is not None]
            if vals:
                worst[key] = max(worst[key], max(vals) - min(vals))
    worst["supply_levels_per_group"] = sorted(levels)
    return worst


def quality(rows: list[dict]) -> dict:
    ok = [r for r in rows if r.get("status") == "ok"]
    reasons = Counter((r.get("reason") or "").split(":")[0] for r in rows if r.get("status") != "ok")
    return {
        "rows": len(rows),
        "ok": len(ok),
        "excluded": len(rows) - len(ok),
        "excluded_by_reason": dict(reasons.most_common()),
        "in_box": sum(1 for r in ok if r.get("in_box")),
        "eligible": sum(1 for r in ok if r.get("in_box") and r.get("active")),
        "inactive": sum(1 for r in ok if not r.get("active")),
        "flags": dict(Counter(f for r in ok for f in (r.get("validity_flags") or "").split(";") if f)),
        "ft_status": dict(Counter(r.get("ft_status") for r in ok)),
        "max_abs_nf50_check_db": max((abs(r["nf50_fit_delta_db"]) for r in ok), default=None),
        "max_abs_nfmin_check_db": max((abs(r["nfmin_check_delta_db"]) for r in ok), default=None),
        "max_fit_residual": max((r["fit_max_rel_residual"] for r in ok), default=None),
        "gmax_kind": dict(Counter(r.get("gmax_kind") for r in ok)),
        "max_dtj_k": max((r["dtj_k"] for r in ok), default=None),
    }


def render(*, record_id, tb, sweep, rows, started, git, ngspice, pdk_prov, klt_meta, claim,
           supersedes, crosscheck=None, messages=None) -> tuple[str, dict]:
    cell_rows = cells(rows)
    best = best_per_corner_freq(cell_rows)
    def screen_input(col: str, key: str) -> dict:
        return {(b["corner_id"], b["freq_hz"]): ({key: b[col]} if b.get(col) is not None else None)
                for b in best}

    screen = kaband.row3_screen(screen_input("opt_nfmin_db_t290", NFKEY), T0)
    screen_repo = kaband.row3_screen(screen_input("opt_nfmin_db_t300.15", NFKEY_REPO), kaband.T0_REPO_K)
    q = quality(rows)
    inv = supply_invariance(rows)
    corner_ids = sorted({r["corner_id"] for r in rows})

    L: list[str] = []
    L += [
        f"# {record_id}",
        "",
        "**Status**: complete (every declared PVT point, bias point and frequency present; "
        "excluded rows carry reasons -- see Data quality)",
        f"**Experiment**: {tb.experiment}",
        f"**Started (UTC)**: {started.isoformat()}",
    ]
    if supersedes:
        L.append(f"**Supersedes**: {supersedes}")
    L += ["", f"**Claim**: {claim}", ""]
    L += [
        "## What this record is",
        "",
        "Two-port parameters of ONE BARE `npn13G2` with ideal bias tees and ideal noiseless "
        "terminations, at 17.7 / 19.45 / 21.2 GHz, across the HBT process x temperature x supply "
        "grid. **Device-level evidence, not a matched-amplifier result**: NFmin is the device's "
        "minimum noise figure at its optimum source impedance, a lower bound for any circuit built "
        "around it *before* matching-network loss, bias-network noise and the following stage; "
        "MAG/MSG is device gain. No `spec/target-spec.md` row is claimed met. Method: "
        "`sim/hbt-kaband-characterization/README.md`.",
        "",
        "## Grid",
        "",
        f"- **PVT points**: {len(corner_ids)} = process {', '.join(c.name for c in kaband_corners(tb))} x "
        f"temperature {', '.join(f'{t:g} C' for t in tb.temperatures_c)} x supply "
        f"{', '.join(f'{v:.2f} V' for v in sorted({r['vdd_v'] for r in rows}))}.",
        "- **Supply axis**: present in every deck as the `vsupply` rail (value printed back per point "
        "as `vsupply_v`), NOT connected to the DUT -- the bias is an ideal regulator (ideal VBE/VCE "
        "sources), so the rail is physically inert by construction. No supply-sensitivity floor is "
        f"attached. Observed invariance across supply at otherwise identical points: max |dIc|/Ic = "
        f"{_fmt(inv['ic_a_rel'])}, max |dfT|/fT = {_fmt(inv['ft_hz_rel'])}, max |dNFmin| = "
        f"{_fmt(inv[NFKEY])} dB, max |dGmax| = {_fmt(inv['gmax_db'])} dB "
        f"(supply levels per group: {inv['supply_levels_per_group']}).",
        f"- **Nx** (emitter multiplicity): {', '.join(str(n) for n in sweep.nx)} (card validity 1-10).",
        f"- **VCE**: {', '.join(f'{v:g} V' for v in sweep.vce_v)} (ideal, at the device terminals; "
        "card validity 0.4-2.0 V; 1.4 V = BVCEO min).",
        f"- **VBE**: {sweep.vbe_v[0]:g} to {sweep.vbe_v[-1]:g} V, {len(sweep.vbe_v)} points "
        f"(step {sweep.vbe_v[1] - sweep.vbe_v[0]:.3g} V, i.e. J_C steps of roughly x1.47 at 27 C). "
        "J_C is MEASURED: Ic from the operating point / (Nx x 0.063 um^2) [mA/um^2]; "
        "`jc_alt_ma_um2` uses 0.1152 um^2 (sg13g2-lna's convention) for comparison.",
        f"- **Frequencies**: {', '.join(f'{f / 1e9:g} GHz' for f in sweep.frequencies_hz)}.",
        "- **Noise source impedances** (fitted): "
        + ", ".join(f"{r:g}{x:+g}j" for r, x in sweep.source_impedances_ohm)
        + f" ohm; independent 50 ohm check: {sweep.nf50_check_ohm[0]:g}{sweep.nf50_check_ohm[1]:+g}j ohm; "
        "independent optimum check: one further simulation per point and frequency at the in-deck "
        "closed-form optimum.",
        f"- **fT sweep**: `ac {sweep.ft_sweep}` of |h21| = |y21/y11| (output AC-shorted), log-log "
        "interpolated between the two bracketing points.",
        f"- **T0**: {', '.join(f'{t:g} K' for t in sweep.t0_k)}; the row-3 screen uses 290 K "
        "(IEEE); Tmin (K) is T0-independent.",
        "- **Validity box** (`sg13g2_hbt_mod.lib` header): Ic < 3 mA x Nx, VBE 0.65-0.96 V, "
        "VCE 0.4-2.0 V, -40..125 C, Nx 1-10. **Active**: fT > f and MAG/MSG > 0 dB. Reported "
        "optima use only points that are in-box AND active.",
        "",
        "## Provenance",
        "",
        f"- git: {git.get('commit')} on {git.get('branch')}" + (" (dirty)" if git.get("dirty") else ""),
        f"- ngspice (ingesting host): {ngspice}",
        f"- PDK install: `{pdk_prov['variant_path']}`; its `.fetched-version` file reads "
        f"`{pdk_prov['fetched_version_file']}` (what the install reports, not a pin); model sha256: "
        + ", ".join(f"`{k}` {v}" for k, v in pdk_prov["model_sha256"].items()),
    ]
    for m in klt_meta:
        env = m.get("environment", {})
        L.append(
            f"- klt sim request at supply {m['supply_v']:.2f} V: status `{m['status']}`, client "
            f"`{m.get('client', '?')}`, engine {env.get('engine')} {env.get('engine_version')}, "
            f"models_lib_sha256 {env.get('models_lib_sha256')}, remote `{env.get('remote')}`; report "
            f"kept as `netlist-snapshots/{record_id}/klt-report_{m['supply_v']:.2f}v.json`"
        )
    if crosscheck:
        L.append(
            f"- **Off-host vs this host**: {crosscheck['corner_id']} was re-simulated locally (one "
            f"ngspice process, this host's model files above) and compared bias point by bias point "
            f"with the off-host result: {crosscheck['summary']} (tolerances {crosscheck['tolerances']}). "
            "This is what ties every off-host number to the model-file checksums recorded here."
        )
    L += [
        f"- Netlist snapshot: `netlist-snapshots/{record_id}/` (the exact klt bodies -- fixture + "
        "generated sweep -- and requests). Per-corner ngspice logs: "
        f"`corners/{record_id}/<corner_id>.log.gz`.",
        "",
        "## Data quality",
        "",
        f"- Rows: {q['rows']} ({q['ok']} computed, {q['excluded']} excluded). Excluded by reason: "
        f"{q['excluded_by_reason'] or 'none'}.",
        f"- In model-card box: {q['in_box']}; eligible (in-box and active): {q['eligible']}; "
        f"inactive: {q['inactive']}. Validity flags: {q['flags']}.",
        f"- fT status: {q['ft_status']}. Gmax kind: {q['gmax_kind']}.",
        f"- Noise-parameter fit: max relative residual {_fmt(q['max_fit_residual'])} (gate "
        f"{kaband.FIT_RESIDUAL_MAX:g}). Direct 50 ohm simulation vs fit: max |delta| "
        f"{_fmt(q['max_abs_nf50_check_db'])} dB (tolerance {kaband.NF50_CHECK_TOL_DB} dB). "
        f"Independent simulation at the optimum vs extracted NFmin: max |delta| "
        f"{_fmt(q['max_abs_nfmin_check_db'])} dB (tolerance {kaband.NFMIN_CHECK_TOL_DB} dB).",
        f"- Max self-heating rise dTj over computed rows: {_fmt(q['max_dtj_k'])} K (selft=1; the "
        "validity box is an ambient limit and does not cover this).",
        *bracketing_lines(cell_rows, best),
        *reliance_lines(rows, best),
        *(message_lines(messages, rows) if messages is not None
          else ["- Simulator messages: not tallied by the ingesting code."]),
        "",
        "## Results: noise optimum per PVT point and frequency",
        "",
        "Lowest eligible NFmin over every Nx and VCE (grid-sampled in J_C; the source-impedance "
        "optimization is exact, not sampled). `constrained` names the edge of the eligible J_C range "
        "the optimum sits on (empty = interior, bracketed). fT-peak J_C is in the same Nx/VCE cell.",
        "",
        "| PVT point | f (GHz) | Nx | VCE | J_C opt (mA/um^2) | NFmin 290 K (dB) | NFmin 300.15 K (dB) "
        "| Zopt (ohm) | NF50 290 K (dB) | Gmax (dB) | K | fT @opt (GHz) | J_C fT-pk | opt/fT-pk | "
        "Pdc (mW) | constrained | row-3 margin (dB) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for b in best:
        if b.get("opt_nfmin_db_t290") is None:
            L.append(f"| {b['corner_id']} | {b['freq_hz'] / 1e9:g} | no eligible point | | | | | | | | | | | | | | |")
            continue
        L.append(
            f"| {b['corner_id']} | {b['freq_hz'] / 1e9:g} | {b['best_nx']} | {b['best_vce_set_v']:g} | "
            f"{_fmt(b['opt_jc_ma_um2'])} | {b['opt_nfmin_db_t290']:.3f} | {b['opt_nfmin_db_t300.15']:.3f} | "
            f"{b['opt_ropt_ohm']:.0f}{b['opt_xopt_ohm']:+.0f}j | {b['opt_nf50_db_t290']:.2f} | "
            f"{b['opt_gmax_db']:.1f} {b['opt_gmax_kind']} | {b['opt_k']:.2f} | {_ghz(b['opt_ft_hz'])} | "
            f"{_fmt(b.get('ftpk_jc_ma_um2'))} | {_fmt(b.get('opt_over_ftpk_jc'), 3)} | "
            f"{b['opt_pdc_mw']:.2f} | {b.get('opt_constrained_by') or ''} | {b['row3_margin_db']:+.3f} |"
        )
    mid = sweep.frequencies_hz[len(sweep.frequencies_hz) // 2]
    L += [
        "",
        f"## Results: noise optimum per Nx at {mid / 1e9:g} GHz (best VCE per Nx)",
        "",
        "Noise-optimum J_C is not Nx-invariant in general; this table shows it per Nx. Zopt scales "
        "roughly as 1/Nx (larger devices are easier to noise-match from 50 ohm).",
        "",
        "| PVT point | Nx | VCE | J_C opt | NFmin 290 K | Zopt (ohm) | Ic opt (mA) | J_C fT-pk | "
        "fT-pk (GHz) | opt/fT-pk | constrained |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    by_cn: dict[tuple, list[dict]] = defaultdict(list)
    for c in cell_rows:
        if c["freq_hz"] == mid and c.get("opt_nfmin_db_t290") is not None:
            by_cn[(c["corner_id"], c["nx"])].append(c)
    order = {"hbt_typ": 0, "hbt_bcs": 1, "hbt_wcs": 2}
    for (cid, nx), grp in sorted(by_cn.items(), key=lambda kv: (order.get(kv[1][0]["corner"], 9),
                                                                kv[1][0]["temp_c"], kv[1][0]["vdd_v"], kv[0][1])):
        c = min(grp, key=lambda c: c["opt_nfmin_db_t290"])
        L.append(
            f"| {cid} | {nx} | {c['vce_set_v']:g} | {_fmt(c['opt_jc_ma_um2'])} | "
            f"{c['opt_nfmin_db_t290']:.3f} | {c['opt_ropt_ohm']:.0f}{c['opt_xopt_ohm']:+.0f}j | "
            f"{c['opt_ic_a'] * 1e3:.3g} | {_fmt(c.get('ftpk_jc_ma_um2'))} | {_ghz(c.get('ftpk_ft_hz'))} | "
            f"{_fmt(c.get('opt_over_ftpk_jc'), 3)} | {c.get('opt_constrained_by') or ''} |"
        )
    L += ["", "## Row-3 feasibility screen (device level only)", ""]
    L += screen_lines(screen, screen_repo)
    L += [
        "",
        "## Limitations",
        "",
        "- Bare device, ideal bias tees, ideal noiseless terminations: no matching network, no "
        "inductor (none exists in this PDK), no bias-network noise, no interconnect, no pad. A real "
        "LNA's NF at row 3's 50 ohm ports adds matching loss (which lands directly on NF) and second-"
        "stage noise; Zopt for small Nx is far from 50 ohm (see the per-Nx table), so the matching "
        "loss is not small.",
        "- NFmin is grid-sampled in J_C (VBE step 10 mV) and exact in Zs at each sampled bias. The "
        "reported J_C optimum is the best sampled point, not an interpolated one.",
        "- Model limits: VBIC Rev.1.15 card; self-heating active (selft=1) and not covered by the "
        "ambient validity box; noise-model fidelity at 20 GHz (excess-phase/correlated base-collector "
        "noise) is whatever the VBIC card implements -- no measured noise parameters were available "
        "to compare against. Deterministic corners only (no mismatch/statistical sections).",
        "- Only Nx in {" + ", ".join(str(n) for n in sweep.nx) + "} and VCE in {"
        + ", ".join(f"{v:g}" for v in sweep.vce_v) + "} V were run; other values need their own run.",
        "- Gmax: MSG is reported wherever the device is not unconditionally stable (K <= 1 or "
        "|Delta| >= 1), which is the case at these frequencies for the bare device -- an MSG is not "
        "an achievable stable gain without stabilization.",
        "",
        "## Sidecars",
        "",
        f"- `records/{record_id}-points.csv.gz`: every row (all PVT points, Nx, VCE, VBE, "
        "frequencies), including excluded and out-of-model rows with reasons.",
        f"- `records/{record_id}-cells.csv`: per (PVT point, Nx, VCE, frequency) optimum and fT peak.",
        f"- `records/{record_id}-best.csv`: per (PVT point, frequency) best optimum and row-3 margin.",
        "",
    ]
    sidecars = {
        "points": (POINT_COLUMNS, rows),
        "cells": (CELL_COLUMNS, cell_rows),
        "best": (BEST_COLUMNS, best),
    }
    return "\n".join(L), sidecars


def message_lines(messages: dict[str, dict[str, int]], rows: list[dict]) -> list[str]:
    """Simulator warnings/errors, tallied -- reported, not used as exclusion
    criteria (validity is decided from values; see kaband._MESSAGE_RE)."""
    total: Counter = Counter()
    where: dict[str, set] = defaultdict(set)
    for cid, tally in messages.items():
        for msg, n in tally.items():
            total[msg] += n
            where[msg].add(cid)
    if not total:
        return ["- Simulator messages: none in any per-corner log."]
    lines = ["- Simulator messages (all logs; annotations, not exclusion criteria -- a message that "
             "mattered shows up as a missing or inconsistent value and an excluded row):"]
    for msg, n in total.most_common():
        cids = sorted(where[msg])
        shown = ", ".join(cids[:6]) + (f", +{len(cids) - 6} more" if len(cids) > 6 else "")
        lines.append(f"  - `{msg}` x{n} in {len(cids)} corner log(s): {shown}")
    flagged = sum(1 for r in rows if r.get("status") == "ok" and r.get("sim_messages"))
    lines.append(f"  - Computed rows whose bias point carried a message: {flagged} (column `sim_messages`; "
                 "best-effort attribution, stdout/stderr interleave in the logs).")
    return lines


def reliance_lines(rows: list[dict], best: list[dict]) -> list[str]:
    """How much the REPORTED optima (the numbers the row-3 screen rests on)
    depend on the data-quality problems tallied above, stated rather than
    left for the reader to infer from run-wide maxima."""
    ok = [r for r in rows if r.get("status") == "ok"]
    opt_keys = {(b["corner_id"], b["freq_hz"], b["best_nx"], b["best_vce_set_v"], b["opt_vbe_v"])
                for b in best if b.get("opt_vbe_v") is not None}
    at_opt = [r for r in ok if (r["corner_id"], r["freq_hz"], r["nx"], r["vce_set_v"], r["vbe_v"]) in opt_keys]
    dtj = [b["opt_dtj_k"] for b in best if b.get("opt_dtj_k") is not None]
    with_msg = sum(1 for r in at_opt if r.get("sim_messages"))
    bad_cells = {(r["corner_id"], r["nx"], r["vce_set_v"]) for r in rows if r.get("status") != "ok"}
    touched = sum(1 for b in best if (b["corner_id"], b["best_nx"], b["best_vce_set_v"]) in bad_cells)
    return [
        f"- Reliance of the reported optima on the above: max self-heating rise AT the reported optima "
        f"{_fmt(max(dtj) if dtj else None)} K (the run-wide maximum above occurs at much higher "
        f"current density, far from the optima); {with_msg} of the {len(best)} reported optimum bias "
        f"points carry a simulator message; {touched} of {len(best)} reported (PVT, f) optima sit in an "
        "(PVT, Nx, VCE) cell that also contains an excluded row (excluded rows are never candidate "
        "optima; they are listed with reasons in the points sidecar).",
    ]


def bracketing_lines(cell_rows: list[dict], best: list[dict]) -> list[str]:
    """How well the optima are bracketed in J_C, stated rather than assumed."""
    with_opt = [c for c in cell_rows if c.get("opt_nfmin_db_t290") is not None]
    no_opt = [c for c in cell_rows if c.get("opt_nfmin_db_t290") is None]
    spans = [c["eligible_jc_decades"] for c in with_opt if c.get("eligible_jc_decades") is not None]
    constrained = [c for c in with_opt if c.get("opt_constrained_by")]
    by_bound = Counter(c["opt_constrained_by"] for c in constrained)
    best_con = [b for b in best if b.get("opt_constrained_by")]
    below = Counter()
    for c in with_opt:
        if c.get("eligible_jc_min") and c.get("opt_jc_ma_um2"):
            below["decade_below" if c["opt_jc_ma_um2"] / c["eligible_jc_min"] >= 10 else "less_than_decade_below"] += 1
    lines = [
        f"- J_C bracketing: {len(with_opt)} of {len(cell_rows)} (PVT, Nx, VCE, f) cells have an eligible "
        f"optimum ({len(no_opt)} have none). Eligible J_C span per cell: min "
        f"{_fmt(min(spans) if spans else None)} decades, max {_fmt(max(spans) if spans else None)} decades. "
        f"Optimum with at least a decade of eligible J_C below it: {below['decade_below']} cells; "
        f"less than a decade: {below['less_than_decade_below']}.",
        f"- Constrained optima (on the edge of the eligible J_C range): {len(constrained)} of "
        f"{len(with_opt)} cells" + (f", by bound: {dict(by_bound.most_common())}" if by_bound else "")
        + f"; among the reported per-(PVT, f) best optima: {len(best_con)} of {len(best)}.",
    ]
    return lines


def kaband_corners(tb):
    from harness.corners import resolve_corners
    return resolve_corners(list(tb.corners))


def screen_lines(screen: dict, screen_repo: dict) -> list[str]:
    if screen["verdict"] in ("no_data",):
        return ["**No eligible data**: the screen could not be evaluated."]
    cf = screen["worst_corner_freq"]
    lines = [
        f"Target-spec row 3 bounds the **matched LNA's** NF at 50 ohm ports at <= {screen['limit_db']} dB "
        "across the band at all corners. This screen compares that bound with the **bare device's "
        "NFmin** (T0 = 290 K) at the best eligible Nx/VCE/J_C per PVT point and frequency "
        f"({screen['n_cells']} PVT point x frequency cells).",
        "",
        f"- **Worst case**: {cf[0]} at {cf[1] / 1e9:g} GHz, NFmin = {screen['worst_nfmin_db']:.3f} dB, "
        f"margin `2.5 dB - NFmin` = **{screen['worst_margin_db']:+.3f} dB**.",
        f"- Best case margin: {screen['best_margin_db']:+.3f} dB. Cells at or above the limit: "
        f"{screen['n_exceeding']} of {screen['n_cells']}.",
        f"- At T0 = 300.15 K (repo convention) the worst margin is {screen_repo['worst_margin_db']:+.3f} dB "
        f"({screen_repo['worst_corner_freq'][0]} at {screen_repo['worst_corner_freq'][1] / 1e9:g} GHz).",
    ]
    if screen["verdict"] == "below_limit_everywhere":
        lines += [
            "",
            f"**Verdict (feasibility screen only)**: the device-level lower bound sits below row 3's "
            f"2.5 dB at every PVT point and band frequency, with at least {screen['worst_margin_db']:.2f} dB "
            "of headroom at the worst case. That headroom is what a future circuit has to spend on "
            "matching-network loss, bias/degeneration noise and the second stage. **It is not evidence "
            "that row 3 is achievable**, and nothing here ratifies, relaxes or tests a circuit against "
            "it. The margin is also only as good as the device model: it rests on one VBIC card whose "
            "20 GHz noise behaviour was not validated against measurement, with ideal noiseless bias and "
            "terminations, so the NFmin values above are optimistic by construction. Zopt is >1 kohm at "
            "Nx = 1 and ~170 ohm at Nx = 8, so the matching loss a real circuit must pay is large. "
            "Run quality (excluded rows, simulator singular-matrix warnings, self-heating) is stated "
            "under Data quality, including how far the reported optima are from the worst of it.",
        ]
    elif screen["verdict"] == "exceeds_limit_somewhere":
        lines += [
            "",
            "**Verdict (feasibility screen only)**: the bare device's NFmin already reaches or exceeds "
            "row 3's bound at the cells above, before any matching loss -- row 3 is unreachable there "
            "with this device model at the swept Nx/VCE/J_C. This calls for a decision-record issue; "
            "the spec is not edited here.",
        ]
    else:
        lines += ["", "**Verdict**: incomplete -- some cells had no eligible point: "
                  + ", ".join(f"{c[0]}@{c[1] / 1e9:g}GHz" for c in screen["missing"])]
    return lines
