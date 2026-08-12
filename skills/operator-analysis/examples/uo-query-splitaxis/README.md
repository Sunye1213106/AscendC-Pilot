# Example（non-normative）— SplitAxis=1 under TND

Worked example only. Numbers are a snapshot; do not copy into normative references.

## Question

TND 布局下，`SplitAxis=1` 是否合法？

## Claim level

`host-produced`（声明域 + Host guard + final overwrite）；不要求 full reachability / TG。

## Suggested hops

1. `uo-product-map` → claim = host-produced for SplitAxis under TND  
2. `acp uo-query --mode tiling_key --pattern SplitAxis`（enum / packing）  
3. `constraints` / `search` for TND layout guards that rewrite or block BN2  
4. Stop when verdict + path:line citations sufficient

## Snapshot notes（FAG arch35，illustrative）

- `SplitAxis=1` maps to BN2-style split in Host packing discussion.  
- TND path is conditional; look for guards such as `d>128`, dropMask, DETER_CAUSAL.  
- RoPE × DTemplate cross-product is **optional** — do not block main verdict.  
- Freshness lesson: summary `relation_count` may disagree with `ir/operator_graph.yaml` `edge_count` when projections were stamped before dropping unproven key→kernel edges (e.g. delta ≈ 13). Query must treat that as `VIEW_STALE`, not trust fingerprint alone.

## Expected shape

```yaml
schema: kb-answer-v1
status: ANSWERED   # or PARTIAL if a material guard span is missing
question: "TND 布局下，SplitAxis=1 是否合法？"
answer_zh: |
  <verdict + guard list with path:line>
citations:
  - path: op_host/...
    lines: "..."
adequacy: ANSWERED
```
