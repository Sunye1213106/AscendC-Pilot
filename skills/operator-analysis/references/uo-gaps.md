# UO · Gaps / Unresolved

按需阅读。Deterministic pass 无法闭合的 residual 合法存在；**不得**默认用 LLM 补进 canonical `.uo`。

## 查什么

- `status` 为 unresolved / partial / unknown 的实体  
- `ir/unresolved.yaml` projection（须 freshness）  
- gap 根因归类 → 交给 `/uo-investigate`，不是 query 静默发明边

## 推荐接口

```text
acp uo-query --mode gaps --pattern <optional_filter>
```

## 回答纪律

图缺口 → `PARTIAL` 或 `UNKNOWN` + `reason_code`（如 `NOT_FOUND_IN_SCOPE`）。  
列出缺口 id；不要假装 ANSWERED。
