"""evidence_checks.lna_headroom: split out of check_evidence_formats.py (issue #163); no rule changes."""

from __future__ import annotations

import re
from pathlib import Path

from .common import Problems, has_section, load_json_object, read_gzip_text, rel
from .passive_p1 import PASSIVE_PACKAGES


# ---------------------------------------------------------------------------
# lna-headroom (sim/lna-headroom/run.py, issue #123)
# ---------------------------------------------------------------------------

HEADROOM_BENCH = "lna-headroom"
HEADROOM_RECORD_FILE_RE = re.compile(r"^(\d{8}-\d{6}-[0-9a-f]{7,40})(\.md|\.json|-sweeps\.json\.gz)$")
HEADROOM_STATUSES = ("COLLECTED", "CONTROLS_FAILED", "BASELINE_NOT_REPRODUCED")
HEADROOM_OUTCOMES = ("stress_valid_p1db_meets_row8", "stress_valid_p1db_below_row8", "headroom_improved_p1db_undetermined",
                     "no_feasible_candidate", "BASELINE_NOT_REPRODUCED",
                     # stage 2 (issue #132): refinement outcome classes
                     "refined_stress_valid_p1db_meets_row8", "refined_stress_valid_p1db_below_row8",
                     "refined_converged_p1db_still_bounded", "refined_unconverged", "refinement_invalid")


def check_lna_headroom(problems: Problems, root: Path, exp_dir: Path) -> None:
    """Structure and honesty of the screening records: files, ids, the frozen plan, one log per request, and
    that the record claims no spec row and states the unchanged-limit scope. Verdict re-derivation is
    ``python3 sim/lna-headroom/run.py verify`` (needs no simulator)."""
    plan_path = exp_dir / "testbench" / "plan.json"
    if not plan_path.is_file():
        problems.add(rel(root, exp_dir), "lna-headroom has no testbench/plan.json declaration")
        return
    declared = load_json_object(problems, root, plan_path) or {}
    ref = declared.get("refinement") or {}
    table = [c.get("id") for c in (declared.get("candidates") or {}).get("table", [])]
    # The stage a record belongs to is the RECORD's own ("stage": 1/2), not the current plan: plan
    # version 2 (issue #132) refines the stage-1 shortlist and must not re-key the stage-1 records.
    ref_cand_ids = list(ref.get("candidates") or [])
    stage2_keys = ["control_one", "control_two"]
    for cid in ref_cand_ids:
        stage2_keys += [f"{cid}_one", f"{cid}_two", f"sparam_{cid}"]

    def keyset_for(rec):
        if rec is not None and rec.get("stage") == 2 and ref:
            return stage2_keys, ref_cand_ids, True
        return ["control"] + table, [k for k in table], False
    records = exp_dir / "records"
    ids: set[str] = set()
    if records.is_dir():
        groups: dict[str, set[str]] = {}
        for p in sorted(records.iterdir()):
            m = HEADROOM_RECORD_FILE_RE.match(p.name)
            if not m:
                problems.add(rel(root, p), "unexpected file in lna-headroom records/ (only <id>.md, <id>.json, <id>-sweeps.json.gz)")
                continue
            groups.setdefault(m.group(1), set()).add(m.group(2))
        for rid, parts in sorted(groups.items()):
            if ".md" not in parts:
                problems.add(rel(root, records), f"evidence for {rid} belongs to no record (no {rid}.md)")
                continue
            ids.add(rid)
            for ext in (".json", "-sweeps.json.gz"):
                if ext not in parts:
                    problems.add(rel(root, records / f"{rid}.md"), f"record has no {rid}{ext}")
            md = (records / f"{rid}.md").read_text(encoding="utf-8", errors="replace")
            if md.splitlines()[:1] != [f"# {HEADROOM_BENCH} record {rid}"]:
                problems.add(rel(root, records / f"{rid}.md"), f"first line must be '# {HEADROOM_BENCH} record {rid}'")
            for sec in ("Declaration", "Controls and baseline reproduction", "DC voltage allocation",
                        "Gain versus stress tradeoff", "Provenance and raw artifacts"):
                if not has_section(md, sec) and f"## {sec}" not in md:
                    problems.add(rel(root, records / f"{rid}.md"), f"missing required section '## {sec}'")
            js = records / f"{rid}.json"
            rec = load_json_object(problems, root, js) if js.is_file() else None
            keys, cand_ids, stage2 = keyset_for(rec)
            if rec is not None:
                if rec.get("record_id") != rid:
                    problems.add(rel(root, js), f"JSON record_id {rec.get('record_id')!r} != {rid!r}")
                if rec.get("status") not in HEADROOM_STATUSES or f"- **Status: {rec.get('status')}**" not in md:
                    problems.add(rel(root, js), f"status {rec.get('status')!r} invalid or not stated in the Markdown")
                if rec.get("spec_rows_claimed_met") != []:
                    problems.add(rel(root, js), "spec_rows_claimed_met must be []")
                oc = (rec.get("ranking") or {}).get("outcome_class")
                if oc not in HEADROOM_OUTCOMES or f"`{oc}`" not in md:
                    problems.add(rel(root, js), f"ranking.outcome_class {oc!r} invalid or not stated in the Markdown")
                if sorted((rec.get("candidates") or {}) ) != sorted(cand_ids):
                    problems.add(rel(root, js), "record does not publish every declared candidate of the frozen plan (rejected ones must stay visible)")
            snap = exp_dir / "netlist-snapshots" / rid
            logs = exp_dir / "corners" / rid
            sp = snap / "plan.json"
            if not sp.is_file():
                problems.add(rel(root, snap), "snapshot has no plan.json")
            else:
                if rec is not None and rec.get("plan_declaration") != load_json_object(problems, root, sp):
                    problems.add(rel(root, sp), "frozen plan differs from the record's plan_declaration")
            for k in keys:
                for f in (snap / f"body_{k}.spice", snap / f"request_{k}.json", snap / f"report_{k}.json", snap / f"variant_{k}.spice"):
                    if f.name.startswith("variant_") and (k == "control" or k.startswith(("control_", "sparam_")) or k not in table):
                        continue
                    if not f.is_file():
                        problems.add(rel(root, f), "missing frozen evidence file")
                if not (logs / f"{k}.log.gz").is_file():
                    problems.add(rel(root, logs / f"{k}.log.gz"), "missing raw log")
                else:
                    read_gzip_text(problems, root, logs / f"{k}.log.gz")
            if ref and stage2:
                for f in ("sparam_fixture.spice", "sparam_tb.json"):
                    if not (snap / f).is_file():
                        problems.add(rel(root, snap / f), "missing frozen small-signal reference")
                for cid in cand_ids:
                    if not (snap / f"variant_{cid}.spice").is_file():
                        problems.add(rel(root, snap / f"variant_{cid}.spice"), "missing frozen evidence file")
    for sub in ("corners", "netlist-snapshots"):
        d = exp_dir / sub
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.name not in ids:
                    problems.add(rel(root, p), f"{sub} entry belongs to no record in this experiment (orphan evidence)")
    for sub in ("probe-logs", PASSIVE_PACKAGES):
        if (exp_dir / sub).exists():
            problems.add(rel(root, exp_dir / sub), f"{sub}/ is not part of the {HEADROOM_BENCH} evidence layout")
