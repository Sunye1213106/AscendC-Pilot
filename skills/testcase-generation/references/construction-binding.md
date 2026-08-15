# Binding

语义绑定把契约变量接到可观察的输入 / 属性 / 上下文。

- 每个 binding 必须能指向 UO 节点或源码 span。
- 默认 overlay（`tilingkey_full_coverage`）下 binding 由 deterministic engine 构建 host-view inventory。
- 若指定了 `--test-script-root`，engine 只扫描入口/CSV 表头；**怎样把列传给算子、精度 vs 性能**由 Agent 读测试仓代码后写入 `tg/init/test_repo_contract.yaml`。未指定测试仓时生成默认 input。
- **空 `reads` / 空 `exactness` 在确定性全覆盖模式下是预期行为，不是 audit blocker**；
  不得因此要求人工确认或把 audit `status` 写成非 `pass`/`fail` 的值。
- 绑定冲突进 audit_report，不得 silent overwrite。
