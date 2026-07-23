#!/usr/bin/env python3
"""Compatibility forwarder for uo_kb_query.

Agents sometimes invent SCRIPT_DIR as skills/uo-query/scripts/. The real CLI
lives at $PLUGIN_ROOT/engines/uo/uo/scripts/uo_kb_query.py. This stub keeps both paths
working when the skill tree is junctioned from the plugin repo.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def _resolve_real_script() -> Path:
    # .../skills/uo-query/scripts/uo_kb_query.py -> plugin root is parents[3]
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "uo" / "scripts" / "uo_kb_query.py",
        Path.home()
        / ".config"
        / "opencode"
        / "understand-operator-plugin"
        / "uo"
        / "scripts"
        / "uo_kb_query.py",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "uo_kb_query.py not found. Expected under PLUGIN_ROOT/engines/uo/uo/scripts/. "
        f"Tried: {[str(p) for p in candidates]}"
    )


if __name__ == "__main__":
    real = _resolve_real_script()
    sys.argv[0] = str(real)
    runpy.run_path(str(real), run_name="__main__")
