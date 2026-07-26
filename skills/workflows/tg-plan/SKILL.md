---
name: tg-plan
description: 生成覆盖规划 / 覆盖义务并人工批准（tg-plan、coverage）。用户要覆盖计划时加载。 Pilot 管阶段；加载后执行 acp
  start tg-plan。
---

# tg-plan

生成覆盖义务并人工批准。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `acp start`（同 workflow 活动 run 则复用）；
2. 调用 `acp next`；
3. 对返回的 action_id 调用 `acp run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后调用 `acp run-action <action_id> --finalize`；
5. 调用 `acp advance`（仅消费 run-action 签发的可信收据）。

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `plan_scope` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-plan/plan-scope` | `-` | `plan-scope-v1` |
| `plan_precheck` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-plan/plan-precheck` | `-` | `plan-precheck-v1` |
| `plan_build` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-plan/plan-build` | `-` | `plan-build-v1` |
| `plan_approve` | `primary_interactive` | `ascendc-pilot` | `controller` | `tg-plan/plan-approve` | `tg/plan-approve` | `plan-approved-v1` |

<!-- END GENERATED ACTIONS -->

