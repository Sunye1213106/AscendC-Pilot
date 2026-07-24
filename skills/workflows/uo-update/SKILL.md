---
name: uo-update
description: >-
  增量更新 / 刷新已有 UO 知识库（含 diff_only）。用户说更新 KB、刷新知识库时加载。
  Pilot 管阶段；加载后执行 acp start uo-update。
---

# uo-update

增量更新 UO KB；含 diff_only。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `acp start uo-update`（同 workflow 活动 run 则复用）；
2. 调用 `acp next`；
3. 对返回的 action_id 调用 `acp run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Bundle 派发 actor → `acp run-action <action_id> --finalize`；
5. 需要推进时：`acp advance <next_phase>`。

## Actions

| action_id | 名称 | agent |
|---|---|---|
| `detect_changes` | 检测源码变更 | `deterministic-uo-engine` |
| `plan_update` | 制定更新计划 | `deterministic-uo-engine` |
| `apply_update` | 应用变更 | `deterministic-uo-engine` |
| `key_resolution` | KEY 语义闭合 | `uo-key-resolve` |
| `confidence_report` | 生成置信度报告 | `deterministic-uo-engine` |
| `confidence_review` | 置信度原因审查 | `uo-confidence-review` |
| `export_integrity` | 导出与完整性校验 | `deterministic-uo-engine` |
| `diff_summary` / `diff_only` | 只读差异摘要 | `deterministic-uo-engine` |
