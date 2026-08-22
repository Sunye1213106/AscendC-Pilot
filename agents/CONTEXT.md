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

**Planning Context** — 用来确定本轮测试范围的上下文。不是正式 `plan.md`，也不是审查结论本身。

**clone 事实** — `workflow=auto` 成功回执中的 worktree 与 changed-files。不是「用户口头说的改动」。

**Open** — TG `worklog.md` 顶部尚未闭合的义务 id。不是 CE 的未决项。

**replay / derived** — TG 两类可判定依据。`replay` 是 Host tiling 回放；`derived` 是由当前输入与代码直接推出。二者都不是 E。易与「板上跑过」混。

**init.yaml** — TG 测试前置契约（列绑定 + 跑法/口径）。不是 cases，也不是 `plan.md`。

**plan.md** — TG 正式测试义务计划。不是 CE `{slug}_plan.md`，也不是 cases。

**cases 表** — TG 可执行用例行。不是义务表，也不是 worklog。

**worklog.md** — TG 求解账本。不是正式 cases；草稿不是正式 worklog。

**session_handoff.md** — 会话交接摘要。不是计划全文副本。

**quality.yaml** — 建库质量看 `grade` / `locate_blocking`。不是 unresolved 条数。

## 同名不可互换

跨 UO / TG / CE 传递时必须保留所属域，禁止仅按名字合并。

| 词 | UO | TG | CE |
| --- | --- | --- | --- |
| `obligation` | `key_field_obligations`（legacy） | `plan.md` 中的测试义务 | 计划里的「测试内容」散文；CE 不写 TG obligation YAML |
| `fingerprint` | graph histogram digest | `init.yaml.uo_digest` | git revision；fresh 与 handle digest 比较 |
| `kind` | `EntityKind`，如 `FIELD ≠ TILING_FIELD` | column mapping kind | 不作为 risk / workflow 路由账本 |
| `TilingKey` | CodeMap 中的维度实体 | 合法域来自 `product_uo.legal_key_rows` | 查询锚点；不等于默认全量覆盖 |
