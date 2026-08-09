# analyze

确定性执行 AscendC CodeMap Pass，把 CompilerFacts 归一为 entity / relation，并显式产生无法可靠闭合的 semantic gaps。

内部步骤包括变量/生命周期归一、输入根推导、predicate、macro/compile-time、template、TilingKey/TilingData、Host↔Kernel 绑定与架构关系分析。

本 Action 不调用 Agent、不绑定 task prompt。没有 provenance 的关系不得写入 CodeMap；未知关系进入 unresolved。
