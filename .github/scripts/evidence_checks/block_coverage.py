"""evidence_checks.block_coverage: item-1 coverage honesty (issue #170).

signoff/evidence/item1-design-sources.json carries ``metrics.block_coverage``.
If it says the mixer is ``no_design_source`` while design/ holds a mixer source,
the attestation has rotted into understating the design; if it claims
``sources_committed`` with no mixer source, it overstates it. Stdlib only.
"""

from __future__ import annotations

import json
from pathlib import Path

EVIDENCE = "signoff/evidence/item1-design-sources.json"
SOURCE_SUFFIXES = (".sch", ".sym", ".spice", ".cir", ".py", ".sh")
NO_SOURCE = "no_design_source"
HAVE_SOURCE = "sources_committed"


def mixer_sources(root: Path) -> list[str]:
    """Files under design/ that are a mixer source (name or, for text sources, content mentions 'mixer')."""
    found = []
    design = root / "design"
    for p in sorted(design.rglob("*")):
        if not p.is_file() or p.suffix not in SOURCE_SUFFIXES:
            continue
        hit = "mixer" in p.name.lower()
        if not hit:
            try:
                hit = "mixer" in p.read_text(errors="replace").lower()
            except OSError:
                hit = False
        if hit:
            found.append(str(p.relative_to(root)))
    return found


def block_coverage_problems(root: Path) -> list[str]:
    path = root / EVIDENCE
    try:
        cov = json.loads(path.read_text())["metrics"]["block_coverage"]
    except (OSError, ValueError, KeyError, TypeError):
        return [f"{EVIDENCE}: missing metrics.block_coverage"]
    if not isinstance(cov, dict) or "mixer" not in cov:
        return [f"{EVIDENCE}: metrics.block_coverage must name the mixer"]
    state, srcs, out = cov["mixer"], mixer_sources(root), []
    if state not in (NO_SOURCE, HAVE_SOURCE):
        out.append(f"{EVIDENCE}: block_coverage.mixer={state!r} is not {NO_SOURCE!r} or {HAVE_SOURCE!r}")
    elif state == NO_SOURCE and srcs:
        out.append(f"{EVIDENCE}: block_coverage.mixer is {NO_SOURCE} but design/ has mixer source(s) {srcs}; "
                   "update the coverage claim and regenerate")
    elif state == HAVE_SOURCE and not srcs:
        out.append(f"{EVIDENCE}: block_coverage.mixer is {HAVE_SOURCE} but design/ has no mixer source")
    return out
