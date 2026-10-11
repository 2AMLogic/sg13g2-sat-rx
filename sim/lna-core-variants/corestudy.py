"""First-stage core-variant study (issue #79): pure logic.

Issue #74 (``sim/lna-match-tradeoff``) showed that no lossless input network
can close NF <= 2.5 dB with S11 <= -10 dB at 8 of 18 in-rail PVT points of the
frozen ``design/lna_stage1`` cascode. This study changes the CORE instead, one
declared change at a time, and re-runs the SAME network-independent bound on
every variant. Nothing about the method changes:

* the grids, thresholds, tolerances, probe networks, port fixture and NF
  convention are read from the #74 declaration
  (``sim/lna-match-tradeoff/testbench/study.json``, sha256 pinned in
  ``testbench/variants.json``) and executed by ``matchstudy.py``;
* each variant is the frozen ``design/netlist/lna_stage1.spice`` with only the
  declared line edits applied (:func:`apply_changes`). The input network lines
  (``Cshunt``, ``Lin``) can never be edited, so ``matchstudy.dut_text`` still
  parameterizes exactly the #74 lines;
* every variant runs the #74 baseline network (for the wide stability sweep,
  the operating point and the model check) plus the 9 #74 probes (for the
  noise-parameter fit and the bound) at every PVT point.

No simulator or PDK is needed to import or test this module. Nothing here
claims a spec row: every matching element, and the emitter inductor of the
degeneration variants, is an IDEAL element (no PDK inductor model; passive
qualification is #46), and the band (row 1) is OPEN/DRAFT.
"""

from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
SIM_DIR = BENCH_DIR.parent
REPO_ROOT = SIM_DIR.parent
METHOD_DIR = SIM_DIR / "lna-match-tradeoff"
sys.path.insert(0, str(METHOD_DIR))

import matchstudy as ms  # noqa: E402

DECLARATION = BENCH_DIR / "testbench" / "variants.json"
METHOD_STUDY = METHOD_DIR / "testbench" / "study.json"
FROZEN = REPO_ROOT / "design" / "netlist" / "lna_stage1.spice"

#: Lines no variant may touch: the #74 input network (the bound must see the
#: same parameterized input lines) and the subcircuit boundary.
PROTECTED_PREFIXES = ("Cshunt ", "Lin ", "Cblk_in ", ".subckt", ".ends")

#: Variant roles. Only ``candidate`` and ``combination`` can be chosen.
ROLES = ("baseline", "candidate", "combination", "diagnostic")
SELECTABLE = ("candidate", "combination")

DEVICE_LABELS = {"xq1": ("q1", "Q1 (CE)"), "xq2": ("q2", "Q2 (CB)"), "xqr": ("qr", "Qref (mirror)")}

POINT_STATUSES = ("ok", "rejected_invalid")

_PARAM_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")


class CoreStudyError(ValueError):
    """The declaration or a collection is malformed (never evidence)."""


# ---------------------------------------------------------------------------
# Declaration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Variant:
    name: str
    role: str
    changes: tuple[str, ...]
    params: dict = field(default_factory=dict, hash=False, compare=False)
    summary: str = ""

    @property
    def n_changes(self) -> int:
        return len(self.changes)


@dataclass
class Declaration:
    raw: dict
    changes: dict            # change id -> {"title", "class", "edits": [{"line", "with": [...]}], ...}
    variants: tuple[Variant, ...]
    derived: dict            # param name -> value (float), from the derivation block
    selection: dict

    def variant(self, name: str) -> Variant:
        for v in self.variants:
            if v.name == name:
                return v
        raise KeyError(name)

    @property
    def baseline(self) -> Variant:
        return next(v for v in self.variants if v.role == "baseline")


def load_declaration(path: Path | None = None, *, partial: bool = False) -> Declaration:
    return declaration_from_dict(json.loads(Path(path or DECLARATION).read_text()), partial=partial)


