# UO Product Map（progressive）

短地图：认清权威分层 → 选语义下一跳 → 够 claim 就停。域细节按需读底部链接。

## 权威分层

| 层 | 是什么 | 不是什么 |
| --- | --- | --- |
| **Semantic authority** | 已 commit 的 `.ascendc-pilot/uo/<op>.<arch>.uo` | LLM 记忆、未校验 staging |
| **Canonical representation** | `entity` / `relation` / `attribute` / `source_span`（及 `entity.data` 派生字段） | 任何可重建索引的「捷径」本身 |
| **Materialized projections** | `view_blob/*`（加速索引） | 独立事实源；由 engine 管 freshness |

Query 路径：projection mismatch → `VIEW_STALE` → **engine** fallback 到 canonical（不进 LLM 自行猜）。

## Claim 层级（sufficiency，不是固定槽）

认清要证明的层级，**不静默扩大**：

1. **domain** — 声明域/枚举/TPL 允许什么值  
2. **template-admissible** — 模板/宏在编译期是否接纳  
3. **host-produced** — Host 在何 guard 下写出/改写该值  
4. **kernel-consumed** — Kernel/分支是否消费该维或字段  
5. **full reachability** — 端到端可达（常需 TG；UO 只给结构证据）

主问只需 1–3 时，不要为了「更完整」拖到 5。

## 默认探索环

```text
mission → identify_claim → read this map → choose_semantic_next_hop
  → acp uo-query (structured) | minimal source window
  → claim_sufficient? → STOP ANSWERED
  → material gap? → STOP PARTIAL | else next_hop
```

预算（软/硬由 harness 执行）：semantic 优先；源码窗口极少；禁止重复同 pattern / 同 span。

## 何时读 projection vs canonical vs 源码

| 需要 | 优先 | fallback |
| --- | --- | --- |
| 符号 / 邻接 / 路径 / guard | `acp uo-query`（canonical graph） | — |
| TilingKey 合法组合摘要 | `tiling_key` / legal_key **indexed** mode | exhaustive 视图 stale → canonical dims |
| 字段写读 | `tiling_data` / `field` | entity attrs + relations |
| 分支 / 模板匹配 | `kernel_branch` / `template_match` | neighbors + source_span |
| Buffer / 存储类 | `buffer` | BUFFER entities |
| 已知缺口 | `gaps` | unresolved entities / `ir/unresolved.yaml` |
| 仅缺 path:line | **已有 `source_span` / packing site 即足够引用** | 不为行号而 Read；仅当图无 span 时才开最小窗口 |

## Citation

- `source_span` 或 packing site 的 `path:line`（或 `path:start-end`）**足够引用**。  
- KB 节点 / `evidence_ref` 可并列，不能替代 span。  
- 无 span 不得假装 `ANSWERED`；用 `PARTIAL` / `UNKNOWN` + `reason_code`（如 `NOT_FOUND_IN_SCOPE`）。

## 交付（kb-answer-v1）

保留 schema 名。`answer_zh` 必填。`findings` / `gaps` / `useful_locations` **optional**。  
未找到：`status: UNKNOWN` + `reason_code: NOT_FOUND_IN_SCOPE`（不要发明事实）。

## 按需域文档

| 域 | 文档 |
| --- | --- |
| TilingKey / packing / legal space | `uo-key.md` |
| TilingData 字段写读 | `uo-tilingdata.md` |
| Kernel 分支 / root trace | `uo-kernel.md` |
| Template / macro / BuildVariant | `uo-template.md` |
| Buffer / LocalTensor | `uo-buffer.md` |
| unresolved / gaps | `uo-gaps.md` |

Worked example（**non-normative**）：`examples/uo-query-splitaxis/`。
