"""evidence_checks.kaband: split out of check_evidence_formats.py (issue #163); no rule changes."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .common import (KABAND_SECTIONS, KABAND_SIDECAR_SUFFIXES, Problems, RECORD_ID_RE, check_supersedes, compare_identities, csv_corner_ids, expand_matrix, has_section, header_field, numbers, read_gzip_text, rel, section_body)


# ---------------------------------------------------------------------------
# Ka-band layout
# ---------------------------------------------------------------------------


def check_kaband_record(problems: Problems, root: Path, exp_dir: Path, md: Path) -> None:
    rid = md.stem
    where = rel(root, md)
    text = md.read_text(encoding="utf-8", errors="replace")

    if not RECORD_ID_RE.match(rid):
        problems.add(where, "record file name is not <YYYYMMDD>-<HHMMSS>-<git-sha>.md")
    first = text.splitlines()[0] if text.strip() else ""
    if first != f"# {rid}":
        problems.add(where, f"first line must be '# {rid}', found {first!r}")
    for name in ("Status", "Experiment", "Started (UTC)", "Claim"):
        if header_field(text, name) is None:
            problems.add(where, f"missing required header field '**{name}**:'")
    experiment = header_field(text, "Experiment")
    if experiment is not None and experiment != exp_dir.name:
        problems.add(where, f"Experiment {experiment!r} does not match its directory {exp_dir.name!r}")
    for title in KABAND_SECTIONS:
        if not has_section(text, title):
            problems.add(where, f"missing required section '## {title}'")
    sup = header_field(text, "Supersedes")
    if sup is not None:
        check_supersedes(problems, where, exp_dir, sup)

    grid = section_body(text, "Grid")
    m = re.search(
        r"\*\*PVT points\*\*: (\d+) = process (.+?) x temperature (.+?) x supply (.+?)\.\s*$",
        grid, re.MULTILINE)
    expected: list[str] | None = None
    supplies: list[float] = []
    if not m:
        problems.add(where, "'## Grid' has no parseable '**PVT points**: N = process .. x temperature .. "
                     "x supply ..' line")
    else:
        processes = [p.strip() for p in m.group(2).split(",") if p.strip()]
        temps = numbers(m.group(3))
        supplies = numbers(m.group(4))
        expected = expand_matrix(processes, temps, supplies)
        if int(m.group(1)) != len(expected):
            problems.add(where, f"declares {m.group(1)} PVT points but its lists expand to {len(expected)}")

    prov = section_body(text, "Provenance")
    for label, what in (("netlist-snapshots", "snapshot"), ("corners", "corner-log")):
        ids = set(re.findall(rf"`{label}/([^/`<]+)/", prov))
        if not ids:
            problems.add(where, f"'## Provenance' does not reference its {what} directory `{label}/<id>/`")
        elif ids != {rid}:
            problems.add(where, f"'## Provenance' {what} reference(s) {sorted(ids)} do not match this record id")
    for v in supplies:
        if not re.search(rf"klt sim request at supply {v:.2f} V", prov):
            problems.add(where, f"'## Provenance' has no 'klt sim request at supply {v:.2f} V' line")

    # per-corner compressed logs
    corners_dir = exp_dir / "corners" / rid
    if not corners_dir.is_dir():
        problems.add(where, f"missing corner directory {rel(root, corners_dir)}/")
    elif expected is not None:
        files = sorted(p for p in corners_dir.iterdir() if p.is_file())
        for p in files:
            if not p.name.endswith(".log.gz"):
                problems.add(rel(root, p), "unexpected non-.log.gz file in a Ka-band corner directory")
        compare_identities(problems, rel(root, corners_dir), "corner directory", expected,
                           [p.name[: -len(".log.gz")] for p in files if p.name.endswith(".log.gz")])
        for p in files:
            if p.name.endswith(".log.gz"):
                read_gzip_text(problems, root, p)

    # snapshot directory
    snap_dir = exp_dir / "netlist-snapshots" / rid
    if not snap_dir.is_dir():
        problems.add(where, f"missing netlist snapshot directory {rel(root, snap_dir)}/")
    elif supplies:
        want: dict[str, bool] = {}
        for v in supplies:
            want[f"body_{v:.2f}v.spice"] = False
            want[f"request_{v:.2f}v.json"] = True
            want[f"klt-report_{v:.2f}v.json"] = True
        have = {p.name for p in snap_dir.iterdir() if p.is_file()}
        for name, is_json in sorted(want.items()):
            p = snap_dir / name
            if name not in have:
                problems.add(rel(root, snap_dir), f"missing snapshot file {name}")
                continue
            if p.stat().st_size == 0:
                problems.add(rel(root, p), "snapshot file is empty")
            elif is_json:
                try:
                    json.loads(p.read_text(encoding="utf-8"))
                except (ValueError, UnicodeDecodeError) as exc:
                    problems.add(rel(root, p), f"not valid JSON ({exc})")
        for name in sorted(have - set(want)):
            problems.add(rel(root, snap_dir), f"unexpected snapshot file {name} (no declared supply for it)")

    # sidecars
    listed = set(re.findall(r"`records/([^`]+)`", section_body(text, "Sidecars")))
    for suffix in KABAND_SIDECAR_SUFFIXES:
        name = f"{rid}{suffix}"
        if name not in listed:
            problems.add(where, f"'## Sidecars' does not list required companion `records/{name}`")
        side = exp_dir / "records" / name
        if not side.is_file():
            problems.add(where, f"missing companion file {rel(root, side)}")
        elif expected is not None:
            ids = csv_corner_ids(problems, root, side)
            if ids is not None:
                compare_identities(problems, rel(root, side), "CSV corner_id column", expected, ids)
    for name in sorted(listed):
        if not (exp_dir / "records" / name).is_file():
            problems.add(where, f"'## Sidecars' lists `records/{name}` which does not exist")
    prefix = f"{rid}-"
    for p in sorted((exp_dir / "records").iterdir()):
        if p.name.startswith(prefix) and p.name not in listed:
            problems.add(rel(root, p), "companion file is not listed in its record's '## Sidecars' section")
