---
name: uo-query
description: >
  只读查询已有 AscendC `.uo` CodeMap，回答 API、Host、TilingKey/TilingData、
  Kernel、模板、宏、编译期变量、架构和数据流问题。用户询问已有 UO 内容、
  某个 KEY/字段/路径或 CodeMap 完整性时使用。
---

# uo-query

编排只读 `.uo` CodeMap 查询。领域方法按需读取 `skills/domain/uo-codemap-query/SKILL.md`。

查询 Agent 只执行当前 Action Bundle 的问题；结构化 `CodeMapQuery` 优先，源码窗口仅用于补证。不得修改 `.uo`。

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `kb_lookup` | `subagent` | `uo-query` | `readonly_analyst` | `uo-query/kb-lookup` | `uo/codemap-query` | `kb-answer-v1` |

<!-- END GENERATED ACTIONS -->
