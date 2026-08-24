# -*- coding: utf-8 -*-
"""Cursor / MCP launcher. Sets sys.path; no PYTHONPATH required in mcp.json."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "pilot"),
    str(ROOT / "engines" / "understand-operator" / "src"),
    str(ROOT / "engines" / "testcase-generation"),
]

from uo_init.query_mcp import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
