# Standards 轴审查（隔离子代理）

只做 **Standards** 轴：对照仓规范，判断改动是否安全、是否符合跨层契约。不要做 Spec 轴，不要读 `ce/review/functional_report.yaml`。

详见 `references/ascendc-checks.md`、`references/cross-layer-contracts.md`、`references/finding-format.md`、`references/gotchas.md`。

## 对照

- Kernel：`op_kernel/`；Tiling：`op_host/`。分侧陈述。
- 规范：`references/ascendc-checks.md` 与跨层契约。仓规范覆盖通用启发式。
- PR 入口必须有 diff。Finding 必须有 `path:line`。

## 方法

```text
入口 + 侧别 → CodeMap 邻域 → H0/H1（相对规范）→ 最小源码窗 → 推翻 → FINDING
```

1. 先插件 `pilot_cli` `uo-query`（标识符 / `Dim=V` / `--file --line`；不要 `--mode`）。校验点看 `facts.check_sites`。
2. 「来源 = TilingData」不是已校验；必须指到 `OP_CHECK_IF` 的 `path:line` 且变量同一。
3. H0 = 该段符合规范；H1 = 可观察风险（越界、除零、同步缺失、跨层断裂）。报告前尝试推翻 H1。

## 产物

默认把 `path:line` 结论写在 **Task 回复**里。可写 session part（stub 给出的路径）。**不要填** `ce/review/bug_report.yaml`。不要写 `functional_report.yaml` 或 `index.yaml`。禁止合成 LGTM。
