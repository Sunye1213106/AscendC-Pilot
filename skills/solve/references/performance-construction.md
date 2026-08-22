# 性能构造旋钮

已经有合法 `F-*` id 之后才读。本步不重新判断该不该挂场景，只把已批准 id 落成列。

怎么跑 profiler、哪一列选 case 以当前仓 `tg/init.yaml` 为准，不要发明 NPU 指标。

挂上任一性能场景时带上 `F-SHAPE-TYPICAL`（网络常用 shape）。切片里有 tail / 切不整再加 `F-SHAPE-TAIL`。

## 选 case

- 切分字段 / 核数 → `F-SPLIT`、`F-BALANCE`
- Buffer / 队列方向 → `F-BUFFER`
- 计算 dtype 路径 → `F-DTYPE`

预算 3–8 条，禁止枚举全部 legal key。Oracle 是 harness profiler。Host HIT 关不了 `F-*`。
