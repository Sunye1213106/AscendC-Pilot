# 缺口 / unresolved

按需阅读。Deterministic pass 无法闭合的 residual 合法存在；**不得**默认用 LLM 补进 canonical `.uo`。

评价建库看 `uo/checks/quality.yaml` 的 `grade`（ready / usable / not_ready）和 `unresolved.locate_blocking`，不要用 `unresolved.yaml` 总条数。HOST 运行时叶、PROJECT/BUILTIN 实体不算定位失败。节点/关系数量在同一份校验结果的 `graph.entity_count` / `graph.relation_count`（verify 写入）。

## 查什么

- `quality.unresolved.locate_blocking`（字段无 owner、缺 Kernel span 等）
- `ir/unresolved.yaml` 里 `bucket` 为 `locate_blocking` / `host_runtime_leaf` / `catalog_unproven` 的条目（须 freshness）
- gap 根因归类 → 交给 `/uo-investigate`，不是 query 静默发明边

## 推荐接口

```text
uo-query --project <op>
```

OpenCode：插件 `pilot_cli`，command 即上列 argv。

无参数索引含 `gaps_count`。细节交给 `/uo-investigate`。

## 回答纪律

图缺口 → `PARTIAL` 或 `UNKNOWN` + `reason_code`（如 `NOT_FOUND_IN_SCOPE`）。  
列出缺口 id；不要声称 ANSWERED。
