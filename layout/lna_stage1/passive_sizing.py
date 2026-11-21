#!/usr/bin/env python3
"""Size every stage-1 resistor and capacitor onto the PDK's own primitive
models (issue #340, part 1 of the passive-realization proposal).

A companion to ``realizability.py`` (issue #198). That script measured *which*
elements have no PDK primitive selected; this one measures *what the PDK's own
models would give each candidate*, so the decision record
(spec/decision-records/0011) argues from PDK-modelled numbers instead of the
first-order ``R = rsh * L / W`` table realizability.py used.

It is still a *measurement, not a selection*: nothing here picks a flavour for
the schematic. For every element it sizes every flavour the model can reach and
records geometry, body area and the model's own corner spread; picking one set
per variant is the study's frozen plan (``sim/lna-passive-study``), and
ratifying one set is the operator's call.

Resistor model (verified against the instanced ``r3_cmc`` OSDI model on the
batch fleet at negligible bias, see ``_PROBE_MEASURED`` and the study record):

    R = rsh * l / (w + 2*lwd) + 2*rzspec/w      (b=0, m=1, drawn w/l)

``resistors_mod.lib`` adds each flavour's drawn-to-electrical width correction
``lwd`` once inside the subckt (``weff = w + lwd``) and the ``r3_cmc`` model
card adds its ``xw`` (the same ``lwd`` value) a second time, so the electrical
width is ``w + 2*lwd``. The end/contact resistance is ``rzspec/w`` per end,
twice. Both corrections are read from the PDK files, never hardcoded; the
formula above only states how they combine.

Capacitor model (``cap_cmim`` / ``cap_rfcmim``, native ngspice):

    C = cap_carea * l * w + cpspec * 2 * (l + w)    (l, w in um)

``cpspec`` (0.040 fF/um, the ``CJSW`` of ``cmim_core``) is NOT rescaled by the
corner sections -- only ``cap_carea`` is (0.9x/1.0x/1.1x), a measured fact the
corner spread records. ``cap_rfcmim``'s own header declares w and l valid on
7..75 um only, so the single-device ceiling is ~8.45 pF typ regardless of the
PCell range constants; larger values need parallel devices.

Inputs (all read, none written): the derived netlist
``design/netlist/lna_stage1.spice``, and from the pinned PDK install
(``sim/pdk-artifact.json``): ``sg13g2_tech.json``,
``libs.tech/ngspice/models/cornerRES.lib``, ``resistors_mod.lib``,
``cornerCAP.lib``, ``capacitors_mod.lib``. Every file read is sha256-recorded
in the output.

Output: ``passive_sizing.json`` beside this script -- deterministic (no
timestamps, no host paths; PDK files are named by PDK-relative path).

Usage::

    python3 layout/lna_stage1/passive_sizing.py [--netlist PATH] [--out PATH]
    python3 layout/lna_stage1/passive_sizing.py --check   # exit 3 if drifted
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from toolchain_pin import (  # noqa: E402  (path set above)
    ToolchainError,
    pdk_install,
    repo_root,
)

#: The netlist whose elements are sized (the same authority realizability.py
#: reads; parsed with the same reader so the two tables cannot disagree on
#: what the stage contains).
from realizability import (  # noqa: E402
    NETLIST_RELPATH,
    PDK_CORNER_CAP,
    PDK_CORNER_RES,
    PDK_TECH_JSON,
    parse_spice_value,
    parse_tech_value,
    read_netlist,
    sha256_file,
)

PDK_RES_MOD = "libs.tech/ngspice/models/resistors_mod.lib"
PDK_CAP_MOD = "libs.tech/ngspice/models/capacitors_mod.lib"

#: The ``.subckt <name>`` prefixes of the resistor models in resistors_mod.lib,
#: and the tech-json parameter prefix that carries each flavour's geometry.
_RES_FLAVOURS = {
    "rsil": "rsil",
    "rppd": "rppd",
    "rhigh": "rhigh",
}

#: Drawn-geometry grid the sizing inverts onto (um). 0.01 um is the PDK PCell
#: grid; widths snap onto the same grid starting from each flavour's minW.
_L_GRID_UM = 0.01


def _grid(value: float, minimum: float) -> float:
    """Round *up* to the 0.01 um grid, never below *minimum* (a drawn length
    below the PDK's own minimum is not a legal geometry, it is a wish)."""
    stepped = max(minimum, _L_GRID_UM * round(value / _L_GRID_UM))
    if stepped < value:
        stepped += _L_GRID_UM
    return round(stepped, 2)


def read_resistor_models(install: str, tech: dict) -> dict:
    """Per flavour: sheet resistances per corner (from cornerRES.lib), the
    width correction / contact resistance / TCs (from resistors_mod.lib) and
    the geometry limits (from sg13g2_tech.json)."""
    corner_text = open(os.path.join(install, PDK_CORNER_RES), encoding="utf-8").read()
    sections: dict[str, dict[str, float]] = {}
    for m in re.finditer(r"^\.LIB\s+(\S+)\s*$([\s\S]*?)^\.ENDL\s+\1", corner_text, re.M):
        name, body = m.group(1), m.group(2)
        params = dict(re.findall(r"^\s*\.param\s+(\w+)\s*=\s*([0-9.eE+-]+)", body, re.M))
        sections[name] = {k: float(v) for k, v in params.items()}
    if not {"res_typ", "res_bcs", "res_wcs"} <= set(sections):
        raise ValueError(f"cornerRES.lib lacks res_typ/res_bcs/res_wcs: {sorted(sections)}")

    mod_text = open(os.path.join(install, PDK_RES_MOD), encoding="utf-8").read()
    tech_params = tech["techParams"]
    out = {}
    for flavour, prefix in _RES_FLAVOURS.items():
        m = re.search(
            rf"^\.subckt\s+{flavour}\s+\S+\s+\S+\s+\S+\s*$([\s\S]*?)^\.ends\s+{flavour}",
            mod_text, re.M,
        )
        if not m:
            raise ValueError(f"no .subckt {flavour} in resistors_mod.lib")
        body = m.group(1)
        weff = re.search(r"weff\s*=\s*w([+-][0-9.]+e-6)", body)
        rzspec = re.search(r"rzspec\s*=\s*([0-9.]+e-6)", body)
        if not weff or not rzspec:
            raise ValueError(f"{flavour}: cannot read weff/rzspec from resistors_mod.lib")
        model = re.search(rf"\.model\s+(\S+)\s+r3_cmc([\s\S]*?)(?=^\+?\.|\Z)", body, re.M)
        if not model:
            raise ValueError(f"{flavour}: no .model r3_cmc card in resistors_mod.lib")
        card = model.group(2)
        xw = re.search(r"xw\s*=\s*([+-]?[0-9.]+)\s*$", card, re.M)
        if not xw:
            raise ValueError(f"{flavour}: no xw on the r3_cmc card")
        lwd_subckt = parse_spice_value(weff.group(1).replace("e-6", "u"))
        lwd_model = float(xw.group(1)) * 1e-6
        # The two corrections are the same number by PDK construction; assert
        # it rather than assume it, so a PDK that changes one half is loud.
        if abs(lwd_subckt - lwd_model) > 1e-12:
            raise ValueError(
                f"{flavour}: subckt weff correction {lwd_subckt} != model xw {lwd_model}"
            )
        rz = parse_spice_value(rzspec.group(1).replace("e-6", "u"))
        tech_rz = parse_tech_value(tech_params[f"{prefix}_rzspec"])
        if abs(rz - tech_rz) > 1e-12:
            raise ValueError(f"{flavour}: rzspec disagrees between model lib and tech json")
        tc1 = float(re.search(r"^\+tc1\s*=\s*([0-9.eE+-]+)", card, re.M).group(1))
        tc2 = float(re.search(r"^\+tc2\s*=\s*([0-9.eE+-]+)", card, re.M).group(1))
        out[flavour] = {
            "model_subckt": flavour,
            "terminals": 3,
            "sheet_ohm_per_sq": {
                corner: sections[section][f"rsh_{flavour}"]
                for corner, section in (
                    ("typ", "res_typ"), ("bcs", "res_bcs"), ("wcs", "res_wcs"))
            },
            "lwd_um": lwd_subckt * 1e6,
            "rzspec_um": rz * 1e6,
            "contact_ohm_per_end_at_w": "rzspec/w",
            "tc1_per_k": tc1,
            "tc2_per_k2": tc2,
            "min_w_um": parse_tech_value(tech_params[f"{prefix}_minW"]) * 1e6,
            "min_l_um": parse_tech_value(tech_params[f"{prefix}_minL"]) * 1e6,
            "max_w_um": parse_tech_value(tech_params[f"{prefix}_maxW"]) * 1e6,
            "max_l_um": parse_tech_value(tech_params[f"{prefix}_maxL"]) * 1e6,
        }
    return out


def read_capacitor_models(install: str, tech: dict) -> dict:
    """Per MIM primitive: area capacitance per corner, perimeter capacitance,
    declared ranges and the model lib's own valid-geometry window."""
    corner_text = open(os.path.join(install, PDK_CORNER_CAP), encoding="utf-8").read()
    sections: dict[str, dict[str, float]] = {}
    for m in re.finditer(r"^\.LIB\s+(\S+)\s*$([\s\S]*?)^\.ENDL\s+\1", corner_text, re.M):
        params = dict(re.findall(r"^\s*\.param\s+(\w+)\s*=\s*([0-9.eE+*/ -]+)", m.group(2), re.M))
        if params:
            sections[m.group(1)] = {k: eval_expr(v) for k, v in params.items()}
    if not {"cap_typ", "cap_bcs", "cap_wcs"} <= set(sections):
        raise ValueError(f"cornerCAP.lib lacks cap_typ/cap_bcs/cap_wcs: {sorted(sections)}")

    mod_text = open(os.path.join(install, PDK_CAP_MOD), encoding="utf-8").read()
    cjsw = re.search(r"\.model\s+cmim_core\s+C\s*\(([^)]*)\)", mod_text)
    if not cjsw:
        raise ValueError("no .model cmim_core in capacitors_mod.lib")
    sw = re.search(r"CJSW\s*=\s*([0-9.eE+-]+)", cjsw.group(1))
    if not sw:
        raise ValueError("cmim_core carries no CJSW")
    cpspec_f_per_um = parse_spice_value(sw.group(1))

    tech_params = tech["techParams"]
    valid = re.search(
        r"valid parameter range for w and l:\s*([0-9.]+)um to ([0-9.]+)um", mod_text)
    rf_min = float(valid.group(1)) if valid else None
    rf_max = float(valid.group(2)) if valid else None
    return {
        "cmim": {
            "model_subckt": "cap_cmim",
            "terminals": 2,
            "area_cap_f_per_um2": {
                "typ": sections["cap_typ"]["cap_carea"],
                "bcs": sections["cap_bcs"]["cap_carea"],
                "wcs": sections["cap_wcs"]["cap_carea"],
            },
            "perim_cap_f_per_um": cpspec_f_per_um,
            "perim_cap_corner_scaled": False,
            "declared_min_c_f": parse_tech_value(tech_params["cmim_minC"]),
            "declared_max_c_f": parse_tech_value(tech_params["cmim_maxC"]),
            "min_lw_um": parse_tech_value(tech_params["cmim_minLW"]) * 1e6,
            "model_valid_lw_um": None,
        },
        "rfcmim": {
            "model_subckt": "cap_rfcmim",
            "terminals": 3,
            "area_cap_f_per_um2": {
                "typ": sections["cap_typ"]["cap_carea"],
                "bcs": sections["cap_bcs"]["cap_carea"],
                "wcs": sections["cap_wcs"]["cap_carea"],
            },
            "perim_cap_f_per_um": cpspec_f_per_um,
            "perim_cap_corner_scaled": False,
            "declared_min_c_f": parse_tech_value(tech_params["rfcmim_minC"]),
            "declared_max_c_f": parse_tech_value(tech_params["rfcmim_maxC"]),
            "min_lw_um": parse_tech_value(tech_params["rfcmim_minLW"]) * 1e6,
            "model_valid_lw_um": [rf_min, rf_max],
        },
    }


def eval_expr(text: str) -> float:
    """Evaluate a cornerCAP.lib `.param` right-hand side (e.g. ``0.9*1.5E-15``)."""
    token = text.strip()
    if not re.fullmatch(r"[0-9.eE+*/ -]+", token):
        raise ValueError(f"cannot evaluate param expression {text!r}")
    return float(eval(token, {"__builtins__": {}}, {}))


def _round_sig(value: float, digits: int = 6) -> float:
    """Round to *digits* significant figures (femtofarads survive; a plain
    ``round(x, 6)`` would flatten every capacitance to zero)."""
    if value == 0 or value != value:
        return value
    mag = 10.0 ** (digits - 1 - math.floor(math.log10(abs(value))))
    return round(value * mag) / mag


#: A sizing whose model value misses the design value by more than this
#: percent is not a sizing of that element -- it is the geometry grid clamping
#: (a minimum length/width forcing a larger model value). Such entries are
#: reported as infeasible for the flavour, never offered as candidates.
_VALUE_TOLERANCE_PCT = 1.0


def model_r_ohm(flavour: dict, w_um: float, l_um: float, corner: str) -> float:
    """The PDK model's R at one corner: ``rsh*l/(w+2*lwd) + 2*rzspec/w``."""
    weff = w_um + 2.0 * flavour["lwd_um"]
    if weff <= 0:
        raise ValueError(f"w={w_um} um leaves non-positive electrical width")
    return flavour["sheet_ohm_per_sq"][corner] * l_um / weff \
        + 2.0 * flavour["rzspec_um"] / w_um


def size_resistor(value_ohm: float, flavour: dict) -> dict | None:
    """Smallest-area legal single-device sizing on a deterministic rule:
    the narrowest width off a fixed grid that clears the PDK's own minimum
    length, with the length then inverted onto the 0.01 um grid.

    Returns None when none of the sampled widths meets the tolerance.
    """
    width_grid = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0, 20.0, 30.0, 50.0,
                  70.0, 100.0, 200.0, 500.0, flavour["max_w_um"]]
    best = None
    for w in width_grid:
        if w < flavour["min_w_um"] or w > flavour["max_w_um"]:
            continue
        contact = 2.0 * flavour["rzspec_um"] / w
        if contact >= value_ohm:
            continue  # even zero body length overshoots the value
        weff = w + 2.0 * flavour["lwd_um"]
        l_raw = (value_ohm - contact) * weff / flavour["sheet_ohm_per_sq"]["typ"]
        l = _grid(l_raw, flavour["min_l_um"])
        if l > flavour["max_l_um"]:
            continue
        r_typ = model_r_ohm(flavour, w, l, "typ")
        err_pct = (r_typ - value_ohm) / value_ohm * 100.0
        if abs(err_pct) > _VALUE_TOLERANCE_PCT:
            continue  # geometry clamped away from the design value
        entry = {
            "w_um": w,
            "l_um": l,
            "squares": round(l / weff, 3),
            "body_area_um2": round(w * l, 1),
            "contact_floor_ohm": round(contact, 3),
            "r_ohm": {
                corner: _round_sig(model_r_ohm(flavour, w, l, corner))
                for corner in ("typ", "bcs", "wcs")
            },
            "r_error_vs_design_pct": round(err_pct, 4),
            "corner_spread_pct": round(
                (model_r_ohm(flavour, w, l, "wcs") - model_r_ohm(flavour, w, l, "bcs"))
                / model_r_ohm(flavour, w, l, "typ") * 100.0, 2),
        }
        if best is None or entry["body_area_um2"] < best["body_area_um2"]:
            best = entry
    return best


