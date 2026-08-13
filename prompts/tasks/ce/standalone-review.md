<task>
对当前修改做只读代码审查。入口为快速 / 文件 / PR 之一；证据先 CodeMap 再最小源码窗；假设检验后产出 finding / unresolved。
</task>

<context>
- Project: `<PROJECT_ROOT>`
- UO: `<UO_ROOT>`
- Current phase: session `current_phase`（scope / review / summary）
- Impact slice (if present): `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/impact/impact_slice.yaml`
- Change capture (if present): `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/impact/change_capture.yaml`

本入口不签发 CE 证书，也不关闭 verification obligation。无 diff 要定位改哪里：`/ce-intent`。有 diff 要范围与证书：`/ce-impact` → `/ce-verify`。
</context>

<instructions>
判定入口（写进 index 的 `entry`）：
- **quick**：用户要快速看风险 / 有没有问题。不写长报告。
- **file**：指定文件或全量检视工作区算子。
- **pr**：存在 change capture / diff。没有 diff 时不要猜 PR，标 UNRESOLVED 并停。

侧别：`op_kernel/` → Kernel，`op_host/` → Tiling。分侧陈述。

证据：
1. 先 `acp uo-query`（`impact` / `locate` / `field` / `buffer` / `kernel_api`）。校验点看 `facts.check_sites`，字段公式看 `facts.rhs`，队列方向看 `facts.tposition`。
2. 再开最小源码窗。不得把 partial 索引当成「没有其他调用者」。
3. 「来源 = TilingData」不是已校验；必须能指到 `OP_CHECK_IF` 的 `path:line` 且变量同一。

假设检验：H0 = 该段安全；H1 = 有可观察风险。Finding 必须有 `path:line`，并说明条件、约束、路径、后果。报告前尝试推翻。

按当前阶段写对应产物，但**每次结束时下面三份文件都必须存在且非空**：
- `ce/review/bug_report.yaml` — 缺陷类 finding（越界/同步/除零等）
- `ce/review/functional_report.yaml` — 跨层 / 合同 / 字段公式
- `ce/review/index.yaml` — 汇总；`entry` 为 quick | file | pr

阶段：
- `scope`：确认入口、侧别、CodeMap 邻域；PR 确认 diff。另两份可写空列表骨架。
- `review`：填写两份 report。快速入口每条 finding 保持短。
- `summary`：更新 index。快速入口 summary 不超过几行。

不确定内容标记 `UNRESOLVED`。禁止写入 `ce/verify/**`。
</instructions>

<output>
写入 `ce/review/` 下三份 YAML，严格使用：

```yaml
# ce/review/bug_report.yaml
schema: ce-review-bug/v1
reviewer_id: ce-reviewer
phase: review
findings: []
unresolved: []

# ce/review/functional_report.yaml
schema: ce-review-functional/v1
reviewer_id: ce-reviewer
phase: review
findings: []
unresolved: []

# ce/review/index.yaml
schema: ce-review-index/v1
reviewer_id: ce-reviewer
phase: summary
entry: file          # quick | file | pr
side: tiling         # kernel | tiling | both
bug_report: ce/review/bug_report.yaml
functional_report: ce/review/functional_report.yaml
finding_count: 0
unresolved_count: 0
summary: ""
```
</output>
