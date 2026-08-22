# 性能邻域取值

**何时加载**：`plan.md` 的 `oracle` 已点性能，并且该变量已经 `TARGET_HIT`。本步不决定测哪些变量，只给命中后的取值邻域。

怎么跑 profiler、哪一列选 case 以当前仓 `tg/init.yaml` 为准。

点了性能时带一条网络常用 shape。切片里有 tail / 切不整再加一条余数 shape。

## 选 case

- 切分字段 / 核数 → 对照 Replay 的 usedCoreNum / split
- Buffer / 队列方向 → workspace / queue
- 计算 dtype 路径 → 与精度邻域分开记账

预算 3–8 条。Oracle 是 harness profiler。Host `HIT` 不是性能 PASS。
