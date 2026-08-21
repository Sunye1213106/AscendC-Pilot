# 性能选 case

**何时加载**：已经有合法 `F-*` id，要选少量 case 时。id 以本 Skill 的场景表为准。

挂上任一性能场景时带上 `F-SHAPE-TYPICAL`（网络常用 shape）。切片里有 tail / 切不整再加 `F-SHAPE-TAIL`。

## 选 case 时看什么（不是打分）

- 切分字段 / 核数 → `F-SPLIT`、`F-BALANCE`
- Buffer / 队列方向 → `F-BUFFER`
- 计算 dtype 路径 → `F-DTYPE`

预算 3–8 条，禁止枚举全部 legal key。Oracle 是 harness `profiler`。Host HIT 关不了 `F-*`。