def model_c_f(cap: dict, w_um: float, l_um: float, corner: str) -> float:
    """The PDK model's C at one corner: ``carea*l*w + cpspec*2*(l+w)``."""
    return cap["area_cap_f_per_um2"][corner] * l_um * w_um \
        + cap["perim_cap_f_per_um"] * 2.0 * (l_um + w_um)


def _square_side(cap: dict, value_f: float, corner: str) -> float:
    """Side of the square plate reaching value_f at *corner* (quadratic)."""
    a = cap["area_cap_f_per_um2"][corner]
    p = cap["perim_cap_f_per_um"]
    if a <= 0:
        raise ValueError("non-positive area capacitance")
    # a*s^2 + 4*p*s - C = 0
    return (-4.0 * p + (16.0 * p * p + 4.0 * a * value_f) ** 0.5) / (2.0 * a)


def size_capacitor(value_f: float, cap: dict) -> dict:
    """Square-plate single-device sizing at the typical corner, with the
    model's own corner spread of the resulting C. The perimeter term makes a
    square plate not exactly ``sqrt(C/carea)``; the quadratic here is the
    PDK's own model inverted, not the first-order area estimate.

    ``meets_design_value`` is False when the geometry grid clamps the plate
    past the design value (e.g. rfcmim's 7 um minimum side is already 74.6 fF,
    more than Cm's 57.8 fF): such a sizing is a fact about the flavour's
    floor, not a candidate."""
    side = _grid(_square_side(cap, value_f, "typ"), cap["min_lw_um"])
    lo, hi = cap["model_valid_lw_um"] or (None, None)
    c_typ = model_c_f(cap, side, side, "typ")
    err_pct = (c_typ - value_f) / value_f * 100.0
    entry = {
        "side_um": side,
        "plate_area_um2": round(side * side, 1),
        "c_f": {corner: _round_sig(model_c_f(cap, side, side, corner))
                for corner in ("typ", "bcs", "wcs")},
        "c_error_vs_design_pct": round(err_pct, 4),
        "corner_spread_pct": round(
            (model_c_f(cap, side, side, "wcs") - model_c_f(cap, side, side, "bcs"))
            / c_typ * 100.0, 2),
        "in_declared_range": bool(
            cap["declared_min_c_f"] <= c_typ <= cap["declared_max_c_f"]),
        "meets_design_value": abs(err_pct) <= _VALUE_TOLERANCE_PCT,
    }
    if lo is not None:
        entry["in_model_valid_geometry"] = bool(lo <= side <= hi)
        entry["model_valid_lw_um"] = [lo, hi]
    return entry


