# Context（agent 常驻词表）

用这里的词思考和说话。人类全表：`docs/reference/glossary.md`。

CE grill 冒出跨 session 会用错的新词时才改本表；算子结构事实仍以 CodeMap 为准。

**CodeMap** — UO 写入的 `.uo` 源码语义图。不是通用 call-graph。
**digest** — session binding 上的 `canonical_graph_digest`。fresh = digest 匹配，不是「刚建过库」。
**plan.md** — `/ce-intent` 确认后冻结的面向用户变更计划，落在 `ce/intent/plan.md`。`/ce-apply` 必须对齐它。面向用户默认只落这一份（加 `todo.md`）。
**todo.md** — `/ce-apply` 工作清单（`ce/apply/todo.md`）。一次一个未勾选垂直切片；简单需求也写这一份。
**两轴** — Spec（是不是 plan 要的；无 plan 则从 diff 推断意图）与 Standards（是不是仓规范）。review 阶段并行两个子代理，禁止合成 LGTM。结论默认在会话中陈述；用户要求落盘才写 `ce/review`。
**tg_plan_intent** — `/ce-impact` 写出的 `ce/impact/tg_plan_intent.yaml`。`/tg-plan` 有则融进 `plan.md` 义务，不做文件强制，也不要静默扩成全部合法 Key。
**简单查询** — 一个起始标识符或一种参数形态、一两轮调用；主控当前会话插件 `pilot_cli`（command=`uo-query …`，不要前导 acp），stdout 即答案。
**复杂查询** — 多个可独立查询的目标；同一轮并行 `Task(agent=uo-query)`，每路一个起始标识符或 `Dim=V`。综合只在主控。禁止因「要交叉综合」而合并 Task。
**查询方式说明** — 查询不是 Host workflow：先向用户说明直接调用还是委派几路，再执行。见 `routing/uo-query.md`。
**Open** — 未闭合集合。CE：`Open = O - V - X`。TG：worklog 文首 `open:` 里尚未闭合的义务 id。两套账本，不要合并。
**Tier A/B/C** — A 权威窗口，B 由 A 确定性推出，C 是线索。C 不能把义务送进 `V` 或 `X`。
**replay / derived** — TG 给 solve 的指标只有两类，都先 root 到 CSV/XLS 列。`replay`：Host tiling（无 NPU）看 key / TD / OP_CHECK / 分支。`derived`：这行输入 + 代码逻辑可推。`Replay reject ≠ E`。
**init.yaml / plan.md / worklog.md** — TG 正式产物只这三份（外加脚本可吃的 cases 表）。草稿只留 `runs/`。
**quality.yaml** — 建库评价看 `grade` / `locate_blocking`，不看 unresolved 条数。

## 同名不可互换

跨 UO / TG / CE 传递时必须带限定，不能按名字合并：

| 词 | UO | TG | CE |
| --- | --- | --- | --- |
| obligation | `key_field_obligations`（legacy） | `plan.md` YAML 义务 | 账本 `ce-{risk_class}-{digest}` / `O-V-X` |
| fingerprint | graph 直方图 digest | `init.yaml` 的 `uo_digest` | `cm_graph_fingerprint` 或 git revision；fresh 比 handle.digest |
| kind | `EntityKind`（FIELD ≠ TILING_FIELD） | 列 mapping | risk 路由 |
| TilingKey | CodeMap 维实体 | 声明域来自 `product_uo.legal_key_rows`；不是默认 T | dispatch 锚点 |
