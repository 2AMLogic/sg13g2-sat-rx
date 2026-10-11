#!/usr/bin/env python3
"""Driver for the lna-core-variants study (issue #79).

    python3 sim/lna-core-variants/run.py plan
    python3 sim/lna-core-variants/run.py derive [--force]    # local single-point scans, fills variants.json
    python3 sim/lna-core-variants/run.py netlists [--out DIR] # write every variant netlist (inspection)
    python3 sim/lna-core-variants/run.py collect [--dry-run] [--workdir DIR]

``derive`` runs ONE local ``ngspice -b`` per declared derivation, each at ONE
PVT point (a parameter scan inside one deck), which the host rules allow.
The PVT campaign (``collect``) is expressed as ``klt sim`` requests on the
batch fleet; a failed batch submit is an error, never a local fallback.
Only ``collect`` writes evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
SIM_DIR = BENCH_DIR.parent
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(BENCH_DIR))
sys.path.insert(0, str(SIM_DIR / "lna-match-tradeoff"))

import corestudy as cs  # noqa: E402
import matchstudy as ms  # noqa: E402


def cmd_plan(args) -> int:
    st = ms.load_study(cs.METHOD_STUDY)
    dec = cs.load_declaration(partial=True)
    nets = cs.networks(st)
    print(f"method: {cs.METHOD_STUDY.relative_to(cs.REPO_ROOT)} (grids, screen, probes, fixture from #74)")
    print(f"networks per deck: {len(nets)} ({nets[0].name} + {len(nets) - 1} probes)")
    for v in dec.variants:
        vals = {ph: dec.derived.get(d, "UNDERIVED") for ph, d in v.params.items()}
        print(f"  {v.name:>22} [{v.role}] changes {list(v.changes) or '-'} {vals or ''}")
    print(f"campaign: {len(dec.variants)} variants x {len(st.supplies_v)} supplies = "
          f"{len(dec.variants) * len(st.supplies_v)} klt requests x {len(st.processes) * len(st.temps_c)} units, "
          "backend batch")
    return 0


def _scan_values(sc: dict) -> list[float]:
    n = int(round((sc["stop"] - sc["start"]) / sc["step"]))
    return [sc["start"] + i * sc["step"] for i in range(n + 1)]


def cmd_derive(args) -> int:
    import localrun  # noqa: PLC0415 - one local ngspice per derivation, one PVT point
    raw = json.loads(cs.DECLARATION.read_text())
    st = ms.load_study(cs.METHOD_STUDY)
    frozen = cs.FROZEN.read_text()
    for d in raw["derivations"]:
        if "value" in d and not args.force:
            print(f"{d['param']}: already declared ({d['value']:g}); skipping")
            continue
        dec = cs.declaration_from_dict(raw, partial=True)
        params = {}
        for ph, src in d["bind"].items():
            params[ph] = "{" + cs.SCAN_PARAM + "}" if src == "SCAN" else dec.derived[src]
        net = cs.apply_changes(frozen, dec, d["changes"], params, label=f"derive {d['param']}")
        values = _scan_values(d["scan"])
        pt = d["point"]
        body = cs.scan_body(st, net, d["kind"], values, float(pt["vdd"]), title=d["param"])
        text = localrun.run_point(body, pt["process"], float(pt["temp_c"]), f"derive_{d['param']}")
        rows = cs.parse_scan(text, len(values))
        ys = [cs.scan_metric(d["kind"], r, st.z0) for r in rows]
        x = cs.solve_crossing(values, ys, float(d["target"]))
        val = ms.round_sig(x, int(d["sig"]))
        i = min(range(len(values)), key=lambda j: abs(values[j] - x))
        lo, hi = max(0, i - 1), min(len(values) - 1, i + 1)
        d["value"] = val
        d["result"] = {"crossing": float(f"{x:.6g}"), "ngspice": localrun.version(),
                       "bracket": [[float(f"{values[j]:.6g}"), float(f"{ys[j]:.6g}")] for j in range(lo, hi + 1)]}
        print(f"{d['param']}: {d['kind']} crosses {d['target']:g} at {x:.5g} -> declared {val:g} "
              f"(bracket {d['result']['bracket']})")
        raw = dict(raw)
    cs.declaration_from_dict(raw)  # every placeholder now bound
    cs.DECLARATION.write_text(json.dumps(raw, indent=2) + "\n")
    print(f"wrote {cs.DECLARATION}")
    return 0


def cmd_netlists(args) -> int:
    dec = cs.load_declaration()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for v in dec.variants:
        (out / f"netlist_{v.name}.spice").write_text(cs.variant_netlist(cs.FROZEN.read_text(), dec, v))
    print(f"wrote {len(dec.variants)} netlists under {out}")
    return 0


def cmd_collect(args) -> int:
    import corecollect  # noqa: PLC0415
    return corecollect.collect(args)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("plan").set_defaults(func=cmd_plan)
    d = sub.add_parser("derive")
    d.add_argument("--force", action="store_true", help="re-derive values already declared (before any record only)")
    d.set_defaults(func=cmd_derive)
    n = sub.add_parser("netlists")
    n.add_argument("--out", default=str(BENCH_DIR / "_build" / "netlists"))
    n.set_defaults(func=cmd_netlists)
    c = sub.add_parser("collect")
    c.add_argument("--klt-cmd", default="klt")
    c.add_argument("--backend", default="batch", help="backend for the 9-unit corner requests")
    c.add_argument("--timeout-s", type=int, default=3600)
    c.add_argument("--no-stage-models", action="store_true")
    c.add_argument("--runner-version-check", default="", choices=("", "enforce", "warn"))
    c.add_argument("--workdir", default="")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(func=cmd_collect)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
