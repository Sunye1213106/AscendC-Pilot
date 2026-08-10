# AscendC 专项检查（按需）

**何时加载**：分析触及 Host/Kernel、TilingKey、buffer 或 AIC/AIV 同步时。

## Host → TilingData → Kernel

- Host 写入的字段是否被 Kernel 以相同语义消费
- 单位、默认值、可选字段是否双边一致
- 新状态是否传播到所有消费者

## TilingKey → 模板分支

- Key 维度与模板实例 / dispatch 是否一致
- 改 Key 计算是否漏改 Kernel 分支
- optional input 是否同时影响 Host 与 Kernel

## 内存与 Buffer

- GM / L1 / L0 / UB 生命周期与 reuse
- 在最后消费者完成前复用
- workspace / atomic / init 是否完备

## 同步

- AIC / AIV、SetFlag / WaitFlag、event / barrier 是否在合法路径匹配
- 错误路径是否绕过等待

## 边界

- tail、alignment、shape/dtype/layout 分支漏实例
- 确定性计算路径是否被意外非确定性替换
