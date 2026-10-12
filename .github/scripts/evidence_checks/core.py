"""Evidence-format and append-only checker for sim/*/ evidence trees.

Standard library only; needs no PDK, no simulator, no third-party package.

What it checks (it validates FORMAT and PROVENANCE only -- it never
reinterprets a historical scientific claim; corrections go in a later record):

1. Format, for every ``sim/<bench>/testbench/tb.json`` bench and every
   ``sim/<bench>/records/*.md`` record in the CURRENT tree. Two committed
   layouts exist and both are recognised; the bench's ``tb.json`` selects
   which (a ``"sweep"`` block means the Ka-band layout):

   harness-native (sim/harness/report.py ``render_markdown``)
       records/<id>.md, corners/<id>/<corner_id>.log (plain text),
       netlist-snapshots/<id>.spice (one frozen file).
       The record declares its matrix as ``Process: ..`` / ``Temperature: ..``
       / ``Supply: ..`` / ``N point full-factorial grid .., M completed`` (a
       run covering the bench's whole required product) or ``N point grid
       (subset of ..), M completed`` (an intentional subset, issue #81). Both
       wordings go through the same expansion and artifact checks.

       A record that additionally carries a ``**Manifest**:`` header field is
       a frozen-manifest record (issue #141): the line names
       ``netlist-snapshots/<id>.tb.json`` -- the verbatim ``tb.json`` bytes
       the run was configured by (analyses, measurement expressions, options,
       parameters, checks, claim), written by sim/harness/report.py
       ``write_manifest_snapshot`` -- and its sha256. The checker requires the
       artifact, recomputes its digest against the declared one and sanity
       checks the JSON; a line naming any other file or form is refused.
       Records without the line are legacy and validate unchanged (no file is
       expected for them), so historical run ids gain nothing.

   Ka-band (sim/hbt-kaband-characterization/report_kaband.py)
       records/<id>.md, corners/<id>/<corner_id>.log.gz (gzip),
       netlist-snapshots/<id>/{body,request,klt-report}_<supply>v.* (one set
       per declared supply), records/<id>-{points.csv.gz,cells.csv,best.csv}.
       The record declares its matrix on the ``**PVT points**`` line.

   The declared matrix is expanded to corner identities and compared with the
   artifacts actually on disk (missing / unexpected / duplicated identities,
   unreadable compressed logs, missing snapshots and companion files, sidecar
   rows naming identities outside the matrix). Nothing is hardcoded to 27.

   mixer-topology-feasibility (sim/mixer-topology-feasibility/collect.py)
       a bench whose ``tb.json`` has a ``"study"`` block: records/<id>.md +
       <id>.json + <id>-cells.json.gz, corners/<id>/*.log.gz, and
       netlist-snapshots/<id>/ with the generated klt bodies/requests/reports
       and the frozen fragments. The sidecar must say the acceptance gate
       passed, declared == accepted cells, every cell id unique and in a
       scientific status, leakage cells carrying the declared seed. It checks
       completeness and consistency only, never the science.

   Further campaigns have no PVT testbench manifest (``tb.json``) and
   are NOT harness PVT benches; each is registered explicitly in
   :data:`ADAPTERS` (never inferred) and validated for identity, status,
   paired Markdown/JSON consistency, provenance and declared companions only:

   lna-match-tradeoff (sim/lna-match-tradeoff/collect.py, issue #74)
       declared by testbench/study.json (not tb.json); records/<id>.md +
       <id>.json + <id>-cells.json.gz, corners/<id>/*.log.gz (one per klt
       unit) and netlist-snapshots/<id>/ (frozen study.json declaration and
       DUT, generated klt bodies/requests/reports/specs). The cell ids must
       be exactly those the FROZEN declaration and the record's shortlist
       imply; ok cells need finite summaries, a passing refined-grid control
       and full per-frequency band data; the sidecar must say the gate
       passed and no spec row is claimed, and its hashes must match the
       frozen declaration and DUT. Completeness and consistency only.


   passive-p1 (sim/passive-p1/scripts/make_record.py, controls.py)
       records/<id>-<STATUS>.{md,json} pairs, where <STATUS> is a campaign
       outcome (QUALIFIED, UNCONVERGED, FIT_FAILED, CAPABILITY_UNAVAILABLE)
       or CONTROLS-PASS / CONTROLS-FAIL. The permanent evidence package is
       the record pair plus the INPUTS.json-hashed input files it names;
       results/, run_log/ and fit/ are mutable solver working output and
       are deliberately NOT protected. SYNTHETIC-* smoke records are not
       campaign evidence and are rejected inside records/.

   mixer-nf-method (sim/mixer-nf-method/run_probe.py)
       records/<id>-<STATUS>.{md,json} (METHOD_VALIDATION, MODEL_ABSENT,
       UNCONVERGED, CAPABILITY_UNAVAILABLE) plus, for every run that reached
       the simulator, the frozen probe-logs/<id>/{deck.spice,stdout.txt,
       stderr.txt,inventory.json} package named by the JSON ``probe_logs``.

   mixer-cm-interface-probe (sim/mixer-cm-interface-probe/run_probe.py, issue #89)
       records/<id>-<STATUS>.{md,json} (INTERFACES_DEMONSTRATED,
       INTERFACES_PARTIAL, INTERFACES_BLOCKED, CAPABILITY_UNAVAILABLE) plus,
       for every run that reached the simulator, the frozen probe-logs/<id>/
       {deck.spice,stdout.txt,stderr.txt,inventory.json} package. A sibling of
       mixer-nf-method with its own status vocabulary (never METHOD_VALIDATION):
       the JSON ``interface_matrix`` must carry exactly the five required
       interfaces with a state and a reference, the status must follow from the
       states, a transfer interface may be ``demonstrated`` only if the
       known-answer control passed, and inventory.json must equal the record's
       matrix. CAPABILITY_UNAVAILABLE carries no probe results.

   mixer-pumped-rf-admittance (sim/mixer-pumped-rf-admittance/run_probe.py, issue #111)
       records/<id>-<STATUS>.{md,json} (SCALAR_ADEQUATE, MATRIX_REQUIRED,
       INCONCLUSIVE, CAPABILITY_UNAVAILABLE) plus the same frozen probe-logs/<id>/
       package. Both halves must carry the method-feasibility scope disclaimer
       (no row-5 compliance claim, no NF claim, DR-0004 untouched); the record's
       thresholds must be complete and committed (thresholds_provenance.dirty
       false); every DUT numerical check's pass flag must agree with its value
       against the recorded threshold; kappa must follow from the recorded 2x2
       admittance; and the status must follow from controls, checks, kappa and
       the scalar bound (SCALAR/MATRIX only with passing known-answer controls).
       inventory.json's 'evaluation' must equal the record's.

   lna-linearity (sim/lna-linearity/run.py, issue #57)
       declared by testbench/plan.json (not tb.json); records/<id>.md + <id>.json +
       <id>-sweeps.json.gz, corners/<id>/<request>.log.gz (one per klt request) and
       netlist-snapshots/<id>/ (frozen plan, DUT, generated bodies/requests/reports).
       The Claim must state the IDEAL-matching placeholder circuit and spec_rows_claimed_met
       must be []. The frozen plan and DUT hashes must match the record, the plan must have
       been committed (dirty false) before the collection, the python and ngspice analytic
       controls and every negative control must be recorded, and per placement: an ok IIP3
       needs both IM3 sidebands each with a fit interval inside the declared sweep, 1:3
       slopes and residuals inside the declared tolerances, a baseline, rejected-point
       reasons and the extrapolation distance; an ok P1dB needs a baseline and a bracket
       straddling the declared drop; a bounded P1dB carries no number; unavailable carries
       a reason; convergence entries for the half_step and double_window variants must agree
       with final.converged / final.status; the target in every assessment must equal the
       ratified row 7/8 target in spec/target-spec.md and the verdict must follow from the
       value, the target and the measured convergence spread. The sweeps sidecar must hold
       every declared point of every variant with both IM3 sidebands. Completeness and
       consistency only; the science is re-derived by ``run.py verify`` and its tests.

   Passive records of ``record_schema`` 2 (issue #58) additionally name a frozen
   ``sim/passive-p1/solver-artifacts/<id>/`` package: ``manifest.json`` lists
   every package-relative file with sha256 and size; the checker verifies the
   outcome-required files are present (completeness), every path is a safe
   relative path (no absolute, ``..``, symlink, dot-file), the bytes match the
   hashes, nothing unlisted is present, no interrupted-publication marker is
   left, the manifest hash agrees with the record, and the record's metrics /
   compare equal the packaged JSON. Legacy records (the two committed before
   #58, listed in :data:`LEGACY_PASSIVE_RECORDS`) stay valid without a package.
   This is hash INTEGRITY and record/package agreement only; it never judges
   whether the numbers are correct or qualified.

   Any other ``sim/<dir>/`` that has records/, corners/, netlist-snapshots/,
   probe-logs/ or solver-artifacts/ but is neither a testbench bench nor a registered adapter
   fails visibly instead of being skipped.

2. Append-only history (``--base`` / environment fallback, see
   :func:`resolve_base`): against the MERGE BASE of the base ref and HEAD
   (never only the last commit of a multi-commit branch) no committed file
   under ``sim/*/{records,corners,netlist-snapshots,probe-logs,solver-artifacts}/`` may be modified,
   deleted, renamed or type-changed, and no file may be ADDED to a record id
   that already existed at the base. New record ids are fine, as are
   independent testbench/harness changes.

   No base available (first push of a new branch with no ``origin/main``,
   all-zero ``before`` sha, ...): the append-only half is SKIPPED with a loud
   notice and the format half still runs; ``--require-base`` turns the skip
   into a failure (the pull_request job uses it).

3. Spec-row coverage (``spec/row-coverage.json``, issue #50): the hand-kept
   manifest must list exactly the rows of the table in ``spec/target-spec.md``
   with the same status and binding corner, every cited bench dir / record
   must exist, a ``measured_*`` verdict may not cite a record whose Claim line
   says placeholder / device-level, and a row without a bench must say what
   blocks it. A row's ``latest_record`` must also not be stale: no
   lexicographically newer ``*.md`` in the same bench's ``records/`` may mention
   the row (``row N``, ``rows A-B``, ``rows A, B and C``). A mention is not a
   claim; resolve a false positive by pointing ``latest_record`` at the newer
   record. Every row must also carry ``statistical`` (a JSON bool),
   a non-blank ``statistical_rationale`` and, when ``statistical`` is true, a
   non-blank ``statistical_card`` (absent on a false row); see DR-0007. It
   records bookkeeping only and never changes a spec value.

Exit status: 0 clean, 1 problems found, 2 usage/environment error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .common import PROTECTED_RE, Problems, RECORD_ID_PREFIX_RE, git, rel
from .hbt_mismatch_pair import check_hbt_mismatch_pair
from .kaband import check_kaband_record
from .lna_headroom import check_lna_headroom
from .lna_linearity import check_lna_linearity
from .lna_match import check_lna_match_tradeoff
from .mixer_cm import check_mixer_cm_interface_probe
from .mixer_feas import check_mixfeas_record, is_mixfeas
from .mixer_nf import check_mixer_nf_method
from .mixer_pra import check_mixer_pumped_rf_admittance
from .native import check_native_record
from .passive_p1 import check_passive_p1
from .readmes import check_bench_readmes
from .spec_rows import (COVERAGE_PATH, OVERCLAIM_RE, SPEC_PATH, VERDICTS, rows_mentioned, spec_table_rows)


# Explicit registry of the non-PVT campaign layouts. A sim/<dir> with evidence
# directories that is neither a testbench bench nor listed here is an error.
ADAPTERS = {
    "passive-p1": check_passive_p1,
    "mixer-nf-method": check_mixer_nf_method,
    "mixer-cm-interface-probe": check_mixer_cm_interface_probe,
    "mixer-pumped-rf-admittance": check_mixer_pumped_rf_admittance,
    "lna-match-tradeoff": check_lna_match_tradeoff,
    "lna-linearity": check_lna_linearity,
    "lna-headroom": check_lna_headroom,
    "hbt-mismatch-pair": check_hbt_mismatch_pair,
}
EVIDENCE_DIRS = ("records", "corners", "netlist-snapshots", "probe-logs", "solver-artifacts")


# ---------------------------------------------------------------------------
# tree walk
# ---------------------------------------------------------------------------


def is_kaband(exp_dir: Path, problems: Problems, root: Path) -> bool:
    tb = exp_dir / "testbench" / "tb.json"
    try:
        manifest = json.loads(tb.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.add(rel(root, tb), f"manifest unreadable ({exc})")
        return False
    if not isinstance(manifest, dict):
        problems.add(rel(root, tb), "manifest is not a JSON object")
        return False
    return "sweep" in manifest


def check_format(root: Path) -> Problems:
    problems = Problems()
    sim = root / "sim"
    exps = sorted(p.parent.parent for p in sim.glob("*/testbench/tb.json"))
    if not exps:
        problems.add("sim/", "no sim/*/testbench/tb.json benches found")
    check_bench_readmes(problems, root)
    bench_names = {e.name for e in exps}
    for d in sorted(p for p in sim.iterdir() if p.is_dir()):
        if d.name in bench_names:
            continue
        if d.name in ADAPTERS:
            ADAPTERS[d.name](problems, root, d)
        else:
            present = [n for n in EVIDENCE_DIRS if (d / n).exists()]
            if present:
                problems.add(rel(root, d), f"unrecognised evidence layout (has {', '.join(n + '/' for n in present)} "
                             "but no testbench/tb.json bench and no registered adapter in ADAPTERS); "
                             "refusing to skip it")
    for exp in exps:
        kaband = is_kaband(exp, problems, root)
        mixfeas = is_mixfeas(exp)
        records = exp / "records"
        mds = sorted(records.glob("*.md")) if records.is_dir() else []
        ids = {p.stem for p in mds}
        for md in mds:
            if mixfeas:
                check_mixfeas_record(problems, root, exp, md)
            elif kaband:
                check_kaband_record(problems, root, exp, md)
            else:
                check_native_record(problems, root, exp, md)
        # evidence that no record claims
        if records.is_dir() and not kaband and not mixfeas:
            for p in sorted(records.iterdir()):
                if p.suffix != ".md":
                    problems.add(rel(root, p), "unexpected file in a harness-native records/ directory")
        if records.is_dir() and (kaband or mixfeas):
            for p in sorted(records.iterdir()):
                m = RECORD_ID_PREFIX_RE.match(p.name)
                if p.suffix != ".md" and not (m and m.group(1) in ids):
                    problems.add(rel(root, p), "evidence file belongs to no record in this experiment")
        for sub in ("corners", "netlist-snapshots"):
            d = exp / sub
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                m = RECORD_ID_PREFIX_RE.match(p.name)
                if not (m and m.group(1) in ids):
                    problems.add(rel(root, p), f"{sub} entry belongs to no record in this experiment (orphan evidence)")
    return problems


# ---------------------------------------------------------------------------
# append-only history
# ---------------------------------------------------------------------------



def resolve_base(root: Path, base: str | None) -> tuple[str | None, str]:
    """Return ``(merge_base_sha_or_None, note)``.

    Order: explicit ``--base``; ``origin/$GITHUB_BASE_REF`` (pull_request);
    ``origin/main``; ``main``. An all-zero sha (new branch push) or an
    unresolvable ref means "no base". The merge base with HEAD is always used,
    so a multi-commit branch is compared as a whole.
    """
    candidates: list[str] = []
    if base and not set(base) <= {"0"}:
        candidates.append(base)
    elif base:
        candidates.append("")  # explicit all-zero: fall through to the defaults below
    if os.environ.get("GITHUB_BASE_REF"):
        candidates.append(f"origin/{os.environ['GITHUB_BASE_REF']}")
    candidates += ["origin/main", "main"]
    for ref in candidates:
        if not ref:
            continue
        if git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode != 0:
            continue
        mb = git(root, "merge-base", ref, "HEAD")
        if mb.returncode == 0 and mb.stdout.strip():
            return mb.stdout.strip(), f"comparing against merge base of {ref} and HEAD ({mb.stdout.strip()[:12]})"
    return None, "no comparison base could be resolved"


def check_append_only(root: Path, base: str | None, require_base: bool) -> tuple[Problems, str]:
    problems = Problems()
    if git(root, "rev-parse", "--git-dir").returncode != 0:
        if require_base:
            problems.add("git", "not a git work tree; append-only history cannot be checked")
        return problems, "append-only check SKIPPED: not a git work tree"
    mb, note = resolve_base(root, base)
    if mb is None:
        shallow = git(root, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
        hint = " (shallow clone: use actions/checkout fetch-depth: 0)" if shallow else ""
        msg = (f"append-only check SKIPPED: {note}{hint}. Current-tree format validation still ran. "
               "First push of a new branch with no origin/main, or an all-zero 'before' sha, lands here.")
        if require_base:
            problems.add("append-only", f"{note}{hint} but --require-base was given")
        return problems, msg

    diff = git(root, "diff", "--name-status", "--no-renames", mb, "--", "sim")
    if diff.returncode != 0:
        problems.add("append-only", f"git diff against {mb[:12]} failed: {diff.stderr.strip()}")
        return problems, note
    base_files = git(root, "ls-tree", "-r", "--name-only", mb, "--", "sim").stdout.splitlines()
    base_ids = {
        m.group(1)
        for f in base_files
        if PROTECTED_RE.match(f)
        for m in [RECORD_ID_PREFIX_RE.match(f.split("/")[3])]
        if m
    }
    for line in diff.stdout.splitlines():
        status, _, path = line.partition("\t")
        if not PROTECTED_RE.match(path):
            continue
        if status == "A":
            parts = path.split("/")
            m = RECORD_ID_PREFIX_RE.match(parts[3]) if len(parts) > 3 else None
            if m and m.group(1) in base_ids:
                problems.add(path, f"adds a file to record {m.group(1)}, which is already committed "
                             "(evidence is append-only; add a new record instead)")
            continue
        verb = {"M": "modified", "D": "deleted or renamed away", "T": "type-changed"}.get(status[0], f"changed ({status})")
        problems.add(path, f"committed evidence was {verb} since the merge base {mb[:12]} "
                     "(append-only: supersede with a later record, never edit or remove)")
    return problems, note


def check_row_coverage(root: Path) -> Problems:
    problems = Problems()
    spec = root / SPEC_PATH
    man = root / COVERAGE_PATH
    if not spec.is_file():
        problems.add(SPEC_PATH, "missing; cannot check spec-row coverage")
        return problems
    if not man.is_file():
        problems.add(COVERAGE_PATH, "missing row-coverage manifest")
        return problems
    try:
        doc = json.loads(man.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.add(COVERAGE_PATH, f"unreadable JSON: {exc}")
        return problems
    entries = doc.get("rows") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        problems.add(COVERAGE_PATH, "top level must be an object with a 'rows' list")
        return problems
    table = spec_table_rows(spec.read_text(encoding="utf-8"))
    if not table:
        problems.add(SPEC_PATH, "no spec table rows parsed")
        return problems

    by_row: dict[int, dict] = {}
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or not isinstance(e.get("row"), int):
            problems.add(COVERAGE_PATH, f"rows[{i}] is not an object with an integer 'row'")
            continue
        if e["row"] in by_row:
            problems.add(COVERAGE_PATH, f"row {e['row']} listed more than once")
        by_row[e["row"]] = e
    for n in sorted(set(table) - set(by_row)):
        what = "RATIFIED row silently absent" if table[n][0] == "ratified-target" else "row missing"
        problems.add(COVERAGE_PATH, f"row {n}: {what} from the manifest")
    for n in sorted(set(by_row) - set(table)):
        problems.add(COVERAGE_PATH, f"row {n}: not in the {SPEC_PATH} table")

    for n in sorted(set(by_row) & set(table)):
        e = by_row[n]
        where = f"{COVERAGE_PATH} row {n}"
        status, corner = table[n]
        if e.get("status") != status:
            problems.add(where, f"status {e.get('status')!r} disagrees with the spec table ({status!r})")
        if e.get("bound_corner") != corner:
            problems.add(where, f"bound_corner {e.get('bound_corner')!r} disagrees with the spec table ({corner!r})")
        stat = e.get("statistical")
        if not isinstance(stat, bool):
            problems.add(where, f"'statistical' must be a JSON bool (got {stat!r}); DR-0007")
        rat = e.get("statistical_rationale")
        if not (isinstance(rat, str) and rat.strip()):
            problems.add(where, "'statistical_rationale' is required and must be a non-blank string")
        card = e.get("statistical_card")
        if stat is True and not (isinstance(card, str) and card.strip()):
            problems.add(where, "statistical true: 'statistical_card' (PDK mismatch/stat model file name) is required")
        if stat is False and "statistical_card" in e:
            problems.add(where, "statistical false: 'statistical_card' must be absent (a card source is only "
                         "meaningful on a row that needs Monte Carlo)")
        verdict = e.get("verdict")
        if verdict not in VERDICTS:
            problems.add(where, f"verdict {verdict!r} not one of {sorted(VERDICTS)}")
            continue
        bench, rec = e.get("bench"), e.get("latest_record")
        if bench is not None:
            if not isinstance(bench, str) or not bench.startswith("sim/") or not (root / bench).is_dir():
                problems.add(where, f"bench {bench!r} is not an existing sim/<experiment> directory")
        if rec is not None:
            rp = root / rec if isinstance(rec, str) else None
            if rp is None or not rp.is_file():
                problems.add(where, f"latest_record {rec!r} does not exist")
        if verdict == "no_bench":
            if bench is not None or rec is not None:
                problems.add(where, "verdict no_bench but a bench or record is cited")
            if not (isinstance(e.get("blocked_by"), str) and e["blocked_by"].strip()):
                problems.add(where, "no bench: 'blocked_by' (issue or DR id) is required")
            continue
        if bench is None or rec is None:
            problems.add(where, f"verdict {verdict} needs both a bench and a latest_record")
            continue
        if isinstance(rec, str) and not rec.startswith(str(bench) + "/records/"):
            problems.add(where, f"latest_record {rec!r} is not under {bench}/records/")
        if isinstance(rec, str) and isinstance(bench, str) and (root / bench / "records").is_dir():
            latest_name = Path(rec).name
            for newer in sorted((root / bench / "records").glob("*.md")):
                if newer.name > latest_name and n in rows_mentioned(
                        newer.read_text(encoding="utf-8", errors="replace")):
                    problems.add(where, f"stale latest_record {rec!r}: newer record {bench}/records/{newer.name} "
                                 f"mentions row {n} (point latest_record at it; a mention is not a claim)")
        if verdict.startswith("measured_") and isinstance(rec, str) and (root / rec).is_file():
            text = (root / rec).read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                if line.startswith("**Claim**") and OVERCLAIM_RE.search(line):
                    problems.add(where, f"overclaimed: {verdict} cites {rec}, whose Claim line says "
                                 "placeholder/device-level")
                    break
    return problems


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".", help="repository root (default: cwd)")
    ap.add_argument("--base", help="base ref/sha for the append-only comparison")
    ap.add_argument("--require-base", action="store_true",
                    help="fail instead of skipping the append-only check when no base resolves")
    ap.add_argument("--skip-history", action="store_true", help="format validation only")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if not (root / "sim").is_dir():
        print(f"error: {root} has no sim/ directory", file=sys.stderr)
        return 2

    problems = check_format(root)
    print(f"format: {'FAILED' if problems else 'ok'} ({len(problems.items)} problem(s))")
    cov = check_row_coverage(root)
    print(f"row-coverage: {'FAILED' if cov else 'ok'} ({len(cov.items)} problem(s))")
    problems.items += cov.items
    if not args.skip_history:
        hist, note = check_append_only(root, args.base, args.require_base)
        print(f"append-only: {note}")
        print(f"append-only: {'FAILED' if hist else 'ok'} ({len(hist.items)} problem(s))")
        problems.items += hist.items
    for item in problems.items:
        print(f"ERROR {item}", file=sys.stderr)
    return 1 if problems else 0

