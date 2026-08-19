# Standalone code review（`/ce-review`）

只读检视。输入是已经绑定到当前算子 workspace 的代码改动；无 diff 则停。不写 `ce/review/`，不写新的正式 YAML 产品。

详见 `references/cross-layer-contracts.md`、`references/ascendc-checks.md`、`references/finding-format.md`、`references/gotchas.md`。

review 阶段由**主控**同一轮并行派两个隔离子代理（`spec-review` / `standards-review`）。本 METHOD 覆盖入口说明。stub 含 `AXIS=` 时不要用这份方法写那一轴。子代禁止再派 Task。

## 输入

- PR flow：Workspace Manager 已把 exact PR head 放到隔离 workspace，并确定当前算子；`change_capture` 提供 **index.md（主输入）** 与可选 hunk 小窗，不是整份 `diff.md`
- 本地 flow：`/ce-apply` 后的工作区 diff，或用户显式给出的 `base...head`
- 当前 `.uo`：只作为语义查询权威

有 PR URL 时禁止用用户当前本地 fork / 未提交改动冒充 patch。没有 diff 索引时标 UNRESOLVED 并停，不要猜。

侧别：`op_kernel/` → Kernel，`op_host/` → Tiling。分侧陈述。

## 语义与影响范围

先读 `change_capture/index.md` / `uo_hints.md`，再 **并行 form-1 查 Added identifiers**，不要先 `uo-query --file --line` 打 format hunk。不要传 `--mode`。禁止 `explain-*` / Grep 通读 / 线性读完整 `diff.md`。snippet 截断不得下「枚举未用」。Kernel 以字段 readers 行为准。每个 changed file：finding / format-only / UNREVIEWED。

- **Spec**：有 `{slug}_plan.md` 对照计划；纯 PR 无计划时从 PR 标题 + 索引 + UO **推断粗意图并验收完成度**（做完 / 半截 / 超范围）。禁止只陈述变更理解。
- **Standards**：对照 `references/ascendc-checks.md`、跨层契约、H0/H1。同样用 index + uo-query，不通读 diff。
- 两轴汇总时除了 findings，还必须给后续 TG 可直接使用的 **TG Planning Context**：
  - `changed_scope`：PR 实际修改的模块/路径/关键语义
  - `affected_scope`：经 UO 证明可能受影响的输入、分支、tiling/kernel 契约或输出行为
  - `risks`：需要测试证明或证伪的风险
  - `test_intent`：针对改动最应该覆盖的场景/边界/组合
  - `validation_targets`：哪些行为应作为精度、性能、replay/derived 指标的验证目标

这段 Planning Context 是对话上下文，不是新的 CE 正式产品；后续 `/tg-plan` 将它与 `tg/init.yaml` 一起作为核心输入。

## 禁止

- Write `ce/**`
- 合成一个 LGTM / 一个子代理写两轴
- 把审查叙述当成测量收据
- 用本地 fork 状态替代显式 PR source
