"""evidence_checks.mixer_cm: split out of check_evidence_formats.py (issue #163); no rule changes."""

from __future__ import annotations

from pathlib import Path

from .common import (PAIR_RE, Problems, RECORD_ID_RE, has_section, load_json_object, need_record_commit, need_sha256, need_str, record_pairs, rel)
from .mixer_nf import check_probe_log_package
from .passive_p1 import PASSIVE_PACKAGES


# ---------------------------------------------------------------------------
# mixer-cm-interface-probe (sim/mixer-cm-interface-probe/run_probe.py, issue #89)
# ---------------------------------------------------------------------------

CM_STATUSES = ("INTERFACES_DEMONSTRATED", "INTERFACES_PARTIAL", "INTERFACES_BLOCKED", "CAPABILITY_UNAVAILABLE")
CM_INTERFACES = ("lo_period_trajectory", "wanted_sideband_transfer", "image_sideband_transfer",
                 "noise_intensity_per_mechanism", "noise_covariance_ib_ic")
CM_STATES = ("demonstrated", "unsupported", "unknown")
CM_BASES = ("probe", "source", "probe+source")
CM_TRANSFERS = ("wanted_sideband_transfer", "image_sideband_transfer")


def cm_expected_status(states: list[str]) -> str:
    if "unsupported" in states:
        return "INTERFACES_BLOCKED"
    if "unknown" in states:
        return "INTERFACES_PARTIAL"
    return "INTERFACES_DEMONSTRATED"


def check_cm_matrix(problems: Problems, where: str, status: str, rec: dict) -> dict | None:
    matrix = rec.get("interface_matrix")
    if not isinstance(matrix, dict):
        problems.add(where, "JSON 'interface_matrix' is missing or not an object")
        return None
    if set(matrix) != set(CM_INTERFACES):
        problems.add(where, f"interface_matrix keys {sorted(matrix)} must be exactly {sorted(CM_INTERFACES)}")
        return matrix
    states = []
    for name in CM_INTERFACES:
        ent = matrix[name]
        if not isinstance(ent, dict):
            problems.add(where, f"interface_matrix[{name!r}] is not an object")
            continue
        st = ent.get("state")
        if st not in CM_STATES:
            problems.add(where, f"interface_matrix[{name!r}].state {st!r} is not one of {', '.join(CM_STATES)}")
        else:
            states.append(st)
        if ent.get("basis") not in CM_BASES:
            problems.add(where, f"interface_matrix[{name!r}].basis must be one of {', '.join(CM_BASES)}")
        ref, marks = ent.get("reference"), ent.get("probe_marks")
        if not isinstance(ref, str) or not ref.strip():
            problems.add(where, f"interface_matrix[{name!r}] has no primary 'reference'")
        if "probe" in str(ent.get("basis")) and not isinstance(marks, dict):
            problems.add(where, f"interface_matrix[{name!r}] claims a probe basis but has no 'probe_marks' object")
    ctl = rec.get("controls")
    ctl_pass = ctl.get("pass") if isinstance(ctl, dict) else None
    if not isinstance(ctl_pass, bool):
        problems.add(where, "JSON 'controls.pass' (known-answer control verdict) is missing or not a bool")
    else:
        for name in CM_TRANSFERS:
            ent = matrix.get(name)
            if isinstance(ent, dict) and ent.get("state") == "demonstrated" and not ctl_pass:
                problems.add(where, f"{name} is 'demonstrated' but the known-answer control did not pass")
    if len(states) == len(CM_INTERFACES) and cm_expected_status(states) != status:
        problems.add(where, f"status {status} does not follow from the interface states "
                     f"(expected {cm_expected_status(states)})")
    return matrix


