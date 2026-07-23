---
name: uo-code-review
description: 基于 KB 的代码审查。 Harness 管阶段；本 Skill 只索引 Action。
disable-model-invocation: true
---

# uo-code-review

基于 KB 的代码审查。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `harness start/resume`；
2. 调用 `harness next`；
3. 加载返回 Action 对应的组合能力（Policy / Capability / Action Method / Prompt / Role）；
4. 执行一个 Action；
5. 将结果交回 Harness。

## Actions

| action_id | 名称 | method | agent |
|---|---|---|---|
| `code_review` | 代码审查 | `uo-code-review/code-review` | `uo-code-reviewer` |

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
| `code_review` | source-authority,code-access,evidence,language,harness-control,output-quality | structured-review,kb-query,cbm-navigation,source-reading | `uo-code-review/code-review` | `uo/code-review` | `uo-code-reviewer` |
