---
name: uo-query
description: >-
  只读查询 UO KB。 Harness 管阶段；本 Skill 只索引 Action。
disable-model-invocation: true
---

# uo-query

只读查询 UO KB。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `harness start/resume`；
2. 调用 `harness next`；
3. 加载返回 Action 对应的组合能力（Policy / Capability / Action Method / Prompt / Role）；
4. 执行一个 Action；
5. 将结果交回 Harness。

## Actions

| action_id | 名称 | method | agent |
|---|---|---|---|
| `kb_lookup` | KB 查询 | `uo-query/kb-lookup` | `uo-query` |
