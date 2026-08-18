# Standalone code review（`/ce-review`）

只读检视。输入只有代码改动。无 diff 则停。不写 `ce/review/`，不写测试意图 yaml。

详见 `references/cross-layer-contracts.md`、`references/ascendc-checks.md`、`references/finding-format.md`、`references/gotchas.md`。

review 阶段由 Host 并行派两个隔离子代理（`spec-review` / `standards-review`）。本 METHOD 覆盖入口说明。stub 含 `AXIS=` 时不要用这份方法写那一轴。

## 输入

- GitCode / GitHub 风格 PR URL（须在对应算子仓打开且该 arch 已有 `.uo`；引擎先匹配已有 remote，否则允许列表内 HTTPS patch，后者需要 `GITHUB_TOKEN` / `GITCODE_TOKEN`）
- `/ce-apply` 后的工作区 diff
- 用户给的 `base...head`（无 PR URL 时）

有 PR URL 时禁止用工作区未提交改动冒充 patch。没有 diff 时标 UNRESOLVED 并停。不要猜。

侧别：`op_kernel/` → Kernel，`op_host/` → Tiling。分侧陈述。

## 语义

先 `uo-query --file PATH --line N`，再对 FOCUS 名做标识符查询。不要传 `--mode`。禁止 `explain-*` / Grep 通读。

- **Spec**：有 `{slug}_plan.md` 对照计划；没有则只陈述变更理解。
- **Standards**：对照 `references/ascendc-checks.md`、跨层契约、H0/H1。

## 禁止

- Write `ce/**`
- 合成一个 LGTM / 一个子代理写两轴
- 把审查叙述当成测量收据
