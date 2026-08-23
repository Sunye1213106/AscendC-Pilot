# Context（agent 常驻词表）

模型常驻的跨工作流术语表。完整人类定义见 `docs/reference/glossary.md`。

每条只回答：是什么 / 不是什么 / 容易和什么混。

## 核心术语

**CodeMap / `.uo`** — 按「算子目录 + architecture」建立的二进制源码语义图。不是通用 call graph。易与「随便一张依赖图」混。

**digest** — session binding 中的 `canonical_graph_digest`。`fresh` 表示当前 digest 匹配，不是「最近建过库」。

**`/uo-update`** — 已有 CodeMap 上刷新源码变化。不是首次 `/uo-init`。

**查询 / `/uo-query`** — 读已有 CodeMap 的即时问答。不是 Host workflow，也不是建库。

**简单查询** — 单一起始符号或一种参数形态。
**复杂查询** — 含多个可独立查询的目标。二者不是「问得深 vs 问得浅」。

**`{slug}_plan.md`** — CE 用户变更计划。不是 TG `plan.md`，也不是 cases。

**ce-apply** — 按 CE 计划未完成 todo 改源码。不是审查，不是查图。

**两轴 review** — Spec 验收需求完成度；Standards 验收仓规范。不是 `plan.md`，也不是 cases。易与「写测试计划」混。

**Planning Context** — `/tg-plan` 第一窗 `plan_scope` 的 session 捕获（外加用户意图 / handoff）。不是磁盘 `targets.yaml`，也不是正式 `plan.md`，也不是审查结论。

**Target** — 可确定性判定 HIT/MISS 的实现状态。不是用户原话、diff 行或 CSV 列。

**Dimension** — Target 已成立时仍造成有意义实现差异、可输入控制、有限等价类、Replay 后可 classify 的语义轴。不是原始 B/N/S/D。

**Guard** — 决定 Target 是否允许进入的启用条件；翻转后 Target 不应再 HIT。

**Control** — 原始输入列（B/N/S/D、dtype 等），用来构造 case。

**evidence** — Host 编译运行后判定是否打到的尺子。`kind`：`replay_field` / `derived` / `dispatch_map` / `probe` / `source_proof`。不是精度/性能收据。

**Target HIT** — 引擎 `coverage_eval` 对 evidence 判定为 HIT。Host TilingKey `HIT` 只有在 evidence 就是那条 field 时才等同。LLM 不得宣布 HIT。

**L0–L3** — Target HIT + 每 Dimension partition 一个 witness / UO 证明的 pairwise / 高阶交互 tuple / 单 Guard 翻转。无 Dimension 时只找一个 Target witness。

**oracle** — 命中之后可选的精度 / 性能 / runtime。未指定不自动挂。

**clone 事实** — `workflow=auto` 成功回执中的 worktree 与 changed-files。不是「用户口头说的改动」。

**Open** — TG `worklog.md` 围栏里尚未 CLOSED 的义务 id。不是 CE 的未决项。空 `open: []` 散文不是签发条件。

**replay / derived** — evidence 的两种 `kind`。`replay_field` 读 Host tiling 回放字段；`derived` 由当前输入与 Replay 字段算出。二者都不是 E。

**init.yaml** — TG 测试前置契约（列绑定 + 跑法/口径）。不是 cases，也不是 `plan.md`。

**plan.md** — TG 正式测试规划：Target / Dimension / Guard + L0–L3。不是 CE `{slug}_plan.md`，也不是 cases。

**cases 表** — TG 可执行用例行。只在 certify 写出。不是 worklog。

**worklog.md** — TG 求解账本（含 coverage ledger 围栏）。不是正式 cases。

**session_handoff.md** — 会话交接摘要。不是计划全文副本。

**quality.yaml** — 建库质量看 `grade` / `locate_blocking`。不是 unresolved 条数。

## 同名不可互换

跨 UO / TG / CE 传递时必须保留所属域，禁止仅按名字合并。

| 词 | UO | TG | CE |
| --- | --- | --- | --- |
| `obligation` | `key_field_obligations`（legacy） | worklog 围栏里的覆盖义务；`plan.md` 写 Target/Dimension/Guard 不是义务 YAML | 计划里的「测试内容」散文；CE 不写 TG 义务 YAML |
| `fingerprint` | graph histogram digest | `init.yaml.uo_digest` | git revision；fresh 与 handle digest 比较 |
| `kind` | `EntityKind`，如 `FIELD ≠ TILING_FIELD` | column mapping kind；evidence.kind | 不作为 risk / workflow 路由账本 |
| `TilingKey` | CodeMap 中的维度实体 | 默认 Target = dispatch，candidate dims = 其维，不是全量合法 Key | 查询锚点；不等于默认全量覆盖 |
