#!/usr/bin/env python3
"""Resolve every element of the LNA stage-1 netlist to a PDK primitive, or
record that none is selected (issue #198).

A layout generator must emit geometry for every element it claims. This script
answers, mechanically and per element, the question that has to be settled
before any such claim: **is there a PDK primitive to instance, and does the
designed value fit inside that primitive's own declared range?**

It is a *measurement*, not a design proposal. It never picks a device flavour,
never writes a spec decision, and never emits layout. For each element it
reports what the PDK itself declares, so a reader can see which elements a
layout could draw today and which are gated on a ratified realization choice.

Inputs (all read, none written):

``design/netlist/lna_stage1.spice``
    the derived netlist -- the authority on what the stage contains. Parsed,
    never edited.

the pinned PDK install (``sim/pdk-artifact.json`` -> ihp-sg13g2 v0.3.0)
    ``libs.tech/klayout/python/sg13g2_pycell_lib/sg13g2_tech.json`` for the
    ``cmim``/``rfcmim`` PCell range declarations (``*_minC``, ``*_maxC``,
    ``*_caspec``, ``*_minLW``), ``libs.tech/ngspice/models/cornerRES.lib`` for
    the three poly-resistor sheet resistances, and
    ``libs.tech/ngspice/models/cornerCAP.lib`` for the MIM area capacitance.
    Every file read is sha256-recorded in the output.

Output: ``realizability.json`` beside this script -- deterministic (no
timestamps, no host paths; PDK files are named by their PDK-relative path).

Per-element verdicts:

``pdk_primitive_modeled``
    the netlist names a PDK device subcircuit directly, so the primitive is
    not in question. Its *drawn* realization may still be constrained -- see
    ``drawn_realization`` on those entries.

``no_primitive_selected``
    the schematic used a generic ideal element (xschem ``res.sym`` /
    ``capa.sym`` / ``ind.sym``). Which PDK primitive realizes it, and at what
    geometry, is an open design choice: the candidates and their consequences
    are listed so the size of that choice is visible.

``exceeds_pdk_device_maximum``
    as above, *and* the designed value is outside the declared range of every
    candidate two-terminal primitive the PDK ships -- so no choice of geometry
    realizes it and the element needs a circuit change, not a layout decision.

``no_pdk_model``
    the PDK ships no model for this element class at all (inductors -- see
    ``spec/target-spec.md``).

Usage::

    python3 layout/lna_stage1/realizability.py [--netlist PATH] [--out PATH]
    python3 layout/lna_stage1/realizability.py --check   # exit 3 if drifted
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from toolchain_pin import (  # noqa: E402  (path set above)
    ToolchainError,
    pdk_install,
    repo_root,
)

#: Netlist path, relative to the repository root.
NETLIST_RELPATH = "design/netlist/lna_stage1.spice"

#: PDK-relative paths this analysis reads. Recorded with their sha256 in the
#: output so a later reader can tell whether the PDK moved under the numbers.
PDK_TECH_JSON = "libs.tech/klayout/python/sg13g2_pycell_lib/sg13g2_tech.json"
PDK_CORNER_RES = "libs.tech/ngspice/models/cornerRES.lib"
PDK_CORNER_CAP = "libs.tech/ngspice/models/cornerCAP.lib"

#: SPICE magnitude suffixes, SPICE semantics (``m`` is milli, ``meg`` is mega;
#: case-insensitive). ``f`` is femto, not farad.
_SUFFIXES = {
    "f": 1e-15,
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "meg": 1e6,
    "g": 1e9,
    "t": 1e12,
}

#: Poly-resistor flavours `klt gen res_array --params flavor=...` can draw on
#: this PDK family, mapped to the ``cornerRES.lib`` parameter carrying each
#: one's typical sheet resistance.
_RES_FLAVOURS = {
    "rsil": "rsh_rsil",
    "rppd": "rsh_rppd",
    "rhigh": "rsh_rhigh",
}


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def parse_spice_value(text: str) -> float:
    """Parse a SPICE magnitude (``8k``, ``57.8f``, ``0.962n``, ``1e3``).

    Raises ``ValueError`` on anything else, so a netlist element this analysis
    cannot read is a loud failure rather than a silently-skipped row.
    """
    token = text.strip().lower()
    match = re.fullmatch(r"([+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)([a-z]*)", token)
    if not match:
        raise ValueError(f"cannot parse SPICE value {text!r}")
    mantissa, suffix = match.group(1), match.group(2)
    value = float(mantissa)
    if not suffix:
        return value
    # Longest-match first so 'meg' wins over 'm'.
    for name in sorted(_SUFFIXES, key=len, reverse=True):
        if suffix.startswith(name):
            return value * _SUFFIXES[name]
    raise ValueError(f"unknown SPICE suffix in {text!r}")


def parse_tech_value(text: str) -> float:
    """Parse a ``sg13g2_tech.json`` techParams magnitude (``8p``, ``1.5m``,
    ``1.14u``, ``1m``).

    Same grammar as a SPICE magnitude, and the PDK writes these the same way
    (``cmim_caspec`` is ``1.5m``, i.e. 1.5e-3 F/m^2 = 1.5 fF/um^2).
    """
    return parse_spice_value(str(text))


def read_netlist(path: str) -> list[dict]:
    """Parse the ``.subckt`` body into element records.

    Returns one record per element in file order, each with ``refdes``,
    ``kind`` (``R``/``C``/``L``/``X``), ``nodes``, and either ``value`` (R/C/L)
    or ``model`` (X).
    """
    elements: list[dict] = []
    in_subckt = False
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("*"):
                continue
            lowered = line.lower()
            if lowered.startswith(".subckt"):
                in_subckt = True
                continue
            if lowered.startswith(".ends"):
                in_subckt = False
                continue
            if not in_subckt or line.startswith("."):
                continue

            fields = line.split()
            refdes = fields[0]
            prefix = refdes[0].upper()
            # Trailing `m=1`-style parameters are not positional arguments.
            positional = [f for f in fields[1:] if "=" not in f]
            if prefix in ("R", "C", "L"):
                # <refdes> <n+> <n-> <value>
                elements.append(
                    {
                        "refdes": refdes,
                        "kind": prefix,
                        "nodes": positional[:2],
                        "value": parse_spice_value(positional[2]),
                        "value_text": positional[2],
                    }
                )
            elif prefix == "X":
                # <refdes> <nodes...> <model>
                elements.append(
                    {
                        "refdes": refdes,
                        "kind": "X",
                        "nodes": positional[:-1],
                        "model": positional[-1],
                        # `Nx=` is the HBT's emitter multiplicity.
                        "params": {
                            k: v
                            for k, v in (
                                f.split("=", 1) for f in fields[1:] if "=" in f
                            )
                        },
                    }
                )
            else:
                raise ValueError(f"unhandled element prefix in {line!r}")
    if not elements:
        raise ValueError(f"no .subckt elements parsed from {path}")
    return elements


def read_pdk_constants(install: str) -> dict:
    """The PDK-declared passive constants this analysis rests on.

    Read from the install rather than transcribed here, so the numbers in
    ``realizability.json`` are the PDK's own and the recorded hashes say which
    revision produced them.
    """
    tech_path = os.path.join(install, PDK_TECH_JSON)
    with open(tech_path, encoding="utf-8") as handle:
        tech = json.load(handle)["techParams"]

    constants: dict = {
        "cmim": {
            "area_cap_f_per_um2": parse_tech_value(tech["cmim_caspec"]) * 1e-12,
            "min_c_f": parse_tech_value(tech["cmim_minC"]),
            "max_c_f": parse_tech_value(tech["cmim_maxC"]),
            "min_lw_um": parse_tech_value(tech["cmim_minLW"]) * 1e6,
        },
        "rfcmim": {
            "area_cap_f_per_um2": parse_tech_value(tech["rfcmim_caspec"]) * 1e-12,
            "min_c_f": parse_tech_value(tech["rfcmim_minC"]),
            "max_c_f": parse_tech_value(tech["rfcmim_maxC"]),
            "min_lw_um": parse_tech_value(tech["rfcmim_minLW"]) * 1e6,
            "terminals": 3,
        },
        "rsil_geometry": {
            "min_w_um": parse_tech_value(tech["rsil_minW"]) * 1e6,
            "min_l_um": parse_tech_value(tech["rsil_minL"]) * 1e6,
        },
    }

    # `cmim_caspec` is F/m^2; 1 F/m^2 = 1e-12 F/um^2. Cross-check it against
    # the ngspice corner library's own area capacitance, which is quoted in
    # F/um^2 directly -- two independent PDK statements of the same number.
    cap_text = open(os.path.join(install, PDK_CORNER_CAP), encoding="utf-8").read()
    typ = re.search(r"^\s*\.param\s+cap_carea\s*=\s*([^\s*]+)", cap_text, re.M)
    if not typ:
        raise ValueError(f"no `.param cap_carea =` found in {PDK_CORNER_CAP}")
    constants["cmim"]["area_cap_f_per_um2_cornerlib"] = parse_spice_value(typ.group(1))

    res_text = open(os.path.join(install, PDK_CORNER_RES), encoding="utf-8").read()
    sheet: dict = {}
    for flavour, param in _RES_FLAVOURS.items():
        hits = re.findall(
            rf"^\s*\.param\s+{param}\s*=\s*([0-9.]+)", res_text, re.M
        )
        if not hits:
            raise ValueError(f"no `.param {param} =` found in {PDK_CORNER_RES}")
        values = sorted({float(h) for h in hits})
        # The first `.param` block in cornerRES.lib is the typical corner;
        # the spread across every block is the corner range.
        sheet[flavour] = {
            "sheet_ohm_per_sq_typ": parse_spice_value(hits[0]),
            "sheet_ohm_per_sq_corner_range": [values[0], values[-1]],
        }
    constants["poly_resistors"] = sheet
    return constants


def resistor_candidates(value_ohm: float, constants: dict) -> list[dict]:
    """Per poly-resistor flavour, the geometry a ``value_ohm`` resistor needs.

    Uses the first-order sheet model ``R = rsh * L / W`` at the PDK's own
    minimum resistor width. *Approximation, stated rather than hidden*: it
    ignores the drawn-to-electrical width/length correction
    (``rsil_lwd`` = 0.04 um) and end/contact resistance, so a value is good to
    the order of magnitude this verdict needs, not to a design sizing. A real
    sizing comes from the PDK model, not from here.
    """
    min_w = constants["rsil_geometry"]["min_w_um"]
    min_l = constants["rsil_geometry"]["min_l_um"]
    out = []
    for flavour, data in sorted(constants["poly_resistors"].items()):
        sheet = data["sheet_ohm_per_sq_typ"]
        squares = value_ohm / sheet
        length_um = squares * min_w
        entry = {
            "flavour": flavour,
            "sheet_ohm_per_sq_typ": sheet,
            "squares": round(squares, 4),
            "length_at_min_width_um": round(length_um, 4),
            "width_um": min_w,
            "body_area_um2": round(length_um * min_w, 4),
        }
        if length_um < min_l:
            entry["below_minimum_geometry"] = True
            entry["note"] = (
                f"needs {length_um:.3f} um of body at the {min_w} um minimum "
                f"width, below the PDK's {min_l} um minimum length -- this "
                "flavour cannot reach the value at min width"
            )
        out.append(entry)
    return out


def capacitor_candidates(value_f: float, constants: dict) -> list[dict]:
    """Per MIM primitive, whether ``value_f`` is inside its declared range."""
    out = []
    for name in ("cmim", "rfcmim"):
        data = constants[name]
        density = data["area_cap_f_per_um2"]
        area = value_f / density
        entry = {
            "primitive": name,
            "terminals": data.get("terminals", 2),
            "area_cap_f_per_um2": density,
            "declared_min_c_f": data["min_c_f"],
            "declared_max_c_f": data["max_c_f"],
            "plate_area_um2": round(area, 4),
            "plate_side_um": round(area**0.5, 4),
            "in_declared_range": data["min_c_f"] <= value_f <= data["max_c_f"],
        }
        if value_f > data["max_c_f"]:
            entry["note"] = (
                f"{value_f:.4g} F exceeds this primitive's declared maximum "
                f"{data['max_c_f']:.4g} F by "
                f"{value_f / data['max_c_f']:.1f}x"
            )
        elif value_f < data["min_c_f"]:
            entry["note"] = (
                f"{value_f:.4g} F is below this primitive's declared minimum "
                f"{data['min_c_f']:.4g} F"
            )
        out.append(entry)
    return out


def classify(element: dict, constants: dict) -> dict:
    """The verdict record for one netlist element."""
    base = {
        "refdes": element["refdes"],
        "kind": element["kind"],
        "nodes": element["nodes"],
    }

    if element["kind"] == "X":
        base.update(
            {
                "model": element["model"],
                "params": element.get("params", {}),
                "verdict": "pdk_primitive_modeled",
                "pdk_primitive": element["model"],
                "schematic_symbol": f"{element['model']}.sym",
            }
        )
        nx = int(element.get("params", {}).get("Nx", "1"))
        base["emitter_multiplicity"] = nx
        if nx == 1:
            base["drawn_realization"] = {
                "status": "drawable_as_designed",
                "how": (
                    "the pinned PDK's primitive stream ships a fixed-geometry "
                    "npn13G2 cell, which is the Nx=1 device"
                ),
            }
        else:
            base["drawn_realization"] = {
                "status": "multiplicity_not_drawable_as_designed",
                "how": (
                    "the pinned PDK's primitive stream ships only the "
                    "fixed-geometry Nx=1 npn13G2 cell. The PDK's own "
                    "parametrized npn13G2 PCell, which draws a multi-emitter "
                    "device, is not instantiable in this environment (see "
                    "pcell_availability below), so Nx>1 can only be "
                    "approximated by Nx parallel unit cells -- a different "
                    "structure, with different base resistance and emitter "
                    "interconnect parasitics from the designed device"
                ),
            }
        return base

    base["value"] = element["value"]
    base["value_text"] = element["value_text"]

    if element["kind"] == "L":
        base.update(
            {
                "verdict": "no_pdk_model",
                "schematic_symbol": "ind.sym",
                "why": (
                    "the PDK ships no inductor model: spec/target-spec.md "
                    "records 'No inductor model, and no transmission-line "
                    "model, anywhere in libs.tech/ngspice/models/', and "
                    "inductor.sym/inductor3.sym ship as symbols with no "
                    "backing subcircuit. The netlist's own header states "
                    "these elements are IDEAL lossless L/C."
                ),
                "ratified_evidence": (
                    "spec/decision-records/0001-band-selection-ka-vs-ku.md "
                    "records openEMS extraction of the PDK's inductor2 PCell: "
                    "the single-turn p1 geometry is 98.5 pH, and the "
                    "multi-turn geometries self-resonate below the ratified "
                    "band ('Multi-turn spirals are dead at Ka band'). Cited, "
                    "not re-derived here."
                ),
            }
        )
        return base

    if element["kind"] == "R":
        candidates = resistor_candidates(element["value"], constants)
        usable = [c for c in candidates if not c.get("below_minimum_geometry")]
        # `null` rather than 1.0 when fewer than two flavours can reach the
        # value at minimum width: "no spread measured" is not "no spread".
        area_spread = (
            round(
                max(c["body_area_um2"] for c in usable)
                / min(c["body_area_um2"] for c in usable),
                1,
            )
            if len(usable) > 1
            else None
        )
        base.update(
            {
                "verdict": "no_primitive_selected",
                "schematic_symbol": "res.sym",
                "why": (
                    "the schematic uses the generic xschem res.sym, so the "
                    "netlist carries a resistance and no PDK device. Which of "
                    "the PDK's three poly-resistor flavours realizes it, and "
                    "at what geometry, is not recorded anywhere in spec/."
                ),
                "candidates": candidates,
                "flavour_choice_body_area_spread": area_spread,
            }
        )
        return base

    if element["kind"] == "C":
        candidates = capacitor_candidates(element["value"], constants)
        in_range = [c for c in candidates if c["in_declared_range"]]
        two_terminal_in_range = [c for c in in_range if c["terminals"] == 2]
        base.update(
            {
                "schematic_symbol": "capa.sym",
                "why": (
                    "the schematic uses the generic xschem capa.sym, so the "
                    "netlist carries a capacitance and no PDK device. Which "
                    "MIM primitive realizes it, and at what plate geometry, "
                    "is not recorded anywhere in spec/."
                ),
                "candidates": candidates,
            }
        )
        if not in_range:
            base["verdict"] = "exceeds_pdk_device_maximum"
            base["blocking"] = (
                "no MIM primitive the PDK ships declares a range containing "
                "this value, so no choice of plate geometry realizes it: this "
                "is a circuit-level gap, not a layout decision"
            )
        elif not two_terminal_in_range:
            base["verdict"] = "no_primitive_selected"
            base["note"] = (
                "only the 3-terminal rfcmim reaches this value; the netlist "
                "element is 2-terminal, so using it adds a substrate node the "
                "schematic does not have"
            )
        else:
            base["verdict"] = "no_primitive_selected"
        return base

    raise ValueError(f"unhandled element kind {element['kind']!r}")


def pcell_availability(install: str) -> dict:
    """Whether the PDK's own PCell libraries can be instantiated here.

    The parametrized devices (a multi-emitter ``npn13G2``, an ``rsil`` at a
    chosen W/L, a ``cmim`` at a chosen plate size) live in the PDK's PyCell
    libraries, which need the ``cni`` compat shim the PDK vendors next to them
    at ``pycell4klayout-api``. Reported as a measured fact because it bounds
    what any generator in this repo can draw.
    """
    shim = os.path.join(
        install, "libs.tech/klayout/python/pycell4klayout-api"
    )
    present = os.path.isdir(shim)
    entries = sorted(os.listdir(shim)) if present else []
    try:
        import cni  # noqa: F401

        importable = True
    except ImportError:
        importable = False
    return {
        "vendored_shim_relpath": "libs.tech/klayout/python/pycell4klayout-api",
        "vendored_shim_present": present,
        "vendored_shim_entry_count": len(entries),
        "cni_importable": importable,
        "pcell_libraries_instantiable": importable,
        "consequence": (
            "`klt gen --list-pdk-pcells` reports both sg13g2 PCell libraries "
            "as unavailable for missing_dependency 'cni'. The shim directory "
            "exists but is empty -- an uninitialized submodule in this PDK "
            "install -- so no PDK-parametrized device can be instanced, and a "
            "generator is limited to the fixed-geometry cells in "
            "libs.ref/sg13g2_pr/gds/sg13g2_pr.gds plus hand-drawn or "
            "`klt gen`-drawn geometry."
        )
        if not importable
        else "the PDK's parametrized PCells are instantiable in this environment",
    }


def build(netlist_path: str, install: str) -> dict:
    elements = read_netlist(netlist_path)
    constants = read_pdk_constants(install)
    classified = [classify(element, constants) for element in elements]

    counts: dict = {}
    for entry in classified:
        counts[entry["verdict"]] = counts.get(entry["verdict"], 0) + 1

    drawable = [
        entry["refdes"]
        for entry in classified
        if entry["verdict"] == "pdk_primitive_modeled"
    ]
    as_designed = [
        entry["refdes"]
        for entry in classified
        if entry.get("drawn_realization", {}).get("status")
        == "drawable_as_designed"
    ]

    return {
        "schema_version": 1,
        "analysis": "lna_stage1_element_realizability",
        "issue": 198,
        "note": (
            "Mechanical resolution of every LNA stage-1 netlist element to a "
            "PDK primitive, or to the absence of one. A measurement, not a "
            "design proposal: it selects no device flavour and proposes no "
            "geometry. See README.md for what this means for T1 items 2/3/11."
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
                "files": {
                    relpath: sha256_file(os.path.join(install, relpath))
                    for relpath in (PDK_TECH_JSON, PDK_CORNER_RES, PDK_CORNER_CAP)
                },
            },
        },
        "pdk_constants": constants,
        "pcell_availability": pcell_availability(install),
        "element_count": len(classified),
        "verdict_counts": counts,
        "summary": {
            "elements_with_a_pdk_primitive": drawable,
            "elements_drawable_at_their_designed_value": as_designed,
            "elements_needing_a_realization_decision": [
                entry["refdes"]
                for entry in classified
                if entry["verdict"] == "no_primitive_selected"
            ],
            "elements_no_primitive_can_realize": [
                entry["refdes"]
                for entry in classified
                if entry["verdict"] == "exceeds_pdk_device_maximum"
            ],
            "elements_with_no_pdk_model": [
                entry["refdes"]
                for entry in classified
                if entry["verdict"] == "no_pdk_model"
            ],
        },
        "elements": classified,
    }


def main(argv: list[str] | None = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--netlist", default=None, help="override netlist path")
    parser.add_argument(
        "--out",
        default=os.path.join(here, "realizability.json"),
        help="output JSON path (default: realizability.json beside this script)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare against the committed output instead of writing it; "
        "exit 3 if it drifted",
    )
    args = parser.parse_args(argv)

    try:
        root = repo_root()
        netlist = args.netlist or os.path.join(root, NETLIST_RELPATH)
        if not os.path.isfile(netlist):
            raise ToolchainError(f"netlist not found: {netlist}")
        report = build(netlist, pdk_install())
    except (ToolchainError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(report, indent=2, sort_keys=False) + "\n"

    if args.check:
        if not os.path.isfile(args.out):
            print(f"error: no committed report at {args.out}", file=sys.stderr)
            return 1
        with open(args.out, encoding="utf-8") as handle:
            committed = handle.read()
        if committed == rendered:
            print(f"match: {os.path.basename(args.out)} still reproduces")
            return 0
        print(
            f"drifted: {os.path.basename(args.out)} is not what this tree and "
            "the installed PDK now produce",
            file=sys.stderr,
        )
        return 3

    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(rendered)

    counts = report["verdict_counts"]
    print(f"wrote: {args.out}")
    print(f"elements: {report['element_count']}")
    for verdict in sorted(counts):
        print(f"  {verdict}: {counts[verdict]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
