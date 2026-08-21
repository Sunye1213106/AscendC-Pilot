# 性能场景 id

合法 `scenario_id`。不要自造 id。

| id | 何时挂上 | 旋钮 | 预算 |
| --- | --- | --- | --- |
| `F-SPLIT` | TilingData 切分字段 writer / rhs 变了 | 对该字段敏感的 shape | 3–8 |
| `F-BUFFER` | BUFFER / QUEUE / `InitBuffer` | 队列方向 + 中等 shape | 3–8 |
| `F-SHAPE-TYPICAL` | 任一性能义务的基线 | 网络常用 / 竞品 shape | 3–8 |
| `F-SHAPE-TAIL` | tail / 切不整 | 非整除 tile、核边界 | ≤3 |
| `F-DTYPE` | 计算 dtype 路径 | fp16 vs fp32，同 shape | ≤2 |
| `F-BALANCE` | usedCoreNum / 多核谓词 | 单核 vs 满核 | ≤2 |

挂上任一性能场景时带上 `F-SHAPE-TYPICAL`。不要把全部合法 Key 当成性能矩阵。
