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
    "固定到隔离 exact-head workspace，禁止用本地 fork 冒充。双轴 Task 必须由主控同一轮派发"
    "（子代不得再派 Task）；结论在 Task 回复，插件用原文 ACK。"
    "对人的汇总是：审查完成、意图是什么、改了哪些文件、计划达成怎样、问题 1…、若测应重点测什么。"
    "意图只是一次审查时留在主线，不要再包 coordinator。"
    "审查结束后返回 Primary；勾掉 Todo 后再 `pilot_run` 下一格，不要再 auto intake。"
)
_legacy.WORKFLOW_ENTRIES["tg-plan"]["description"] = (
    "规划测试义务，只落 tg/plan.md。两项核心输入都必须存在：tg/init.yaml + Planning Context。"
    "Planning Context 来自 ce-review 结论、ce-plan「测试内容」、用户已陈述范围、handoff、"
    "或用户明确只要用例时主控综合的 uo-query 结论；`/tg-plan` 不审查 diff。"
    "把测试意图落到有限覆盖子集（CSV/XLS 列或代码变量）及精度/性能要求。"
    "缺脚本/列/生成器（含随机数）写 test_harness_gap 说明书交 /ce-apply，不默认全量 tilingkey。"
    "缺 Planning Context 返回 PLAN_CONTEXT_REQUIRED。"
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
