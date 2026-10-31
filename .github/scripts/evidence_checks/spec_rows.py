"""evidence_checks.spec_rows: split out of check_evidence_formats.py (issue #163); no rule changes."""

from __future__ import annotations

import re



# ---------------------------------------------------------------------------
# Spec-row coverage manifest (issue #50)

COVERAGE_PATH = "spec/row-coverage.json"
SPEC_PATH = "spec/target-spec.md"
VERDICTS = {"no_bench", "placeholder_circuit", "device_level_only", "method_absent",
            "measured_pass", "measured_fail"}
NEEDS_RECORD = VERDICTS - {"no_bench"}
OVERCLAIM_RE = re.compile(r"placeholder|device-level|device level|not a matched|not spec", re.I)
SPEC_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|")
# Deliberately simple: "row 5", "rows 2-5", "rows 2, 3 and 6". Case-insensitive.
ROW_MENTION_RE = re.compile(r"\brows?\s+(\d+)(?:\s*[-\u2013]\s*(\d+))?((?:\s*(?:,|and)\s*\d+)*)", re.I)


def rows_mentioned(text: str) -> set[int]:
    """Spec row numbers named in a record (a mention is not a claim)."""
    found: set[int] = set()
    for m in ROW_MENTION_RE.finditer(text):
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        if lo <= hi <= lo + 30:
            found.update(range(lo, hi + 1))
        found.update(int(x) for x in re.findall(r"\d+", m.group(3) or ""))
    return found


def spec_table_rows(text: str) -> dict[int, tuple[str, str]]:
    """{row: (status, binding-corner cell)} parsed from the target-spec table."""
    rows: dict[int, tuple[str, str]] = {}
    for line in text.splitlines():
        m = SPEC_ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(cells) < 7:
            continue
        st = re.search(r"\*\*(RATIFIED|OPEN)", cells[2])
        if st:
            rows[int(m.group(1))] = ("ratified-target" if st.group(1) == "RATIFIED" else "open", cells[6])
    return rows