def check_cm_record(problems: Problems, root: Path, exp_dir: Path, stem: str, files: dict[str, Path],
                    claimed_logs: set[str]) -> None:
    md_path, js_path = files.get("md"), files.get("json")
    if md_path is None or js_path is None:
        return
    where_md, where_js = rel(root, md_path), rel(root, js_path)
    m = PAIR_RE.match(md_path.name)
    assert m is not None
    rid, status = m.group(1), m.group(2)
    if status not in CM_STATUSES:
        problems.add(where_md, f"status {status!r} is not one of {', '.join(CM_STATUSES)}")
        return
    md = md_path.read_text(encoding="utf-8", errors="replace")
    first = md.splitlines()[0] if md.strip() else ""
    if first != f"# mixer-cm-interface-probe record {stem}":
        problems.add(where_md, f"first line must be '# mixer-cm-interface-probe record {stem}', found {first[:80]!r}")
    if f"- **Status: {status}**" not in md:
        problems.add(where_md, f"Markdown does not state '- **Status: {status}**'")
    if "Scope:" not in md:
        problems.add(where_md, "missing the '**Scope: ...**' statement")
    rec = load_json_object(problems, root, js_path)
    if rec is None:
        return
    if rec.get("record_id") != rid:
        problems.add(where_js, f"JSON record_id {rec.get('record_id')!r} does not match the record id {rid!r}")
    if rec.get("status") != status:
        problems.add(where_js, f"JSON status {rec.get('status')!r} does not match file name status {status!r}")
    reasons = rec.get("reasons")
    if not isinstance(reasons, list) or not reasons or not all(isinstance(r, str) and r for r in reasons):
        problems.add(where_js, "JSON 'reasons' must be a non-empty list of strings")
    scope = need_str(problems, where_js, rec, "scope")
    if scope is not None and "no active-mixer NF number" not in scope:
        problems.add(where_js, "JSON 'scope' does not disclaim an active-mixer NF number")
    env = rec.get("environment")
    if not isinstance(env, dict):
        problems.add(where_js, "JSON 'environment' is missing")
        env = {}
    commit = need_record_commit(problems, where_js, env, rid)
    for field in ("host", "platform", "python"):
        need_str(problems, where_js, env, field, f"environment.{field}")
    for field in ("placeholder_sha256", "pdk_artifact_sha256"):
        need_sha256(problems, where_js, env.get(field), f"environment.{field}")

    if status == "CAPABILITY_UNAVAILABLE":
        need_str(problems, where_js, rec, "failed_check")
        for key in ("interface_matrix", "probe_logs", "controls"):
            if key in rec:
                problems.add(where_js, f"CAPABILITY_UNAVAILABLE record carries '{key}' "
                             "(no probe ran; it cannot establish absence)")
        if "Failed check:" not in md:
            problems.add(where_md, "missing the 'Failed check:' statement")
        return

    if not has_section(md, "Provenance"):
        problems.add(where_md, "missing required section '## Provenance'")
    ng, pdk = env.get("ngspice"), env.get("pdk")
    need_sha256(problems, where_js, ng.get("sha256") if isinstance(ng, dict) else None, "environment.ngspice.sha256")
    if not isinstance(pdk, dict) or not pdk.get("fetched_version"):
        problems.add(where_js, "environment.pdk.fetched_version is missing")
    if isinstance(commit, str) and f"`{commit}`" not in md:
        problems.add(where_md, "Markdown '## Provenance' does not carry the JSON environment.git.commit")
    matrix = check_cm_matrix(problems, where_js, status, rec)

    logs = check_probe_log_package(problems, root, exp_dir, rid, rec, md, where_js, where_md, claimed_logs)
    if logs is None:
        return
    inv_path = logs / "inventory.json"
    if inv_path.is_file():
        inv = load_json_object(problems, root, inv_path)
        if inv is not None:
            if not isinstance(inv.get("parsed"), dict) or not isinstance(inv.get("interface_matrix"), dict):
                problems.add(rel(root, inv_path), "inventory.json needs 'parsed' and 'interface_matrix' objects")
            elif matrix is not None and inv["interface_matrix"] != matrix:
                problems.add(rel(root, inv_path), "inventory.json 'interface_matrix' differs from the record's "
                             "JSON 'interface_matrix' (record and frozen log disagree)")


def check_mixer_cm_interface_probe(problems: Problems, root: Path, exp_dir: Path) -> None:
    records = exp_dir / "records"
    claimed: set[str] = set()
    if records.is_dir():
        for stem, files in record_pairs(problems, root, records).items():
            check_cm_record(problems, root, exp_dir, stem, files, claimed)
    logs_root = exp_dir / "probe-logs"
    if logs_root.is_dir():
        for p in sorted(logs_root.iterdir()):
            if not (p.is_dir() and RECORD_ID_RE.match(p.name)):
                problems.add(rel(root, p), "probe-logs entry is not a <YYYYMMDD>-<HHMMSS>-<git-sha>/ run directory")
            elif p.name not in claimed:
                problems.add(rel(root, p), "probe-log package belongs to no record (orphan or incomplete run)")
    for sub in ("corners", "netlist-snapshots", PASSIVE_PACKAGES):
        if (exp_dir / sub).exists():
            problems.add(rel(root, exp_dir / sub), f"{sub}/ is not part of the mixer-cm-interface-probe evidence layout")
