# 精度/性能类发现

**何时加载**：审查窗口里出现 Cast、拷贝、队列或切分公式，要把发现写成 H0/H1 线索时。这些线索不进 CE 的 `V`。

## 侧别

`op_kernel/` → 核内数值 / 拷贝 / 队列。`op_host/` → 切分公式 / 可选输入守卫。两边都动了就两边都写。

## 线索

| 窗口 | H1（必须有 path:line） | 相关场景线索 |
| --- | --- | --- |
| `Cast` | 错 dst dtype 或跳过路径 | `P-CAST`、`P-DTYPE` |
| `DataCopy` 末维非 32B 且未 Pad | 未对齐拷贝 | `P-COPY-ALIGN` |
| 计算没有 EnQue/DeQue | 陈旧 UB / 全零 | `P-QUEUE` |
| 长 reduce 没有稳定累加 dtype | 大 S 漂移 | `P-REDUCE-LONG` |
| 切分字段 rhs 变了 | tile/核边界偏移 | `F-SPLIT` |
| InitBuffer / 队列 tposition | UB 压力 | `F-BUFFER` |

没有 `path:line` 就不是 finding。测试义务交给计划的测试内容，不要在审查里宣称 golden 或 profiler 结果。