def build(netlist_path: str, install: str) -> dict:
    elements = read_netlist(netlist_path)
    with open(os.path.join(install, PDK_TECH_JSON), encoding="utf-8") as handle:
        tech = json.load(handle)
    res_models = read_resistor_models(install, tech)
    cap_models = read_capacitor_models(install, tech)

    resistors = [e for e in elements if e["kind"] == "R"]
    capacitors = [e for e in elements if e["kind"] == "C"]

    res_out = []
    for element in resistors:
        candidates = {}
        for flavour, model in sorted(res_models.items()):
            sized = size_resistor(element["value"], model)
            if sized is not None:
                candidates[flavour] = sized
            else:
                candidates[flavour] = {
                    "infeasible": True,
                    "why": (f"No sampled width from {model['min_w_um']:g} to "
                            f"{model['max_w_um']:g} um gives a legal length within "
                            f"{_VALUE_TOLERANCE_PCT:g}% of the design resistance."),
                }
        areas = [c["body_area_um2"] for c in candidates.values() if "body_area_um2" in c]
        res_out.append({
            "refdes": element["refdes"],
            "nodes": element["nodes"],
            "value_ohm": element["value"],
            "value_text": element["value_text"],
            "schematic_symbol": "res.sym",
            "candidates": candidates,
            "flavour_choice_body_area_spread": round(max(areas) / min(areas), 1)
            if len(areas) > 1 else None,
        })

    cap_out = []
    for element in capacitors:
        value = element["value"]
        entry = {
            "refdes": element["refdes"],
            "nodes": element["nodes"],
            "value_f": value,
            "value_text": element["value_text"],
            "schematic_symbol": "capa.sym",
            "candidates": {},
        }
        for name, model in sorted(cap_models.items()):
            single = size_capacitor(value, model)
            entry["candidates"][name] = {"single_device": single}
            single_ok = (
                single.get("meets_design_value", False)
                and single.get("in_declared_range", False)
                and single.get("in_model_valid_geometry", True)
            )
            if not single_ok:
                # Parallel-array sizings the DR's options need: smallest count
                # of identical square devices reaching the value.
                count = 2
                while count <= 2000:
                    per_device = value / count
                    arr = size_capacitor(per_device, model)
                    if (arr.get("meets_design_value", False)
                            and arr.get("in_declared_range", False)
                            and arr.get("in_model_valid_geometry", True)):
                        entry["candidates"][name]["parallel_array"] = {
                            "m": count,
                            "per_device": arr,
                            "total_plate_area_um2": round(
                                count * arr["plate_area_um2"], 1),
                        }
                        break
                    count += 1
                else:
                    why = ["no count <= 2000 of identical model-valid square "
                           "devices in the declared range reaches the value"]
                    if not single.get("meets_design_value", False) and value < \
                            single["c_f"]["typ"]:
                        why.insert(0, (
                            f"single device clamps at the model's geometry floor "
                            f"({single['c_f']['typ']:.4g} F at a "
                            f"{single['side_um']} um side), above the "
                            f"{value:.4g} F design value"))
                    entry["candidates"][name]["parallel_array"] = {
                        "m": None,
                        "why": "; ".join(why),
                    }
        cap_out.append(entry)

    files = {
        relpath: sha256_file(os.path.join(install, relpath))
        for relpath in (PDK_TECH_JSON, PDK_CORNER_RES, PDK_RES_MOD,
                        PDK_CORNER_CAP, PDK_CAP_MOD)
    }
    return {
        "schema_version": 1,
        "analysis": "lna_stage1_passive_sizing",
        "issue": 340,
        "note": (
            "PDK-model sizing of every stage-1 resistor and capacitor onto "
            "rsil/rppd/rhigh (r3_cmc, drawn-to-electrical width correction and "
            "end/contact resistance included) and cap_cmim/cap_rfcmim (area + "
            "perimeter capacitance). A measurement feeding the DR-0011 "
            "proposal: it selects nothing and edits no schematic."
        ),
        "resistor_model": (
            "R = rsh*l/(w + 2*lwd) + 2*rzspec/w per corner section of "
            "cornerRES.lib; lwd and rzspec parsed from resistors_mod.lib and "
            "cross-checked against sg13g2_tech.json. Verified against the "
            "instanced r3_cmc OSDI model on the klt batch fleet at 1 uA bias "
            "(see _PROBE_MEASURED in passive_sizing.py and the "
            "sim/lna-passive-study record)."
        ),
        "capacitor_model": (
            "C = cap_carea*l*w + 0.040 fF/um * 2*(l+w) per corner section of "
            "cornerCAP.lib; only cap_carea is corner-scaled (0.9x/1.0x/1.1x), "
            "the perimeter term is not -- measured on cap_cmim and cap_rfcmim "
            "instanced on the batch fleet at 1 MHz."
        ),
        "inputs": {
            "netlist": {
                "path": NETLIST_RELPATH,
                "scope": "repo",
                "content_hash": sha256_file(netlist_path),
            },
            "pdk": {
                "install_subtree": "ihp-sg13g2",
                "pin": "sim/pdk-artifact.json",
                "files": files,
            },
        },
        "resistor_models": res_models,
        "capacitor_models": cap_models,
        "resistors": res_out,
        "capacitors": cap_out,
    }


