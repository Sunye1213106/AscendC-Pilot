# CE：代码工程

CE（Code Engineering）当前是一条以代码审查为中心的工作流，不应被描述为已经具备自动改码、调试 Agent 或 PR 生成等未落地能力。它的价值不在于多读几遍 diff，而在于借助 UO CodeMap 分析跨 Host、Tiling 与 Kernel 的影响传播。

## 当前能力：`/ce-review`

```text
Git change
  -> context build
  -> CodeMap query
  -> affected state
  -> propagation
  -> invariant risk
  -> observable consequence
  -> review finding
```

CE 输入是 source diff 或 review target，以及 UO CodeMap 和 query view。它会将改动关联到受影响的 Host state、TilingData field、predicate 或 Kernel branch，并要求 finding 能说明证据与可观测后果。当前产物写入 `<arch>/ce/review/**` 和 run 的 `code_review` action 目录。

如果 CodeMap 缺失或 stale，先运行 `/uo-init` 或 `/uo-update`；CE 不会为审查任务重建完整源码理解，也不替代 TG 的覆盖闭环。

### 委托只读查询

跨层影响需要结构解释时，CE 使用 `Task(actor=uo-query)` + 显式 **UO Product Handle**（禁止子代理自找 `.uo`），**不要**嵌套完整 `/uo-query` workflow。详见 [Agent Runtime](../architecture/agent-runtime.md)。

## 后续方向

影响分析、修改建议、调试和 PR 辅助是合理的扩展方向，但不是当前公开工作流的既有承诺。新增这些能力时，应先在 workflow、权限、输出合同和测试中落地，再将其写入本文档。

实现入口：`engines/code-engineering/code_engineering/impact.py`、`skills/code-review/`、`agents/ce-reviewer.yaml` 和 `prompts/tasks/ce/code-review.md`。
