# 性能邻域

**何时加载**：`plan.md` 的 `oracle` 已点性能，并且该变量已经 `TARGET_HIT`。

怎么跑 profiler、哪一列选 case 以当前仓 `tg/init.yaml` 为准。shape 必须来自 init domains、harness 能力、corpus / 显式需求 / benchmark profile 之一。没有出处就不要编「网络常用 shape」。

## 选 case

- 切分字段 / 核数 → 对照 Replay 的 usedCoreNum / split
- Buffer / 队列方向 → workspace / queue
- 计算 dtype 路径 → 与精度邻域分开记账
- 切片里有 tail / 切不整、且域内合法 → 再加一条余数 shape

预算 3–8 条，且每条都在合法域内。Oracle 是 harness profiler。Host `HIT` 不是性能 PASS。
