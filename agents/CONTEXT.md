# Context（agent 常驻词表）

用这里的词思考和说话。人类全表：`docs/reference/glossary.md`。

CE grill 冒出跨 session 会用错的新词时才改本表；算子结构事实仍以 CodeMap 为准。

**CodeMap** — UO 写入的 `.uo` 源码语义图。不是通用 call-graph。
**digest** — session binding 上的 `canonical_graph_digest`。fresh = digest 匹配，不是「刚建过库」。
**plan.md** — `/ce-intent` 确认后冻结的面向用户变更计划，落在 `ce/intent/plan.md`。`/ce-apply` 必须对齐它。面向用户默认只落这一份（加 `todo.md`）。
**todo.md** — `/ce-apply` 工作清单（`ce/apply/todo.md`）。一次一个未勾选垂直切片；简单需求也写这一份。
**两轴** — Spec（是不是 plan 要的；无 plan 则从 diff 推断意图）与 Standards（是不是仓规范）。review 阶段并行两个子代理，禁止合成 LGTM。结论默认在会话中陈述；用户要求落盘才写 `ce/review`。
**tg_plan_intent** — `/ce-impact` 写出的 `ce/impact/tg_plan_intent.yaml`，`/tg-plan` 直接消费（mode=`ce_change_scoped`），不要静默扩成全部合法 Key。
**简单查询** — 一个起始标识符或一种参数形态、一两轮调用；主控当前会话 `acp uo-query`，stdout 即答案。
**复杂查询** — 多个可独立查询的目标；同一轮并行 `Task(agent=uo-query)`，每路一个起始标识符或 `Dim=V`。综合只在主控。禁止因「要交叉综合」而合并 Task。
**查询方式说明** — 查询不是 Host workflow：先向用户说明直接调用还是委派几路，再执行。见 `routing/uo-query.md`。
**Open** — 未闭合集合。CE：`Open = O - V - X`。TG：`T` 中尚未进入 `(R∩T)∪E` 的元素。两套账本，不要合并。
**Tier A/B/C** — A 权威窗口，B 由 A 确定性推出，C 是线索。C 不能把义务送进 `V` 或 `X`。
**R / E / T / D** — TG：`R` Host replay 见证，`E` 源码不可达引理，`T` 已批准目标，`D` 声明 legal key。完成：`T = (R∩T) ∪ E` 且 `R∩E = ∅`。`Replay reject ≠ E`。
**quality.yaml** — 建库评价看 `grade` / `locate_blocking`，不看 unresolved 条数。

## 同名不可互换

跨 UO / TG / CE 传递时必须带限定，不能按名字合并：

| 词 | UO | TG | CE |
| --- | --- | --- | --- |
| obligation | `key_field_obligations`（legacy） | `coverage_obligations.yaml` | 账本 `ce-{risk_class}-{digest}` / `O-V-X` |
| fingerprint | graph 直方图 digest | kb 文件 sha256 | `cm_graph_fingerprint` 或 git revision；fresh 比 handle.digest |
| kind | `EntityKind`（FIELD ≠ TILING_FIELD） | binding：`key_dim` / `key_dim_host` | risk 路由 |
| TilingKey | CodeMap 维实体 | contract 里 `D` 是 packed int | dispatch 锚点 |
