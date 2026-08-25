# -*- coding: utf-8 -*-
"""Run Plan → Solve contract (validate_plan_fence + compile_obligations)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ENGINE = Path(__file__).resolve().parents[2] / "engines" / "testcase-generation"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))


def _column_names(init: dict[str, Any] | None, fallback: list[str] | None = None) -> list[str]:
    names: list[str] = []
    if isinstance(init, dict):
        for item in init.get("columns") or []:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
            else:
                name = str(item or "").strip()
            if name:
                names.append(name)
    if names:
        return names
    return [str(c).strip() for c in (fallback or []) if str(c).strip()]


def solve_contract_errors(
    fence: dict[str, Any],
    init: dict[str, Any] | None,
    *,
    fallback_columns: list[str] | None = None,
) -> list[str]:
    from testcase_agent import products
    from testcase_agent.coverage.compile import PlanCompileError, compile_obligations
    from testcase_agent.plan_fill import AssembleError, ensure_v3

    try:
        fence = ensure_v3(fence, init)
    except AssembleError as exc:
        return list(exc.errors)

    cols = _column_names(init, fallback_columns)
    mapping = init.get("mapping") if isinstance(init, dict) else None
    errors = products.validate_plan_fence(fence, init_columns=cols, init_mapping=mapping)
    if errors:
        return errors
    try:
        compile_obligations(fence)
    except PlanCompileError as exc:
        return list(exc.errors)
    return []
