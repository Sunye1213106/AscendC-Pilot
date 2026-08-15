# CE：代码工程

CE（Code Engineering）用 UO CodeMap 将变更意图、影响范围和验证证据连成可审计流程。它不等同于自动改码、调试 Agent 或 PR 生成器；CodeMap 切片也不能代替运行时、精度或性能测量。

账本恒等式：`Open = O - V - X`。这是 Pilot 的闭环，审查对方日常流程没有这一层。

## 工作流

认知 Skill 分工（不要混用）：

| 入口 | Skill |
| --- | --- |
| `/ce-intent`、`/ce-impact`、`/ce-verify` | `skills/code-engineering/` |
| `/ce-review` | `skills/code-review/` |

intent / impact / verify 走变更闭环与义务账本；review 是只读检视，不签发 CE 证书。

### `/ce-intent`

```text
intent -> UO freshness -> feature decomposition -> referee review
       -> backward locate -> human confirmation
```

**无 diff**：先定位再下结论。Referee 写入 `ce/intent/plan_review.yaml`；Host `feature_promote` 再写出 canonical `feature_decomposition.yaml`。随后 `anchor_locate` 沿受限关系做 backward slice，得到候选修改点。名称近似命中只能作为 Tier C 线索，不能直接形成证明。遗留的 `ce/impact/change_capture.yaml` 不得阻断 intent 定位。

对应 Issue「先读代码、钉最小改动点」。不实现 GitCode、不写 PR 文案。

### `/ce-impact`

```text
reproducible change -> freshness -> forward/backward UO slices -> risk classes
                    -> ScenarioSet skeleton -> obligation ledger -> referee impact audit
```

**有 diff**：切片 + 按 CodeMap `kind` 挂义务。Freshness 优先比较 change capture 的 Git `base_sha/head_sha` 与 UO 产品 meta 的 `source_revision`（`/uo-init` commit 写入），并比会话/run 钉住的 `canonical_graph_digest`（handle.digest）与当前 `.uo`。不得把当前 UO 自己的 graph fingerprint 同自己比较来宣称 fresh。digest 变化时 reason_code 为 `UO_DIGEST_CHANGED`。工作区变更而 UO 只覆盖 committed HEAD 时进入 `lexical` 降级；revision 缺失或不匹配时 fail-closed 为 `stale`。

影响切片是有方向、有 edge filter、depth 和 budget 的确定性派生；必须保留 `truncated` 与 evidence-tier hints。未指定 `edge_kinds` 时默认走有用边（WRITES/READS/CALLS/CONTROLS/DERIVES/SELECTS/LAUNCHES/SIGNALS/AWAITS/FLOWS_TO/BINDS）。切片边界、stale UO 或未支持关系不能被解释为“没有影响”。

`evaluate_risks` 按锚点 `kind` 挂义务，并且**每个锚点单独成条**：BUFFER 只进 sync/perf，不会单独产生 dispatch；一条 Tier C 锚点不得把其它锚点的义务打成 `open_only`。无 kind 的锚点默认不挂类；只有调用方**显式**传入 `risk_classes` 时才按所选类挂上，这不是静默默认。

风险用开发者语言理解：Tiling 失败 / Kernel 找不到 → dispatch；越界与同步 → sync；精度 / 性能 → 外部测量才能进 `V`。

### 场景 overlay 与 harness

日常精度/性能不默认跑全量 TilingKey。`/ce-impact` 与 `/ce-intent` 会写出 `ce/scenarios/scenario_set.yaml`（`ce-scenario-set/v1`），场景 id 只能来自目录（`P-*` / `F-*`）。`scenario_targeted` overlay 由引擎写骨架，Agent 只写 knobs staging，Host `scenario_apply` 合并后再人话确认。测试仓适配器把少量 CSV 的跑测译成 `ce-external-evidence/v1`；没有适配器时精度/性能保持 Open，并记录 `harness_missing`。Host replay 不能关闭 `P-*` / `F-*`。全量覆盖仍走独立的 `tilingkey_full_coverage` overlay。

### `/ce-verify`

```text
impact ledger -> obligation-driven review -> TG coverage bridge
              -> residuals -> external verification / referee exclusion
              -> CE certificate
```

验证按 obligation 执行。`V` 只收**本仓库可审计的测量或测试收据**，schema 为 `ce-external-evidence/v1`：

- UT / ST 通过
- 精度对比（atol/rtol 记录）
- profiling / 性能复测
- 卡死/崩溃场景复测通过

静态合同类义务可由 `ce/verify/code_review.yaml` 的源码证明进入 `V`。精度、性能、硬件时序不得用审查叙述关闭。外部 evidence receipt 只能进入 `V`，不能直接进入 `X`；`X` 只接受 `ce-change-referee` 输出的 Tier A 排除证明。

### `/ce-review`

只读检视，三种入口（quick / file / pr）由同一 Action `code_review` 跨 `scope` / `review` / `summary` 判定。证据先 CodeMap 再最小源码窗；假设检验（H0/H1）且必须有 `path:line`。不建立完整变更闭环。产物仍是 `ce/review/*.yaml`。

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

实现入口：`engines/code-engineering/code_engineering/`；`/ce-intent` `/ce-impact` `/ce-verify` → `skills/code-engineering/`；`/ce-review` → `skills/code-review/`；工作流合同在 `pilot/ascendc_pilot/workflows/specs.py`。
