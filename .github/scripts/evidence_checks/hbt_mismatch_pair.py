"""evidence_checks.hbt_mismatch_pair: the Monte Carlo mismatch-pair METHOD probe
(sim/hbt-mismatch-pair/run_probe.py, issue #186).

Scope of the checks: the record is and stays a NON-CLAIMING method record. It
may never carry a spec-row verdict, never move `spec/row-coverage.json` row
15, and its status must follow from the gates its own JSON sidecar declares.
No simulator, no PDK: everything here reads committed text/JSON.
"""

from __future__ import annotations

from pathlib import Path

from .common import PAIR_RE, Problems, load_json_object, record_pairs, rel

#: Mirrors mcpair.STATUSES (the checker is stdlib-only and imports nothing
#: from sim/); keep in sync.
MC_STATUSES = (
    "MC_METHOD_WORKS",
    "MC_METHOD_CONTROL_FAIL",
    "MC_METHOD_REPRODUCIBILITY_FAIL",
    "MC_LOCAL_AGREEMENT_FAIL",
)
CONTROL_GATES = ("nominal_exact", "stat_global_cancels", "mismatch_sampled")
SCOPE_PREFIX = "- **Scope: METHOD only.**"
VERDICT_WORDS = ("measured_pass", "measured_fail", "placeholder_circuit",
                 "device_level_only", "method_absent")


def check_mcpair_record(problems: Problems, root: Path, exp_dir: Path, stem: str,
                        files: dict[str, Path], claimed_logs: set[str]) -> None:
    md_path, js_path = files.get("md"), files.get("json")
    if md_path is None or js_path is None:
        return
    where_md, where_js = rel(root, md_path), rel(root, js_path)
    m = PAIR_RE.match(md_path.name)
    assert m is not None
    rid, status = m.group(1), m.group(2)
    if status not in MC_STATUSES:
        problems.add(where_md, f"status {status!r} is not one of {', '.join(MC_STATUSES)}")
        return

    md = md_path.read_text(encoding="utf-8", errors="replace")
    first = md.splitlines()[0] if md.strip() else ""
    if first != f"# hbt-mismatch-pair record {stem}":
        problems.add(where_md, f"first line must be '# hbt-mismatch-pair record {stem}', found {first[:80]!r}")
    if f"- **Status: {status}**" not in md:
        problems.add(where_md, f"Markdown does not state '- **Status: {status}**'")
    if not md.lstrip().startswith(f"# hbt-mismatch-pair record {stem}\n\n- **Status:"):
        problems.add(where_md, "record must open with the title, then the Status line")
    if SCOPE_PREFIX not in md:
        problems.add(where_md,
                     f"Markdown carries no '{SCOPE_PREFIX}' non-claiming scope line "
                     "(this bench is method evidence only)")
    for word in VERDICT_WORDS:
        if f"- **Verdict: {word}" in md or f'"verdict": "{word}"' in js_text(js_path):
            problems.add(where_md if f"- **Verdict: {word}" in md else where_js,
                         f"a method record never carries a spec verdict ({word!r})")
    if "probe-logs/" not in md:
        problems.add(where_md, "Markdown does not reference its probe-logs/ package")

    rec = load_json_object(problems, root, js_path)
    if rec is None:
        return
    if rec.get("status") != status:
        problems.add(where_js, f"JSON status {rec.get('status')!r} disagrees with the filename ({status!r})")
    if rec.get("scope") != "method-only; no spec-row evidence":
        problems.add(where_js, "JSON scope must be the non-claiming 'method-only; no spec-row evidence'")
    if "verdict" in rec:
        problems.add(where_js, "a method record never carries a verdict field")

    gates = rec.get("gates")
    if not isinstance(gates, dict):
        problems.add(where_js, "JSON 'gates' is missing or not an object")
    else:
        if status == "MC_METHOD_WORKS":
            for g in CONTROL_GATES:
                if gates.get(g) is not True:
                    problems.add(where_js, f"status MC_METHOD_WORKS requires gate {g!r} true")
            if gates.get("reproducibility_max_rel") is None:
                problems.add(where_js, "status MC_METHOD_WORKS requires a fixed-seed rerun "
                             "(reproducibility_max_rel), not a skipped leg")
            if gates.get("local_vs_batch_max_rel") is None:
                problems.add(where_js, "status MC_METHOD_WORKS requires the local agreement leg "
                             "(local_vs_batch_max_rel), not a skipped leg")
        if status in ("MC_METHOD_CONTROL_FAIL",) and not any(
                gates.get(g) is False for g in CONTROL_GATES):
            problems.add(where_js, "status MC_METHOD_CONTROL_FAIL but no control gate is false")

    # The probe-log package: request + body + per-sample values must exist and
    # the record must cite them; the raw out_*/ trees are scratch (gitignored).
    logs = exp_dir / "probe-logs" / rid
    claimed_logs.add(rid)
    if not logs.is_dir():
        problems.add(where_js, f"probe-log package sim/{exp_dir.name}/probe-logs/{rid}/ does not exist")
        return
    present = {p.name for p in logs.iterdir()}
    for name in ("pair_body.spice", "request_mc.json", "request_local.json", "stats.json"):
        if name not in present:
            problems.add(rel(root, logs), f"probe-log package is missing {name}")
    for name in ("samples_mc.json",):
        if name not in present:
            problems.add(rel(root, logs), f"probe-log package is missing {name} "
                         "(the per-sample values are the committed evidence)")


def js_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def check_hbt_mismatch_pair(problems: Problems, root: Path, exp_dir: Path) -> None:
    """Adapter entry: records/ + probe-logs/ packages of the mismatch-pair probe."""
    claimed_logs: set[str] = set()
    records = exp_dir / "records"
    if records.is_dir():
        for stem, files in record_pairs(problems, root, records).items():
            check_mcpair_record(problems, root, exp_dir, stem, files, claimed_logs)
    # any probe-logs dir no record claims is orphan scratch (e.g. a --no-write
    # validation run) -- it must not linger in the committed tree
    pl = exp_dir / "probe-logs"
    if pl.is_dir():
        for d in sorted(pl.iterdir()):
            if d.is_dir() and d.name not in claimed_logs:
                problems.add(rel(root, d),
                             "probe-log package belongs to no record in records/ (commit it "
                             "with its record, or do not commit it at all)")
