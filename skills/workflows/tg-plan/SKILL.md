---
name: tg-plan
description: 覆盖规划：默认全量 TilingKey 闭环；也可按用户描述或 PR 生成计划。用户要覆盖计划、 tg-plan、tilingkey 义务时加载。Pilot
  管阶段；加载后 acp start tg-plan。
---

# tg-plan

生成覆盖义务并批准。

语义方法：`skills/domain/tg-plan/SKILL.md`。

链路：`uo-init → tg-init → tg-plan → tg-solve`。  
默认意图：`mode=tilingkey_full_coverage`。

## Pilot

1. `acp start` → `acp next` → `acp run-action` →（语义则 finalize）→ `acp advance`
2. 禁止跳过 `plan_intent` 直接 build
3. 禁止自行宣布 workflow passed

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
