"""sim-harness-core — the generic ~40% of an analog canary's sim/ harness.

Scaffolded by ``everyblock/scaffold.sh`` into ``sim/harness/`` for the
``analog`` and ``mixed-signal`` variants (block and chip kind alike). See
``README.md`` next to this file for what is generic core versus what a block
is expected to layer on top, and for the reference implementation this
package was distilled from.
"""

from __future__ import annotations

#: Bump when a change here would make an existing block's extension modules
#: (its own corners.py additions, evidence.py subclass, runner.py deck hooks)
#: worth re-checking against this core.
HARNESS_VERSION = "1.0.0"

#: Where this package was distilled from — read to find the generic/
#: block-specific split, never forked or vendored wholesale. Recorded here so
#: a record's ``environment`` block can point back at it (see report.py).
UPSTREAM_PATTERN = "https://github.com/2AMLogic/gf180-sar-adc/tree/main/sim/harness"

__all__ = ["HARNESS_VERSION", "UPSTREAM_PATTERN"]
