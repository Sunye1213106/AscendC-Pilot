---
name: tg-plan
description: 生成覆盖义务并人工批准。 Harness 管阶段；本 Skill 只索引 Action。
---

# tg-plan

生成覆盖义务并人工批准。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `harness start`（同 workflow 活动 run 则复用）；
2. 调用 `harness next`；
3. 对返回的 action_id 调用 `harness run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后调用 `harness run-action <action_id> --finalize`；
5. 调用 `harness advance`（仅消费 run-action 签发的可信收据）。

## Actions

| action_id | 名称 | method | agent | role |
|---|---|---|---|---|
| `plan_scope` | 确定规划范围 | `tg-plan/plan-scope` | `deterministic-tg-engine` | `deterministic_engine` |
| `plan_precheck` | 规划前置门禁 | `tg-plan/plan-precheck` | `deterministic-tg-engine` | `deterministic_engine` |
| `plan_build` | 生成覆盖义务 | `tg-plan/plan-build` | `deterministic-tg-engine` | `deterministic_engine` |
| `plan_approve` | 批准规划 | `tg-plan/plan-approve` | `human` | `-` |

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
| `plan_scope` | source-authority,code-access,evidence,language,harness-control,output-quality | obligation-analysis,kb-query | `tg-plan/plan-scope` | `-` | `deterministic-tg-engine` |
| `plan_precheck` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `tg-plan/plan-precheck` | `-` | `deterministic-tg-engine` |
| `plan_build` | source-authority,code-access,evidence,language,harness-control,output-quality | obligation-analysis,kb-query | `tg-plan/plan-build` | `-` | `deterministic-tg-engine` |
| `plan_approve` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `tg-plan/plan-approve` | `tg/plan-approve` | `human` |

## Action runtime index

| action_id | method_path | prompt_path | output_contract | role |
|---|---|---|---|---|
| `plan_scope` | `actions/plan-scope/METHOD.md` | `-` | `plan-scope-v1` | `deterministic_engine` |
| `plan_precheck` | `actions/plan-precheck/METHOD.md` | `-` | `plan-precheck-v1` | `deterministic_engine` |
| `plan_build` | `actions/plan-build/METHOD.md` | `-` | `plan-build-v1` | `deterministic_engine` |
| `plan_approve` | `actions/plan-approve/METHOD.md` | `prompts/tasks/tg/plan-approve.md` | `plan-approved-v1` | `-` |