def declaration_from_dict(m: dict, *, partial: bool = False) -> Declaration:
    """``partial`` accepts a declaration whose derived values are not filled in
    yet (only ``run.py derive`` uses it)."""
    if not isinstance(m, dict):
        raise CoreStudyError("declaration is not an object")
    changes = m.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise CoreStudyError("declaration has no changes")
    variants = []
    for v in m.get("variants") or []:
        variants.append(Variant(name=str(v["name"]), role=str(v["role"]), changes=tuple(v.get("changes") or ()),
                                params=dict(v.get("params") or {}), summary=str(v.get("summary", ""))))
    derived = {}
    for d in m.get("derivations") or []:
        if "value" in d:
            derived[d["param"]] = float(d["value"])
    dec = Declaration(raw=m, changes=changes, variants=tuple(variants), derived=derived,
                      selection=dict(m.get("selection_rule") or {}))
    problems = validate_declaration(dec, partial=partial)
    if problems:
        raise CoreStudyError("; ".join(problems))
    return dec


def validate_declaration(dec: Declaration, *, partial: bool = False) -> list[str]:
    p: list[str] = []
    names = [v.name for v in dec.variants]
    if len(names) != len(set(names)):
        p.append("duplicate variant names")
    if [v.role for v in dec.variants].count("baseline") != 1:
        p.append("exactly one baseline variant is required")
    for v in dec.variants:
        if not re.match(r"^[a-z0-9_]+$", v.name):
            p.append(f"{v.name}: name must be [a-z0-9_]")
        if v.role not in ROLES:
            p.append(f"{v.name}: role {v.role!r}")
        if v.role == "baseline" and v.changes:
            p.append(f"{v.name}: the baseline variant is the frozen core (no changes)")
        if v.role == "candidate" and len(v.changes) != 1:
            p.append(f"{v.name}: a candidate variant makes exactly one declared change")
        if v.role == "combination" and len(v.changes) < 2:
            p.append(f"{v.name}: a combination combines at least two declared changes")
        for c in v.changes:
            if c not in dec.changes:
                p.append(f"{v.name}: unknown change {c!r}")
        need = set()
        for c in v.changes:
            for e in (dec.changes.get(c) or {}).get("edits", []):
                for ln in e.get("with", []):
                    need |= set(_PARAM_RE.findall(ln))
        if set(v.params) != need:
            p.append(f"{v.name}: params {sorted(v.params)} do not bind the placeholders {sorted(need)}")
        if not partial:
            for ph, dname in v.params.items():
                if dname not in dec.derived:
                    p.append(f"{v.name}: {ph} -> {dname} has no derived value")
    for cid, c in dec.changes.items():
        if not re.match(r"^[A-Za-z0-9_]+$", cid):
            p.append(f"change {cid!r}: id must be [A-Za-z0-9_]")
        for e in c.get("edits", []):
            line = e.get("line", "")
            if any(line.startswith(x) for x in PROTECTED_PREFIXES):
                p.append(f"change {cid}: may not edit the protected line {line!r}")
            if not isinstance(e.get("with"), list) or not e["with"]:
                p.append(f"change {cid}: edit of {line!r} needs a non-empty 'with' list")
            for ln in e.get("with", []):
                if any(ln.startswith(x) for x in PROTECTED_PREFIXES):
                    p.append(f"change {cid}: may not write a protected line {ln!r}")
    rule = dec.selection
    for key in ("gt_min_db", "k_min", "delta_max", "nf_max_db", "s11_max_db"):
        if key not in rule:
            p.append(f"selection_rule.{key} missing")
    return p


# ---------------------------------------------------------------------------
# Variant netlists
# ---------------------------------------------------------------------------


def _fmt_value(x: float) -> str:
    return repr(float(x))


