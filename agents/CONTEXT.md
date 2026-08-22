# Context（agent 常驻词表）

模型常驻的跨工作流术语表。完整人类定义见 `docs/reference/glossary.md`。

只回答：这个词是什么、不是什么、易与哪个词混淆。编排不写在这里。人记 slash（`/tg-init` / `/tg-plan` / `/tg-solve` / `/ce-*` / `/uo-*` / `/handoff`），不记磁盘 `skills/` 目录名。

## 核心术语

**CodeMap / `.uo`** — 按「算子目录 + architecture」建立的二进制源码语义图。不是通用 call graph。UO 查询、TG、CE 的语义底座。

**digest** — session binding 中的 `canonical_graph_digest`。`fresh` 表示当前 digest 匹配，不表示「最近建过库」。

**`/uo-update`** — 已有 CodeMap 上刷新源码变化。不同于首次 `/uo-init`。

**查询 / `/uo-query`** — 读 CodeMap 的 Command，不是 Host workflow。形态见 code-access 不变量。

**简单查询** — 单一起始符号或参数形态。
**复杂查询** — 含多个可独立查询的目标。

**`{slug}_plan.md`** — `/ce-plan` 确认后的用户变更计划（`ce/plan/{slug}_plan.md`）。输入是需求 + UO 语义，不是 PR。边问边写：实现分析、todo、测试内容。不是 `plan.md`，也不是 cases。

**ce-apply** — 按计划未完成 `- [ ]` 改代码，或按 `test_harness_gap` 改测试脚本。不是审查，不是查图。

**两轴 review** — Spec：是否完成计划（无计划时按 diff 推断粗粒度意图）。Standards：是否符合仓规范。结论留在会话，可作为 Planning Context，但不是 `plan.md` 或 cases。

**Planning Context** — 用来确定本轮测试范围的上下文。来源可以是当前会话、审查结论、`{slug}_plan.md` 的测试内容、用户已陈述范围、`session_handoff.md`，或已有 `init.yaml` + 查询结论。

**clone 事实** — `workflow=auto` 成功回执中的 worktree 与 changed-files。

**Open** — TG `worklog.md` 顶部 `open:` 里尚未闭合的 obligation id。CE 不维护该账本。

**replay / derived** — TG 两类可判定依据，均须 root 到列或 `init.yaml` 已声明变量。`replay`：Host tiling 回放（key / TD / OP_CHECK / 分支）。`derived`：由当前输入与代码直接推出。`Replay reject ≠ E`。

**init.yaml** — `/tg-init` 的测试前置契约：列绑定 + 跑法/口径。不是 cases，也不是 `plan.md`。

**plan.md** — `/tg-plan` 的测试义务表。不是可执行用例。缺脚本/列/生成器记 `test_harness_gap`，不改算子仓。

**cases 表** — `/tg-solve` 按义务构造、经 replay / 引理闭合后的可执行行。存在未落地 `test_harness_gap` 时不得 start。

**worklog.md** — TG 求解账本；临时草稿只放 `runs/`。

**session_handoff.md** — 会话交接摘要。只引用已有产物路径与下一步 slash，不复制计划全文。

**quality.yaml** — 建库质量看 `grade` / `locate_blocking`，不看 unresolved 条数。

## 同名不可互换

跨 UO / TG / CE 传递时必须保留所属域，禁止仅按名字合并。

| 词 | UO | TG | CE |
| --- | --- | --- | --- |
| `obligation` | `key_field_obligations`（legacy） | `plan.md` 中的测试义务 | 计划里的「测试内容」散文；CE 不写 TG obligation YAML |
| `fingerprint` | graph histogram digest | `init.yaml.uo_digest` | git revision；fresh 与 handle digest 比较 |
| `kind` | `EntityKind`，如 `FIELD ≠ TILING_FIELD` | column mapping kind | 不作为 risk / workflow 路由账本 |
| `TilingKey` | CodeMap 中的维度实体 | 合法域来自 `product_uo.legal_key_rows` | 查询锚点；不等于默认全量覆盖 |
