---
name: ce-review
description: 基于 KB 的代码审查 / code review / 查 bug。用户要审查算子代码时加载。Pilot 管阶段；加载后执行 acp start
  ce-review。
---

# ce-review

编排代码审查 Action。

领域认知：`skills/domain/code-review`。

## Pilot

`acp start` → `next` → `run-action` →（语义则 finalize）→ `advance`。

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `code_review` | `subagent` | `ce-reviewer` | `readonly_reviewer` | `ce-review/code-review` | `ce/code-review` | `code-review-v1` |

<!-- END GENERATED ACTIONS -->