def apply_changes(frozen: str, dec: Declaration, change_ids, params: dict[str, float], *, label: str = "") -> str:
    """The frozen netlist with the declared edits of ``change_ids`` applied.

    Every edited line must appear exactly once, verbatim, in the frozen text
    (or in the text produced by an earlier change of the same variant); two
    changes may not edit the same line. ``params`` binds every ``{name}``
    placeholder to a number, written as a literal (the simulated value is the
    declared value). Every other line is unchanged (a test checks this)."""
    lines = frozen.splitlines()
    touched: set[str] = set()
    for cid in change_ids:
        for e in dec.changes[cid]["edits"]:
            old = e["line"]
            if old in touched:
                raise CoreStudyError(f"change {cid}: line {old!r} already edited by another change")
            idx = [i for i, ln in enumerate(lines) if ln.strip() == old]
            if len(idx) != 1:
                raise CoreStudyError(f"change {cid}: line {old!r} found {len(idx)} times in the netlist "
                                     "(the frozen design moved: re-derive the study)")
            new = []
            for ln in e["with"]:
                def sub(m):
                    if m.group(1) not in params:
                        raise CoreStudyError(f"change {cid}: no value for placeholder {{{m.group(1)}}}")
                    val = params[m.group(1)]
                    # a string is written verbatim (derivation scans keep a
                    # ``{scan_x}`` placeholder for alterparam)
                    return val if isinstance(val, str) else _fmt_value(val)
                new.append(_PARAM_RE.sub(sub, ln))
            lines[idx[0]:idx[0] + 1] = new
            touched.add(old)
            touched.update(new)
    out = "\n".join(lines) + "\n"
    if label:
        out = f"* CORE VARIANT {label} (issue #79): {', '.join(change_ids) or 'frozen core, no change'}\n" + out
    return out


def variant_params(dec: Declaration, v: Variant) -> dict[str, float]:
    return {ph: dec.derived[dname] for ph, dname in v.params.items()}


def variant_netlist(frozen: str, dec: Declaration, v: Variant) -> str:
    return apply_changes(frozen, dec, v.changes, variant_params(dec, v), label=v.name)


def devices_of(netlist: str) -> tuple:
    """``matchstudy.DEVICES``-shaped tuple read from the netlist's own
    ``Xq1``/``Xq2``/``Xqr`` lines (terminal nodes and Nx), so the operating
    point and the row-17 checks follow a variant's topology and size."""
    found = {}
    for ln in netlist.splitlines():
        t = ln.split()
        if not t or t[0].lower() not in DEVICE_LABELS:
            continue
        nx = None
        for tok in t[5:]:
            if tok.lower().startswith("nx="):
                nx = int(tok.split("=", 1)[1])
        if nx is None or len(t) < 6:
            raise CoreStudyError(f"cannot read the device line {ln!r}")
        dev, label = DEVICE_LABELS[t[0].lower()]
        found[t[0].lower()] = (dev, label, nx, t[0].lower(), t[1], t[2], t[3])
    if set(found) != set(DEVICE_LABELS):
        raise CoreStudyError(f"netlist lacks devices {sorted(set(DEVICE_LABELS) - set(found))}")
    return tuple(found[k] for k in ("xq1", "xq2", "xqr"))


# ---------------------------------------------------------------------------
# Derivation scans (one local ngspice run at one PVT point each)
# ---------------------------------------------------------------------------

SCAN_PARAM = "scan_x"


def scan_body(st: ms.Study, netlist: str, kind: str, values: list[float], vdd: float, *, title: str) -> str:
    """One deck that sweeps the ``{scan_x}`` parameter of ``netlist`` over
    ``values`` at one PVT point and prints, per value, either the core's
    input impedance at f0 (``kind = "zin_f0"``: the #74 thru probe, forward
    drive, dense grid) or Q1's collector current (``kind = "ic_q1"``)."""
    thru = st.candidate("probe_thru")
    dense = st.dense_freqs()
    i0 = min(range(len(dense)), key=lambda i: abs(dense[i] - st.f0_hz))
    lo, hi = st.band_hz
    devs = devices_of(netlist.replace("{" + SCAN_PARAM + "}", "1"))
    q1 = next(d for d in devs if d[0] == "q1")
    lines = [f"* lna-core-variants derivation scan: {title} -- GENERATED by corestudy.py, do not edit",
             f".param vdd_val={vdd!r}", ".param mag1=1 mag2=0", f".param {SCAN_PARAM}={_fmt_value(values[0])}"]
    lines += [f".param {k}={_fmt_value(x)}" for k, x in thru.params().items()]
    lines += ["", ms.dut_text(netlist).rstrip("\n"), "", ms.PORTS.rstrip("\n"), "", ".control", "set noaskquit",
              "set numdgt = 10"]
    for i, x in enumerate(values):
        lines += [f"alterparam {SCAN_PARAM} = {_fmt_value(x)}", "alterparam mag1 = 1", "alterparam mag2 = 0", "reset"]
        if kind == "zin_f0":
            lines += [f"ac lin {st.grid.dense_n} {_fmt_value(lo)} {_fmt_value(hi)}",
                      f"let sre = real(v(p1)[{i0}])", f"let sim = imag(v(p1)[{i0}])",
                      f"let sf = real(frequency[{i0}])",
                      f"echo LMSCAN {i} {_fmt_value(x)} $&sf $&sre $&sim", "destroy all"]
        elif kind == "ic_q1":
            lines += ["op", f"let sic = @q.xdut.{q1[3]}.qnpn13g2[ic]", f"echo LMSCAN {i} {_fmt_value(x)} $&sic",
                      "destroy all"]
        else:
            raise CoreStudyError(f"unknown scan kind {kind!r}")
    lines += ["echo LM_DONE", ".endc", ""]
    return "\n".join(lines)


