---
name: uo-query
description: 只读查询 UO 知识库 / 问答 / 查某个 KEY。用户提问已有 KB 内容时加载。 Pilot 管阶段；加载后执行 acp start
  uo-query。
---

# uo-query

编排只读 KB 查询。领域认知：`skills/domain/uo-kb-query`。

## Pilot

`acp start` → `next` → `run-action` →（语义则 finalize）→ `advance`。

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `kb_lookup` | `subagent` | `uo-query` | `readonly_analyst` | `uo-query/kb-lookup` | `uo/kb-lookup` | `kb-answer-v1` |

<!-- END GENERATED ACTIONS -->