#: Fleet-probe cross-check (klt sim, ngspice-47 on aws-batch-fleet, jobs under
#: sim/lna-passive-study/records/<id>): the closed forms above reproduce these
#: instanced-model measurements exactly at the printed precision. Kept here so
#: the table's derivation is falsifiable without re-running the fleet.
_PROBE_MEASURED = {
    "rsil w=0.5 l=1": {"typ": 31.4615, "bcs": 29.5769, "wcs": 33.3462},
    "rsil w=0.5 l=2": {"typ": 44.9231},
    "rsil w=0.5 l=10": {"typ": 152.615},
    "rppd w=0.5 l=1": {"typ": 647.812, "bcs": 597.031, "wcs": 698.594},
    "rppd w=1.0 l=1": {"typ": 326.917},
    "rppd w=0.5 l=10": {"typ": 5218.12},
    "rhigh w=0.5 l=1": {"typ": 3558.09, "bcs": 2748.57, "wcs": 4367.62},
    "rhigh w=1.0 l=1": {"typ": 1638.26},
    "rhigh w=0.5 l=10": {"typ": 32701.0},
    "cmim 6.2x6.2 fF": {"typ": 58.652e-15, "wcs": 64.418e-15},
    "rfcmim 75x75 fF": {"typ": 8449.5e-15},
}


