"""evidence_checks.lna_core: lna-core-variants adapter (issue #79), ported onto the #163 package layout."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .common import Problems, duplicates, load_json_object, read_gzip_text, rel
from .lna_match import LNAMATCH_STATUSES, _all_numbers, _lnamatch_cid
from .passive_p1 import PASSIVE_PACKAGES, _sha256_of


# ---------------------------------------------------------------------------
# lna-core-variants (sim/lna-core-variants/corecollect.py, issue #79)
# ---------------------------------------------------------------------------

LNACORE_RECORD_FILE_RE = re.compile(r"^(\d{8}-\d{6}-[0-9a-f]{7,40})(\.md|\.json|-points\.json\.gz)$")
LNACORE_MD_MARKERS = (
    "**Spec rows claimed met**: none",
    "## Method",
    "## Intentional reductions",
    "## Variant declarations",
    "## Controls",
    "## Per-variant comparison",
    "## Selection",
    "## Per-point bound",
    "## Conclusion",
    "## Provenance and raw artifacts",
)
LNACORE_PROVENANCE = ("git", "ngspice", "klt", "pdk", "klt_requests", "frozen_inputs")
LNACORE_SELECTABLE = ("candidate", "combination")
LNACORE_BOUND_KEYS = ("f_hz", "nf_bound_db", "fmin_db", "rn_ohm", "gt_at_nf_bound_db")


def lnacore_expected_ids(variants: dict, study: dict) -> list[str]:
    """(frozen variants) x (frozen #74 PVT grid); mirrors corestudy.expected_points."""
    pvt = study["pvt"]
    return [f"{v['name']}__{_lnamatch_cid(p, float(t), float(vv))}" for v in variants["variants"]
            for p in pvt["processes"] for t in pvt["temperatures_c"] for vv in pvt["supplies_v"]]


def check_lnacore_points(problems: Problems, root: Path, path: Path, points: object, variants: dict | None,
                         study: dict | None, accepted: object) -> None:
    wp = rel(root, path)
    if not isinstance(points, list):
        problems.add(wp, "points file is not a JSON list")
        return
    if len(points) != accepted:
        problems.add(wp, f"{len(points)} points on disk, sidecar says accepted_points {accepted!r}")
    ids = [x.get("id") if isinstance(x, dict) else None for x in points]
    for dup in duplicates(ids):
        problems.add(wp, f"duplicate point id {dup!r}")
    if variants is not None and study is not None:
        try:
            want = lnacore_expected_ids(variants, study)
        except (KeyError, TypeError, ValueError) as exc:
            problems.add(wp, f"cannot expand the frozen declaration ({exc!r})")
            want = None
        if want is not None:
            for missing in sorted(set(want) - set(ids)):
                problems.add(wp, f"missing declared point {missing!r}")
            for extra in sorted(set(i for i in ids if i is not None) - set(want)):
                problems.add(wp, f"undeclared point {extra!r}")
    dense_n = ((study or {}).get("grid") or {}).get("dense_points")
    for x in points:
        if not isinstance(x, dict):
            problems.add(wp, "point is not an object")
            continue
        pid, status = x.get("id"), x.get("status")
        if status not in LNAMATCH_STATUSES:
            problems.add(wp, f"{pid}: status {status!r} is not a scientific outcome")
            continue
        if x.get("model_section") != x.get("process"):
            problems.add(wp, f"{pid}: model_section {x.get('model_section')!r} != process {x.get('process')!r}")
        if status == "rejected_invalid":
            if not x.get("reason"):
                problems.add(wp, f"{pid}: rejected point without a reason")
            continue
        sm = x.get("summary")
        scalars = [v for v in sm.values() if not isinstance(v, list)] if isinstance(sm, dict) else []
        if not isinstance(sm, dict) or not sm or not _all_numbers(scalars):
            problems.add(wp, f"{pid}: ok point with a missing or non-finite summary")
        b = x.get("bound")
        if not isinstance(b, dict) or not isinstance(b.get("f_hz"), list):
            problems.add(wp, f"{pid}: ok point without per-frequency bound data")
            continue
        n = len(b["f_hz"])
        if dense_n is not None and n != dense_n:
            problems.add(wp, f"{pid}: bound grid has {n} points, the declaration says {dense_n}")
        for key in LNACORE_BOUND_KEYS:
            arr = b.get(key)
            if not isinstance(arr, list) or len(arr) != n or not _all_numbers(arr):
                problems.add(wp, f"{pid}: bound.{key} missing, wrong length or non-finite")
        if not isinstance(x.get("op"), dict) or "pass" not in x["op"]:
            problems.add(wp, f"{pid}: ok point without an operating-point verdict")


def check_lnacore_record(problems: Problems, root: Path, exp_dir: Path, rid: str) -> None:
    md = exp_dir / "records" / f"{rid}.md"
    where = rel(root, md)
    text = md.read_text(encoding="utf-8", errors="replace")
    first = text.splitlines()[0] if text.strip() else ""
    if first != f"# lna-core-variants record {rid}":
        problems.add(where, f"first line must be '# lna-core-variants record {rid}', found {first[:80]!r}")
    for marker in LNACORE_MD_MARKERS:
        if marker not in text:
            problems.add(where, f"record lacks required content {marker!r}")
    snap = exp_dir / "netlist-snapshots" / rid
    variants = study = None
    if not snap.is_dir():
        problems.add(rel(root, snap), "netlist-snapshots/<id>/ directory missing")
    else:
        for name in ("variants.json", "study.json", "lna_stage1.spice"):
            if not (snap / name).is_file():
                problems.add(rel(root, snap), f"snapshot lacks the frozen {name}")
        if (snap / "variants.json").is_file():
            variants = load_json_object(problems, root, snap / "variants.json")
        if (snap / "study.json").is_file():
            study = load_json_object(problems, root, snap / "study.json")
        for v in (variants or {}).get("variants", []):
            if isinstance(v, dict) and not (snap / f"netlist_{v.get('name')}.spice").is_file():
                problems.add(rel(root, snap), f"snapshot lacks netlist_{v.get('name')}.spice")
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
    if not (data.get("reproduction") or {}).get("ok"):
        problems.add(wj, "the #74 reproduction by the frozen core is not recorded as ok")
    dp, ap = data.get("declared_points"), data.get("accepted_points")
    if not (isinstance(dp, int) and dp > 0 and dp == ap):
        problems.add(wj, f"declared_points {dp!r} != accepted_points {ap!r}")
    prov = data.get("provenance") if isinstance(data.get("provenance"), dict) else {}
    if not prov:
        problems.add(wj, "no provenance object")
    for key in LNACORE_PROVENANCE:
        if prov.get(key) in (None, "", {}, []):
            problems.add(wj, f"provenance.{key} missing or empty")
    fi = prov.get("frozen_inputs") if isinstance(prov.get("frozen_inputs"), dict) else {}
    for key, name in (("variants_json_sha256", "variants.json"), ("method_study_sha256", "study.json"),
                      ("design_netlist_sha256", "lna_stage1.spice")):
        f = snap / name
        if f.is_file() and fi.get(key) != _sha256_of(f):
            problems.add(wj, f"frozen_inputs.{key} does not match the frozen netlist-snapshots/<id>/{name}")
    if (snap / "variants.json").is_file() and (data.get("declaration") or {}).get("sha256") != \
            _sha256_of(snap / "variants.json"):
        problems.add(wj, "declaration.sha256 does not match the frozen netlist-snapshots/<id>/variants.json")
    chosen = (data.get("selection") or {}).get("chosen")
    if variants is not None and chosen is not None:
        roles = {v.get("name"): v.get("role") for v in variants.get("variants", []) if isinstance(v, dict)}
        if roles.get(chosen) not in LNACORE_SELECTABLE:
            problems.add(wj, f"selection.chosen {chosen!r} is not a declared selectable variant")
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
    if data.get("points_file") != f"{rid}-points.json.gz":
        problems.add(wj, f"points_file {data.get('points_file')!r} != {rid + '-points.json.gz'!r}")
    pgz = exp_dir / "records" / f"{rid}-points.json.gz"
    if not pgz.is_file():
        problems.add(where, f"record has no points file {pgz.name}")
    else:
        raw = read_gzip_text(problems, root, pgz)
        if raw is not None:
            try:
                pts = json.loads(raw)
            except ValueError as exc:
                problems.add(rel(root, pgz), f"points file is not valid JSON ({exc})")
            else:
                check_lnacore_points(problems, root, pgz, pts, variants, study, ap)
    logs = exp_dir / "corners" / rid
    if not logs.is_dir() or not any(logs.glob("*.log.gz")):
        problems.add(rel(root, logs), "no corners/<id>/*.log.gz raw logs for this record")
    else:
        n_logs = 0
        for p in sorted(logs.iterdir()):
            if not p.name.endswith(".log.gz"):
                problems.add(rel(root, p), "unexpected file in an lna-core-variants corners directory")
            else:
                n_logs += 1
                read_gzip_text(problems, root, p)
        if reqs and n_logs != units:
            problems.add(rel(root, logs), f"{n_logs} raw logs, but the requests ran {units} units")


def check_lna_core_variants(problems: Problems, root: Path, exp_dir: Path) -> None:
    if not (exp_dir / "testbench" / "variants.json").is_file():
        problems.add(rel(root, exp_dir), "lna-core-variants has no testbench/variants.json declaration")
    records = exp_dir / "records"
    ids: set[str] = set()
    if records.is_dir():
        groups: dict[str, set[str]] = {}
        for p in sorted(records.iterdir()):
            m = LNACORE_RECORD_FILE_RE.match(p.name)
            if not m:
                problems.add(rel(root, p), "unexpected file in lna-core-variants records/ "
                             "(only <id>.md, <id>.json, <id>-points.json.gz)")
                continue
            groups.setdefault(m.group(1), set()).add(m.group(2))
        for rid, parts in sorted(groups.items()):
            if ".md" not in parts:
                problems.add(rel(root, records), f"evidence for {rid} belongs to no record (no {rid}.md)")
                continue
            ids.add(rid)
            check_lnacore_record(problems, root, exp_dir, rid)
    for sub in ("corners", "netlist-snapshots"):
        d = exp_dir / sub
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.name not in ids:
                    problems.add(rel(root, p), f"{sub} entry belongs to no record in this experiment (orphan evidence)")
    for sub in ("probe-logs", PASSIVE_PACKAGES):
        if (exp_dir / sub).exists():
            problems.add(rel(root, exp_dir / sub), f"{sub}/ is not part of the lna-core-variants evidence layout")