def parse_scan(text: str, n: int) -> list[list[float]]:
    rows = {}
    done = False
    for ln in text.splitlines():
        s = ln.strip()
        if s == "LM_DONE":
            done = True
        if s.startswith("LMSCAN "):
            t = s.split()
            rows[int(t[1])] = [float(x) for x in t[2:]]
    if not done or sorted(rows) != list(range(n)):
        raise CoreStudyError(f"scan log incomplete: {len(rows)}/{n} rows, done={done}")
    return [rows[i] for i in range(n)]


def scan_metric(kind: str, row: list[float], z0: float = 50.0) -> float:
    """``zin_f0``: Re(Z_in) of the core at f0 from S11 = 2 V(p1) - 1;
    ``ic_q1``: Q1 collector current (A)."""
    if kind == "zin_f0":
        s11 = 2 * complex(row[2], row[3]) - 1
        return ms.z_from_gamma(s11, z0).real
    return row[1]


def solve_crossing(xs: list[float], ys: list[float], target: float) -> float:
    """The unique ``x`` where the scanned ``y`` crosses ``target`` (linear
    interpolation between the bracketing scan values). No crossing, or more
    than one, is an error: the declared rule then has no unique answer."""
    hits = []
    for i in range(len(xs) - 1):
        a, b = ys[i] - target, ys[i + 1] - target
        if a == 0:
            hits.append(xs[i])
        elif a * b < 0:
            hits.append(xs[i] + (xs[i + 1] - xs[i]) * (target - ys[i]) / (ys[i + 1] - ys[i]))
    if ys and ys[-1] == target:
        hits.append(xs[-1])
    hits = sorted(set(hits))
    if len(hits) != 1:
        raise CoreStudyError(f"target {target:g} crossed {len(hits)} times over the scan "
                             f"[{ys[0]:.4g} .. {ys[-1]:.4g}]")
    return hits[0]


# ---------------------------------------------------------------------------
# Per-point analysis
# ---------------------------------------------------------------------------


def point_id(variant: str, process: str, temp_c: float, vdd: float) -> str:
    return f"{variant}__{ms.corner_id(process, temp_c, vdd)}"


def networks(st: ms.Study) -> list[ms.Candidate]:
    """What every variant deck simulates: the #74 baseline network (wide
    stability sweep, op, model check) and the #74 probes (fit + bound)."""
    return [st.baseline] + [c for c in st.candidates if c.role == "probe"]


