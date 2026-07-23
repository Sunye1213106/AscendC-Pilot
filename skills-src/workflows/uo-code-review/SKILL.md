---
name: uo-code-review
description: >-
  基于 KB 的代码审查。 Harness 管阶段；本 Skill 只索引 Action。
disable-model-invocation: true
---

# uo-code-review

基于 KB 的代码审查。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `harness start/resume`；
2. 调用 `harness next`；
3. 加载返回 Action 对应的组合能力（Policy / Capability / Action Method / Prompt / Role）；
4. 执行一个 Action；
5. 将结果交回 Harness。

## Actions

| action_id | 名称 | method | agent |
|---|---|---|---|
| `code_review` | 代码审查 | `uo-code-review/code-review` | `uo-code-reviewer` |
