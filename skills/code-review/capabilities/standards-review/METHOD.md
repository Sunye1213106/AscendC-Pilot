# Standards 轴审查（隔离子代理）

只做 **Standards** 轴：对照仓规范，判断改动是否安全、是否符合跨层契约。不要做 Spec 轴。

详见 `references/ascendc-checks.md`、`references/cross-layer-contracts.md`、`references/gotchas.md`。

## 对照

- Kernel：`op_kernel/`；Tiling：`op_host/`。分侧陈述。
- 规范：`references/ascendc-checks.md` 与跨层契约。仓规范覆盖通用启发式。
- PR 入口必须有 `change_capture/index.md`。Finding 必须有 `path:line`。禁止线性通读 `diff.md`。

## 方法

```text
index 的 Added identifiers → 并行查标识符 → 字段 readers / 跨层契约 → H0/H1 → FINDING
```

1. 先读 `change_capture/index.md` / `uo_hints.md`，再插件 `pilot_cli` `uo-query`（**有 ident 用标识符**；卡片给出 `file:line` 后 **必须** `--file --line`，不要改去 Read 整文件。不要把 format hunk 当第一跳）。校验点看 `facts.check_sites`。
2. snippet 截断不得下「枚举未用」。Kernel 以字段 readers 行为准。每个 changed file：finding / format-only / UNREVIEWED。未审 `op_kernel` 禁止「无 high/medium」。
3. 「来源 = TilingData」不是已校验；必须指到 `OP_CHECK_IF` 的 `path:line` 且变量同一。
4. H0 = 该段符合规范；H1 = 可观察风险（越界、除零、同步缺失、跨层断裂）。报告前尝试推翻 H1。

## 产物

默认把 `path:line` 结论写在 **Task 回复**里。不要 Write `parts/*.md` 收票。禁止 Write `ce/**`。禁止合成 LGTM。对人说审查结论时不要堆 H0/H1 编号表。