def analyze_point(st: ms.Study, v: Variant, devices: tuple, process: str, temp_c: float, vdd: float,
                  tables: dict, op: dict) -> dict:
    """One variant at one PVT point: the network-independent bound (fit from
    the probes, model check on the drawn network), the per-frequency
    transducer gain at the NF-bound source reflection, stability (k is
    invariant to the lossless input network, so the drawn network's in-band
    and 1-100 GHz sweep stands for every network) and the row-17 operating
    point. Scientific failures become ``rejected_invalid`` with a reason."""
    cid = ms.corner_id(process, temp_c, vdd)
    cell = ms.make_cell(st, "corners", st.baseline, process, temp_c, vdd, tables.get(st.baseline.name, {}), op, devices)
    bound = ms.point_bound(st, tables, networks(st))
    pt = {"id": point_id(v.name, process, temp_c, vdd), "variant": v.name, "role": v.role, "process": process,
          "model_section": process, "temp_c": temp_c, "vdd_v": vdd, "corner_id": cid,
          "supply_class": "excursion" if vdd > st.rail_ceiling_v + 1e-9 else "in_rail", "op": cell["op"]}
    problems = []
    if cell["status"] != "ok":
        problems.append(f"drawn network: {cell.get('reason')}")
    if not bound.get("valid"):
        problems += [f"bound: {x}" for x in bound.get("problems", [])]
    if problems:
        pt.update(status="rejected_invalid", reason="; ".join(problems))
        return pt
    sm = cell["summary"]
    rows = bound["rows"]
    f = [r["f_hz"] for r in rows]
    i_top = len(rows) - 1
    i0 = min(range(len(f)), key=lambda i: abs(f[i] - st.f0_hz))
    nf_max = float(st.screen["nf_max_db"])
    pt.update(status="ok", bound={
        "f_hz": f,
        "nf_bound_db": [r["nf_bound_db"] for r in rows],
        "fmin_db": [r["fmin_db"] for r in rows],
        "rn_ohm": [r["rn_ohm"] for r in rows],
        "zopt_ohm": [r["zopt"] for r in rows],
        "zin_core_ohm": [r["zin_core"] for r in rows],
        "gt_at_nf_bound_db": [r["gt_at_nf_bound_db"] for r in rows],
        "s11_bound_db": [r["s11_bound_db"] for r in rows],
        "fit_rms_db": [r["fit_rms_db"] for r in rows],
    }, summary={
        "nf_bound_max_db": bound["summary"]["nf_bound_max_db"],
        "f_at_nf_bound_max_hz": bound["summary"]["f_at_nf_bound_max_hz"],
        "nf_bound_top_db": rows[i_top]["nf_bound_db"],
        "margin_top_db": nf_max - rows[i_top]["nf_bound_db"],
        "margin_db": nf_max - bound["summary"]["nf_bound_max_db"],
        "fmin_min_db": bound["summary"]["fmin_min_db"], "fmin_max_db": bound["summary"]["fmin_max_db"],
        "fmin_top_db": rows[i_top]["fmin_db"],
        "n_freq_jointly_infeasible": bound["summary"]["n_freq_jointly_infeasible"],
        "n_freq": bound["summary"]["n_freq"],
        "gt_at_nf_bound_min_db": min(r["gt_at_nf_bound_db"] for r in rows),
        "zin_core_f0_ohm": rows[i0]["zin_core"], "zopt_f0_ohm": rows[i0]["zopt"],
        "model_check_worst_db": bound["summary"]["model_check_worst_db"],
        "fit_rms_max_db": bound["summary"]["fit_rms_max_db"],
        "drawn_s21_min_db": sm["s21_min_db"], "drawn_nf_max_db": sm["nf_max_db"],
        "drawn_s11_max_db": sm["s11_max_db"],
        "k_min": min(sm["k_min"], sm["wide_k_min"]), "delta_max": max(sm["delta_max"], sm["wide_delta_max"]),
        "wide_f_kmin_hz": sm["wide_f_kmin_hz"],
        "vce_max_v": max(d["vce"] for d in cell["op"]["devices"].values()),
        "q1_ic_ma": op.get("q1_ic", float("nan")) * 1e3,
    })
    return pt


# ---------------------------------------------------------------------------
# Variant summaries, selection, gate
# ---------------------------------------------------------------------------


def expected_points(st: ms.Study, dec: Declaration) -> list[str]:
    return [point_id(v.name, p, t, vv) for v in dec.variants for p, t, vv in st.pvt_points()]


#: The row-3 binding corner named by #74 (process, temperature); every
#: variant reports its Fmin and bound there explicitly.
BINDING = ("hbt_wcs", 125.0)


