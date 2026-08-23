#!/usr/bin/env python3
"""Compose runtime: Commands + Action Skills. Primary owns routing; no closed skill families."""

from __future__ import annotations

import sys

import compose_runtime_legacy as _legacy

for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)

_legacy.CONTROL_PLANE_SKILL_IDS = ()

_legacy.WORKFLOW_ENTRIES["ce-review"]["description"] = (
    "只读审查已有代码改动：PR、工作区 diff 或 base...head。无 diff 则停。"
    "Spec 轴对照 `{slug}_plan.md`（无计划则从 diff 索引推断粗意图）；Standards 轴对照仓规范。"
    "结论留在对话。建议测试走 /tg-plan。用 `pilot_run`。"
)
_legacy.WORKFLOW_ENTRIES["tg-plan"]["description"] = (
    "白盒测试规划，只落 tg/plan.md。`plan_scope` 像 uo-query：说清要测什么，不写文件。"
    "fuse 交覆盖模型 YAML；Primary 写三节散文并校对 YAML；promote 拼成 plan.md。"
    "`/tg-plan` 不审查 diff。全量 tilingkey 仅当用户点名时用 coverage.enumerate: legal_keys。"
    "缺脚本/列/生成器写 test_harness_gap 交 /ce-apply。缺 fuse YAML → PLAN_FUSE_REQUIRED；缺散文 → PLAN_PROSE_REQUIRED。"
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
