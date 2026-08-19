# Context（agent 常驻词表）

用这里的词思考和说话。人类全表：`docs/reference/glossary.md`。

CE grill 冒出跨 session 会用错的新词时才改本表；算子结构事实仍以 CodeMap 为准。

**CodeMap** — UO 写入的 `.uo` 源码语义图。不是通用 call-graph。
**digest** — session binding 上的 `canonical_graph_digest`。fresh = digest 匹配，不是「刚建过库」。
**`{slug}_plan.md`** — `/ce-plan` 确认后的面向用户变更计划，落在 `ce/plan/{slug}_plan.md`。含实现分析、分步计划、可勾选 todo、测试内容。`/ce-apply` 只按未完成 `- [ ]` 改码，并可勾选该文件。
**两轴** — Spec（有计划则对照 `{slug}_plan.md`；无计划则从 PR/diff 索引推断粗意图并验收完成度）与 Standards（是不是仓规范）。`/ce-review` 并行两个子代理，禁止合成 LGTM。结论留在对话，不落盘。
**简单查询** — 一个起始标识符或一种参数形态、一两轮调用；主控当前会话插件 `pilot_cli`（command=`uo-query …`），stdout 即答案。
**复杂查询** — 多个可独立查询的目标；同一轮并行 `Task(agent=uo-query)`，每路一个起始标识符或 `Dim=V`。综合只在主控。禁止因「要交叉综合」而合并 Task。
**查询方式说明** — 查询不是 Host workflow。简单查询直接 `pilot_cli` `uo-query`，禁止单独一轮只宣布路数；复杂查询同一轮并行 `Task(agent=uo-query)`。见 `routing/uo-query.md`。四种形态：标识符 / `Dim=V` / `--file --line` / 无参数索引。不要传 `--mode`。禁止 `explain-*`、`search`、`locate`。
**Open** — TG worklog 文首 `open:` 里尚未闭合的义务 id。CE 不维护账本。
**replay / derived** — TG 给 solve 的指标只有两类，都先 root 到 CSV/XLS 列。`replay`：Host tiling（无 NPU）看 key / TD / OP_CHECK / 分支。`derived`：这行输入 + 代码逻辑可推。`Replay reject ≠ E`。
**init.yaml / plan.md / worklog.md** — TG 正式产物只这三份（外加脚本可读的 cases 表）。草稿只留 `runs/`。
**session_handoff.md** — `/handoff` 写出的对话总结，落在 arch 根。只引用已有产物路径和下一步 slash，不抄 `{slug}_plan.md` 全文。
**quality.yaml** — 建库评价看 `grade` / `locate_blocking`，不看 unresolved 条数。

## 同名不可互换

跨 UO / TG / CE 传递时必须带限定，不能按名字合并：

| 词 | UO | TG | CE |
| --- | --- | --- | --- |
| obligation | `key_field_obligations`（legacy） | `plan.md` YAML 义务 | 计划 md 的「测试内容」节（散文）；TG 自己总结，CE 不写义务 yaml |
| fingerprint | graph 直方图 digest | `init.yaml` 的 `uo_digest` | git revision；fresh 比 handle.digest |
| kind | `EntityKind`（FIELD ≠ TILING_FIELD） | 列 mapping | 不按 risk 路由写账本 |
| TilingKey | CodeMap 维实体 | 声明域来自 `product_uo.legal_key_rows`；不是默认 T | 查询锚点，不是默认全量覆盖 |
