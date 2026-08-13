# -*- coding: utf-8 -*-
"""CLI: discover missing-header -I dirs for one operator.

Used by prepare automatically. This script is the standalone / debug entry.

    python engines/understand-operator/tools/uo_heal_includes.py \\
        --op-dir <op> --arch-dir arch35 [--probe]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from uo_init.include_heal import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