def summarize_variant(st: ms.Study, dec: Declaration, v: Variant, points: list[dict]) -> dict:
    """The numbers the issue asks for, per variant, over the 18 in-rail
    points; excursion (2.75 V) points are reported apart and never enter
    the verdict."""
    rule = dec.selection
    mine = [p for p in points if p["variant"] == v.name]
    inr = [p for p in mine if p["supply_class"] == "in_rail"]
    exc = [p for p in mine if p["supply_class"] == "excursion"]
    invalid = sorted(p["corner_id"] for p in mine if p["status"] != "ok")
    ok = [p for p in inr if p["status"] == "ok"]
    out: dict = {"name": v.name, "role": v.role, "changes": list(v.changes), "n_changes": v.n_changes,
                 "params": variant_params(dec, v) if all(d in dec.derived for d in v.params.values()) else {},
                 "in_rail_points": len(inr), "invalid": invalid}
    if not ok:
        out["verdict"] = "no valid in-rail point"
        out["eligible"] = False
        return out
    infeasible = sorted(p["corner_id"] for p in ok if p["summary"]["n_freq_jointly_infeasible"] > 0)
    worst = max(ok, key=lambda p: p["summary"]["nf_bound_max_db"])
    bproc, btemp = BINDING
    binding = {f"{p['vdd_v']:.2f}v": [p["summary"]["fmin_min_db"], p["summary"]["fmin_max_db"]]
               for p in ok if p["process"] == bproc and p["temp_c"] == btemp}
    binding_bound = {f"{p['vdd_v']:.2f}v": p["summary"]["nf_bound_max_db"]
                     for p in ok if p["process"] == bproc and p["temp_c"] == btemp}
    n = st.nominal
    nom = next((p for p in ok if p["process"] == n["process"] and p["temp_c"] == float(n["temp_c"])
                and p["vdd_v"] == float(n["vdd"])), None)
    op_fail = sorted(p["corner_id"] for p in inr if not p["op"].get("pass", False))
    gt_min = min(p["summary"]["gt_at_nf_bound_min_db"] for p in ok)
    k_min = min(p["summary"]["k_min"] for p in ok)
    d_max = max(p["summary"]["delta_max"] for p in ok)
    out.update({
        "n_infeasible": len(infeasible), "infeasible_points": infeasible,
        "worst_nf_bound_db": worst["summary"]["nf_bound_max_db"], "worst_point": worst["corner_id"],
        "worst_margin_db": float(rule["nf_max_db"]) - worst["summary"]["nf_bound_max_db"],
        "binding_fmin_db": binding, "binding_nf_bound_db": binding_bound,
        "nominal_margin_top_db": nom["summary"]["margin_top_db"] if nom else None,
        "nominal_nf_bound_top_db": nom["summary"]["nf_bound_top_db"] if nom else None,
        "nominal_zin_f0_ohm": nom["summary"]["zin_core_f0_ohm"] if nom else None,
        "nominal_q1_ic_ma": nom["summary"]["q1_ic_ma"] if nom else None,
        "gt_at_nf_bound_min_db": gt_min,
        "drawn_s21_min_db": min(p["summary"]["drawn_s21_min_db"] for p in ok),
        "k_min": k_min, "delta_max": d_max,
        "vce_max_v": max(p["summary"]["vce_max_v"] for p in ok),
        "op_fail_in_rail": op_fail,
        "op_fail_excursion": sorted(p["corner_id"] for p in exc if not p["op"].get("pass", False)),
        "model_check_worst_db": max(p["summary"]["model_check_worst_db"] for p in ok),
    })
    reasons = []
    if v.role not in SELECTABLE:
        reasons.append(f"role {v.role} is never selectable")
    if invalid:
        reasons.append(f"invalid points {invalid}")
    if len(ok) != len(inr):
        reasons.append("not every in-rail point is valid")
    if op_fail:
        reasons.append(f"row 17 / card-box operating point fails at {op_fail}")
    if gt_min < float(rule["gt_min_db"]):
        reasons.append(f"GT at the NF-bound source {gt_min:.2f} dB < {rule['gt_min_db']} dB")
    if k_min <= float(rule["k_min"]):
        reasons.append(f"k min {k_min:.3f} <= {rule['k_min']}")
    if d_max >= float(rule["delta_max"]):
        reasons.append(f"|Delta| max {d_max:.3f} >= {rule['delta_max']}")
    if infeasible:
        reasons.append(f"bound jointly infeasible at {len(infeasible)}/{len(inr)} in-rail points")
    out["eligible"] = not reasons
    out["ineligible_reasons"] = reasons
    out["verdict"] = ("closes the per-frequency bound at every in-rail point" if not infeasible
                      else f"bound jointly infeasible at {len(infeasible)}/{len(inr)} in-rail points")
    return out


