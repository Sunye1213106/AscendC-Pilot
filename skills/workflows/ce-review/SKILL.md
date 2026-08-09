---
name: ce-review
description: 基于 KB 的代码审查 / code review / 查 bug。用户要审查算子代码时加载。Pilot 管阶段；加载后执行 acp start
  ce-review。
---

# ce-review

对算子代码做有源码证据的审查。

语义方法：`skills/domain/code-review/SKILL.md`。

## Pilot

1. `acp start`（同 workflow 活动 run 则复用）
2. `acp next`
3. `acp run-action <action_id>`（确定性自动 finalize；语义产出后 `--finalize`）
4. `acp advance`（仅消费可信收据）

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `code_review` | `subagent` | `ce-reviewer` | `readonly_reviewer` | `ce-review/code-review` | `ce/code-review` | `code-review-v1` |

<!-- END GENERATED ACTIONS -->
