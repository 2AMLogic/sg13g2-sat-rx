"""Put this bench's directory on sys.path so ``import mcpair`` works from any cwd.

These tests need neither ngspice, a PDK nor klt: they exercise request shape,
report ingestion, the known-answer gates and the sabotage negative controls on
synthetic reports.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
