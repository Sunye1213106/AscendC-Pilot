# 抽取质量

**何时加载**：评估 Host/Kernel/Registry/TilingKey 抽取是否可用时。

- Host 控制流与 Key 计算路径是否被提取
- Kernel 消费的状态是否与 Host 语义对齐
- Registry 是否覆盖实际入口
- 归一化变量/谓词是否保留源码锚点
- 模板/宏分支是否被静默丢掉
- SHARED `common/` 是否进入 ScopeSet **且** Host/Kernel walk 真正消费（勿被裸 `op_needle` 过滤）

质量不够时记 gap，勿用空壳占位当作成功。与 `evidence-quality.md`、`completeness.md` 联用。
