"""evidence_checks.native: split out of check_evidence_formats.py (issue #163); no rule changes."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .artifact_manifests import check_stored_native_record
from .common import (NATIVE_SECTIONS, NATIVE_SNAPSHOT_NOTE, NATIVE_STATUSES, Problems, RECORD_ID_RE, check_supersedes, compare_identities, expand_matrix, has_section, header_field, numbers, rel)


# ---------------------------------------------------------------------------
# harness-native layout
# ---------------------------------------------------------------------------


#: The harness-native grid-size line, in either wording ``render_markdown``
#: emits: ``- N point full-factorial grid (...), M completed`` for a run that
#: covers the required process x temperature x supply product, or
#: ``- N point grid (subset of ...), M completed`` for an intentional subset.
NATIVE_GRID_LINE_RE = re.compile(
    r"^\s*- (\d+) point (?:full-factorial grid|grid \(subset of)[^\n]*?, (\d+) completed",
    re.MULTILINE,
)


def declared_native_matrix(text: str) -> tuple[list[str], list[float], list[float], int | None, int | None]:
    """Return (processes, temperatures, supplies, n_total, n_done) as declared
    by a harness-native record.

    The grid-size line may use the full-factorial or the subset wording (see
    :data:`NATIVE_GRID_LINE_RE`). The wording only says whether the run met the
    bench's required product; either way N must equal the expansion of the
    Process/Temperature/Supply lists and the corner logs must match that
    expansion, so accepting a subset relaxes none of the other checks.
    """
    def line(label: str) -> str:
        m = re.search(rf"^\s*- {label}: (.+)$", text, re.MULTILINE)
        return m.group(1) if m else ""

    processes = [p.strip() for p in line("Process").split(",") if p.strip()]
    temps = numbers(line("Temperature"))
    supplies = numbers(line("Supply"))
    m = NATIVE_GRID_LINE_RE.search(text)
    n_total = int(m.group(1)) if m else None
    n_done = int(m.group(2)) if m else None
    return processes, temps, supplies, n_total, n_done


def check_native_record(problems: Problems, root: Path, exp_dir: Path, md: Path) -> None:
    rid = md.stem
    where = rel(root, md)
    text = md.read_text(encoding="utf-8", errors="replace")

    if not RECORD_ID_RE.match(rid):
        problems.add(where, "record file name is not <YYYYMMDD>-<HHMMSS>-<git-sha>.md")
    first = text.splitlines()[0] if text.strip() else ""
    if first != f"# {rid}":
        problems.add(where, f"first line must be '# {rid}', found {first!r}")
    for name in ("Status", "Experiment", "Started (UTC)", "Wall time"):
        if header_field(text, name) is None:
            problems.add(where, f"missing required header field '**{name}**:'")
    if header_field(text, "Claim") is None:
        problems.add(where, "missing required header field '**Claim**:'")
    status = header_field(text, "Status")
    if status is not None and status not in NATIVE_STATUSES:
        problems.add(where, f"Status {status!r} is not one of {', '.join(NATIVE_STATUSES)}")
    experiment = header_field(text, "Experiment")
    if experiment is not None and experiment != exp_dir.name:
        problems.add(where, f"Experiment {experiment!r} does not match its directory {exp_dir.name!r}")
    for title in NATIVE_SECTIONS:
        if not has_section(text, title):
            problems.add(where, f"missing required section '## {title}'")
    sup = header_field(text, "Supersedes")
    if sup is not None:
        check_supersedes(problems, where, exp_dir, sup)

    processes, temps, supplies, n_total, n_done = declared_native_matrix(text)
    if not (processes and temps and supplies) or n_total is None:
        problems.add(where, "cannot find the declared corner matrix "
                     "('Process:', 'Temperature:', 'Supply:' and an 'N point full-factorial grid ..., M completed' "
                     "or 'N point grid (subset of ...), M completed' line)")
        expected: list[str] | None = None
    else:
        expected = expand_matrix(processes, temps, supplies)
        if n_total != len(expected):
            problems.add(where, f"declares {n_total} grid points but its process x temperature x supply "
                         f"lists expand to {len(expected)}")
        if n_done is not None and n_done > n_total:
            problems.add(where, f"declares {n_done} completed points out of {n_total}")
        if status == "pass" and n_done is not None and n_done != n_total:
            problems.add(where, f"Status is pass but only {n_done}/{n_total} points are declared completed")

    stored = has_section(text, "Stored evidence")
    corners_dir = exp_dir / "corners" / rid
    if stored:
        # Stored form (issue #226): logs and snapshots are artifact-store
        # objects named by manifests/artifacts/<bench>-<rid>.manifest.json.
        check_stored_native_record(problems, root, exp_dir, rid, where, text, expected)
    elif not corners_dir.is_dir():
        problems.add(where, f"missing corner directory {rel(root, corners_dir)}/")
    elif expected is not None:
        logs = sorted(p for p in corners_dir.iterdir() if p.is_file())
        names = [p.name for p in logs]
        bad = [n for n in names if not n.endswith(".log")]
        for n in bad:
            problems.add(rel(root, corners_dir / n), "unexpected non-.log file in a harness-native corner directory")
        compare_identities(problems, rel(root, corners_dir), "corner directory", expected,
                           [n[: -len(".log")] for n in names if n.endswith(".log")])
        for p in logs:
            if p.name.endswith(".log") and p.stat().st_size == 0:
                problems.add(rel(root, p), "corner log is empty")

    snap = exp_dir / "netlist-snapshots" / f"{rid}.spice"
    if stored:
        pass
    elif not snap.is_file():
        problems.add(where, f"missing netlist snapshot {rel(root, snap)}")
    else:
        check_native_snapshot(problems, rel(root, snap), snap.read_bytes(), rid)
    extra_snap_dir = exp_dir / "netlist-snapshots" / rid
    if extra_snap_dir.exists() and not stored:
        problems.add(rel(root, extra_snap_dir), "directory-style snapshot in a harness-native bench")

    manifest_line = header_field(text, "Manifest")
    if manifest_line is not None and stored:
        if not NATIVE_MANIFEST_LINE_RE.fullmatch(manifest_line):
            problems.add(where, "'**Manifest**:' must be '`netlist-snapshots/<record-id>.tb.json` "
                         "sha256 `<64-hex>`'")
    elif manifest_line is not None:
        check_native_manifest_snapshot(problems, root, exp_dir, rid, where, manifest_line)


def check_native_snapshot(problems: Problems, where: str, data: bytes, rid: str) -> None:
    """Verify a harness-native frozen netlist snapshot (issue #93).

    Writer convention (sim/harness/report.py ``write_netlist_snapshot``): exactly
    three header lines, each terminated by ``\\n``::

        * Frozen netlist snapshot for record <rid>
        * sha256     : <hex digest of the payload bytes>
        * This is a verbatim copy taken at record time. Do not edit.

    followed immediately by the verbatim DUT bytes. The payload is everything
    after the third newline, so comment lines inside it that look like
    metadata are payload, not provenance. The digest is recomputed over those
    bytes; the current DUT is never consulted.
    """
    parts = data.split(b"\n", 3)
    if len(parts) < 4:
        problems.add(where, "snapshot is truncated: it lacks the three-line provenance header")
        return
    first, digest_line, note, payload = parts
    if first.decode("utf-8", "replace") != f"* Frozen netlist snapshot for record {rid}":
        problems.add(where, f"snapshot header does not name record {rid}")
    m = re.fullmatch(rb"\* sha256\s*: ([0-9a-f]{64})", digest_line)
    if not m:
        problems.add(where, "snapshot is missing its '* sha256 :' provenance line "
                     "(must be the second line)")
        return
    if note != NATIVE_SNAPSHOT_NOTE:
        problems.add(where, "snapshot third header line is not the writer's "
                     "'* This is a verbatim copy ...' note")
    # Ambiguity: a second provenance header inside the header region is
    # impossible by construction; one at the start of the payload would be a
    # duplicated header, which the writer never emits.
    if re.match(rb"\* (Frozen netlist snapshot for record|sha256\s*:)", payload):
        problems.add(where, "snapshot has a duplicate provenance header at the start of its payload")
    actual = hashlib.sha256(payload).hexdigest()
    declared = m.group(1).decode()
    if actual != declared:
        problems.add(where, f"snapshot payload sha256 {actual} does not match declared {declared}")


#: The ``**Manifest**:`` record line of a frozen-manifest record (issue #141):
#: the frozen artifact path relative to the experiment directory and its
#: sha256 over the whole file (the writer freezes the manifest verbatim, with
#: no header of its own). This exact form is the format contract; a future
#: revision must introduce a new discriminator rather than silently reuse it.
NATIVE_MANIFEST_LINE_RE = re.compile(r"`netlist-snapshots/([^`]+)` sha256 `([0-9a-f]{64})`")


def check_native_manifest_snapshot(
    problems: Problems, root: Path, exp_dir: Path, rid: str, where: str, value: str
) -> None:
    """Verify the frozen testbench manifest a frozen-manifest record declares.

    The record's ``**Manifest**:`` header field is the format discriminator:
    its presence selects the frozen-manifest contract, its absence means a
    legacy record that carries (and requires) no manifest artifact. Missing
    (file absent), altered (digest mismatch) and mismatched (artifact naming
    another record) manifests are all refused; the frozen JSON must still
    carry the manifest loader's required keys so the package cannot silently
    degrade into something no run could have been configured by.
    """
    m = NATIVE_MANIFEST_LINE_RE.fullmatch(value)
    if not m:
        problems.add(where, "'**Manifest**:' must be '`netlist-snapshots/<record-id>.tb.json` "
                     "sha256 `<64-hex>`'")
        return
    name, declared = m.group(1), m.group(2)
    if name != f"{rid}.tb.json":
        problems.add(where, f"'**Manifest**:' names {name!r}, not this record's own frozen manifest")
        return
    path = exp_dir / "netlist-snapshots" / name
    if not path.is_file():
        problems.add(where, f"missing frozen testbench manifest {rel(root, path)}")
        return
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != declared:
        problems.add(rel(root, path),
                     f"frozen manifest sha256 {actual} does not match declared {declared}")
        return
    try:
        manifest = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        problems.add(rel(root, path), f"frozen manifest is not valid JSON ({exc})")
        return
    if not isinstance(manifest, dict):
        problems.add(rel(root, path), "frozen manifest is not a JSON object")
        return
    for key in ("netlist", "measure"):
        if key not in manifest:
            problems.add(rel(root, path), f"frozen manifest is missing required key {key!r}")
