# Code Engineering — Gotchas

- **无 diff 先定位，有 diff 再切片**：`/ce-intent` 没有 change capture 时禁止假装已改完；`/ce-impact` 必须先有可复现 diff。
- **截断切片不是无影响**：`truncated` 是披露边界，不能当成「没有义务」或直接进 `X`。
- **Tier C 不能关账**：线索可以扩充 `O`，但不能把义务放进 `V` 或 `X`。
- **精度/性能只收测量收据**：审查叙述、Host 命中 TilingKey、空跑 profiling 文案都不是 `ce-external-evidence/v1`。
- **Open = O - V - X**：不得从 `O` 删掉义务来把 Open 变小；排除项必须经 referee。
- **只读审查走 `/ce-review`**：code-engineering 不管 Git 写操作、fork、PR 文案。
- **场景 overlay ≠ 全量 Key 闭环**：`P-*` / `F-*` ScenarioSet 不得写成 tilingkey full coverage 证书。
