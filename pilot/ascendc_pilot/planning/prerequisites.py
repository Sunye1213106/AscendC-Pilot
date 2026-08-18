# -*- coding: utf-8 -*-
"""Inspect on-disk state the planner uses after LLM intake (never before)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def available_state(project_root: Path | str, *, architecture: str = "") -> dict[str, Any]:
    """Facts the planner may use after Intent has been understood."""
    root = Path(project_root).expanduser().resolve()
    arch = str(architecture or "").strip()
    has_project = False
    try:
        from ascendc_pilot.intake import looks_like_operator_package

        has_project = looks_like_operator_package(root)
    except Exception:  # noqa: BLE001
        has_project = (root / "op_host").is_dir() or (root / "op_kernel").is_dir()

    has_uo = False
    uo_stale = False
    try:
        from ascendc_pilot.paths import uo_root

        uo_dir = uo_root(root, arch=arch or None)
        has_uo = uo_dir.is_dir() and any(uo_dir.glob("*.uo"))
    except Exception:  # noqa: BLE001
        agent = root / ".ascendc-pilot"
        has_uo = any(agent.glob("*/uo/*.uo")) if agent.is_dir() else False
    try:
        from ascendc_pilot.state import load_state

        st = load_state(root) or {}
        uo_stale = bool(st.get("uo_stale"))
        if not arch:
            arch = str(st.get("architecture") or "").strip()
    except Exception:  # noqa: BLE001
        pass

    scope_decided = False
    try:
        from ascendc_pilot.user_goal import load_user_goal

        goal = load_user_goal(root) or {}
        arts = goal.get("artifacts") if isinstance(goal.get("artifacts"), dict) else {}
        scope_decided = bool(arts.get("scope_decision") or arts.get("scope_receipt"))
    except Exception:  # noqa: BLE001
        pass

    has_tg_init = False
    try:
        from ascendc_pilot.paths import tg_root

        has_tg_init = (tg_root(root, arch=arch or None) / "init.yaml").is_file()
    except Exception:  # noqa: BLE001
        has_tg_init = False

    return {
        "has_project": has_project,
        "has_uo": has_uo,
        "uo_stale": uo_stale,
        "has_tg_init": has_tg_init,
        "architecture": arch,
        "scope_decided": scope_decided,
        "project": str(root),
    }
