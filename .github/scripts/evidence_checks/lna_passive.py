"""evidence_checks.lna_passive: the sim/lna-passive-study bench (issue #340).

Stored-evidence layout (issue #226): git keeps ``records/<id>.md`` (with the
``## Stored evidence`` table the store appends), the ``records/<id>.json``
sidecar and ``manifests/artifacts/lna-passive-study-<id>.manifest.json``; the
raw bytes (per-cell logs, generated bodies/requests/reports, frozen deck
copies) live in the artifact store. The variant DUT decks themselves are bench
INPUTS and stay committed under ``testbench/variants/``.

Checked here (format, provenance and honesty only -- the science is re-derived
by ``python3 sim/lna-passive-study/run.py verify``, which needs no simulator):

* the frozen ``testbench/plan.json`` declaration exists and its scope states
  the non-claiming posture (IDEAL inductors, no spec row, selects nothing,
  comparative deltas only);
* every record's Markdown/JSON pair agrees (status, record id, variants), the
  status is in the study's vocabulary and stated in the Markdown, and
  ``spec_rows_claimed_met`` is ``[]``;
* every published variant is one the frozen plan declares, and the committed
  variant deck's sha256 matches the sidecar's;
* a stored-form record (``## Stored evidence`` section) names a manifest whose
  entries are exactly the table rows, include one log per declared cell of the
  plan's grid for the control and every published variant, and the snapshot
  package (bodies/requests/reports per request, decks, declarations);
* no committed bytes under ``corners/``/``netlist-snapshots/`` and no foreign
  evidence directories.
"""

from __future__ import annotations

import re
from pathlib import Path

from .artifact_manifests import load_manifest, stored_table, MANIFEST_DIR
from .common import Problems, rel

BENCH = "lna-passive-study"
STATUSES = ("COLLECTED", "CONTROLS_FAILED", "PREMATCH_FAILED")
RECORD_FILE_RE = re.compile(r"^(\d{8}-\d{6}-[0-9a-f]{7,40})(\.md|\.json)$")
REQUIRED_SECTIONS = (
    "Declaration",
    "Controls and method identity",
    "Comparative deltas at the row bound cells (variant - control)",
    "Worst-case deltas per variant (over the bound cells)",
    "Provenance and stored evidence",
    "Stored evidence",
)
CLAIM_NEEDLES = ("IDEAL", "No spec row is claimed", "COMPARATIVE DELTAS ONLY")


def _plan_variant_ids(plan: dict) -> list[str]:
    return [v.get("id") for v in plan.get("variants", [])]


def _expected_log_names(plan: dict, variants: list[str], rid: str) -> list[str]:
    """One corner log per declared cell: {deck}__{process}__{temp}C__{vdd}V."""
    processes = [c["name"] for c in plan.get("corner_axis", [])]
    temps = plan.get("temperatures_c", [])
    supplies = plan.get("supplies_v", [])
    names = []
    for deck in ["V00"] + list(variants):
        for proc in processes:
            for temp in temps:
                t = f"{temp:g}"
                for vdd in supplies:
                    names.append(f"corners/{rid}/%s__{proc}__{t}C__{vdd:.2f}V.log" % deck)
    return names


def _snapshot_names(plan: dict, variants: list[str], rid: str) -> list[str]:
    names = [
        f"netlist-snapshots/{rid}/plan.json",
        f"netlist-snapshots/{rid}/prematch.json",
        f"netlist-snapshots/{rid}/control_V00.spice",
    ]
    for vid in variants:
        names.append(f"netlist-snapshots/{rid}/variant_{vid}.spice")
        for vdd in plan.get("supplies_v", []):
            key = f"{vid}_{vdd:.2f}v"
            names.append(f"netlist-snapshots/{rid}/body_{key}.spice")
            names.append(f"netlist-snapshots/{rid}/request_{key}.json")
            names.append(f"netlist-snapshots/{rid}/report_{key}.json")
    for vdd in plan.get("supplies_v", []):
        key = f"V00_{vdd:.2f}v"
        names += [
            f"netlist-snapshots/{rid}/body_{key}.spice",
            f"netlist-snapshots/{rid}/request_{key}.json",
            f"netlist-snapshots/{rid}/report_{key}.json",
        ]
    names.append(f"netlist-snapshots/{rid}/body_probe.spice")
    names.append(f"netlist-snapshots/{rid}/request_probe.json")
    names.append(f"netlist-snapshots/{rid}/report_probe.json")
    names.append(f"netlist-snapshots/{rid}/body_grid.spice")
    names.append(f"netlist-snapshots/{rid}/request_grid.json")
    names.append(f"netlist-snapshots/{rid}/report_grid.json")
    names.append(f"records/{rid}-cells.json.gz")
    return names


#: The prematch probe/grid raw decks are optional snapshot members: the frozen
#: OUTCOME (testbench/prematch.json, always required) is what the collection
#: consumes; the probe jobs ran in the study's development iteration and ride
#: the manifest only when their reports were part of the collected run.
OPTIONAL_SNAPSHOT_SUFFIXES = (
    "body_probe.spice", "request_probe.json", "report_probe.json",
    "body_grid.spice", "request_grid.json", "report_grid.json",
)


