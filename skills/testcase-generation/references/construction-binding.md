# Binding

语义绑定把契约变量接到可观察的输入 / 属性 / 上下文。

- 每个 binding 必须能指向 UO 节点或源码 span。
- 默认 overlay（`tilingkey_full_coverage`）下 binding 由 deterministic engine 构建 host-view inventory。
- **空 `reads` / 空 `exactness` 在确定性全覆盖模式下是预期行为，不是 audit blocker**；
  不得因此要求人工确认或把 audit `status` 写成非 `pass`/`fail` 的值。
- 绑定冲突进 audit_report，不得 silent overwrite。
