"""evidence_checks.mixer_feas: split out of check_evidence_formats.py (issue #163); no rule changes."""

from __future__ import annotations

import json
from pathlib import Path

from .common import (Problems, RECORD_ID_RE, duplicates, load_json_object, read_gzip_text, rel)


MIXFEAS_STATUSES = ("ok", "rejected_stress", "not_applicable_no_drive")
MIXFEAS_SNAPSHOT_REQUIRED = ("tb.json", "ports_common.spice")
MIXFEAS_MD_MARKERS = (
    "Spec rows claimed met**: none",
    "## Intentional reductions",
    "## LO-drive selection",
    "## Conclusion",
    "## Provenance and raw artifacts",
)


def is_mixfeas(exp_dir: Path) -> bool:
    try:
        manifest = json.loads((exp_dir / "testbench" / "tb.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(manifest, dict) and "study" in manifest and "sweep" not in manifest


def check_mixfeas_record(problems: Problems, root: Path, exp_dir: Path, md: Path) -> None:
    stem = md.stem
    where = rel(root, md)
    text = md.read_text(encoding="utf-8")
    first = text.splitlines()[0] if text.strip() else ""
    if first != f"# mixer-topology-feasibility record {stem}":
        problems.add(where, f"first line must be '# mixer-topology-feasibility record {stem}', found {first[:80]!r}")
    if not RECORD_ID_RE.match(stem):
        problems.add(where, "record id is not <YYYYMMDD>-<HHMMSS>-<git-sha>")
    for marker in MIXFEAS_MD_MARKERS:
        if marker not in text:
            problems.add(where, f"record lacks required content {marker!r}")
    js = exp_dir / "records" / f"{stem}.json"
    cells_gz = exp_dir / "records" / f"{stem}-cells.json.gz"
    data = load_json_object(problems, root, js) if js.is_file() else None
    if data is None:
        if not js.is_file():
            problems.add(where, f"record has no JSON sidecar {stem}.json")
    else:
        wj = rel(root, js)
        if data.get("record_id") != stem:
            problems.add(wj, f"JSON record_id {data.get('record_id')!r} != {stem!r}")
        if "no spec row" not in str(data.get("scope", "")):
            problems.add(wj, "JSON 'scope' does not state that no spec row is claimed met")
        gate = data.get("gate")
        if not (isinstance(gate, dict) and gate.get("validate_collection") == "passed" and not gate.get("problems")):
            problems.add(wj, "acceptance gate result is not recorded as passed")
        dc, ac = data.get("declared_cells"), data.get("accepted_cells")
        if not (isinstance(dc, int) and dc > 0 and dc == ac):
            problems.add(wj, f"declared_cells {dc!r} != accepted_cells {ac!r}")
        prov = data.get("provenance")
        if not isinstance(prov, dict):
            problems.add(wj, "no provenance object")
            prov = {}
        for key in ("git", "ngspice", "klt", "pdk", "klt_requests", "converge", "crosscheck", "mismatch_seed"):
            if prov.get(key) in (None, "", {}, []):
                problems.add(wj, f"provenance.{key} missing or empty")
        pdk = prov.get("pdk")
        if isinstance(pdk, dict) and not pdk.get("model_sha256"):
            problems.add(wj, "provenance.pdk.model_sha256 missing or empty")
        if data.get("cells_file") != cells_gz.name:
            problems.add(wj, f"cells_file {data.get('cells_file')!r} != {cells_gz.name!r}")
        seed = prov.get("mismatch_seed")
        if not cells_gz.is_file():
            problems.add(where, f"record has no cells file {cells_gz.name}")
        else:
            raw = read_gzip_text(problems, root, cells_gz)
            cells = None
            if raw is not None:
                try:
                    cells = json.loads(raw)
                except ValueError as exc:
                    problems.add(rel(root, cells_gz), f"cells file is not valid JSON ({exc})")
            if cells is not None:
                wc = rel(root, cells_gz)
                if not isinstance(cells, list):
                    problems.add(wc, "cells file is not a JSON list")
                else:
                    ids = [c.get("id") if isinstance(c, dict) else None for c in cells]
                    if len(cells) != ac:
                        problems.add(wc, f"{len(cells)} cells on disk, sidecar says accepted_cells {ac!r}")
                    for dup in duplicates(ids):
                        problems.add(wc, f"duplicate cell id {dup!r}")
                    for c in cells:
                        if not isinstance(c, dict):
                            problems.add(wc, "cell is not an object")
                            continue
                        cid = c.get("id")
                        if c.get("status") not in MIXFEAS_STATUSES:
                            problems.add(wc, f"{cid}: status {c.get('status')!r} is not a scientific outcome")
                        if c.get("model_section") != c.get("corner"):
                            problems.add(wc, f"{cid}: model_section {c.get('model_section')!r} != corner {c.get('corner')!r}")
                        if c.get("matrix") == "leakage" and c.get("seed") != seed:
                            problems.add(wc, f"{cid}: leakage cell seed {c.get('seed')!r} != declared {seed!r}")
                        if c.get("status") in ("ok", "rejected_stress"):
                            rejecting = (c.get("stress") or {}).get("rejecting")
                            if rejecting is None:
                                problems.add(wc, f"{cid}: no stress classification")
                            elif (c["status"] == "ok") == bool(rejecting):
                                problems.add(wc, f"{cid}: status {c['status']} contradicts its stress violations")
    logs = exp_dir / "corners" / stem
    if not logs.is_dir() or not any(logs.glob("*.log.gz")):
        problems.add(rel(root, logs), "no corners/<id>/*.log.gz raw logs for this record")
    else:
        for p in sorted(logs.iterdir()):
            if not p.name.endswith(".log.gz"):
                problems.add(rel(root, p), "unexpected file in a mixer-topology-feasibility corners directory")
            else:
                read_gzip_text(problems, root, p)
    snap = exp_dir / "netlist-snapshots" / stem
    if not snap.is_dir():
        problems.add(rel(root, snap), "netlist-snapshots/<id>/ directory missing")
    else:
        names = [p.name for p in snap.iterdir()]
        for need in MIXFEAS_SNAPSHOT_REQUIRED:
            if need not in names:
                problems.add(rel(root, snap), f"snapshot lacks {need}")
        for prefix in ("body_", "request_", "report_", "spec_"):
            if not any(n.startswith(prefix) for n in names):
                problems.add(rel(root, snap), f"snapshot has no {prefix}* file")
        if not any(n.startswith("cand_") for n in names):
            problems.add(rel(root, snap), "snapshot has no frozen cand_* fragment")
