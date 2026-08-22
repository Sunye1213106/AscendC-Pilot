# 精度/性能类发现

审查窗口里出现 Cast、拷贝、队列或切分公式，要把发现写成带 `path:line` 的线索时才读。这些线索不进 CE 的 `V`。不要在审查里写测试分类 id。

## 侧别

`op_kernel/` → 核内数值 / 拷贝 / 队列。`op_host/` → 切分公式 / 可选输入守卫。两边都动了就两边都写。

## 线索

| 窗口 | H1（必须有 path:line） |
| --- | --- |
| `Cast` | 错 dst dtype 或跳过路径 |
| `DataCopy` 末维非 32B 且未 Pad | 未对齐拷贝 |
| 计算没有 EnQue/DeQue | 陈旧 UB / 全零 |
| 长 reduce 没有稳定累加 dtype | 大 S 漂移 |
| 切分字段 rhs 变了 | tile/核边界偏移 |
| InitBuffer / 队列 tposition | UB 压力 |

没有 `path:line` 就不是 finding。测试内容交给计划散文，不要在审查里宣称 golden 或 profiler 结果。