def select(dec: Declaration, summaries: dict) -> dict:
    """The declared selection rule: among eligible variants, the fewest
    declared changes first, then the largest worst-case in-rail margin, then
    the name. No eligible variant -> no choice (the decision-record path)."""
    elig = [s for s in summaries.values() if s.get("eligible")]
    if not elig:
        return {"chosen": None, "ranking": [],
                "outcome": "no declared core change closes the network-independent bound at every in-rail point"}
    ranked = sorted(elig, key=lambda s: (s["n_changes"], -s["worst_margin_db"], s["name"]))
    ch = ranked[0]
    return {"chosen": ch["name"], "ranking": [s["name"] for s in ranked],
            "outcome": (f"chosen core change: {ch['name']} ({' + '.join(ch['changes'])}); worst in-rail NF bound "
                        f"{ch['worst_nf_bound_db']:.3f} dB at {ch['worst_point']}")}


def reproduction(points: list[dict], baseline_bounds: dict, baseline_variant: str, tol_db: float) -> dict:
    """The frozen core here vs the #74 record's per-point bound summary:
    NF-bound max, Fmin range and the jointly-infeasible count must agree."""
    worst = 0.0
    problems = []
    n = 0
    for p in points:
        if p["variant"] != baseline_variant or p["status"] != "ok":
            continue
        ref = (baseline_bounds.get(f"corners__{p['corner_id']}") or {}).get("summary")
        if not ref:
            problems.append(f"{p['corner_id']}: no #74 bound to compare")
            continue
        n += 1
        for k in ("nf_bound_max_db", "fmin_min_db", "fmin_max_db"):
            worst = max(worst, abs(p["summary"][k] - ref[k]))
        if p["summary"]["n_freq_jointly_infeasible"] != ref["n_freq_jointly_infeasible"]:
            problems.append(f"{p['corner_id']}: jointly infeasible {p['summary']['n_freq_jointly_infeasible']} "
                            f"!= #74 {ref['n_freq_jointly_infeasible']}")
    if worst > tol_db:
        problems.append(f"bound differs from #74 by {worst:.3g} dB > {tol_db:g} dB")
    return {"compared_points": n, "worst_db": worst, "tol_db": tol_db, "problems": problems,
            "ok": not problems and n > 0}


def validate_collection(st: ms.Study, dec: Declaration, points: list[dict]) -> list[str]:
    """Acceptance gate: every declared (variant, PVT) point exactly once and
    nothing undeclared, scientific statuses, finite ok summaries, model
    section = process, and process must move the frozen core's bound."""
    p: list[str] = []
    ids = [x.get("id") for x in points]
    want = expected_points(st, dec)
    seen = set()
    for i in ids:
        if i in seen:
            p.append(f"duplicate point {i}")
        seen.add(i)
    p += [f"missing declared point {i}" for i in sorted(set(want) - seen)]
    p += [f"undeclared point {i}" for i in sorted(seen - set(want))]
    for x in points:
        if x.get("status") not in POINT_STATUSES:
            p.append(f"{x.get('id')}: status {x.get('status')!r}")
            continue
        if x.get("model_section") != x.get("process"):
            p.append(f"{x.get('id')}: model section != process")
        if x["status"] == "ok":
            vals = [v for v in x["summary"].values() if not isinstance(v, list)]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals):
                p.append(f"{x['id']}: ok point with a non-finite summary")
        elif not x.get("reason"):
            p.append(f"{x['id']}: rejected point without a reason")
    # sabotage control (as #74): process must move the frozen core's S21
    by: dict = {}
    for x in points:
        if x.get("variant") == dec.baseline.name and x.get("status") == "ok":
            by.setdefault((x["temp_c"], x["vdd_v"]), set()).add(round(x["summary"]["drawn_s21_min_db"], 9))
    if by and not any(len(s) > 1 for s in by.values()):
        p.append("process corners do not move the frozen core's S21 (corner sections not applied?)")
    return p
