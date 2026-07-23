---
name: uo-update
description: 增量更新 UO KB；含 diff_only。 Harness 管阶段；本 Skill 只索引 Action。
---

# uo-update

增量更新 UO KB；含 diff_only。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `harness start`（同 workflow 活动 run 则复用）；
2. 调用 `harness next`；
3. 对返回的 action_id 调用 `harness run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后调用 `harness run-action <action_id> --finalize`；
5. 调用 `harness advance`（仅消费 run-action 签发的可信收据）。

## Actions

| action_id | 名称 | method | agent | role |
|---|---|---|---|---|
| `detect_changes` | 检测源码变更 | `uo-update/detect-changes` | `deterministic-uo-engine` | `deterministic_engine` |
| `plan_update` | 制定更新计划 | `uo-update/plan-update` | `uo-semantic-resolve` | `producer` |
| `apply_update` | 应用变更 | `uo-update/apply-update` | `uo-semantic-resolve` | `producer` |
| `key_resolution` | KEY 语义闭合 | `uo-update/key-resolution` | `uo-key-resolve` | `producer` |
| `confidence_report` | 生成置信度报告 | `uo-update/confidence-report` | `deterministic-uo-engine` | `deterministic_engine` |
| `confidence_review` | 置信度原因审查 | `uo-update/confidence-review` | `uo-confidence-review` | `referee` |
| `export_integrity` | 导出与完整性校验 | `uo-update/export-integrity` | `deterministic-uo-engine` | `deterministic_engine` |
| `diff_summary` | 只读差异摘要 | `uo-update/diff-summary` | `deterministic-uo-engine` | `deterministic_engine` |
| `diff_only` | 仅差异摘要（跳过完整更新） | `uo-update/diff-only` | `deterministic-uo-engine` | `deterministic_engine` |

## Composed: harness-control

# Policy: harness-control

## Purpose

Harness 独占状态、合法边、门禁与完成态。

## Rules

1. 只能执行 `harness next` 返回的 Action。
2. Skill、Prompt、Agent、Capability、Action Method **不得**推进工作流状态。
3. 终态只认 `harness complete`；禁止自行宣布 `done` / `passed`。
4. Gate fail ≠ 立即 `blocked`；保持 phase，进入 `rework_required` / `human_required`。
5. 禁止直调领域 CLI（`build_layered_kb.py`、`tg-init`、`tg-plan`、`tg-solve` 等）；须经 harness 包装。
6. 正式产物须 Harness 签发收据。

## Runtime loop (primary only)

1. `harness route` / `harness start`（若无活动 run）
2. `harness next` → 取 Action
3. 执行一个 Action 的领域方法
4. 交回 Harness（advance / rework / complete 由控制面决定）

## Composition index

| action_id | policies | capabilities | method | prompt | agent |
|---|---|---|---|---|---|
| `detect_changes` | source-authority,code-access,evidence,language,harness-control,output-quality | source-reading | `uo-update/detect-changes` | `-` | `deterministic-uo-engine` |
| `plan_update` | source-authority,code-access,evidence,language,harness-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-update/plan-update` | `uo/plan-update` | `uo-semantic-resolve` |
| `apply_update` | source-authority,code-access,evidence,language,harness-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-update/apply-update` | `uo/apply-update` | `uo-semantic-resolve` |
| `key_resolution` | source-authority,code-access,evidence,language,harness-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-update/key-resolution` | `uo/key-resolution` | `uo-key-resolve` |
| `confidence_report` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `uo-update/confidence-report` | `-` | `deterministic-uo-engine` |
| `confidence_review` | source-authority,code-access,evidence,language,harness-control,output-quality | structured-review,kb-query | `uo-update/confidence-review` | `uo/confidence-review` | `uo-confidence-review` |
| `export_integrity` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `uo-update/export-integrity` | `-` | `deterministic-uo-engine` |
| `diff_summary` | source-authority,code-access,evidence,language,harness-control,output-quality | kb-query | `uo-update/diff-summary` | `-` | `deterministic-uo-engine` |
| `diff_only` | source-authority,code-access,evidence,language,harness-control,output-quality | kb-query | `uo-update/diff-only` | `-` | `deterministic-uo-engine` |

## Action runtime index

| action_id | method_path | prompt_path | output_contract | role |
|---|---|---|---|---|
| `detect_changes` | `actions/detect-changes/METHOD.md` | `-` | `change-detect-v1` | `deterministic_engine` |
| `plan_update` | `actions/plan-update/METHOD.md` | `prompts/tasks/uo/plan-update.md` | `update-plan-v1` | `producer` |
| `apply_update` | `actions/apply-update/METHOD.md` | `prompts/tasks/uo/apply-update.md` | `update-apply-v1` | `producer` |
| `key_resolution` | `actions/key-resolution/METHOD.md` | `prompts/tasks/uo/key-resolution.md` | `input-derivable-patch-v1` | `producer` |
| `confidence_report` | `actions/confidence-report/METHOD.md` | `-` | `confidence-report-v1` | `deterministic_engine` |
| `confidence_review` | `actions/confidence-review/METHOD.md` | `prompts/tasks/uo/confidence-review.md` | `confidence-reason-review-v1` | `referee` |
| `export_integrity` | `actions/export-integrity/METHOD.md` | `-` | `integrity-v1` | `deterministic_engine` |
| `diff_summary` | `actions/diff-summary/METHOD.md` | `-` | `diff-summary-v1` | `deterministic_engine` |
| `diff_only` | `actions/diff-only/METHOD.md` | `-` | `diff-summary-v1` | `deterministic_engine` |
