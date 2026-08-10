---
name: tg-plan
description: >
  制定 TG 测试目标并冻结 target set。用户未指定目标时默认计划全部源码声明 TilingKey；
  指定 packed keys 或维度过滤条件时只计划该子集。Plan 不构造 case、不做可达性求解。
---

# tg-plan

领域规则：`skills/domain/tg-plan/SKILL.md`。

```text
intent → scope → gate → build → approve
```

核心产品是：

```text
tg/plan/levels/<level>/target_set.yaml
```

- `D` = 当前 Kernel template 声明域；
- `T` = 本次 Solve 目标，`T ⊆ D`；
- 无显式目标时 `T=D`；
- approve 冻结 `target_hash + snapshot_hash + plan_hash`；
- `tg-solve` 不得扩大 T。

Full TilingKey mode 的 precheck 检查 `.uo` 与当前 Kernel schema。`csv_consumer` 模式使用自己的 precheck 与契约路径。

## Pilot

`acp start tg-plan` → 按顺序执行 Action → `plan_approve`。禁止跳过 intent/build；目标变更必须重新 Plan/Approve。

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
