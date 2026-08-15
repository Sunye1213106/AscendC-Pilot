# -*- coding: utf-8 -*-
"""Deterministic uo-query fan-out, Cursor-style.

The QueryPlan compiler lives in ``uo_init.query.plan``. This module re-exports
it so Host/Runtime keep a stable import path.
"""

from __future__ import annotations

from uo_init.query.plan import (  # noqa: F401
    MAX_SLICES,
    compile_query,
    focused_user_question,
    is_differential_question,
    is_ut_authoring,
    plan_query_slices,
)

__all__ = [
    "MAX_SLICES",
    "compile_query",
    "focused_user_question",
    "is_differential_question",
    "is_ut_authoring",
    "plan_query_slices",
]
