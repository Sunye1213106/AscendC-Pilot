# 精度场景 id

合法 `scenario_id`。不要自造 id。

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
