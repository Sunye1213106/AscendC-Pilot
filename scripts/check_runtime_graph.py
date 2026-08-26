#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime graph check with repository engine import roots bootstrapped."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for rel in (
    "pilot",
    "engines/understand-operator/src",
    "engines/testcase-generation",
    "engines/code-engineering",
    "engines/common",
):
    path = REPO / rel
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import check_runtime_graph_legacy as _legacy  # noqa: E402

for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)

if __name__ == "__main__":
    raise SystemExit(_legacy._main())
