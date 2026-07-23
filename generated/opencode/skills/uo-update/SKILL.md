---
name: uo-update
description: 增量更新 UO KB；含 diff_only。 Pilot 管阶段；本 Skill 只索引 Action。
---

# uo-update

增量更新 UO KB；含 diff_only。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `acp start`（同 workflow 活动 run 则复用）；
2. 调用 `acp next`；
3. 对返回的 action_id 调用 `acp run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后调用 `acp run-action <action_id> --finalize`；
5. 调用 `acp advance`（仅消费 run-action 签发的可信收据）。

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

## Composed: pilot-control

# Policy: pilot-control

## Purpose

Pilot 独占状态、合法边、门禁与完成态。

## Rules

1. 只能执行 `acp next` 返回的 Action。
2. Skill、Prompt、Agent、Capability、Action Method **不得**推进工作流状态。
3. 终态只认 `acp complete`；禁止自行宣布 `done` / `passed`。
4. Gate fail ≠ 立即 `blocked`；保持 phase，进入 `rework_required` / `human_required`。
5. 禁止直调领域 CLI（`build_layered_kb.py`、`tg-init`、`tg-plan`、`tg-solve` 等）；须经 acp 包装。
6. 正式产物须 Pilot 签发收据。
7. **进度只进 OpenCode 原生 Todo**（见下方「原生 Todo」）；禁止在主对话输出工作流状态面板。
8. bash 优先用工具 `workdir` 指向算子目录；若写 `cd <dir> && acp …`，Pilot 只认末尾纯 `acp` 段（禁止夹杂其它命令）。

## 原生 Todo（所有 workflow 共用 · OpenCode `todowrite`）

阶段列表**不得**写死在各 Skill 里。一律以当前路由工作流为准：

1. `acp route` / `acp start <workflow_id>` 确定活动工作流。
2. 响应里的 `todo.todo_sync.items`（与 `todo.native_items` 相同）即该工作流在 Spec 中的**完整**阶段（必须含 `id` + 中文 `content` + `status`）。
3. **`acp start` 成功后立刻**按 `todo.todo_sync` 调用 `todowrite`：`merge` 取 JSON 中的布尔值（新 start 为 `false`）。
4. 之后每次 `acp next` / `advance` / `rework` / `complete` / `status`：再按最新 `todo.todo_sync` 同步（`merge: true`）。
5. **硬约束（违反即视为控制面违规）**：
   - `todos` **必须等于** `todo.todo_sync.items` 全量（长度与每个 `id` 一致）。
   - **禁止**只写当前阶段、禁止省略 `id`、禁止子集覆盖导致其它阶段从面板消失。
   - 任意时刻最多一个 `in_progress`。
6. 状态映射（若只有 `phases[].status`）：`done`→`completed`，`current`→`in_progress`，`pending`→`pending`。工作流 `passed` 后全部 `completed`。
7. **禁止**向用户粘贴或复述：`Workflow TODO`、`todo_md`、`.ascendc-pilot/todo.md`、`状态：running`、`当前阶段`、阶段 checklist、`下一步 Action`、`正在执行 …`。进度只出现在右侧 Todo 面板。

## Runtime loop (primary only)

1. `acp route` / `acp start`（若无活动 run）→ 立刻按 `todo.todo_sync` 做 `todowrite`
2. `acp next` → 取 Action，并用 `todowrite` 全量同步（不向用户粘贴阶段表）
3. 执行一个 Action 的领域方法
4. 交回 Pilot（advance / rework / complete 由控制面决定）→ 再 `todowrite` 全量同步

## Composition index

| action_id | policies | capabilities | method | prompt | agent |
|---|---|---|---|---|---|
| `detect_changes` | source-authority,code-access,evidence,language,pilot-control,output-quality | source-reading | `uo-update/detect-changes` | `-` | `deterministic-uo-engine` |
| `plan_update` | source-authority,code-access,evidence,language,pilot-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-update/plan-update` | `uo/plan-update` | `uo-semantic-resolve` |
| `apply_update` | source-authority,code-access,evidence,language,pilot-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-update/apply-update` | `uo/apply-update` | `uo-semantic-resolve` |
| `key_resolution` | source-authority,code-access,evidence,language,pilot-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-update/key-resolution` | `uo/key-resolution` | `uo-key-resolve` |
| `confidence_report` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-update/confidence-report` | `-` | `deterministic-uo-engine` |
| `confidence_review` | source-authority,code-access,evidence,language,pilot-control,output-quality | structured-review,kb-query | `uo-update/confidence-review` | `uo/confidence-review` | `uo-confidence-review` |
| `export_integrity` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-update/export-integrity` | `-` | `deterministic-uo-engine` |
| `diff_summary` | source-authority,code-access,evidence,language,pilot-control,output-quality | kb-query | `uo-update/diff-summary` | `-` | `deterministic-uo-engine` |
| `diff_only` | source-authority,code-access,evidence,language,pilot-control,output-quality | kb-query | `uo-update/diff-only` | `-` | `deterministic-uo-engine` |

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
