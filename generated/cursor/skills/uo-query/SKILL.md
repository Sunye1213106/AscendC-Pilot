---
name: uo-query
description: 只读查询 UO KB。 Harness 管阶段；本 Skill 只索引 Action。
disable-model-invocation: true
---

# uo-query

只读查询 UO KB。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `harness start`（同 workflow 活动 run 则复用）；
2. 调用 `harness next`；
3. 对返回的 action_id 调用 `harness run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后调用 `harness run-action <action_id> --finalize`；
5. 调用 `harness advance`（仅消费 run-action 签发的可信收据）。

## Actions

| action_id | 名称 | method | agent | role |
|---|---|---|---|---|
| `kb_lookup` | KB 查询 | `uo-query/kb-lookup` | `uo-query` | `readonly_analyst` |

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
| `kb_lookup` | source-authority,code-access,evidence,language,harness-control,output-quality | kb-query,cbm-navigation,source-reading | `uo-query/kb-lookup` | `uo/kb-lookup` | `uo-query` |

## Action runtime index

| action_id | method_path | prompt_path | output_contract | role |
|---|---|---|---|---|
| `kb_lookup` | `actions/kb-lookup/METHOD.md` | `prompts/tasks/uo/kb-lookup.md` | `kb-answer-v1` | `readonly_analyst` |
