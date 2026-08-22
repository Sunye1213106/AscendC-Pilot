# Spec 易错点

**何时加载**：写 Spec 发现、判断完成度时。

- 禁止「只陈述理解就算完成」。无 `path:line` 的「可能有问题」降级或不报。
- 每个 changed file 必须落成 finding / format-only / UNREVIEWED。
- snippet 截断 + 未覆盖 WRITES 行时，继续查字段卡 `write_sites` / readers，不得下「枚举未用」。
- Kernel 以字段 readers 行为准，不要把 `kernel_call_boundary` 调用点当成定义。
- 未审 `op_kernel` 时不宣称无高风险。
