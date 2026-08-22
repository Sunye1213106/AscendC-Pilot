# AscendC 专项检查（按需）

**何时加载**：分析触及 Host/Kernel、TilingKey、buffer 或 AIC/AIV 同步时。用 CodeMap 定位，不要把本文件当成条例库。

## Host → TilingData → Kernel

- Host 写入的字段是否被 Kernel 以相同语义消费
- 单位、默认值、可选字段是否双边一致
- 新状态是否传播到所有消费者
- 字段公式：`field` 的 `facts.rhs` / `value_defining_sites` 与 Kernel 读取是否同一表达式语义

## 上游校验

- Host `OP_CHECK_IF` / `OP_TILING_CHECK`：`locate` 字段或输入，看 `facts.check_sites`（`file:line` + 短 guard）
- 声称「Tiling 已校验」必须指到具体校验点，且 guard 保护的变量与风险变量相同（或可证明赋值等价）
- 「来源 = TilingData」本身不是已校验

## TilingKey → 模板分支

- Key 维度与模板实例 / dispatch 是否一致
- 改 Key 计算是否漏改 Kernel 分支
- optional input 是否同时影响 Host 与 Kernel
- 561002：先 `tiling_key` / `legal_key`，再看 Host 是否写出该组合

## 内存与 Buffer

- GM / L1 / L0 / UB 生命周期与 reuse
- `facts.tposition`：VECIN vs VECOUT（不要都当成 UB 就结束）
- DataCopy：dst/src 方向、对齐、拷贝长度是否与 Tiling 字段一致
- 在最后消费者完成前复用
- workspace / atomic / init 是否完备

## 队列方向（TQue，独立于 Flag 配对）

- EnQue / DeQue 与 QUEUE `tposition` 是否同向（VECIN 入、VECOUT 出）
- 这是 CANN TQue 编程模型：交接在队列实现里，不要用 SetFlag/WaitFlag 去对 EnQue
- 错误路径是否绕过 DeQue（那是 TQue 生命周期，不是缺 WaitFlag）

## 同步（Flag）

- AIC / AIV、SetFlag / WaitFlag、CrossCore*、event / barrier 是否在合法路径上 **成对出现**（CodeMap：`SIGNALS`/`AWAITS` + `flag_paired`）
- identity 级成对出现不是 happens-before；哪一次 Wait 等哪一次 Set 仍要看源码

## 边界

- tail、alignment、shape/dtype/layout 分支漏实例
- 确定性计算路径是否被意外非确定性替换
