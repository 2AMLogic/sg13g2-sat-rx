import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
