# Binding

语义绑定把契约变量接到可观察的输入 / 属性 / 上下文。

- 每个 binding 必须能指向 UO 节点或源码 span。
- 默认 overlay（`tilingkey_full_coverage`）下 binding 由 deterministic engine 构建。
- csv_consumer overlay 才允许 LLM producer 写 `semantic_bind_patch.yaml`；仍禁止发明列名。
- 绑定冲突进 audit_report，不得 silent overwrite。
