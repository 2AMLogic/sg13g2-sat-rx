"""evidence_checks.mixer_pra: split out of check_evidence_formats.py (issue #163); no rule changes."""

from __future__ import annotations

import re
from pathlib import Path

from .common import (PAIR_RE, Problems, RECORD_ID_RE, git, has_section, load_json_object, need_sha256, need_str, record_pairs, rel)
from .mixer_nf import check_probe_log_package
from .passive_p1 import PASSIVE_PACKAGES


# ---------------------------------------------------------------------------
# mixer-pumped-rf-admittance (sim/mixer-pumped-rf-admittance/run_probe.py, issue #111)
# ---------------------------------------------------------------------------

PRA_BENCH = "mixer-pumped-rf-admittance"
PRA_STATUSES = ("SCALAR_ADEQUATE", "MATRIX_REQUIRED", "INCONCLUSIVE", "CAPABILITY_UNAVAILABLE")
#: every phrase must appear in the JSON 'scope' (pumped.SCOPE)
PRA_SCOPE_PHRASES = ("method-feasibility evidence only", "no row-5 compliance claim",
                     "no mixer or cascade NF claim", "DR-0004 is neither ratified nor reversed")
#: every marker must appear verbatim in the Markdown (run_probe.SCOPE_MD_MARKERS)
PRA_MD_MARKERS = ("- **Scope: method-feasibility evidence only.**",
                  "**no claim of `spec/target-spec.md` row 5 compliance**")
PRA_THRESHOLDS = ("control_mag_rel_tol", "control_phase_tol_deg", "control_null_rel_tol", "cond_max",
                  "halving_rel_tol", "window_rel_tol", "timestep_rel_tol", "response_to_baseline_min",
                  "kappa_scalar_max")
#: DUT numerical check -> (value field, threshold key, comparison)
PRA_DUT_CHECKS = {
    "halving": ("rel_change", "halving_rel_tol", "le"),
    "window": ("rel_change", "window_rel_tol", "le"),
    "timestep": ("rel_change", "timestep_rel_tol", "le"),
    "conditioning": ("cond_max_over_sets", "cond_max", "le"),
    "response_to_baseline": ("min_ratio", "response_to_baseline_min", "ge"),
}
PRA_ELEMENTS = ("uu", "ul", "lu", "ll")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _cabs(v: object) -> float | None:
    if isinstance(v, list) and len(v) == 2 and all(_num(x) for x in v):
        return abs(complex(v[0], v[1]))
    return None


def pra_expected_status(ctl_pass: bool, checks_pass: bool, kappa: float, u: float, ks: float) -> str:
    if not ctl_pass or not checks_pass:
        return "INCONCLUSIVE"
    if kappa + u < ks:
        return "SCALAR_ADEQUATE"
    if kappa - u > ks:
        return "MATRIX_REQUIRED"
    return "INCONCLUSIVE"


def check_pra_evaluation(problems: Problems, where: str, status: str, rec: dict) -> dict | None:
    """Thresholds, controls, DUT checks and status-follows-from-numbers. Never the science."""
    thr = rec.get("thresholds")
    if not isinstance(thr, dict) or set(thr) != set(PRA_THRESHOLDS) or not all(
            _num(thr[k]) and thr[k] > 0 for k in thr):
        problems.add(where, f"JSON 'thresholds' must carry exactly {', '.join(PRA_THRESHOLDS)} as positive numbers")
        thr = None
    prov = rec.get("thresholds_provenance")
    if not isinstance(prov, dict):
        problems.add(where, "JSON 'thresholds_provenance' is missing")
    else:
        need_sha256(problems, where, prov.get("sha256"), "thresholds_provenance.sha256")
        if not isinstance(prov.get("commit"), str) or not SHA1_RE.match(prov["commit"]):
            problems.add(where, "thresholds_provenance.commit must name the commit that declared the thresholds")
        if prov.get("dirty") is not False:
            problems.add(where, "thresholds_provenance.dirty must be false: thresholds are declared (committed) "
                         "before the DUT result they judge")
    if rec.get("classification") != status:
        problems.add(where, f"JSON 'classification' {rec.get('classification')!r} does not match status {status!r}")
    ev = rec.get("evaluation")
    if not isinstance(ev, dict):
        problems.add(where, "JSON 'evaluation' is missing or not an object")
        return None
    ctl = ev.get("controls")
    cchecks = ctl.get("checks") if isinstance(ctl, dict) else None
    ctl_pass = ctl.get("pass") if isinstance(ctl, dict) else None
    if not isinstance(ctl_pass, bool) or not isinstance(cchecks, dict) or not cchecks:
        problems.add(where, "evaluation.controls needs a bool 'pass' and a non-empty 'checks' object")
        return ev
    if ctl_pass != all(isinstance(c, dict) and c.get("pass") is True for c in cchecks.values()):
        problems.add(where, "evaluation.controls.pass disagrees with its individual checks")
    for fx in ("rc", "md"):
        if not any(n.startswith(fx + ".") for n in cchecks):
            problems.add(where, f"evaluation.controls has no '{fx}.*' known-answer checks")
    if ev.get("status") != status:
        problems.add(where, f"evaluation.status {ev.get('status')!r} does not match status {status!r}")
    dut = ev.get("dut")
    if not isinstance(dut, dict):
        problems.add(where, "evaluation.dut is missing or not an object")
        return ev
    y = dut.get("y")
    mags = {e: _cabs(y.get(e)) for e in PRA_ELEMENTS} if isinstance(y, dict) else {}
    if not isinstance(y, dict) or set(y) != set(PRA_ELEMENTS) or any(m is None for m in mags.values()):
        problems.add(where, f"evaluation.dut.y must carry {', '.join(PRA_ELEMENTS)} as [re, im] pairs")
        return ev
    kappa, u = dut.get("kappa"), dut.get("kappa_uncertainty")
    if not _num(kappa) or not _num(u):
        problems.add(where, "evaluation.dut.kappa / kappa_uncertainty must be numbers")
        return ev
    if mags["uu"] and mags["ll"]:
        k2 = max(mags["ul"] / mags["uu"], mags["lu"] / mags["ll"])
        if abs(k2 - kappa) > 1e-9 * max(1.0, k2):
            problems.add(where, f"evaluation.dut.kappa {kappa!r} does not follow from evaluation.dut.y ({k2!r})")
    checks = dut.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(PRA_DUT_CHECKS):
        problems.add(where, f"evaluation.dut.checks must be exactly {', '.join(PRA_DUT_CHECKS)}")
        return ev
    for name, (field, key, cmp) in PRA_DUT_CHECKS.items():
        c = checks[name]
        if not isinstance(c, dict) or not _num(c.get(field)) or not isinstance(c.get("pass"), bool):
            problems.add(where, f"evaluation.dut.checks[{name!r}] needs a numeric {field!r} and a bool 'pass'")
            continue
        if thr is not None:
            ok = c[field] <= thr[key] if cmp == "le" else c[field] >= thr[key]
            if ok != c["pass"]:
                problems.add(where, f"evaluation.dut.checks[{name!r}].pass={c['pass']} contradicts {field}="
                             f"{c[field]!r} against thresholds.{key}={thr[key]!r}")
    checks_pass = all(isinstance(c, dict) and c.get("pass") is True for c in checks.values())
    if dut.get("numerics_pass") is not checks_pass:
        problems.add(where, "evaluation.dut.numerics_pass disagrees with its checks")
    if thr is not None:
        exp = pra_expected_status(ctl_pass, checks_pass, kappa, u, thr["kappa_scalar_max"])
        if exp != status:
            problems.add(where, f"status {status} does not follow from the recorded controls, numerical checks, "
                         f"kappa and thresholds (expected {exp})")
    return ev


