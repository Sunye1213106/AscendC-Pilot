---
name: uo-code-review
description: >-
  基于 KB 的代码审查。 Harness 管阶段；本 Skill 只索引 Action。
disable-model-invocation: true
---

# uo-code-review

基于 KB 的代码审查。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `harness start`（同 workflow 活动 run 则复用）；
2. 调用 `harness next`；
3. 对返回的 action_id 调用 `harness run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后调用 `harness run-action <action_id> --finalize`；
5. 调用 `harness advance`（仅消费 run-action 签发的可信收据）。

## Actions

| action_id | 名称 | method | agent |
|---|---|---|---|
| `code_review` | 代码审查 | `uo-code-review/code-review` | `uo-code-reviewer` |
