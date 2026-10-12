"""evidence_checks.lna_match: split out of check_evidence_formats.py (issue #163); no rule changes."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .common import Problems, duplicates, load_json_object, read_gzip_text, rel
from .passive_p1 import PASSIVE_PACKAGES, _sha256_of


# ---------------------------------------------------------------------------
# lna-match-tradeoff (sim/lna-match-tradeoff/collect.py, issue #74)
# ---------------------------------------------------------------------------

LNAMATCH_STATUSES = ("ok", "rejected_invalid")
LNAMATCH_RECORD_FILE_RE = re.compile(r"^(\d{8}-\d{6}-[0-9a-f]{7,40})(\.md|\.json|-cells\.json\.gz)$")
LNAMATCH_MD_MARKERS = (
    "**Spec rows claimed met**: none",
    "## Method",
    "## Intentional reductions",
    "## Controls",
    "## Nominal screen",
    "## Shortlist",
    "## Network-independent bound",
    "## Corner campaign",
    "## Conclusion",
    "## Provenance and raw artifacts",
)
LNAMATCH_PROVENANCE = ("git", "ngspice", "klt", "pdk", "klt_requests", "frozen_inputs")


def _lnamatch_cid(process: str, temp: float, vdd: float) -> str:
    return f"{process}_{temp:g}c_{vdd:.2f}v"


def lnamatch_expected_ids(decl: dict, shortlist: list) -> list[str]:
    """Declared cell ids from the FROZEN declaration (the record's own
    netlist-snapshots/<id>/study.json) and the record's shortlist: every
    declared network at the nominal screen point, and the shortlist plus every
    probe at every PVT point. Mirrors matchstudy.expected_cells."""
    n, pvt = decl["nominal"], decl["pvt"]
    nom = _lnamatch_cid(n["process"], float(n["temp_c"]), float(n["vdd"]))
    ids = [f"screen__{c['name']}__{nom}" for c in decl["candidates"]]
    probes = [c["name"] for c in decl["candidates"] if c.get("role") == "probe"]
    for name in list(shortlist) + probes:
        for p in pvt["processes"]:
            for t in pvt["temperatures_c"]:
                for v in pvt["supplies_v"]:
                    ids.append(f"corners__{name}__{_lnamatch_cid(p, float(t), float(v))}")
    return ids


def _all_numbers(values) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)


def check_lnamatch_cells(problems: Problems, root: Path, path: Path, cells: object, decl: dict | None,
                         shortlist: list, accepted: object) -> None:
    wc = rel(root, path)
    if not isinstance(cells, list):
        problems.add(wc, "cells file is not a JSON list")
        return
    if len(cells) != accepted:
        problems.add(wc, f"{len(cells)} cells on disk, sidecar says accepted_cells {accepted!r}")
    ids = [c.get("id") if isinstance(c, dict) else None for c in cells]
    for dup in duplicates(ids):
        problems.add(wc, f"duplicate cell id {dup!r}")
    if decl is not None:
        try:
            want = lnamatch_expected_ids(decl, shortlist)
        except (KeyError, TypeError, ValueError) as exc:
            problems.add(wc, f"cannot expand the frozen declaration ({exc!r})")
            want = None
        if want is not None:
            for missing in sorted(set(want) - set(ids)):
                problems.add(wc, f"missing declared cell {missing!r}")
            for extra in sorted(set(i for i in ids if i is not None) - set(want)):
                problems.add(wc, f"undeclared cell {extra!r}")
    dense_n = ((decl or {}).get("grid") or {}).get("dense_points")
    for c in cells:
        if not isinstance(c, dict):
            problems.add(wc, "cell is not an object")
            continue
        cid = c.get("id")
        status = c.get("status")
        if status not in LNAMATCH_STATUSES:
            problems.add(wc, f"{cid}: status {status!r} is not a scientific outcome")
            continue
        if c.get("model_section") != c.get("process"):
            problems.add(wc, f"{cid}: model_section {c.get('model_section')!r} != process {c.get('process')!r}")
        if status == "rejected_invalid":
            if not c.get("reason"):
                problems.add(wc, f"{cid}: rejected cell without a reason")
            continue
        sm = c.get("summary")
        if not isinstance(sm, dict) or not sm or not _all_numbers(sm.values()):
            problems.add(wc, f"{cid}: ok cell with a missing or non-finite summary")
        if c.get("role") == "probe":
            continue
        if not (c.get("refined") or {}).get("ok"):
            problems.add(wc, f"{cid}: ok cell without a passing refined-grid control")
        band = c.get("band")
        if not isinstance(band, dict) or not isinstance(band.get("f_hz"), list):
            problems.add(wc, f"{cid}: ok cell without per-frequency band data")
            continue
        n = len(band["f_hz"])
        if dense_n is not None and n != dense_n:
            problems.add(wc, f"{cid}: band grid has {n} points, the declaration says {dense_n}")
        for key in ("s11_db", "s21_db", "s22_db", "s12_db", "nf_db", "k", "delta"):
            arr = band.get(key)
            if not isinstance(arr, list) or len(arr) != n or not _all_numbers(arr):
                problems.add(wc, f"{cid}: band.{key} missing, wrong length or non-finite")
        wide = c.get("wide")
        if not isinstance(wide, dict) or not wide.get("k") or not _all_numbers(wide["k"]):
            problems.add(wc, f"{cid}: ok cell without a finite wide stability sweep")
        if not isinstance(c.get("screen"), dict) or "pass" not in c["screen"]:
            problems.add(wc, f"{cid}: ok cell without a screen outcome")


def check_lnamatch_record(problems: Problems, root: Path, exp_dir: Path, rid: str) -> None:
    md = exp_dir / "records" / f"{rid}.md"
    where = rel(root, md)
    text = md.read_text(encoding="utf-8", errors="replace")
    first = text.splitlines()[0] if text.strip() else ""
    if first != f"# lna-match-tradeoff record {rid}":
        problems.add(where, f"first line must be '# lna-match-tradeoff record {rid}', found {first[:80]!r}")
    for marker in LNAMATCH_MD_MARKERS:
        if marker not in text:
            problems.add(where, f"record lacks required content {marker!r}")
    snap = exp_dir / "netlist-snapshots" / rid
    decl = None
    decl_path = snap / "study.json"
    if not snap.is_dir():
        problems.add(rel(root, snap), "netlist-snapshots/<id>/ directory missing")
    elif not decl_path.is_file():
        problems.add(rel(root, snap), "snapshot lacks the frozen declaration study.json")
    else:
        decl = load_json_object(problems, root, decl_path)
    if snap.is_dir() and not (snap / "lna_stage1.spice").is_file():
        problems.add(rel(root, snap), "snapshot lacks the frozen DUT lna_stage1.spice")
    js = exp_dir / "records" / f"{rid}.json"
    if not js.is_file():
        problems.add(where, f"record has no JSON sidecar {rid}.json")
        return
    data = load_json_object(problems, root, js)
    if data is None:
        return
    wj = rel(root, js)
    if data.get("record_id") != rid:
        problems.add(wj, f"JSON record_id {data.get('record_id')!r} != {rid!r}")
    if "no spec row" not in str(data.get("scope", "")) or data.get("spec_rows_claimed_met") != []:
        problems.add(wj, "JSON must state that no spec row is claimed met (scope + empty spec_rows_claimed_met)")
    gate = data.get("gate")
    if not (isinstance(gate, dict) and gate.get("validate_collection") == "passed" and not gate.get("problems")):
        problems.add(wj, "acceptance gate result is not recorded as passed")
    dc, ac = data.get("declared_cells"), data.get("accepted_cells")
    if not (isinstance(dc, int) and dc > 0 and dc == ac):
        problems.add(wj, f"declared_cells {dc!r} != accepted_cells {ac!r}")
    prov = data.get("provenance") if isinstance(data.get("provenance"), dict) else {}
    if not prov:
        problems.add(wj, "no provenance object")
    for key in LNAMATCH_PROVENANCE:
        if prov.get(key) in (None, "", {}, []):
            problems.add(wj, f"provenance.{key} missing or empty")
    if isinstance(prov.get("pdk"), dict) and not prov["pdk"].get("model_sha256"):
        problems.add(wj, "provenance.pdk.model_sha256 missing or empty")
    decl_sha = (data.get("declaration") or {}).get("sha256")
    if decl_path.is_file() and decl_sha != _sha256_of(decl_path):
        problems.add(wj, "declaration.sha256 does not match the frozen netlist-snapshots/<id>/study.json")
    fi = prov.get("frozen_inputs") if isinstance(prov.get("frozen_inputs"), dict) else {}
    dut = snap / "lna_stage1.spice"
    if dut.is_file() and fi.get("design_netlist_sha256") != _sha256_of(dut):
        problems.add(wj, "frozen_inputs.design_netlist_sha256 does not match the frozen DUT snapshot")
    sl = data.get("shortlist") if isinstance(data.get("shortlist"), dict) else {}
    names = sl.get("names") if isinstance(sl.get("names"), list) else []
    if decl is not None:
        roles = {c.get("name"): c.get("role") for c in decl.get("candidates", []) if isinstance(c, dict)}
        if not names or roles.get(names[0]) != "baseline":
            problems.add(wj, "shortlist must start with the declared baseline")
        for n in names:
            if roles.get(n) not in ("baseline", "candidate"):
                problems.add(wj, f"shortlist names {n!r}, which is not a declared selectable network")
    reqs = prov.get("klt_requests") if isinstance(prov.get("klt_requests"), list) else []
    units = 0
    for r in reqs:
        if not isinstance(r, dict) or not r.get("key") or not isinstance(r.get("units"), int):
            problems.add(wj, "malformed provenance.klt_requests entry")
            continue
        units += r["units"]
        if snap.is_dir():
            for prefix, suffix in (("body_", ".spice"), ("request_", ".json"), ("report_", ".json"), ("spec_", ".json")):
                if not (snap / f"{prefix}{r['key']}{suffix}").is_file():
                    problems.add(rel(root, snap), f"snapshot lacks {prefix}{r['key']}{suffix}")
    if data.get("cells_file") != f"{rid}-cells.json.gz":
        problems.add(wj, f"cells_file {data.get('cells_file')!r} != {rid + '-cells.json.gz'!r}")
    cells_gz = exp_dir / "records" / f"{rid}-cells.json.gz"
    if not cells_gz.is_file():
        problems.add(where, f"record has no cells file {cells_gz.name}")
    else:
        raw = read_gzip_text(problems, root, cells_gz)
        if raw is not None:
            try:
                cells = json.loads(raw)
            except ValueError as exc:
                problems.add(rel(root, cells_gz), f"cells file is not valid JSON ({exc})")
            else:
                check_lnamatch_cells(problems, root, cells_gz, cells, decl, names, ac)
    logs = exp_dir / "corners" / rid
    if not logs.is_dir() or not any(logs.glob("*.log.gz")):
        problems.add(rel(root, logs), "no corners/<id>/*.log.gz raw logs for this record")
    else:
        n_logs = 0
        for p in sorted(logs.iterdir()):
            if not p.name.endswith(".log.gz"):
                problems.add(rel(root, p), "unexpected file in an lna-match-tradeoff corners directory")
            else:
                n_logs += 1
                read_gzip_text(problems, root, p)
        if reqs and n_logs != units:
            problems.add(rel(root, logs), f"{n_logs} raw logs, but the requests ran {units} units")


def check_lna_match_tradeoff(problems: Problems, root: Path, exp_dir: Path) -> None:
    decl = exp_dir / "testbench" / "study.json"
    if not decl.is_file():
        problems.add(rel(root, exp_dir), "lna-match-tradeoff has no testbench/study.json declaration")
    records = exp_dir / "records"
    ids: set[str] = set()
    if records.is_dir():
        groups: dict[str, set[str]] = {}
        for p in sorted(records.iterdir()):
            m = LNAMATCH_RECORD_FILE_RE.match(p.name)
            if not m:
                problems.add(rel(root, p), "unexpected file in lna-match-tradeoff records/ "
                             "(only <id>.md, <id>.json, <id>-cells.json.gz)")
                continue
            groups.setdefault(m.group(1), set()).add(m.group(2))
        for rid, parts in sorted(groups.items()):
            if ".md" not in parts:
                problems.add(rel(root, records), f"evidence for {rid} belongs to no record (no {rid}.md)")
                continue
            ids.add(rid)
            check_lnamatch_record(problems, root, exp_dir, rid)
    for sub in ("corners", "netlist-snapshots"):
        d = exp_dir / sub
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.name not in ids:
                    problems.add(rel(root, p), f"{sub} entry belongs to no record in this experiment (orphan evidence)")
    for sub in ("probe-logs", PASSIVE_PACKAGES):
        if (exp_dir / sub).exists():
            problems.add(rel(root, exp_dir / sub), f"{sub}/ is not part of the lna-match-tradeoff evidence layout")
