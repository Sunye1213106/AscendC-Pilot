---
name: tg-plan
description: >-
  生成覆盖规划 / 覆盖义务并人工批准（tg-plan、coverage）。用户要覆盖计划时加载。
  Pilot 管阶段；加载后执行 acp start tg-plan。
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

| action_id | 名称 | method | agent |
|---|---|---|---|
| `plan_scope` | 确定规划范围 | `tg-plan/plan-scope` | `deterministic-tg-engine` |
| `plan_precheck` | 规划前置门禁 | `tg-plan/plan-precheck` | `deterministic-tg-engine` |
| `plan_build` | 生成覆盖义务 | `tg-plan/plan-build` | `deterministic-tg-engine` |
| `plan_approve` | 批准规划 | `tg-plan/plan-approve` | `human` |
