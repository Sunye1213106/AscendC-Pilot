---
name: uo-update
description: 增量更新 / 刷新已有 UO 知识库（含 diff_only）。用户说更新 KB、刷新知识库时加载。 Pilot 管阶段；加载后执行 acp
  start uo-update。
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

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `detect_changes` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/detect-changes` | `-` | `change-detect-v1` |
| `plan_update` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/plan-update` | `-` | `update-plan-v1` |
| `apply_update` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/apply-update` | `-` | `update-apply-v1` |
| `key_triage` | `subagent` | `uo-key-resolve` | `producer` | `uo-init/key-triage` | `uo/key-triage` | `key-triage-v1` |
| `key_resolution` | `subagent` | `uo-key-resolve` | `producer` | `uo-init/key-resolution` | `uo/key-resolution` | `input-derivable-patch-v1` |
| `confidence_report` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/confidence-report` | `-` | `confidence-report-v1` |
| `confidence_review` | `subagent` | `uo-confidence-review` | `referee` | `uo-init/confidence-review` | `uo/confidence-review` | `confidence-reason-review-v1` |
| `export_integrity` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/export-integrity` | `-` | `integrity-v1` |
| `diff_summary` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/diff-summary` | `-` | `diff-summary-v1` |
| `diff_only` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/diff-only` | `-` | `diff-summary-v1` |

<!-- END GENERATED ACTIONS -->

