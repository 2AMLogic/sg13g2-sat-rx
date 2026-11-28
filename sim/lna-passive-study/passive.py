"""Pure logic for the lna-passive-study bench (issue #340).

No simulator, no klt, no network: everything here is deterministic text and
arithmetic over committed inputs, so ``run.py verify`` and the tests re-derive
every published verdict without a fleet.

What this study is: a NON-CLAIMING comparison of at most four substituted-
primitive candidate sets of ``design/lna_stage1`` against a same-method
control (the committed ideal-passive DUT under this study's own deck) at the
bound corners of ratified rows 2, 3, 4 and 6. The method is the lna-sparam-nf
bench's, reused verbatim and pinned by hash: the fixture structure from its
``testbench/lna_stage1.spice`` and the whole ``.control`` block (analyses +
measurement expressions) from its ``testbench/tb.json``. The element sizings
come from ``layout/lna_stage1/passive_sizing.json`` (PDK models, not
``R = rsh*L/W``). Inductors stay IDEAL in every variant and every record.

Nothing here selects a primitive, claims a spec row, or edits a schematic:
that is DR-0011's proposal and the operator's ratification call.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
SIM_DIR = BENCH_DIR.parent
REPO_ROOT = SIM_DIR.parent

# the sizing table's inversion helpers (layout/lna_stage1 sibling)
import sys as _sys  # noqa: E402

_sys.path.insert(0, str(REPO_ROOT / "layout" / "lna_stage1"))

#: The committed DUT netlist (the same authority realizability.py parses).
DUT_PATH = REPO_ROOT / "design" / "netlist" / "lna_stage1.spice"

#: The reused method, pinned by hash in the plan.
METHOD_TB = SIM_DIR / "lna-sparam-nf" / "testbench" / "tb.json"
METHOD_FIXTURE = SIM_DIR / "lna-sparam-nf" / "testbench" / "lna_stage1.spice"
#: The post-#79 characterization record this study's deltas are read against.
BASELINE_RECORD = "sim/lna-sparam-nf/records/20261114-211735-8a92c6e.md"
BASELINE_RECORD_ID = "20261114-211735-8a92c6e"

#: PDK-model sizing table (issue #340 part 1) and the plan that freezes the
#: study's declaration.
SIZING_PATH = REPO_ROOT / "layout" / "lna_stage1" / "passive_sizing.json"
PLAN_PATH = BENCH_DIR / "testbench" / "plan.json"
PREMATCH_PATH = BENCH_DIR / "testbench" / "prematch.json"
VARIANTS_DIR = BENCH_DIR / "testbench" / "variants"

#: The process axis: each named corner is a bundle of one .lib section per
#: model family (klt sim per-section corner libraries, klayout-tools #2522).
#: Rows 2/3 name hbt_wcs; row 4 names cap_* x res_* extremes; row 6 names the
#: worst process x temp x supply, whose post-#79 worst k cell was
#: hbt_typ/-40 C/2.75 V. Section names are the PDK's own.
MODEL_LIBS = {
    "hbt": "libs.tech/ngspice/models/cornerHBT.lib",
    "res": "libs.tech/ngspice/models/cornerRES.lib",
    "cap": "libs.tech/ngspice/models/cornerCAP.lib",
}
PROCESS_CORNERS = [
    {"name": "typ", "sections": {"hbt": "hbt_typ", "res": "res_typ", "cap": "cap_typ"}},
    {"name": "hbt_wcs", "sections": {"hbt": "hbt_wcs", "res": "res_typ", "cap": "cap_typ"}},
    {"name": "hbt_bcs", "sections": {"hbt": "hbt_bcs", "res": "res_typ", "cap": "cap_typ"}},
    {"name": "res_bcs__cap_bcs",
     "sections": {"hbt": "hbt_typ", "res": "res_bcs", "cap": "cap_bcs"}},
    {"name": "res_wcs__cap_wcs",
     "sections": {"hbt": "hbt_typ", "res": "res_wcs", "cap": "cap_wcs"}},
    {"name": "res_bcs__cap_wcs",
     "sections": {"hbt": "hbt_typ", "res": "res_bcs", "cap": "cap_wcs"}},
    {"name": "res_wcs__cap_bcs",
     "sections": {"hbt": "hbt_typ", "res": "res_wcs", "cap": "cap_bcs"}},
]
TEMPERATURES_C = (-40.0, 27.0, 125.0)
SUPPLIES_V = (2.25, 2.5, 2.75)

#: DRAFT band points (row 1 is OPEN; same three points the reused method uses).
BAND_HZ = (17.7e9, 19.45e9, 21.2e9)
BAND_CENTRE_HZ = 19.45e9

#: Row-4's ratified S11 target, used ONLY as the prematch grid's selection
#: rule (a bounded design iteration, not a compliance claim).
S11_TARGET_DB = -10.0

#: The prematch grid for candidate V04 (option b for Cblk_in): on-chip cmim
#: blocking values, smallest first. Sides are derived at build time from the
#: sizing table's own inversion (the plan stores the farads; the derived side
#: is checked against passive_sizing.json).
PREMATCH_GRID_F = (0.5e-12, 1e-12, 2e-12, 5e-12, 10e-12)
PREMATCH_CORNERS = tuple(c["name"] for c in PROCESS_CORNERS if c["name"].startswith("res_"))
PREMATCH_TEMPS_C = (-40.0, 125.0)

#: Study statuses (the record's Markdown must state the JSON's status).
STATUSES = ("COLLECTED", "CONTROLS_FAILED", "PREMATCH_FAILED")


def sha256_text(text: str) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_plan() -> dict:
    return load_json(PLAN_PATH)


def load_sizing() -> dict:
    return load_json(SIZING_PATH)


# ---------------------------------------------------------------------------
# variant DUT decks
# ---------------------------------------------------------------------------

_DUT_SUBCKT_RE = re.compile(r"^\.subckt\s+lna_stage1\s", re.M)
_ELEMENT_RE = re.compile(
    r"^(?P<refdes>[A-Z][A-Za-z0-9_]*)\s+(?P<a>\S+)\s+(?P<b>\S+)\s+(?P<val>\S+)(?P<rest>.*)$")


def _fmt(value: float) -> str:
    return f"{value:g}"


def resistor_line(refdes: str, nodes: tuple[str, str], spec: dict) -> str:
    w, l = spec["w_um"], spec["l_um"]
    m = spec.get("m", 1)
    return (f"X{refdes[1:]} {nodes[0]} {nodes[1]} gnd {spec['flavour']} "
            f"w={_fmt(w)}u l={_fmt(l)}u m={m}")


def capacitor_line(refdes: str, nodes: tuple[str, str], spec: dict) -> str:
    side, m = spec["side_um"], spec.get("m", 1)
    if spec["primitive"] == "cap_rfcmim":
        return (f"X{refdes[1:]} {nodes[0]} {nodes[1]} gnd cap_rfcmim "
                f"w={_fmt(side)}u l={_fmt(side)}u m={m}")
    return (f"X{refdes[1:]} {nodes[0]} {nodes[1]} cap_cmim "
            f"w={_fmt(side)}u l={_fmt(side)}u m={m}")


def variant_dut_text(dut_text: str, assignment: dict, header_note: str) -> str:
    """The DUT subckt with every assigned element replaced by its PDK-model
    instance. Unassigned elements pass through verbatim; the ideal inductors
    (Lin, Lfeed, Le1) are never assigned (#110 / DR-0005 keep them ideal)
    except an explicit ``ideal_value`` re-match (V04). Kind ``drop`` removes
    the element entirely (the prematch probe's bare-core port)."""
    if not _DUT_SUBCKT_RE.search(dut_text):
        raise ValueError("committed DUT has no .subckt lna_stage1")
    out = [line for line in header_note.splitlines()] if header_note else []
    for line in dut_text.splitlines():
        m = _ELEMENT_RE.match(line)
        if not m or m.group("refdes") not in assignment:
            out.append(line)
            continue
        refdes = m.group("refdes")
        nodes = (m.group("a"), m.group("b"))
        spec = assignment[refdes]
        if spec.get("kind") == "drop":
            continue
        if spec.get("kind") == "offchip_ideal":
            out.append(f"* {refdes} {nodes[0]} {nodes[1]} {m.group('val')}: realized OFF-CHIP")
            out.append(f"* (boundary port) -- the element KEEPS its designed value as an IDEAL")
            out.append(f"* ngspice C (zero on-chip area, no PDK primitive); the pad/bond/PCB")
            out.append(f"* path and the off-chip part's own parasitics are NOT modelled")
            out.append(f"* (stated omission)")
            out.append(line)
        elif spec["kind"] == "resistor":
            out.append(f"* {refdes} -> {spec['flavour']} "
                       f"(R_typ {spec['r_typ_ohm']:.6g} ohm vs design {m.group('val')})")
            out.append(resistor_line(refdes, nodes, spec))
        elif spec["kind"] == "capacitor":
            note = f"* {refdes} -> {spec['primitive']} x{spec.get('m', 1)} " \
                   f"(C_typ {spec['c_typ_f']:.6g} F vs design {m.group('val')})"
            out.append(note)
            out.append(capacitor_line(refdes, nodes, spec))
        elif spec["kind"] == "ideal_value":
            out.append(f"* {refdes} re-matched for the on-chip Cblk_in "
                       f"({m.group('val')} -> {spec['value_text']}, "
                       f"DR-0011 option b bounded iteration)")
            out.append(f"{refdes} {nodes[0]} {nodes[1]} {spec['value_text']} m=1")
        else:
            raise ValueError(f"{refdes}: unknown assignment kind {spec.get('kind')!r}")
    return "\n".join(out) + "\n"


def control_dut_text(dut_text: str) -> str:
    """The control DUT: the committed ideal-passive netlist verbatim, with a
    header saying so. It selects nothing; it exists so every variant delta is
    a same-method, same-deck comparison and so the passive corner sections are
    proven inert for the ideal netlist (a negative control)."""
    if not _DUT_SUBCKT_RE.search(dut_text):
        raise ValueError("committed DUT has no .subckt lna_stage1")
    header = [
        "* CONTROL DUT of sim/lna-passive-study (issue #340): the committed",
        "* design/netlist/lna_stage1.spice verbatim (IDEAL generic R/C passives).",
        "* Not a candidate set: it selects nothing. Its cells give the deltas'",
        "* baseline under this study's own deck, prove the res_*/cap_* sections",
        "* are inert for a netlist that instances no such device, and tie the",
        f"* method to the post-#79 record {BASELINE_RECORD_ID} via the op-table gate.",
    ]
    return "\n".join(header) + "\n" + dut_text


# ---------------------------------------------------------------------------
# the reused method: fixture + control block
# ---------------------------------------------------------------------------

_FIXTURE_BEGIN = ".param z0=50"


def fixture_text() -> str:
    """The two-port fixture (ports, Thevenin sources, load) reused verbatim
    from the lna-sparam-nf testbench netlist: everything after the embedded
    DUT block. The method is thereby literally the committed one."""
    text = METHOD_FIXTURE.read_text(encoding="utf-8")
    idx = text.find(_FIXTURE_BEGIN)
    if idx < 0:
        raise ValueError(f"cannot find the fixture section in {METHOD_FIXTURE}")
    return text[idx:]


def control_block(tb: dict) -> list[str]:
    """The bench's own .control block, generated exactly the way the
    lna-sparam-nf klt body does: the tb's analyses verbatim, then one
    ``let m_<name> = <expr>`` and one ``print m_<name>`` per measurement."""
    lines = ["set numdgt=10", "set noaskquit"]
    lines += [f"  {a}" for a in tb["analyses"]]
    lines += [f"  let m_{n} = {e}" for n, e in tb["measure"].items()]
    lines += [f"  print m_{n}" for n in tb["measure"]]
    return lines


def body_text(name: str, dut_subckt: str, tb: dict, supply_v: float,
              note: str) -> str:
    """One self-contained klt body: PVT params, the DUT subckt, the reused
    fixture and the reused .control block. klt appends the corner's .lib
    cards, .temp and its own sentinel analysis."""
    lines = [
        f"* {name}: klt sim body, supply {supply_v:.2f} V -- GENERATED by "
        f"sim/lna-passive-study/run.py, do not edit",
        note,
        f".param vdd_nom={tb['nominal_supply_v']!r}",
        f".param vdd_val={supply_v!r}",
    ]
    lines += [f".param {k}={v}" for k, v in tb["params"].items()]
    lines += ["", dut_subckt.rstrip(), "", fixture_text().rstrip(), "",
              ".control"] + control_block(tb) + [".endc", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# klt request
# ---------------------------------------------------------------------------

def klt_request(body_name: str, processes: list[str], temps: list[float],
                timeout_s: int, osdi_path: str) -> dict:
    """One klt sim request. The per-section corner bundles carry the whole
    model story (HBT + RES + CAP .lib sections); the r3_cmc OSDI model the
    substituted resistors need is staged (not runner-resolved) so the report
    hashes the exact bytes. The trailing tran sentinel is klt's own grading
    analysis; the body's .control block runs the real bench."""
    axis = []
    for name in processes:
        spec = next(c for c in PROCESS_CORNERS if c["name"] == name)
        axis.append({
            "name": name,
            "sections": [
                {"lib": MODEL_LIBS[family], "section": section}
                for family, section in sorted(spec["sections"].items())
            ],
        })
    return {
        "netlist": body_name,
        "backend": "batch",
        "models": {"pdk": "ihp-sg13g2"},
        "corners": {"process": axis, "temperature_c": list(temps)},
        "analysis": {"kind": "tran", "args": "1p 2p"},
        "measurements": [
            {"name": "lna_rail_v",
             "spice": ".meas tran lna_rail_v FIND v(vdd) AT=2p", "unit": "V"},
        ],
        "options": {
            "timeout_s": timeout_s,
            "keep_artifacts": True,
            "stage_model_inputs": True,
            "osdi_preload": [osdi_path],
        },
    }


def cell_key(variant: str, process: str, temp_c: float, vdd: float) -> str:
    return f"{variant}__{process}__{temp_c:g}C__{vdd:.2f}V"


def hbt_of(process: str) -> str:
    spec = next(c for c in PROCESS_CORNERS if c["name"] == process)
    return spec["sections"]["hbt"]


def control_cell_key(process: str, temp_c: float, vdd: float) -> str:
    """The control cell a variant cell compares with: same hbt section, same
    temperature, same supply. The control's typ process covers the passive
    extremes because the ideal netlist instances no passive device; note the
    typ bundle is *named* ``typ`` while its hbt section is ``hbt_typ``."""
    hbt_section = hbt_of(process)
    control_process = "typ" if hbt_section == "hbt_typ" else hbt_section
    return cell_key("V00", control_process, temp_c, vdd)


# ---------------------------------------------------------------------------
# log parsing / measurements
# ---------------------------------------------------------------------------

_MEAS_RE = re.compile(r"^\s*m_(\w+)\s*=\s*([-+]?[0-9.]+(?:[eE][-+]?[0-9]+)?)\s*$")


def parse_log(text: str) -> dict[str, float]:
    """The lna_nf log grammar: every ``m_<name> = <value>`` line the body's
    ``print`` emitted."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        m = _MEAS_RE.match(line)
        if m:
            out[m.group(1)] = float(m.group(2))
    return out


#: The measures the delta table reports (the reused method's names).
DELTA_MEASURES = ("s21_db_lo", "s21_db_mid", "s21_db_hi",
                  "nf_db_lo", "nf_db_mid", "nf_db_hi",
                  "s11_db_lo", "s11_db_mid", "s11_db_hi",
                  "k_lo", "k_mid", "k_hi", "sw_kmin", "sw_nunst")


def deltas(variant_cells: dict[str, dict[str, float]],
           control_cells: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """Per variant cell, ``measure -> variant - control`` at the matching
    control cell. Raises on a missing control value: a delta without its
    baseline is not a delta."""
    out: dict[str, dict[str, float]] = {}
    for key, meas in sorted(variant_cells.items()):
        parts = key.split("__")
        _v, temp, vdd = parts[0], parts[-2], parts[-1]
        process = "__".join(parts[1:-2])
        ctrl = control_cells.get(control_cell_key(process, float(temp[:-1]),
                                                  float(vdd[:-1])))
        if ctrl is None:
            raise ValueError(f"no control cell for {key}")
        row = {}
        for name in DELTA_MEASURES:
            if name not in meas or name not in ctrl:
                raise ValueError(f"{key}: missing {name} in variant or control")
            row[name] = meas[name] - ctrl[name]
            if not math.isfinite(row[name]):
                raise ValueError(f"{key}: non-finite delta for {name}")
        out[key] = row
    return out


# ---------------------------------------------------------------------------
# the Cblk_in re-match (option b), from the design's own L-section method
# ---------------------------------------------------------------------------

def l_section_match(r_b: float, x_b: float, cblk_f: float, f0: float) -> tuple[float, float]:
    """(Lin_h, Cshunt_f) tuning the FIXED committed input topology (shunt C at
    the port, series L, series blocking C) for Z_b + Cblk at f0, by the method
    design/lna_stage1.md used: the series element cancels the load reactance
    and supplies the L-section's series arm when the base resistance is below
    50 ohm; the shunt capacitor completes the section.

    A base resistance AT OR ABOVE 50 ohm (the post-Le1 core measures ~334 ohm,
    see the prematch record) cannot be matched by this topology at all
    (max Re(Y_port) = 1/R_b < 1/50), so the tuning degrades gracefully to
    reactance cancellation only -- Lin absorbs the blocking capacitor's
    reactance, Cshunt keeps its committed value -- and the achievable S11 is
    whatever the grid then measures. The selection rule still applies."""
    if r_b <= 0:
        raise ValueError(f"R_b={r_b:g} ohm is not a passive load")
    w = 2.0 * math.pi * f0
    x_c = 1.0 / (w * cblk_f)
    if r_b >= 50.0:
        lin_h = (x_c - x_b) / w
        if lin_h < 0:
            raise ValueError(
                f"reactance-cancellation needs a negative Lin ({lin_h*1e9:.3f} nH): the "
                f"blocking cap's reactance under-cancels Z_b's at this value")
        return lin_h, 170e-15  # committed Cshunt: no L-section exists for R_b >= 50
    x_series = math.sqrt(50.0 * r_b - r_b * r_b)
    lin_h = (x_series - x_b + x_c) / w
    cshunt_f = x_series / (50.0 * r_b * w)
    if lin_h <= 0:
        raise ValueError(
            f"re-match needs a negative Lin ({lin_h*1e9:.3f} nH): the blocking cap's "
            f"reactance over-cancels Z_b's at this value")
    return lin_h, cshunt_f


def model_cap_f(sizing: dict, primitive: str, side_um: float, corner: str = "typ") -> float:
    """Model capacitance of one square plate, from the sizing table's own model."""
    import passive_sizing as PS  # noqa: PLC0415
    return PS.model_c_f(sizing["capacitor_models"][primitive], side_um, side_um, corner)


# Frozen annotations known to disagree with the sizing table. The decks they appear in
# are hash-bound to published records, so they are not rewritten; the erratum says why.
ANNOTATION_ERRATA = {("V03", "Cblk_in"): "errata/20261121-101130-e6a7e3e.md"}


def cap_annotation_problems(plan: dict, sizing: dict, tol: float = 1e-3) -> list[str]:
    """Check each declared capacitor c_typ_f against m x the table's plate model."""
    out = []
    for var in plan.get("variants", []):
        for refdes, spec in sorted(var.get("assignment", {}).items()):
            if spec.get("kind") != "capacitor" or "c_typ_f" not in spec or "side_um" not in spec:
                continue
            want = spec.get("m", 1) * model_cap_f(
                sizing, spec["primitive"].removeprefix("cap_"), spec["side_um"])
            if abs(spec["c_typ_f"] / want - 1.0) > tol and (var["id"], refdes) not in ANNOTATION_ERRATA:
                out.append(f"{var['id']}/{refdes}: c_typ_f {spec['c_typ_f']:.6g} F != "
                           f"{want:.6g} F from the sizing model")
    return out


def cap_side_for_value(sizing: dict, primitive: str, value_f: float) -> dict:
    """The sizing table's own square-plate inversion for one capacitance
    (reused, not reimplemented: side and model C come from the table's
    per-primitive constants)."""
    import passive_sizing as PS  # noqa: PLC0415  (repo layout sibling, path set by caller)
    model = sizing["capacitor_models"][primitive]
    side = PS._grid(PS._square_side(model, value_f, "typ"), model["min_lw_um"])
    lo, hi = model["model_valid_lw_um"] or (None, None)
    if lo is not None and not lo <= side <= hi:
        raise ValueError(f"{primitive} side {side} um outside the model's {lo}-{hi} um window")
    c_typ = PS.model_c_f(model, side, side, "typ")
    if abs(c_typ - value_f) / value_f * 100.0 > PS._VALUE_TOLERANCE_PCT:
        raise ValueError(f"grid clamps {primitive} to {c_typ:.4g} F, away from {value_f:.4g} F")
    return {"side_um": side, "c_typ_f": c_typ}


# ---------------------------------------------------------------------------
# plan validation
# ---------------------------------------------------------------------------

def plan_problems(plan: dict, dut_text: str, sizing: dict) -> list[str]:
    """Why the plan cannot be the frozen declaration of this study."""
    problems: list[str] = []
    if plan.get("plan_version") != 2:
        problems.append("plan_version must be 2")
    scope = plan.get("scope", "")
    for needle in ("IDEAL", "no spec row", "selects nothing", "DR-0011",
                   "comparative deltas only"):
        if needle.lower() not in scope.lower():
            problems.append(f"scope does not state {needle!r}")
    if plan.get("baseline_record") != BASELINE_RECORD:
        problems.append(f"baseline_record must be {BASELINE_RECORD}")
    method = plan.get("method", {})
    if method.get("tb_file") != str(METHOD_TB.relative_to(REPO_ROOT)):
        problems.append("method.tb_file must point at the lna-sparam-nf tb.json")
    if method.get("tb_sha256") != sha256_text(METHOD_TB.read_text(encoding="utf-8")):
        problems.append("method.tb_sha256 does not match the committed tb.json")
    if method.get("fixture_sha256") != sha256_text(METHOD_FIXTURE.read_text(encoding="utf-8")):
        problems.append("method.fixture_sha256 does not match the committed fixture")
    if plan.get("sizing_sha256") != sha256_text(SIZING_PATH.read_text(encoding="utf-8")):
        problems.append("sizing_sha256 does not match the committed passive_sizing.json")

    names = [c["name"] for c in plan.get("corner_axis", [])]
    if names != [c["name"] for c in PROCESS_CORNERS]:
        problems.append("corner_axis must be exactly this module's PROCESS_CORNERS names")
    if plan.get("temperatures_c") != list(TEMPERATURES_C):
        problems.append("temperatures_c must be exactly this module's TEMPERATURES_C")
    if plan.get("supplies_v") != list(SUPPLIES_V):
        problems.append("supplies_v must be exactly this module's SUPPLIES_V")

    variants = plan.get("variants", [])
    if not 1 <= len(variants) <= 4:
        problems.append("the study declares at most four candidate sets")
    ids = [v.get("id") for v in variants]
    if len(set(ids)) != len(ids):
        problems.append("duplicate variant ids")
    prematch = plan.get("prematch", {})
    if prematch.get("grid_f") != list(PREMATCH_GRID_F):
        problems.append("prematch.grid_f must be exactly this module's PREMATCH_GRID_F")
    if (prematch.get("corners") != list(PREMATCH_CORNERS)
            or prematch.get("temperatures_c") != list(PREMATCH_TEMPS_C)):
        problems.append("prematch must cover all eight row-4 cells")
    if abs(prematch.get("s11_target_db", 0) - S11_TARGET_DB) > 1e-9:
        problems.append("prematch.s11_target_db must be the row-4 target -10 dB")

    sizing_res = {r["refdes"]: r for r in sizing["resistors"]}
    sizing_cap = {c["refdes"]: c for c in sizing["capacitors"]}
    for var in variants:
        for refdes, spec in sorted(var.get("assignment", {}).items()):
            kind = spec.get("kind")
            if kind == "resistor":
                cand = sizing_res[refdes]["candidates"].get(spec["flavour"])
                if not cand or "body_area_um2" not in cand:
                    problems.append(f"{var['id']}/{refdes}: flavour {spec['flavour']} "
                                    f"is not a feasible candidate in the sizing table")
                    continue
                if (abs(cand["w_um"] - spec["w_um"]) > 1e-9
                        or abs(cand["l_um"] - spec["l_um"]) > 1e-9):
                    problems.append(f"{var['id']}/{refdes}: w/l disagrees with the "
                                    f"sizing table's candidate for {spec['flavour']}")
            elif kind == "capacitor":
                # the sizing table keys candidates by the PDK's short name
                short = spec["primitive"].removeprefix("cap_")
                cand = sizing_cap[refdes]["candidates"].get(short, {})
                if refdes in ("Cblk_in", "Cshunt") and spec.get("from_prematch"):
                    continue  # frozen by the prematch outcome, checked elsewhere
                single = cand.get("single_device", {})
                arr = cand.get("parallel_array", {})
                want_m = spec.get("m", 1)
                if want_m == 1 and single.get("side_um") != spec.get("side_um"):
                    problems.append(f"{var['id']}/{refdes}: side disagrees with the "
                                    f"sizing table's single-device candidate")
                if want_m > 1 and (not arr.get("m") or arr["m"] != want_m
                                   or arr["per_device"]["side_um"] != spec.get("side_um")):
                    problems.append(f"{var['id']}/{refdes}: array disagrees with the "
                                    f"sizing table's parallel_array candidate")
            elif kind in ("offchip_ideal", "ideal_value"):
                continue
            else:
                problems.append(f"{var['id']}/{refdes}: unknown kind {kind!r}")
    problems.extend(cap_annotation_problems(plan, sizing))
    return problems
