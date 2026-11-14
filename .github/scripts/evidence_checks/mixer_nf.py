"""evidence_checks.mixer_nf: split out of check_evidence_formats.py (issue #163); no rule changes."""

from __future__ import annotations

from pathlib import Path

from .common import (PAIR_RE, Problems, check_probe_log_bench, check_probe_log_package, has_section, load_json_object, need_record_commit, need_sha256, need_str, rel)
from .passive_p1 import MIXER_STATUSES, PASSIVE_PACKAGES


def check_mixer_record(problems: Problems, root: Path, exp_dir: Path, stem: str, files: dict[str, Path],
                       claimed_logs: set[str]) -> None:
    md_path, js_path = files.get("md"), files.get("json")
    if md_path is None or js_path is None:
        return
    where_md, where_js = rel(root, md_path), rel(root, js_path)
    m = PAIR_RE.match(md_path.name)
    assert m is not None
    rid, status = m.group(1), m.group(2)
    if status not in MIXER_STATUSES:
        problems.add(where_md, f"status {status!r} is not one of {', '.join(MIXER_STATUSES)}")
        return
    md = md_path.read_text(encoding="utf-8", errors="replace")
    first = md.splitlines()[0] if md.strip() else ""
    if first != f"# mixer-nf-method record {stem}":
        problems.add(where_md, f"first line must be '# mixer-nf-method record {stem}', found {first[:80]!r}")
    if f"- **Status: {status}**" not in md:
        problems.add(where_md, f"Markdown does not state '- **Status: {status}**'")
    rec = load_json_object(problems, root, js_path)
    if rec is None:
        return
    if rec.get("record_id") != rid:
        problems.add(where_js, f"JSON record_id {rec.get('record_id')!r} does not match the record id {rid!r}")
    if rec.get("status") != status:
        problems.add(where_js, f"JSON status {rec.get('status')!r} does not match file name status {status!r}")
    reasons = rec.get("reasons")
    if status != "METHOD_VALIDATION" and (
            not isinstance(reasons, list) or not reasons or not all(isinstance(r, str) and r for r in reasons)):
        problems.add(where_js, "JSON 'reasons' must be a non-empty list of strings")
    env = rec.get("environment")
    if not isinstance(env, dict):
        problems.add(where_js, "JSON 'environment' is missing")
        env = {}
    commit = need_record_commit(problems, where_js, env, rid)
    for field in ("host", "platform", "python"):
        need_str(problems, where_js, env, field, f"environment.{field}")

    if status == "CAPABILITY_UNAVAILABLE":
        need_str(problems, where_js, rec, "failed_check")
        if "inventory" in rec or "probe_logs" in rec:
            problems.add(where_js, "CAPABILITY_UNAVAILABLE record carries probe results/logs "
                         "(no simulator ran; it cannot establish model absence)")
        if "Failed check:" not in md:
            problems.add(where_md, "missing the 'Failed check:' statement")
        return

    # a probe record: scope statement, provenance and the frozen log package
    if "Scope:" not in md:
        problems.add(where_md, "missing the '**Scope: ...**' statement (methodology evidence only)")
    scope = need_str(problems, where_js, rec, "scope")
    if scope is not None and "no active-mixer NF number" not in scope:
        problems.add(where_js, "JSON 'scope' does not disclaim an active-mixer NF number")
    if not has_section(md, "Provenance"):
        problems.add(where_md, "missing required section '## Provenance'")
    for field in ("placeholder_sha256", "template_sha256"):
        need_sha256(problems, where_js, env.get(field), f"environment.{field}")
    ng, pdk = env.get("ngspice"), env.get("pdk")
    need_sha256(problems, where_js, ng.get("sha256") if isinstance(ng, dict) else None, "environment.ngspice.sha256")
    if not isinstance(pdk, dict) or not pdk.get("fetched_version"):
        problems.add(where_js, "environment.pdk.fetched_version is missing")
    if isinstance(commit, str) and f"`{commit}`" not in md:
        problems.add(where_md, "Markdown '## Provenance' does not carry the JSON environment.git.commit")
    if not isinstance(rec.get("inventory"), dict):
        problems.add(where_js, "JSON 'inventory' is missing")

    logs = check_probe_log_package(problems, root, exp_dir, rid, rec, md, where_js, where_md, claimed_logs)
    if logs is None:
        return
    inv_path = logs / "inventory.json"
    if inv_path.is_file():
        inv = load_json_object(problems, root, inv_path)
        if inv is not None:
            if not isinstance(inv.get("parsed"), dict) or not isinstance(inv.get("inventory"), dict):
                problems.add(rel(root, inv_path), "inventory.json needs 'parsed' and 'inventory' objects")
            elif inv["inventory"] != rec.get("inventory"):
                problems.add(rel(root, inv_path), "inventory.json 'inventory' differs from the record's "
                             "JSON 'inventory' (record and frozen log disagree)")


def check_mixer_nf_method(problems: Problems, root: Path, exp_dir: Path) -> None:
    check_probe_log_bench(problems, root, exp_dir, "mixer-nf-method", check_mixer_record,
                          ("corners", "netlist-snapshots", PASSIVE_PACKAGES))
