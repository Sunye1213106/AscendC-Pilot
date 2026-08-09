---
name: uo-query
description: 只读查询 UO 知识库 / 问答 / 查某个 KEY。用户提问已有 KB 内容时加载。 Pilot 管阶段；加载后执行 acp start
  uo-query。
---

# uo-query

只读查询 UO KB。

语义方法：`skills/domain/uo-kb-query/SKILL.md`。

## Pilot

1. `acp start`（同 workflow 活动 run 则复用）
2. `acp next`
3. `acp run-action <action_id>`（确定性自动 finalize；语义产出后 `--finalize`）
4. `acp advance`（仅消费可信收据）

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `kb_lookup` | `subagent` | `uo-query` | `readonly_analyst` | `uo-query/kb-lookup` | `uo/kb-lookup` | `kb-answer-v1` |

<!-- END GENERATED ACTIONS -->
