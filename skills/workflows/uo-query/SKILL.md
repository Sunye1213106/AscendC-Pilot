---
name: uo-query
description: >-
  只读查询 UO KB。 Pilot 管阶段；本 Skill 只索引 Action。
disable-model-invocation: true
---

# uo-query

只读查询 UO KB。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `acp start`（同 workflow 活动 run 则复用）；
2. 调用 `acp next`；
3. 对返回的 action_id 调用 `acp run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后调用 `acp run-action <action_id> --finalize`；
5. 调用 `acp advance`（仅消费 run-action 签发的可信收据）。

## Actions

| action_id | 名称 | method | agent |
|---|---|---|---|
| `kb_lookup` | KB 查询 | `uo-query/kb-lookup` | `uo-query` |
