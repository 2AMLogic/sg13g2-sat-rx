"""evidence_checks.readmes: split out of check_evidence_formats.py (issue #163); no rule changes."""

from __future__ import annotations

import re
from pathlib import Path

from .common import Problems, rel


# ---------------------------------------------------------------------------
# bench cold-start READMEs and PDK naming (T1 item 9 preconditions, issue #85)
# ---------------------------------------------------------------------------

#: Heading titles that count as a bench's documented invocation section.
INVOCATION_HEADING_RE = re.compile(
    r"^#{2,3}\s+(?:Cold start|Running it|Reproduce|Stages and commands)\b[^\n]*$", re.M | re.I)
FENCE_RE = re.compile(r"^\s*(?:```|~~~)", re.M)

#: Records that name the PDK as ``unknown`` (the harness's ``Pdk.version`` read a
#: ``SOURCES`` file that IHP-Open-PDK does not ship). Records are append-only,
#: so these are grandfathered BY ID and the set is closed: any record not listed
#: here that names the PDK ``unknown`` fails. Note the last entry post-dates the
#: model-artifact pin (sim/pdk-artifact.json); that is the remaining T1 item 9
#: gap and is why item 9 is not attested (signoff/README.md).
LEGACY_UNKNOWN_PDK = frozenset({
    "sim/lna-sparam-nf/records/20260912-034726-9204518.md",
    "sim/mixer-conversion-iip3/records/20260912-034727-9204518.md",
    "sim/lna-sparam-nf/records/20261009-134024-57e1898.md",
    "sim/lna-sparam-nf/records/20261010-012923-6cad7fc.md",
})
PDK_UNKNOWN_RE = re.compile(r"^- PDK:.*\(unknown\b", re.M)
#: Native records written since #103 print the installation marker separately
#: ("(install marker: <v>, via ...)") and carry the verified artifact identity on
#: a "- PDK artifact:" line. The marker may legitimately be ``unknown`` (markerless
#: installs); the artifact line may not be anything but a verified full identity.
PDK_MARKER_RE = re.compile(r"^- PDK:.*\(install marker:", re.M)
PDK_ARTIFACT_RE = re.compile(
    r"^- PDK artifact: \*\*verified\*\* -- upstream .*? commit `[0-9a-f]{40}`; "
    r"\S+ sha256 `[0-9a-f]{64}`; \d+ model files hash-verified", re.M)


def readme_invocation_problem(readme: Path) -> str | None:
    """Why ``readme`` is not a cold-start README, or None if it is one."""
    if not readme.is_file() or readme.stat().st_size == 0:
        return "missing or empty README.md"
    text = readme.read_text(errors="replace")
    heads = list(INVOCATION_HEADING_RE.finditer(text))
    if not heads:
        return ("no invocation section (a '## Cold start', '## Running it', '## Reproduce' "
                "or '## Stages and commands' heading)")
    for m in heads:
        nxt = re.search(r"^#{1,3}\s", text[m.end():], re.M)
        body = text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():]
        if FENCE_RE.search(body):
            return None
    return "invocation section contains no fenced command block"


def check_bench_readmes(problems: Problems, root: Path) -> None:
    """Every sim/<dir> holding records/ has a README with a runnable invocation,
    and no un-grandfathered record names the PDK ``unknown``."""
    sim = root / "sim"
    for d in sorted(p for p in sim.iterdir() if p.is_dir()):
        records = d / "records"
        if not records.is_dir():
            continue
        why = readme_invocation_problem(d / "README.md")
        if why:
            problems.add(rel(root, d / "README.md"),
                         f"bench has records/ but no cold-start README: {why}")
        for md in sorted(records.glob("*.md")):
            r = rel(root, md)
            text = md.read_text(errors="replace")
            if PDK_MARKER_RE.search(text) and not PDK_ARTIFACT_RE.search(text):
                problems.add(r, "record separates the PDK install marker but carries no verified "
                             "'- PDK artifact: **verified** -- ... commit `<40-hex>`; ... sha256 `<64-hex>`' line")
            if PDK_UNKNOWN_RE.search(text) and r not in LEGACY_UNKNOWN_PDK:
                problems.add(r, "record names the PDK as 'unknown' and is not a grandfathered legacy record; "
                             "cite the pinned artifact (sim/pdk-artifact.json) instead")
