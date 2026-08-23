# 定向构造

**何时加载**：按已批准 Dimension / Guard 的 controls 与 `construct_hint` 填行，而不是铺成全量 Key 矩阵时。

```text
已批准 plan.md + OPEN 义务
  → 只改该义务相关的 control 列
  → 其余列用 init.yaml defaults 或 recipe fillers
  → 交回 YAML 围栏（禁止 Write）
```

## 规则

1. 显式行必须填满 `init.yaml` 列。
2. 每个 OPEN 义务的独立条件要能在控制列取值上看到（hint 是大致边，Replay 用谓词收口）。
3. 本轮交多少由 LLM 判断；禁止盲铺笛卡尔。全量 Key 只交 `recipe.kind: enumerate_legal_keys`。
4. 缺生成器走 `test_harness_gap`。TG 不改算子仓。
5. 正式表只在 certify 写出。
