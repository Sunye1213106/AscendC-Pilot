# 查询产品地图

短地图：认清权威 → 调用 Cursor MCP `uo_query`（或 OpenCode `pilot_cli` `uo-query`）→ 查询完成后立即作答。简单查询直接调用；复杂查询同一轮委派。禁止 `pilot_run`。怎么选形状、Claim 分层、空结果纪律见 `skills/uo-query/SKILL.md`。

同一查询目标可沿图继续调用（跟卡片 `next`）。是否并行委派见 `pilot/policies/pilot-control/POLICY.md`。

## 权威分层

统一 `.uo` 是 query 的唯一 authority。正常查询路径不得打开原始 `product_map.json` 当另一套真值。product-map 属于 UO build / `/uo-init`：用来生成 deterministic facts、诊断 product coverage。Query 只消费引擎编译后的 `.uo` 卡片。

| 层 | 是什么 | 不是什么 |
| --- | --- | --- |
| **正式产品** | 已 commit 的 `.ascendc-pilot/<arch>/uo/<op>.<arch>.uo` | LLM 记忆、未校验草稿、原始 `product_map.json` |
| **图** | `entity` / `relation` / `source_span` | 任何可重建索引本身 |
| **加速投影** | 查询用的派生视图 | 独立事实源；过期由 engine 回退正式产品 |

无法验证 freshness 时不得当作 fresh。缺 `.uo` 时 fail closed：`/uo-init` 或明确走源码证据，不要在查询层换一套数据源。

## UO 不回答

配对、时序、仿真、sanitizer、运行时日志解读、happens-before、测量、Git / PR、完整 ST 矩阵、runtime full reachability **不在 UO**。TilingKey / Kernel / unresolved 分开查，不要一次扩到端到端可达。

Worked example（**non-normative**）：标识符 → 看 `sel_sites` / `edges.*.count` → 若 count > 已列出再查或 PARTIAL → `--file --line` 看语句 → verdict。
