---
name: tg-solve
description: >-
  Z3 求解与 CSV 投影。 Pilot 管阶段；本 Skill 只索引 Action。
disable-model-invocation: true
---

# tg-solve

Z3 求解与 CSV 投影。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `acp start`（同 workflow 活动 run 则复用）；
2. 调用 `acp next`；
3. 对返回的 action_id 调用 `acp run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后调用 `acp run-action <action_id> --finalize`；
5. 调用 `acp advance`（仅消费 run-action 签发的可信收据）。

## Actions

| action_id | 名称 | method | agent |
|---|---|---|---|
| `solve_precheck` | 求解前置校验 | `tg-solve/solve-precheck` | `deterministic-tg-engine` |
| `z3_solve` | 求解并投影 | `tg-solve/z3-solve` | `deterministic-tg-engine` |
| `cover_confirm` | 覆盖确认 | `tg-solve/cover-confirm` | `deterministic-tg-engine` |
