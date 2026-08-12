# CE：代码工程

CE（Code Engineering）用 UO CodeMap 将变更意图、影响范围和验证证据连成可审计流程。它不等同于自动改码、调试 Agent 或 PR 生成器；CodeMap 切片也不能代替运行时、精度或性能测量。

## 工作流

### `/ce-intent`

```text
intent -> UO freshness -> feature decomposition -> code anchors
       -> referee plan review -> human confirmation
```

捕获要改什么、为什么改，并将特性分解绑定到 Host / Tiling / Kernel 的 CodeMap anchor。输出是经审查的变更计划，不是实现正确性证明。

### `/ce-impact`

```text
reproducible change -> forward/backward UO slices -> risk classes
                    -> obligation ledger -> referee impact audit
```

影响切片是有方向、有 edge filter、depth 和 budget 的确定性派生；必须保留 `truncated` 与 evidence-tier hints。切片边界、stale UO 或未支持关系不能被解释为“没有影响”。

### `/ce-verify`

```text
impact ledger -> obligation-driven review -> TG coverage bridge
              -> residuals -> external evidence / exclusions
              -> CE certificate
```

验证按 obligation 执行。代码审查和 TG coverage 可提供一部分证据；真实精度、性能、硬件时序或外部系统行为必须摄取对应外部证据。没有外部证据时保持 open，不得用模型判断补齐。

### `/ce-review`

保留只读代码审查入口：从 diff 与 UO 关系追踪受影响状态、约束和可观察后果，产出 finding / unresolved。它不建立完整变更闭环；需要范围与证书时使用上述 intent → impact → verify 链路。

## Evidence tiers

- **Tier A**：compiler/AST、精确源码、canonical CodeMap direct provenance、测试/构建/测量结果。
- **Tier B**：从 Tier A 输入可复现地确定性派生，例如带参数和边界的 UO slice。
- **Tier C**：lexical heuristic、模型判断、命名推测或 provenance 未闭合的线索。

Tier C 可用于发现 anchor 或新增 obligation，不能关闭 obligation。

## Obligation ledger

```text
Open = O - V - X
```

`O` 是识别出的全部验证义务；`V` 是被证据验证的义务；`X` 是 referee 根据 Tier A 或由 Tier A 支撑的 Tier B 证据批准的排除项。义务始终保留在 `O`，不得通过删除记录缩小 `Open`，Tier C 不得写入 `V` 或支持 `X`。

如果 CodeMap 缺失或 stale，先运行 `/uo-init` 或 `/uo-update`。跨层结构解释使用显式 UO Product Handle 的只读查询，不让子任务自行猜测 `.uo` 路径。

实现入口：`engines/code-engineering/code_engineering/`、`skills/code-engineering/`、`skills/code-review/` 与 `pilot/ascendc_pilot/workflows/specs.py`。
