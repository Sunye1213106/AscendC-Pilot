# 缺口 / unresolved

按需阅读。Deterministic pass 无法闭合的 residual 合法存在；**不得**默认用 LLM 补进 canonical `.uo`。

评价建库看 `uo/checks/quality.yaml` 的 `grade`（ready / usable / not_ready）和 `unresolved.locate_blocking`，不要用 `unresolved.yaml` 总条数。HOST 运行时叶、PROJECT/BUILTIN 实体不算定位失败。节点/关系数量在同一份校验结果的 `graph.entity_count` / `graph.relation_count`（verify 写入）。

## 查什么

- `quality.unresolved.locate_blocking`（字段无 owner、缺 Kernel span 等）
- 无参数索引里的 `gaps_count`
- 卡片上的 incomplete / missing 字段

## 回答纪律

图缺口 → `PARTIAL` 或 `UNKNOWN` + `reason_code`（如 `NOT_FOUND_IN_SCOPE`）。  
列出缺口 id / `gap_code` / `residual_id`（卡片有则原样带回）。不要声称 ANSWERED。

消费事实的本步到这里停止。不要因为事实缺失自动进入「修事实系统」的模式。是否诊断 UO build residual 由 Framework / maintainer workflow 决定，不是 query 的下一步。