def check_pra_record(problems: Problems, root: Path, exp_dir: Path, stem: str, files: dict[str, Path],
                     claimed_logs: set[str]) -> None:
    md_path, js_path = files.get("md"), files.get("json")
    if md_path is None or js_path is None:
        return
    where_md, where_js = rel(root, md_path), rel(root, js_path)
    m = PAIR_RE.match(md_path.name)
    assert m is not None
    rid, status = m.group(1), m.group(2)
    if status not in PRA_STATUSES:
        problems.add(where_md, f"status {status!r} is not one of {', '.join(PRA_STATUSES)}")
        return
    md = md_path.read_text(encoding="utf-8", errors="replace")
    first = md.splitlines()[0] if md.strip() else ""
    if first != f"# {PRA_BENCH} record {stem}":
        problems.add(where_md, f"first line must be '# {PRA_BENCH} record {stem}', found {first[:80]!r}")
    if f"- **Status: {status}**" not in md:
        problems.add(where_md, f"Markdown does not state '- **Status: {status}**'")
    for marker in PRA_MD_MARKERS:
        if marker not in md:
            problems.add(where_md, f"missing the scope disclaimer {marker!r}")
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
    if scope is not None:
        for phrase in PRA_SCOPE_PHRASES:
            if phrase not in scope:
                problems.add(where_js, f"JSON 'scope' does not carry the disclaimer {phrase!r}")
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
    for field in ("placeholder_sha256", "pdk_artifact_sha256"):
        need_sha256(problems, where_js, env.get(field), f"environment.{field}")

    if status == "CAPABILITY_UNAVAILABLE":
        need_str(problems, where_js, rec, "failed_check")
        for key in ("evaluation", "probe_logs", "classification"):
            if key in rec:
                problems.add(where_js, f"CAPABILITY_UNAVAILABLE record carries '{key}' "
                             "(no probe ran; it cannot establish anything about the method)")
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
    ev = check_pra_evaluation(problems, where_js, status, rec)

    logs = check_probe_log_package(problems, root, exp_dir, rid, rec, md, where_js, where_md, claimed_logs)
    if logs is None:
        return
    inv_path = logs / "inventory.json"
    if inv_path.is_file():
        inv = load_json_object(problems, root, inv_path)
        if inv is not None:
            if not isinstance(inv.get("parsed"), dict) or not isinstance(inv.get("evaluation"), dict):
                problems.add(rel(root, inv_path), "inventory.json needs 'parsed' and 'evaluation' objects")
            elif ev is not None and inv["evaluation"] != ev:
                problems.add(rel(root, inv_path), "inventory.json 'evaluation' differs from the record's "
                             "JSON 'evaluation' (record and frozen log disagree)")


def check_mixer_pumped_rf_admittance(problems: Problems, root: Path, exp_dir: Path) -> None:
    records = exp_dir / "records"
    claimed: set[str] = set()
    if records.is_dir():
        for stem, files in record_pairs(problems, root, records).items():
            check_pra_record(problems, root, exp_dir, stem, files, claimed)
    logs_root = exp_dir / "probe-logs"
    if logs_root.is_dir():
        for p in sorted(logs_root.iterdir()):
            if not (p.is_dir() and RECORD_ID_RE.match(p.name)):
                problems.add(rel(root, p), "probe-logs entry is not a <YYYYMMDD>-<HHMMSS>-<git-sha>/ run directory")
            elif p.name not in claimed:
                problems.add(rel(root, p), "probe-log package belongs to no record (orphan or incomplete run)")
    for sub in ("corners", "netlist-snapshots", PASSIVE_PACKAGES):
        if (exp_dir / sub).exists():
            problems.add(rel(root, exp_dir / sub), f"{sub}/ is not part of the {PRA_BENCH} evidence layout")
