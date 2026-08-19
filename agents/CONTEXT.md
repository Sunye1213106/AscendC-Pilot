# Context（agent 常驻词表）

用这里的词思考和说话。人类全表：`docs/reference/glossary.md`。

CE grill 冒出跨 session 会用错的新词时才改本表；算子结构事实仍以 CodeMap 为准。

**CodeMap / `.uo`** — `/uo-init` 按算子目录 + architecture 建立的二进制源码语义图。不是通用 call-graph。TG / CE / 查询的语义底座。确定性引擎：主控只 `pilot_run`，不开 LLM 子代理。
**digest** — session binding 上的 `canonical_graph_digest`。fresh = digest 匹配，不是「刚建过库」。
**刷新 `.uo`** — `/uo-update`：已有 `.uo` 上按工作区 / diff / PR 变更检测，增量重建受影响层（host / kernel / compile / commit）。不是再跑 `/uo-init`。common / 头文件变更可能扩成全量抽取。确定性引擎。
**查询** — `/uo-query`：CodeMap 的对外查询接口。禁止 `pilot_run`。简单查询：主控当前会话 `pilot_cli`（command=`uo-query …`），stdout 即答案。复杂查询：主控同一轮并行 `Task(agent=uo-query)`，每路一个起始标识符或 `Dim=V`，综合只在主控。TG / CE 缺语义时用它，不要 Grep 算子仓。子代禁止再派 Task。意图只是查语义：留在主线，不要再包一层 coordinator。
**简单查询** — 一个起始标识符或一种参数形态、一两轮调用；主控直接 `pilot_cli`，不委派子代理。
**复杂查询** — 多个可独立查询的目标；同一轮并行 `Task(agent=uo-query)`。禁止因「要交叉综合」而合并 Task。
**查询方式说明** — 查询不是 Host workflow。见 `routing/uo-query.md`。四种形态：标识符 / `Dim=V` / `--file --line` / 无参数索引。不要传 `--mode`。禁止 `explain-*`、`search`、`locate`。
**`{slug}_plan.md`** — `/ce-plan` 确认后的面向用户变更计划，落在 `ce/plan/{slug}_plan.md`。输入是用户「改什么 / 实现什么」+ UO 语义（grillme），不是 PR。含实现分析、分步计划、可勾选 todo、测试内容。`/ce-apply` 只按未完成 `- [ ]` 改码，并可勾选该文件。
**ce-apply** — 按 todo 改 `op_host/` / `op_kernel/` / `common/` / `test_script/`。也可按 `/tg-plan` 的 `test_harness_gap` 说明书生成或修改测试脚本（含随机数生成器）。apply 不查图、不审。
**两轴** — Spec（有计划则对照 `{slug}_plan.md`；无计划则从已有 diff 索引推断粗意图并验收完成度）与 Standards（是不是仓规范）。`/ce-review` 由**主控**同一轮并行两个 `ce-reviewer`，禁止合成 LGTM。结论留在对话，不落盘。结论是 **Planning Context** 的一种来源（意图 / 改了什么 / 计划达成 / 问题 / 若测应重点测什么），不是 `plan.md`，不是 cases。`/tg-plan` 不审查 diff。意图只是审查：留在主线，不要再包 coordinator。
**Planning Context** — `/tg-plan` 写义务所依据的测试范围。不是 `init.yaml`，不是 cases。来源：同一会话 `/ce-review` 结论、`{slug}_plan.md` 的「测试内容」、用户已说清的范围、`session_handoff.md`、或用户已选定只要用例时主控综合的 `/uo-query` 结论。没有范围就不要开 `/tg-plan`。
**clone 事实** — `workflow=auto` 成功回执给出 worktree、changed-files；若路径令牌唯一确定 `(算子, architecture)`，将该对用于后续 `pilot_run`，不要再问架构，也不要为理解语义通读全量 git diff。多算子或多 architecture 才 AskQuestion。禁止把卡片全文写入后续 slash 的 intent。
**Open** — TG worklog 文首 `open:` 里尚未闭合的义务 id。CE 不维护账本。
**replay / derived** — TG 给 solve 的指标只有两类，都先 root 到 CSV/XLS 列或 `init.yaml` 已声明的代码变量。`replay`：Host tiling（无 NPU）看 key / TD / OP_CHECK / 分支。`derived`：这行输入 + 代码逻辑可推。`Replay reject ≠ E`。
**init.yaml** — `/tg-init` 写出的测试前置契约。用 `.uo` + **可选**测试脚本：有仓则绑定脚本输入变量（CSV/XLS 列、生成器、代码里的读点）与算子 / UO 变量，并写 golden 对照、精度条件、性能条件；mapping 空则失败。无仓则用 uo-query 读输入 API 设计 `kind=default_input` 控制面。不是 cases。
**plan.md** — `/tg-plan` 写出的测试义务计划：测试意图 + `init.yaml` → 有限覆盖子集（表列变量或代码变量）及精度 / 性能要求。不是可执行用例。缺脚本 / 列 / 生成器（含随机数）写 `test_harness_gap` 说明书，交 `/ce-apply` 补仓或改脚本；不要在 TG 里改算子仓。
**cases 表** — `/tg-solve` 按 plan 定向构造、Host 动态回放、引理闭合后物化的可执行用例。不是 `plan.md`。`test_harness_gap` 未落地禁止 start。
**worklog.md** — TG 求解过程账本。草稿只留 `runs/`。
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
