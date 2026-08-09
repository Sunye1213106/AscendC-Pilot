# -*- coding: utf-8 -*-
"""uo-init wall-time profiles.

``fast`` (default) targets cold uo-init ≤ ``UO_COLD_BUDGET_S`` (180s):
keypath controllability, no pairwise kernel fold.  ``full`` restores the
previous feature-complete path (full closure + fold).
"""
from __future__ import annotations

import os
from typing import Any


def profile_name(ctx: dict[str, Any] | None = None) -> str:
    raw = ""
    if isinstance(ctx, dict):
        raw = str(ctx.get("init_profile") or ctx.get("uo_init_profile") or "")
    if not raw:
        raw = os.environ.get("UO_INIT_PROFILE", "fast")
    name = str(raw or "fast").strip().lower()
    if name in {"complete", "all", "max"}:
        return "full"
    if name in {"budget", "cold", "3min", "quick"}:
        return "fast"
    if name not in {"fast", "full"}:
        return "fast"
    return name


def cold_budget_s() -> float:
    try:
        return float(os.environ.get("UO_COLD_BUDGET_S", "180"))
    except ValueError:
        return 180.0


def default_closure_mode(ctx: dict[str, Any] | None = None) -> str:
    """Product extract_host default when ctx omits closure_mode."""
    if isinstance(ctx, dict) and ctx.get("closure_mode") is not None:
        return str(ctx.get("closure_mode")).strip().lower() or "keypath"
    if isinstance(ctx, dict) and ctx.get("with_closure") is not None:
        raw = ctx.get("with_closure")
        if isinstance(raw, str):
            return raw.strip().lower() or "keypath"
        return "full" if raw else "off"
    return "keypath" if profile_name(ctx) == "fast" else "full"


def default_closure_max_nodes(ctx: dict[str, Any] | None = None) -> int:
    if isinstance(ctx, dict) and ctx.get("closure_max_nodes") not in (None, ""):
        try:
            return int(ctx.get("closure_max_nodes"))
        except (TypeError, ValueError):
            pass
    if profile_name(ctx) == "fast":
        try:
            return int(os.environ.get("UO_KEYPATH_MAX_NODES", "96"))
        except ValueError:
            return 96
    return 10**9


def default_fold_kernel(ctx: dict[str, Any] | None = None) -> bool:
    if isinstance(ctx, dict) and "fold_kernel" in ctx:
        return bool(ctx.get("fold_kernel"))
    env = os.environ.get("UO_FOLD_KERNEL")
    if env is not None and str(env).strip() != "":
        return str(env).strip().lower() not in {"0", "false", "off", "no"}
    return profile_name(ctx) == "full"


def review_skips_closure_gate(closure_mode: str) -> bool:
    """keypath/off never measured full source_closure — do not demand 0.95."""
    return str(closure_mode or "").strip().lower() in {
        "",
        "off",
        "none",
        "keypath",
        "budget",
    }
