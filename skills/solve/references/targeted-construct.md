# 定向构造

**何时加载**：按已批准变量的 `direction` 填行，而不是铺成全量 Key 矩阵时。

```text
已批准 plan.md
  → 只改该变量 direction 点名的列
  → 其余列用 init.yaml defaults 或 recipe
  → 写出脚本仓能直接吃的行
```

## 规则

1. 行必须填满 `init.yaml` 列。
2. 每个变量的独立条件要能在控制列取值上看到（direction 是大致边，Replay 用 evidence 收口）。
3. 未指定时造 L0+L1。L2 有界笛卡尔只在用户点名时做。L3 特殊值不铺进每一组 L0。
4. 缺生成器走 `test_harness_gap`。TG 不改算子仓。
5. 正式表由 `construct_promote` 写出；草稿只留 `runs/`。
