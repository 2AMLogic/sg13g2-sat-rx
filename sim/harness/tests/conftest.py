"""Put sim/ on sys.path so ``import harness`` works from any cwd.

These tests need neither ngspice nor a PDK: they exercise corner expansion,
manifest validation and record rendering on synthetic results.
"""

import sys
from pathlib import Path

SIM = Path(__file__).resolve().parents[2]
if str(SIM) not in sys.path:
    sys.path.insert(0, str(SIM))
