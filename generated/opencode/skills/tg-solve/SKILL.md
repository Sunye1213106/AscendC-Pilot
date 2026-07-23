---
name: tg-solve
description: Z3 求解与 CSV 投影。 Harness 管阶段；本 Skill 只索引 Action。
---

# tg-solve

Z3 求解与 CSV 投影。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `harness start`（同 workflow 活动 run 则复用）；
2. 调用 `harness next`；
3. 对返回的 action_id 调用 `harness run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后调用 `harness run-action <action_id> --finalize`；
5. 调用 `harness advance`（仅消费 run-action 签发的可信收据）。

## Actions

| action_id | 名称 | method | agent | role |
|---|---|---|---|---|
| `solve_precheck` | 求解前置校验 | `tg-solve/solve-precheck` | `deterministic-tg-engine` | `deterministic_engine` |
| `z3_solve` | 求解并投影 | `tg-solve/z3-solve` | `deterministic-tg-engine` | `deterministic_engine` |
| `cover_confirm` | 覆盖确认 | `tg-solve/cover-confirm` | `deterministic-tg-engine` | `deterministic_engine` |

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
| `solve_precheck` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `tg-solve/solve-precheck` | `-` | `deterministic-tg-engine` |
| `z3_solve` | source-authority,code-access,evidence,language,harness-control,output-quality | obligation-analysis | `tg-solve/z3-solve` | `-` | `deterministic-tg-engine` |
| `cover_confirm` | source-authority,code-access,evidence,language,harness-control,output-quality | obligation-analysis | `tg-solve/cover-confirm` | `-` | `deterministic-tg-engine` |

## Action runtime index

| action_id | method_path | prompt_path | output_contract | role |
|---|---|---|---|---|
| `solve_precheck` | `actions/solve-precheck/METHOD.md` | `-` | `solve-precheck-v1` | `deterministic_engine` |
| `z3_solve` | `actions/z3-solve/METHOD.md` | `-` | `z3-solve-v1` | `deterministic_engine` |
| `cover_confirm` | `actions/cover-confirm/METHOD.md` | `-` | `cover-confirm-v1` | `deterministic_engine` |
