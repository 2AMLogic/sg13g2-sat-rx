"""evidence_checks.passive_p1: split out of check_evidence_formats.py (issue #163); no rule changes."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .common import (PAIR_RE, Problems, RECORD_ID_RE, has_section, load_json_object, need_sha256, need_str, record_pairs, rel)


# ---------------------------------------------------------------------------
# explicit adapters for non-PVT campaign layouts
# ---------------------------------------------------------------------------
PASSIVE_STATUSES = ("QUALIFIED", "UNCONVERGED", "FIT_FAILED", "CAPABILITY_UNAVAILABLE")
PASSIVE_CONTROLS_STATUSES = ("CONTROLS-PASS", "CONTROLS-FAIL")
MIXER_STATUSES = ("METHOD_VALIDATION", "MODEL_ABSENT", "UNCONVERGED", "CAPABILITY_UNAVAILABLE")
MIXER_PROBE_FILES = ("deck.spice", "stdout.txt", "stderr.txt", "inventory.json")
PASSIVE_SCHEMA = "passive-p1-solver-artifacts/1"
PASSIVE_PACKAGES = "solver-artifacts"
PASSIVE_INCOMPLETE = ".INCOMPLETE"
# Campaign records committed before #58 froze nothing; they stay valid as legacy. Any other
# non-controls passive record must be record_schema 2 with a package (explicit set, not a clock).
LEGACY_PASSIVE_RECORDS = frozenset({"20261009-141515-0e10117-CAPABILITY_UNAVAILABLE"})
_SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")
_PKG_TOP = ("results", "fit", "run_log")
_SOLVES = ("results/inductor_p1", "results/convergence/p1_mesh0p5", "results/convergence/p1_margin400")
_SOLVER_FILES = tuple(p for b in _SOLVES for p in (b + ".s2p", b + "/port_information.json", b + "/run_meta.json"))
_POST_FILES = ("results/p1_metrics.json", "results/p1_lq.csv", "results/p1_deembedded.s2p")
_FIT_FILES = ("fit/p1_fit_parameters.json", "fit/p1_fit_candidate.spice")
_COMPARE_FILES = ("results/p1_compare.json",)
def check_passive_input_hashes(problems: Problems, root: Path, exp_dir: Path, where: str, rec: dict) -> None:
    ih = rec.get("input_hashes")
    files = ih.get("files") if isinstance(ih, dict) else None
    if not isinstance(files, dict) or not files:
        problems.add(where, "JSON 'input_hashes.files' is missing or empty (no input provenance)")
        return
    if not (exp_dir / "INPUTS.json").is_file():
        problems.add(where, f"declared input manifest {rel(root, exp_dir / 'INPUTS.json')} does not exist")
    for name, entry in sorted(files.items()):
        need_sha256(problems, where, entry.get("sha256") if isinstance(entry, dict) else None,
                    f"input_hashes.files[{name!r}].sha256")
        if not (exp_dir / name).is_file():
            problems.add(where, f"declared input {name!r} does not exist under {rel(root, exp_dir)}/")


def safe_package_path(p: object) -> bool:
    if not isinstance(p, str) or not p or p.startswith("/") or "\\" in p or "\x00" in p:
        return False
    return all(_SAFE_COMPONENT_RE.match(c) and c not in (".", "..") for c in p.split("/"))


def passive_required_paths(status: str, stages: list[str], has_compare: bool) -> list[str]:
    """Mirror of sim/passive-p1/scripts/freeze_package.py required_paths() (a test asserts they agree)."""
    st = set(stages)
    if status == "CAPABILITY_UNAVAILABLE":
        return []
    req = list(_SOLVER_FILES) + list(_POST_FILES)
    if "geometry" in st:
        req += ["run_log/geometry_overlay.txt", "run_log/geometry_p1.txt", "run_log/geometry_xor.txt"]
    if "em" in st:
        req.append("run_log/em_p1.txt")
    if "convergence" in st:
        req += ["run_log/em_conv_p1_mesh0p5.txt", "run_log/em_conv_p1_margin400.txt"]
    if "post" in st:
        req.append("run_log/postprocess.txt")
    if status == "FIT_FAILED":
        if "fit" in st:
            req.append("run_log/fit.txt")
        if has_compare:
            req += list(_FIT_FILES) + list(_COMPARE_FILES)
            if "compare" in st:
                req.append("run_log/compare.txt")
    elif status == "QUALIFIED":
        req += list(_FIT_FILES) + list(_COMPARE_FILES)
        req += [f"run_log/{k}.txt" for k in ("fit", "compare") if k in st]
    return sorted(set(req))


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_passive_package(problems: Problems, root: Path, exp_dir: Path, pid: str, status: str, rec: dict,
                          md: str, where_js: str, where_md: str) -> None:
    """record_schema 2: validate the frozen package named by the record (see module docstring)."""
    ap = rec.get("artifact_package")
    expected = f"sim/{exp_dir.name}/{PASSIVE_PACKAGES}/{pid}/"
    if not isinstance(ap, dict):
        problems.add(where_js, "record_schema 2 needs an 'artifact_package' object")
        return
    if ap.get("path") != expected:
        problems.add(where_js, f"artifact_package.path {ap.get('path')!r} must be {expected!r} "
                     "(relative, no traversal, this record's own run id)")
        return
    if ap.get("schema") != PASSIVE_SCHEMA:
        problems.add(where_js, f"artifact_package.schema {ap.get('schema')!r} must be {PASSIVE_SCHEMA!r}")
    if ap.get("manifest") != "manifest.json":
        problems.add(where_js, "artifact_package.manifest must be 'manifest.json'")
    need_sha256(problems, where_js, ap.get("manifest_sha256"), "artifact_package.manifest_sha256")
    if expected not in md:
        problems.add(where_md, f"Markdown does not name its frozen package {expected}")
    if isinstance(ap.get("manifest_sha256"), str) and f"`{ap['manifest_sha256']}`" not in md:
        problems.add(where_md, "Markdown does not carry the JSON artifact_package.manifest_sha256")
    pkg = exp_dir / PASSIVE_PACKAGES / pid
    where_pkg = rel(root, pkg)
    if pkg.is_symlink() or not pkg.is_dir():
        problems.add(where_js, f"declared artifact package {where_pkg}/ does not exist")
        return
    if (pkg / PASSIVE_INCOMPLETE).exists():
        problems.add(where_pkg, f"package carries {PASSIVE_INCOMPLETE}: interrupted/incomplete publication")
    mpath = pkg / "manifest.json"
    if not mpath.is_file() or mpath.is_symlink():
        problems.add(where_pkg, "package has no manifest.json (incomplete publication)")
        return
    if isinstance(ap.get("manifest_sha256"), str) and _sha256_of(mpath) != ap["manifest_sha256"]:
        problems.add(rel(root, mpath), "manifest sha256 does not match the record's artifact_package.manifest_sha256")
    man = load_json_object(problems, root, mpath)
    if man is None:
        return
    where_man = rel(root, mpath)
    if man.get("schema") != PASSIVE_SCHEMA:
        problems.add(where_man, f"manifest schema {man.get('schema')!r} must be {PASSIVE_SCHEMA!r}")
    if man.get("run_id") != pid:
        problems.add(where_man, f"manifest run_id {man.get('run_id')!r} does not match {pid!r}")
    if man.get("status") != status:
        problems.add(where_man, f"manifest status {man.get('status')!r} does not match record status {status!r}")
    stages = rec.get("stages")
    stage_list = stages.split() if isinstance(stages, str) else []
    if man.get("stages") != stage_list:
        problems.add(where_man, "manifest stages disagree with the record's 'stages'")
    files = man.get("files")
    if not isinstance(files, list) or not files:
        problems.add(where_man, "manifest 'files' is missing or empty")
        return
    listed: dict[str, dict] = {}
    for e in files:
        path = e.get("path") if isinstance(e, dict) else None
        if not safe_package_path(path):
            problems.add(where_man, f"unsafe or malformed package path {path!r} (must be a relative, "
                         "traversal-free path of plain components)")
            continue
        if path in listed:
            problems.add(where_man, f"duplicate manifest path {path!r}")
            continue
        if path != "settings.json" and path.split("/")[0] not in _PKG_TOP:
            problems.add(where_man, f"path {path!r} is outside settings.json/{'/'.join(_PKG_TOP)}/")
            continue
        listed[path] = e
        need_sha256(problems, where_man, e.get("sha256"), f"files[{path!r}].sha256")
        if not isinstance(e.get("bytes"), int) or isinstance(e.get("bytes"), bool):
            problems.add(where_man, f"files[{path!r}].bytes is not an integer")
        fp = pkg.joinpath(*path.split("/"))
        if fp.is_symlink() or not fp.is_file():
            problems.add(where_man, f"listed file {path} is missing from the package")
            continue
        if isinstance(e.get("sha256"), str) and _sha256_of(fp) != e["sha256"]:
            problems.add(rel(root, fp), "sha256 does not match the manifest (package bytes were altered)")
        elif isinstance(e.get("bytes"), int) and fp.stat().st_size != e["bytes"]:
            problems.add(rel(root, fp), "size does not match the manifest")
    on_disk = set()
    for p in sorted(pkg.rglob("*")):
        if p.is_symlink():
            problems.add(rel(root, p), "symlink inside a frozen package")
        elif p.is_file():
            on_disk.add(p.relative_to(pkg).as_posix())
    for extra in sorted(on_disk - set(listed) - {"manifest.json", PASSIVE_INCOMPLETE}):
        problems.add(rel(root, pkg / extra), "file in the package is not listed in manifest.json")
    if "settings.json" not in listed:
        problems.add(where_man, "manifest does not list settings.json (stage settings are required)")
    has_compare = isinstance(rec.get("compare"), dict)
    for need in passive_required_paths(status, stage_list, has_compare):
        if need not in listed:
            problems.add(where_man, f"package is incomplete: required stage output {need} is not in the "
                         f"manifest for a {status} record with stages [{' '.join(stage_list)}]")
    if status == "CAPABILITY_UNAVAILABLE":
        solver = [p for p in listed if p.startswith("results/") or p.startswith("fit/")]
        if solver:
            problems.add(where_man, f"CAPABILITY_UNAVAILABLE package carries solver/analysis data ({solver[0]}); "
                         "diagnostics (logs) only")
    # record <-> frozen bytes agreement (the record was derived from the frozen copy)
    for key, relname in (("metrics", "results/p1_metrics.json"), ("compare", "results/p1_compare.json")):
        fp = pkg.joinpath(*relname.split("/"))
        if relname in listed and fp.is_file():
            try:
                frozen = json.loads(fp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                problems.add(rel(root, fp), "packaged JSON is not valid JSON")
                continue
            if frozen != rec.get(key):
                problems.add(where_js, f"record '{key}' differs from the packaged {relname}")
        elif rec.get(key) is not None and relname not in listed:
            problems.add(where_js, f"record carries '{key}' numbers but the package has no {relname}")


def check_passive_record(problems: Problems, root: Path, exp_dir: Path, stem: str, files: dict[str, Path],
                         claimed_packages: set[str]) -> None:
    md_path, js_path = files.get("md"), files.get("json")
    if md_path is None or js_path is None:
        return  # the missing half is already reported by record_pairs
    where_md, where_js = rel(root, md_path), rel(root, js_path)
    m = PAIR_RE.match(md_path.name)
    assert m is not None
    rid, status = m.group(1), m.group(2)
    md = md_path.read_text(encoding="utf-8", errors="replace")
    rec = load_json_object(problems, root, js_path)

    if status.startswith("SYNTHETIC-") or md.lstrip().startswith("> **SYNTHETIC") or (
            rec is not None and rec.get("synthetic") is True):
        problems.add(where_md, "synthetic smoke record inside records/ (SYNTHETIC-* pipeline output is not "
                     "campaign evidence and must be kept out of records/)")
        return
    controls = status in PASSIVE_CONTROLS_STATUSES
    if not controls and status not in PASSIVE_STATUSES:
        problems.add(where_md, f"status {status!r} is not one of "
                     f"{', '.join(PASSIVE_STATUSES + PASSIVE_CONTROLS_STATUSES)}")
        return

    kind = "controls record" if controls else "record"
    first = md.splitlines()[0] if md.strip() else ""
    if first != f"# passive-p1 {kind} {stem}":
        problems.add(where_md, f"first line must be '# passive-p1 {kind} {stem}', found {first[:80]!r}")
    if rec is None:
        return
    if rec.get("record_id") != stem:
        problems.add(where_js, f"JSON record_id {rec.get('record_id')!r} does not match its file name {stem!r}")

    if controls:
        want_pass = status == "CONTROLS-PASS"
        if not isinstance(rec.get("all_pass"), bool):
            problems.add(where_js, "JSON 'all_pass' is missing or not a boolean")
        groups = rec.get("groups")
        if not isinstance(groups, dict) or not groups:
            problems.add(where_js, "JSON 'groups' is missing or empty")
            groups = {}
        results = {}
        for name, grp in groups.items():
            if not isinstance(grp, dict) or not isinstance(grp.get("pass"), bool):
                problems.add(where_js, f"control group {name!r} has no boolean 'pass'")
            else:
                results[name] = grp["pass"]
        if isinstance(rec.get("all_pass"), bool):
            if rec["all_pass"] != want_pass:
                problems.add(where_js, f"all_pass={rec['all_pass']} contradicts status suffix {status}")
            if results and rec["all_pass"] != all(results.values()):
                problems.add(where_js, "all_pass is not the conjunction of the control group results")
        need_str(problems, where_js, rec, "kind")
        need_sha256(problems, where_js, rec.get("fixture_sha256"), "fixture_sha256")
        fixture = rec.get("fixture")
        if not isinstance(fixture, str) or not (exp_dir / fixture).is_file():
            problems.add(where_js, f"declared fixture {fixture!r} does not exist under {rel(root, exp_dir)}/")
        for field in ("ngspice", "numpy"):
            need_str(problems, where_js, rec, field)
        if isinstance(rec.get("limits"), dict) is False:
            problems.add(where_js, "JSON 'limits' is missing")
        overall = "ALL CONTROLS BEHAVED AS REQUIRED" if want_pass else "FAILURE"
        if f"- Overall: **{overall}**" not in md:
            problems.add(where_md, f"Markdown does not state '- Overall: **{overall}**' for status {status}")
        md_groups = dict(re.findall(r"^## (.+?) -- (PASS|FAIL)\s*$", md, re.MULTILINE))
        if set(md_groups) != set(results) or any(md_groups[g] != ("PASS" if results[g] else "FAIL")
                                                   for g in md_groups if g in results):
            problems.add(where_md, "Markdown control sections disagree with the JSON groups/results")
        sha = rec.get("fixture_sha256")
        if isinstance(sha, str) and f"`{sha}`" not in md:
            problems.add(where_md, "Markdown does not carry the JSON fixture_sha256")
        if "**Scope**:" not in md:
            problems.add(where_md, "missing '**Scope**:' statement (controls make no EM claim)")
        return

    # campaign record
    if rec.get("status") != status:
        problems.add(where_js, f"JSON status {rec.get('status')!r} does not match file name status {status!r}")
    if rec.get("synthetic") is not False:
        problems.add(where_js, "JSON 'synthetic' must be false for a campaign record")
    if f"- **Status: {status}**" not in md:
        problems.add(where_md, f"Markdown does not state '- **Status: {status}**'")
    reasons = rec.get("reasons")
    if not isinstance(reasons, list) or not reasons or not all(isinstance(r, str) and r for r in reasons):
        problems.add(where_js, "JSON 'reasons' must be a non-empty list of strings")
    utc = need_str(problems, where_js, rec, "utc")
    if utc is not None:
        mt = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", utc)
        if not mt or "".join(mt.groups()[:3]) + "-" + "".join(mt.groups()[3:]) != rid[:15]:
            problems.add(where_js, f"JSON utc {utc!r} does not match the record id timestamp {rid[:15]!r}")
    digest = rec.get("numerical_digest")
    need_sha256(problems, where_js, digest, "numerical_digest")
    if isinstance(digest, str) and f"`{digest}`" not in md:
        problems.add(where_md, "Markdown does not carry the JSON numerical_digest")
    env = rec.get("environment")
    if not isinstance(env, dict):
        problems.add(where_js, "JSON 'environment' is missing")
    else:
        commit = env.get("git_commit")
        if not isinstance(commit, str) or not commit.startswith(rid.split("-")[2]):
            problems.add(where_js, f"environment.git_commit {commit!r} does not match the sha in the record id")
        for field in ("host", "platform", "python"):
            need_str(problems, where_js, env, field, f"environment.{field}")
        if isinstance(commit, str) and f"`{commit}`" not in md:
            problems.add(where_md, "Markdown '## Provenance' does not carry the JSON environment.git_commit")
    for title in ("Provenance", "Limitations (stated beside the claims)"):
        if not has_section(md, title):
            problems.add(where_md, f"missing required section '## {title}'")
    if "Claim scope:" not in md:
        problems.add(where_md, "missing the 'Claim scope:' statement")
    check_passive_input_hashes(problems, root, exp_dir, where_js, rec)
    if status == "CAPABILITY_UNAVAILABLE":
        need_str(problems, where_js, rec, "failed_command")
        if rec.get("metrics") is not None or rec.get("compare") is not None:
            problems.add(where_js, "CAPABILITY_UNAVAILABLE record carries metrics/compare numbers "
                         "(an unavailable capability establishes no number)")
        if not has_section(md, "Failed capability check"):
            problems.add(where_md, "missing required section '## Failed capability check'")
    else:
        if not isinstance(rec.get("metrics"), dict):
            problems.add(where_js, f"{status} record has no 'metrics' object")
        if status in ("QUALIFIED", "FIT_FAILED") and rec.get("compare") is not None and not isinstance(
                rec.get("compare"), dict):
            problems.add(where_js, "JSON 'compare' is neither null nor an object")
        if status == "QUALIFIED" and not isinstance(rec.get("compare"), dict):
            problems.add(where_js, "QUALIFIED record has no 'compare' (fit validation) object")
    schema = rec.get("record_schema")
    if schema is None:
        if stem not in LEGACY_PASSIVE_RECORDS:
            problems.add(where_js, "record has no 'record_schema': only the pre-#58 legacy records "
                         "may omit the frozen solver-artifact package; new records must be record_schema 2")
        elif "artifact_package" in rec:
            problems.add(where_js, "legacy record unexpectedly carries an artifact_package")
        # legacy: run_log/ files named by the record must exist (existence only: working output)
        for ref in sorted(set(re.findall(r"\(?`?(run_log/[A-Za-z0-9_.\-]+)", md))):
            if not (exp_dir / ref).is_file():
                problems.add(where_md, f"declared companion {ref} does not exist under {rel(root, exp_dir)}/")
    elif schema == 2:
        claimed_packages.add(rid)
        check_passive_package(problems, root, exp_dir, rid, status, rec, md, where_js, where_md)
    else:
        problems.add(where_js, f"unknown record_schema {schema!r} (known: absent=legacy, 2)")


def check_passive_p1(problems: Problems, root: Path, exp_dir: Path) -> None:
    records = exp_dir / "records"
    if not records.is_dir():
        return
    claimed: set[str] = set()
    for stem, files in record_pairs(problems, root, records).items():
        check_passive_record(problems, root, exp_dir, stem, files, claimed)
    pk = exp_dir / PASSIVE_PACKAGES
    if pk.exists():
        if not pk.is_dir():
            problems.add(rel(root, pk), f"{PASSIVE_PACKAGES} must be a directory of <id>/ run packages")
        else:
            for p in sorted(pk.iterdir()):
                if p.is_symlink() or not (p.is_dir() and RECORD_ID_RE.match(p.name)):
                    problems.add(rel(root, p), f"{PASSIVE_PACKAGES} entry is not a <YYYYMMDD>-<HHMMSS>-<git-sha>/ "
                                 "run directory")
                elif p.name not in claimed:
                    problems.add(rel(root, p), "solver-artifact package belongs to no record "
                                 "(orphan or interrupted publication)")
    for sub in ("corners", "netlist-snapshots", "probe-logs"):
        if (exp_dir / sub).exists():
            problems.add(rel(root, exp_dir / sub), f"{sub}/ is not part of the passive-p1 evidence layout")
