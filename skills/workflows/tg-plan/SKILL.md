---
name: tg-plan
description: 覆盖规划：默认全量 TilingKey 闭环；也可按用户描述或 PR 生成计划。用户要覆盖计划、 tg-plan、tilingkey 义务时加载。Pilot
  管阶段；加载后 acp start tg-plan。
---

# tg-plan

生成覆盖义务并人工批准。

## 链路位置

```text
uo-init → tg-init → tg-plan → tg-solve
```

## 默认意图

未指定时：`mode=tilingkey_full_coverage`（目标 `D=(R∩D)∪E`，不依赖 CSV）。

`plan_intent`（primary）AskQuestion 三选一：默认全量 / 用户描述 / PR。

## 硬规则

1. `acp start` → `acp next` → `acp run-action` →（语义则 finalize）→ `acp advance`
2. 禁止跳过 `plan_intent` 直接 build
3. 禁止自行宣布 passed；终态只认 `acp complete`
4. 进度只进原生 Todo

## 阶段意图

```text
intent → scope → gate → build → approve
```

- `plan_build`：tilingkey 模式写闭环义务；csv 模式走原 `tg_plan()`
- `plan_approve`：人工批准

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `plan_intent` | `primary_interactive` | `ascendc-pilot` | `controller` | `tg-plan/plan-intent` | `tg/plan-intent` | `plan-intent-v1` |
| `plan_scope` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-plan/plan-scope` | `-` | `plan-scope-v1` |
| `plan_precheck` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-plan/plan-precheck` | `-` | `plan-precheck-v1` |
| `plan_build` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-plan/plan-build` | `-` | `plan-build-v1` |
| `plan_approve` | `primary_interactive` | `ascendc-pilot` | `controller` | `tg-plan/plan-approve` | `tg/plan-approve` | `plan-approved-v1` |

<!-- END GENERATED ACTIONS -->
