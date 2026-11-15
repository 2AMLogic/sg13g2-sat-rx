#!/usr/bin/env python3
"""Evidence-format and append-only checker for sim/*/ evidence trees.

Thin CLI shim: the implementation lives in the stdlib-only ``evidence_checks``
package beside this file (see evidence_checks/core.py for the full description
of what is checked). Every public name of the former single-file checker is
re-exported here, so ``import check_evidence_formats`` keeps working.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

for _m in ("common", "artifact_manifests", "native", "kaband", "passive_p1", "mixer_nf", "mixer_cm", "mixer_pra",
           "mixer_feas", "lna_match", "lna_core", "lna_linearity", "lna_headroom", "hbt_mismatch_pair",
           "readmes", "spec_rows", "core"):
    _mod = importlib.import_module(f"evidence_checks.{_m}")
    globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})

if __name__ == "__main__":
    sys.exit(main())  # noqa: F821
