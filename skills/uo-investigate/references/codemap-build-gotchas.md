# 构建失败 vs 图缺口

**何时加载**：要区分「编译/探针没过」和「图上真有 residual」时。

Agent 规则。假编译环境、补头、prelude 由 engine 做。

- **确定性提取优先**：未闭合项记入 `unresolved.yaml`；不要用 LLM 补进正式 `.uo`。
- **范围不由人工确认文件清单**：operator + arch 给定后，prepare 用 Clang include closure 建范围；失败记 blocker。
- **Clang 是权威，regex 不是**：regex 只作引导；Clang 成功后替换，不是并集。
- **发现 common ≠ 消费 common**：共享头进范围后必须按范围成员走，不得按算子名丢掉。
- **禁止跳过编译验证**：产品路径禁止测试开关绕过探针。
- **禁止命名闭合**：blocker 不得因变量名相似、文件邻近而关闭。
- **跨层边必须有证据**：Host→Tiling→Kernel 边缺少 source span 时保持 unresolved。
- **BuildVariant 混用**：不同 architecture / 编译宏下的符号不得并进同一无身份。
- **局部变量生命周期**：保存-修改-恢复里，临时写回不是最终 defining site。

探针缺头、include 路径没对齐 → 交给 `skills/propose-include-heal/SKILL.md`，不要在本步当图缺口结案。
