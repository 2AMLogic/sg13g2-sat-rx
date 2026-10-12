"""evidence_checks.mixer_nf: split out of check_evidence_formats.py (issue #163); no rule changes."""

from __future__ import annotations

from pathlib import Path

from .common import (PAIR_RE, Problems, RECORD_ID_RE, git, has_section, load_json_object, need_sha256, need_str, record_pairs, rel)
from .passive_p1 import MIXER_PROBE_FILES, MIXER_STATUSES, PASSIVE_PACKAGES


def check_probe_log_package(problems, root, exp_dir, rid, rec, md, where_js, where_md, claimed_logs):
    """Shared probe-log package contract; returns the package path, or None if the directory is missing."""
    declared = rec.get("probe_logs")
    expected = f"sim/{exp_dir.name}/probe-logs/{rid}/"
    if declared != expected:
        problems.add(where_js, f"JSON probe_logs {declared!r} must be {expected!r}")
    logs = exp_dir / "probe-logs" / rid
    claimed_logs.add(rid)
    if f"probe-logs/{rid}/" not in md:
        problems.add(where_md, f"Markdown does not reference its probe-logs/{rid}/ package")
    if not logs.is_dir():
        problems.add(where_js, f"declared probe-log package {rel(root, logs)}/ does not exist")
        return None
    # stderr may legitimately be empty
    present = {p.name for p in logs.iterdir() if p.is_file()}
    for name in MIXER_PROBE_FILES:
        if name not in present:
            problems.add(rel(root, logs), f"probe-log package is missing {name}")
        elif name != "stderr.txt" and (logs / name).stat().st_size == 0:
            problems.add(rel(root, logs / name), "probe-log file is empty")
    for name in sorted(present - set(MIXER_PROBE_FILES)):
        problems.add(rel(root, logs / name), "unexpected file in a probe-log package")
    for p in logs.iterdir():
        if p.is_dir():
            problems.add(rel(root, p), "unexpected directory in a probe-log package")
    return logs


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
    git = env.get("git")
    commit = git.get("commit") if isinstance(git, dict) else None
    if not isinstance(commit, str) or not commit.startswith(rid.split("-")[2]):
        problems.add(where_js, f"environment.git.commit {commit!r} does not match the sha in the record id")
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
    records = exp_dir / "records"
    claimed: set[str] = set()
    if records.is_dir():
        for stem, files in record_pairs(problems, root, records).items():
            check_mixer_record(problems, root, exp_dir, stem, files, claimed)
    logs_root = exp_dir / "probe-logs"
    if logs_root.is_dir():
        for p in sorted(logs_root.iterdir()):
            if not (p.is_dir() and RECORD_ID_RE.match(p.name)):
                problems.add(rel(root, p), "probe-logs entry is not a <YYYYMMDD>-<HHMMSS>-<git-sha>/ run directory")
            elif p.name not in claimed:
                problems.add(rel(root, p), "probe-log package belongs to no record (orphan or incomplete run)")
    for sub in ("corners", "netlist-snapshots", PASSIVE_PACKAGES):
        if (exp_dir / sub).exists():
            problems.add(rel(root, exp_dir / sub), f"{sub}/ is not part of the mixer-nf-method evidence layout")
