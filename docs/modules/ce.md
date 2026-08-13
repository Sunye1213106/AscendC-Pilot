# CE：代码工程

CE（Code Engineering）用 UO CodeMap 将变更意图、影响范围和验证证据连成可审计流程。它不等同于自动改码、调试 Agent 或 PR 生成器；CodeMap 切片也不能代替运行时、精度或性能测量。

## 工作流

### `/ce-intent`

```text
intent -> UO freshness -> feature decomposition -> backward locate
       -> referee plan review -> human confirmation
```

在还没有 diff 时，`anchor_locate` 消费经审查的 feature target / candidate anchor，并沿受限关系做 backward slice，得到候选修改点。名称近似命中只能作为 Tier C 线索，不能直接形成证明。

### `/ce-impact`

```text
reproducible change -> freshness -> forward/backward UO slices -> risk classes
                    -> obligation ledger -> referee impact audit
```

Freshness 优先比较 change capture 的 Git `base_sha/head_sha` 与 UO `source_revision`。不得把当前 UO 自己的 graph fingerprint 同自己比较来宣称 fresh。工作区变更而 UO 只覆盖 committed HEAD 时进入 `lexical` 降级；revision 不匹配时 fail-closed 为 `stale`。

影响切片是有方向、有 edge filter、depth 和 budget 的确定性派生；必须保留 `truncated` 与 evidence-tier hints。切片边界、stale UO 或未支持关系不能被解释为“没有影响”。

### `/ce-verify`

```text
impact ledger -> obligation-driven review -> TG coverage bridge
              -> residuals -> external verification / referee exclusion
              -> CE certificate
```

验证按 obligation 执行。真实精度、性能、硬件时序或外部系统行为必须摄取对应外部证据。外部 evidence receipt 只能进入 `V`，不能直接进入 `X`；`X` 只接受 `ce-change-referee` 输出的 Tier A 排除证明。

### `/ce-review`

保留只读代码审查入口：从 diff 与 UO 关系追踪受影响状态、约束和可观察后果，产出 finding / unresolved。它不建立完整变更闭环；需要范围与证书时使用 intent → impact → verify 链路。

## Evidence tiers

- **Tier A**：compiler/AST、精确源码、canonical CodeMap direct provenance、测试/构建/测量结果。
- **Tier B**：从 Tier A 输入可复现地确定性派生，例如带参数和边界的 UO slice。
- **Tier C**：lexical heuristic、模型判断、命名推测或 provenance 未闭合的线索。

Tier 不是展示字段，而是 deterministic policy boundary：

```text
Tier A -> 可按风险类 closure requirement 进入 static/runtime/external 验证
Tier B -> review_only，不允许排除
Tier C -> open_only，不允许关闭或排除
```

## Obligation ledger

```text
Open = O - V - X
```

`O` 是全部验证义务。`V` 只能由可审计证据回执派生；`X` 只能由 `ce-change-referee` 的 Tier A 源码排除证明派生。调用方传入的裸 `verified/excepted` id 不具有关闭能力，deterministic ledger 在保存和读取时都会重新根据 evidence artifacts 计算 V/X，并拒绝无证据 transition。验证阶段的 ledger 也不得缩小 canonical `O`。

## Change Certificate

`ce/verify/certificate.yaml` 除 O/V/X/Open 外还包含：

- `residual`
- `blind_spots`
- `analyzability`
- `intent_drift`
- `closure_evidence`
- `freshness`
- `transition_audit`

因此 `Open = []` 不再是唯一上下文；证书同时说明闭环证据、静态盲区、UO 可分析度与需求偏移。

如果 CodeMap 缺失或 stale，先运行 `/uo-init` 或 `/uo-update`。跨层结构解释使用显式 UO Product Handle 的只读查询，不让子任务自行猜测 `.uo` 路径。

实现入口：`engines/code-engineering/code_engineering/`、`skills/code-engineering/`、`skills/code-review/` 与 `pilot/ascendc_pilot/workflows/specs.py`。
