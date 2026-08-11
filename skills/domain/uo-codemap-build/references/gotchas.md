# UO CodeMap Build — Gotchas

- **确定性 frontend/pass 优先**：LLM 只消解 `unresolved.yaml` 里显式 blocker；不得重做 Clang/extract。
- **staging ≠ canonical**：resolve 只写 staging；canonical IR 由 harness merge / commit。
- **禁止命名闭合**：blocker 不得因变量名相似、文件邻近而关闭。
- **跨层边必须有证据**：Host→Tiling→Kernel 边缺少 source span / evidence_ref 时保持 unresolved。
- **BuildVariant 混用**：不同 architecture / 编译宏下的符号不得并进同一无身份。
- **局部变量生命周期**：保存-修改-恢复模式中，临时写回不是最终 defining site。
- **Replay 反驳规则时撤销该规则**，不要降权后继续保留错误边。
