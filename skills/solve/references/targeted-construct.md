# 定向构造

**何时加载**：按已批准义务填行、不要铺成全量 Key 矩阵时。

```text
已批准 plan.md
  → 只改义务点名的控制列
  → 其余列用 init.yaml defaults 或 recipe
  → 写出脚本仓能直接吃的行
```

## 规则

1. 行必须填满 `init.yaml` 列；不要发明列。
2. 每个义务的 `why` 必须能在控制列取值上看到。
3. 不要笛卡尔展开全部合法 Key，除非意图点名全量 tilingkey。L3 特殊值不要铺进每一组 L0 shape。
4. 不要改算子仓。缺生成器走 `test_harness_gap`。
5. 正式表由 `construct_promote` 写出；草稿只留 `runs/`。
