# Construct cases

**何时加载**：`/tg-solve` 的 `construct_cases`。

```text
已批准 plan.md
  → 按义务填控制列
  → 其余列用 init.yaml defaults
  → 写出脚本仓能直接吃的行
  → Host replay 只在义务 class=replay 时作为证据
```

## 规则

1. 行必须填满 `init.yaml` 列；不要发明列（除非 plan `added_columns` 且已 CE 落地）。
2. 每个义务的 `why` 必须能在控制列取值上看到。
3. 不要笛卡尔展开全部合法 Key，除非意图点名全量 tilingkey。
4. 不要改算子仓。缺生成器走 `test_harness_gap`。
5. 正式表由 `construct_promote` 写出；草稿只留 `runs/`。
