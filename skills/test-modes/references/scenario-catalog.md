# 场景 id 目录

合法 `scenario_id`。不要自造 id。精度与性能分表，不要混用。

## 精度 `P-*`

| id | 何时挂上 | 旋钮 | 预算 |
| --- | --- | --- | --- |
| `P-DTYPE` | INPUT dtype / key 维 InputDType / Cast 路径 | 受影响 dtype，同 shape | 每 dtype 2–4 |
| `P-CAST` | 切片里 callee `Cast` | 该 dtype 路径 + 典型与边界 shape | ≤4 |
| `P-COPY-ALIGN` | `DataCopy` / `DataCopyPad` | 末维对齐 vs +1 | ≤4 |
| `P-QUEUE` | 计算周围 `EnQue` / `DeQue` | 最小可复现 shape | ≤2 |
| `P-REDUCE-LONG` | reduce / softmax 累加路径 | 长序列 / 大 reduce 轴 | ≤2 |
| `P-OPTIONAL` | 可选 mask / pse / dropout / rope | 有/无，只走合法 shape | ≤4 |
| `P-ILLEGAL` | 源码或蒸馏出的非法组合 | Disable / 排除；**不上 NPU** | 0 NPU |
| `P-TAIL` | tail 核 / 空 tensor / 最小 shape | `[1]`、零轴、余数 tile | ≤3 |

不要把全部合法 Key 当成精度矩阵。全量 tilingkey 是 TG 意图，不是本表。

## 性能 `F-*`

| id | 何时挂上 | 旋钮 | 预算 |
| --- | --- | --- | --- |
| `F-SPLIT` | TilingData 切分字段 writer / rhs 变了 | 对该字段敏感的 shape | 3–8 |
| `F-BUFFER` | BUFFER / QUEUE / `InitBuffer` | 队列方向 + 中等 shape | 3–8 |
| `F-SHAPE-TYPICAL` | 任一性能义务的基线 | 网络常用 / 竞品 shape | 3–8 |
| `F-SHAPE-TAIL` | tail / 切不整 | 非整除 tile、核边界 | ≤3 |
| `F-DTYPE` | 计算 dtype 路径 | fp16 vs fp32，同 shape | ≤2 |
| `F-BALANCE` | usedCoreNum / 多核谓词 | 单核 vs 满核 | ≤2 |

挂上任一性能场景时带上 `F-SHAPE-TYPICAL`。不要把全部合法 Key 当成性能矩阵。
