# CE verify code review — 按义务判定，不签发证书

对 `ce/impact` 账本里的义务做有源码依据的验证审查。不重建 CodeMap 权威。排除项只由 `ce-change-referee` 处理。

详见 `references/ascendc-checks.md`、`references/cross-layer-contracts.md`、`references/precision-perf-findings.md`、`references/evidence-quality.md`。证据档次见 `skills/code-engineering/references/evidence-tiers.md`。

## 方法

1. 先读 `ce/impact/change_capture.yaml`，将 `head_sha` 原样写入 `change_head_sha`；不得猜测或复用旧 SHA。
2. 先按 obligation anchor 查询 CodeMap，再读最小必要源码窗口。
3. `NO_CONFIRMED_ISSUE` 不是验证证据，不得关闭 obligation。
4. 只有 closure requirement 可由静态源码证明满足时，才可输出 `VERIFIED`。runtime/external obligation（dispatch 复测、精度、性能、卡死复现）必须保持 `UNRESOLVED`，等 `ce-external-evidence/v1` 测量收据。
5. 每条 `VERIFIED` 必须带非空 `evidence_refs`（`path:line` 或区间）和 `evidence_tier` A/B。
6. 不确定标 `UNRESOLVED`。审查叙述不能充当 UT/ST/精度/profiling 收据。

## 禁止

- 输出 `excepted_obligations`
- 把本步当成 `/ce-review` 的 quick/file/pr 入口 SOP
- 签发 CE 证书或改写 O/V/X