def main(argv: list[str] | None = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--netlist", default=None, help="override netlist path")
    parser.add_argument(
        "--out", default=os.path.join(here, "passive_sizing.json"),
        help="output JSON path (default: passive_sizing.json beside this script)")
    parser.add_argument(
        "--check", action="store_true",
        help="compare against the committed output instead of writing it; "
             "exit 3 if it drifted")
    args = parser.parse_args(argv)

    try:
        netlist = args.netlist or os.path.join(repo_root(), NETLIST_RELPATH)
        if not os.path.isfile(netlist):
            raise ToolchainError(f"netlist not found: {netlist}")
        report = build(netlist, pdk_install())
    except (ToolchainError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(report, indent=2, sort_keys=False) + "\n"
    if args.check:
        if not os.path.isfile(args.out):
            print(f"error: no committed table at {args.out}", file=sys.stderr)
            return 1
        with open(args.out, encoding="utf-8") as handle:
            committed = handle.read()
        if committed == rendered:
            print(f"match: {os.path.basename(args.out)} still reproduces")
            return 0
        print(f"drifted: {os.path.basename(args.out)} is not what this tree and "
              "the installed PDK now produce", file=sys.stderr)
        return 3

    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    n_res = len(report["resistors"])
    n_cap = len(report["capacitors"])
    print(f"wrote: {args.out}")
    print(f"elements: {n_res} resistors, {n_cap} capacitors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
