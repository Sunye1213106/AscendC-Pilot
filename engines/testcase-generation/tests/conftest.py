from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT.parent / "common"
for path in (ROOT, COMMON):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
