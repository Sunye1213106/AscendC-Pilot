# Standalone code review（`/ce-review`）

只读检视。不签发 CE 证书，不关闭 verification obligation。无 diff 要定位改哪里：`/ce-intent`。有 diff 要范围与证书：`/ce-impact` → `/ce-verify`。

详见 `references/cross-layer-contracts.md`、`references/ascendc-checks.md`、`references/finding-format.md`、`references/evidence-quality.md`、`references/gotchas.md`。

## 入口（写入 index `entry`）

- **quick**：快速看风险。短 finding，不写长报告。
- **file**：指定文件或全量检视当前算子。
- **pr**：存在 change capture / diff。没有 diff 时不要猜 PR，标 UNRESOLVED 并停。

侧别：`op_kernel/` → Kernel，`op_host/` → Tiling。分侧陈述。

## 证据与假设

```text
入口 + 侧别 → CodeMap 邻域 → H0/H1 → 最小源码窗 → 推翻 → FINDING / NO_CONFIRMED_ISSUE / UNRESOLVED
```

1. 先 `acp uo-query`（`impact` / `locate` / `field` / `buffer` / `kernel_api`）。校验点看 `facts.check_sites`，字段公式看 `facts.rhs`，队列方向看 `facts.tposition`。
2. 再开最小源码窗。不得把 partial 索引当成「没有其他调用者」。
3. 「来源 = TilingData」不是已校验；必须能指到 `OP_CHECK_IF` 的 `path:line` 且变量同一。
4. H0 = 该段安全；H1 = 有可观察风险。Finding 必须有 `path:line`，并说明条件、约束、路径、后果。报告前尝试推翻 H1。

## 阶段产物

每次结束时三份文件都必须存在且非空：`ce/review/bug_report.yaml`、`functional_report.yaml`、`index.yaml`。

- `scope`：确认入口、侧别、CodeMap 邻域；PR 确认 diff。另两份可写空列表骨架。
- `review`：填写两份 report。快速入口每条 finding 保持短。
- `summary`：更新 index。快速入口 summary 不超过几行。

禁止写入 `ce/verify/**`。
