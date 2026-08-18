#!/usr/bin/env python3
"""Compose runtime with Primary-owned NL routing and five cognitive skills."""

from __future__ import annotations

import sys

import compose_runtime_legacy as _legacy

for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)

_legacy.CONTROL_PLANE_SKILL_IDS = ()

_legacy.WORKFLOW_ENTRIES["ce-review"]["description"] = (
    "只读审查已有代码改动：PR、工作区 diff 或 base...head。PR source 已由 Workspace Manager "
    "固定到隔离 exact-head workspace，禁止用本地 fork 冒充。除 findings 外，汇总 changed_scope、"
    "affected_scope、risks、test_intent、validation_targets，作为后续 TG Planning Context。"
)
_legacy.WORKFLOW_ENTRIES["tg-plan"]["description"] = (
    "规划测试义务，只落 tg/plan.md。两项核心输入都必须存在：tg/init.yaml + Planning Context。"
    "PR 测试 flow 的 Planning Context 来自前置 ce-review；也可来自 ce-plan、用户显式计划或 handoff。"
    "再用 uo-query 语义落根，并补齐 coverage、precision、可执行 performance 与 replay/derived solve 判据。"
    "缺上下文返回 PLAN_CONTEXT_REQUIRED；缺列/生成器写 test_harness_gap，不默认全量 tilingkey。"
)

# Keep the Primary OpenCode permission contract explicit at the entrypoint. The
# implementation lives in compose_runtime_legacy.py, but these aliases make this
# file the visible SSOT for Host contract checks and future maintainers.
OPENCODE_PRIMARY_TASK_ALLOW = _legacy.OPENCODE_PRIMARY_TASK_ALLOW
opencode_primary_task_permission = _legacy.opencode_primary_task_permission
opencode_isolated_primary_permission = _legacy.opencode_isolated_primary_permission

# Concrete permissions that the implementation emits for Pilot Primary.
# Do **not** set top-level ``*: deny``: OpenCode would block normal read/grep.
_PRIMARY_REQUIRED_PERMISSIONS = {
    "external_directory": "allow",
    "read": "allow",
    "Get-ChildItem": "allow",
    "pilot_run": "allow",
}

# Export patched mutable objects too.
CONTROL_PLANE_SKILL_IDS = _legacy.CONTROL_PLANE_SKILL_IDS
WORKFLOW_ENTRIES = _legacy.WORKFLOW_ENTRIES

if __name__ == "__main__":
    sys.exit(_legacy.main())