def check_lna_passive(problems: Problems, root: Path, exp_dir: Path) -> None:
    plan_path = exp_dir / "testbench" / "plan.json"
    if not plan_path.is_file():
        problems.add(rel(root, exp_dir), "lna-passive-study has no testbench/plan.json declaration")
        return
    try:
        import json
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        problems.add(rel(root, plan_path), f"plan.json is not valid JSON: {exc}")
        return
    scope = plan.get("scope", "")
    for needle in ("IDEAL", "no spec row", "selects nothing", "comparative deltas only"):
        if needle.lower() not in scope.lower():
            problems.add(rel(root, plan_path), f"plan scope does not state {needle!r}")
    if plan.get("record", {}).get("spec_rows_claimed_met") != []:
        problems.add(rel(root, plan_path), "plan.record.spec_rows_claimed_met must be []")
    if plan.get("baseline_record") != "sim/lna-sparam-nf/records/20261114-211735-8a92c6e.md":
        problems.add(rel(root, plan_path), "plan baseline_record must be the post-#79 record")

    records = exp_dir / "records"
    ids: set[str] = set()
    if records.is_dir():
        import json
        for p in sorted(records.iterdir()):
            m = RECORD_FILE_RE.match(p.name)
            if not m:
                problems.add(rel(root, p), "unexpected file in lna-passive-study records/")
                continue
            ids.add(m.group(1))
        for rid in sorted(ids):
            md_path, js_path = records / f"{rid}.md", records / f"{rid}.json"
            for need in (md_path, js_path):
                if not need.is_file():
                    problems.add(rel(root, records), f"record {rid} lacks its {need.suffix} half")
            if not (md_path.is_file() and js_path.is_file()):
                continue
            md = md_path.read_text(encoding="utf-8", errors="replace")
            where = rel(root, md_path)
            try:
                rec = json.loads(js_path.read_text(encoding="utf-8"))
            except ValueError as exc:
                problems.add(rel(root, js_path), f"not valid JSON: {exc}")
                continue
            if md.splitlines()[:1] != [f"# {BENCH} record {rid}"]:
                problems.add(where, f"first line must be '# {BENCH} record {rid}'")
            for sec in REQUIRED_SECTIONS:
                if f"## {sec}" not in md:
                    problems.add(where, f"missing required section '## {sec}'")
            if rec.get("record_id") != rid:
                problems.add(rel(root, js_path), f"JSON record_id {rec.get('record_id')!r} != {rid!r}")
            if rec.get("status") not in STATUSES or f"- **Status: {rec.get('status')}**" not in md:
                problems.add(rel(root, js_path), f"status {rec.get('status')!r} invalid or not stated in the Markdown")
            if rec.get("spec_rows_claimed_met") != []:
                problems.add(rel(root, js_path), "spec_rows_claimed_met must be []")
            claim = rec.get("claim", "")
            for needle in CLAIM_NEEDLES:
                if needle not in claim:
                    problems.add(rel(root, js_path), f"claim must state {needle!r}")
            variants = rec.get("variants", [])
            declared = _plan_variant_ids(plan)
            if not set(variants) <= set(declared):
                problems.add(rel(root, js_path), "publishes variants outside the frozen plan")
            for vid in variants:
                folder = exp_dir / "testbench" / "variants"
                if vid == "V04" and rec.get("plan_declaration", {}).get("plan_version") == 1:
                    folder = folder / "v1"
                deck = folder / f"{vid}.spice"
                if not deck.is_file():
                    problems.add(rel(root, deck), f"committed variant deck of {vid} is missing")
                elif rec.get("variant_deck_sha256", {}).get(vid) != _sha(deck):
                    problems.add(where, f"{vid}: deck sha256 disagrees with the sidecar")
            # the stored-evidence manifest must cover exactly the declared grid
            mpath = root / MANIFEST_DIR / f"{BENCH}-{rid}.manifest.json"
            if not mpath.is_file():
                problems.add(where, f"stored-evidence record but {rel(root, mpath)} is missing")
                continue
            manifest = load_manifest(problems, root, mpath)
            if manifest is None:
                continue
            names = {e["name"]: e for e in manifest["entries"]}
            table = stored_table(md)
            for name, e in names.items():
                if not name.startswith(f"sim/{BENCH}/"):
                    problems.add(rel(root, mpath), f"entry {name!r} is outside sim/{BENCH}/")
                row = table.get(name)
                if row is None:
                    problems.add(where, f"Stored evidence table has no row for manifest entry {name!r}")
                elif row != (e["size"], e["sha256"]):
                    problems.add(where, f"Stored evidence row for {name!r} disagrees with the manifest")
            for name in sorted(set(table) - set(names)):
                problems.add(where, f"Stored evidence row {name!r} has no manifest entry")
            prefix = f"sim/{BENCH}/"
            expected_logs = [prefix + n
                             for n in _expected_log_names(plan, variants, rid)]
            have_logs = {n[len(prefix + "corners/"):-len(".log")]
                         for n in names if n.startswith(prefix + "corners/") and n.endswith(".log")}
            want_logs = {n[len(prefix + "corners/"):-len(".log")] for n in expected_logs}
            for miss in sorted(want_logs - have_logs):
                problems.add(rel(root, mpath), f"no stored log for declared cell {miss}")
            for extra in sorted(have_logs - want_logs):
                problems.add(rel(root, mpath), f"stored log {extra} is not a declared cell")
            for snap in _snapshot_names(plan, variants, rid):
                if snap.rsplit("/", 1)[-1] in OPTIONAL_SNAPSHOT_SUFFIXES:
                    continue
                if prefix + snap not in names:
                    problems.add(rel(root, mpath), f"no stored entry for {snap}")
            if rec.get("status") == "COLLECTED" and not rec.get("gates", {}).get("pass"):
                problems.add(rel(root, js_path), "status COLLECTED but the sidecar's gates did not pass")
    for sub in ("corners", "netlist-snapshots", "probe-logs", "solver-artifacts"):
        if (exp_dir / sub).exists():
            problems.add(rel(root, exp_dir / sub), f"{sub}/ is not part of the {BENCH} evidence layout "
                          "(stored evidence lives in the artifact store)")


def _sha(path: Path) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
