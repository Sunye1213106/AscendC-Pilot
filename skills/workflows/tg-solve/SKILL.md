---
name: tg-solve
description: Z3 求解与 CSV 投影 / 生成测例 CSV。用户说求解、tg-solve、生成 csv 时加载。 Pilot 管阶段；加载后执行 acp
  start tg-solve。
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

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `solve_precheck` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/solve-precheck` | `-` | `solve-precheck-v1` |
| `z3_solve` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/z3-solve` | `-` | `z3-solve-v1` |
| `cover_confirm` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/cover-confirm` | `-` | `cover-confirm-v1` |

<!-- END GENERATED ACTIONS -->

