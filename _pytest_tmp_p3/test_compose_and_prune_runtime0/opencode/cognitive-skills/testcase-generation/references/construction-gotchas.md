# TG Init — Gotchas

- **契约不是测例**：init 产出 contract / binding，不构造 case，不跑 Host。
- **UO 视图缺失 ≠ 可猜维度**：`tiling/exhaustive_key_space` 或 `tg_host_view` 缺失时先物化 UO，禁止手填 Key 维。
- **CSV overlay 与默认 overlay 分离**：`tilingkey_full_coverage` 下 semantic_bind 是 deterministic；不要按 csv_consumer 的 LLM producer 路径操作。
- **绑定必须可回放**：每个 binding 要有 UO/源码证据；“看起来合理”的列名映射无效。
- **不得发明 CSV 列或 Key**：forbid invent_csv_columns_or_keys；缺口进 audit，不进 silent default。
- **human_confirm 前不得 solve**：init 未确认时禁止进入 tg-solve。
