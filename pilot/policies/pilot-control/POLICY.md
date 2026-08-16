# Policy: pilot-control

## Purpose

Pilot 独占状态、合法边、门禁与完成态。

## Rules

1. 只能执行 `acp next` 返回的 Action。
2. Skill、Prompt、Agent、Capability、Action Method **不得**推进工作流状态。
3. 终态只认 `acp complete`；禁止自行宣布 `done` / `passed`。
4. Gate fail ≠ 立即 `blocked`；保持 phase，进入 `rework_required` / `human_required`。进入 `human_required` 后，`acp next` / finalize 会返回 `needs_human_decision` + `ask_question`：**同一轮**必须用 `question` 弹出可点选框（环境修好后重试 / 查看失败 / 终止），禁止只写旁白不交互。
5. 禁止直调领域 CLI（`build_layered_kb.py`、`tg-init`、`tg-plan`、`tg-solve` 等）；须经 acp 包装。
6. 正式产物须 Pilot 签发收据。
7. **进度**：长任务（尤其 `uo-init`）由 Host 工具 `pilot_run` 在 OpenCode 工具行显示进度条；同时同步原生 Todo 面板。禁止在主对话输出工作流状态面板 / 阶段 checklist。
8. bash 优先用工具 `workdir` 指向算子目录；若写 `cd <dir> && acp …`，Pilot 只认末尾纯 `acp` 段（禁止夹杂其它命令）。禁止用 bash/`>`/`Set-Content`/`tee` 写入 `.ascendc-pilot/**` 正式产物以绕过 Write 围栏。**只读定位**允许：`ls`/`Get-ChildItem`/`grep`/`rg`/`Select-String`/`findstr`（无写重定向）；仍不得当高置信证据。**`uo-query` / `kb_lookup` 禁止仓级 findstr/grep/rg**，只用 `acp uo-query` 或 `acp ro-search --paths <已 citation 文件>`。优先 `pilot_run`。若必须 bash 调 `acp`，禁止管道缓冲：PowerShell `| Select-Object -Last N`、`| Out-String`，bash `| tail`。
8a. **子代 skill / Host rg / 跨目录 Read**：子代理禁止 OpenCode `skill` 工具（读 session `method.md`）；主控 skill 由插件从已安装 `SKILL.md` 恢复，不依赖 OpenCode 进程里的 `rg`。MCP 不拦截——`uo-query` 能答就不应改走其它索引。**AscendC-Pilot 模式对任意目录 Read 直接 allow**（`external_directory` / `read` 不 ask）；算子仓在 Host 工作区外时禁止把 session/源码 Read 弹成确认框。Write/edit 仍 ask；Pilot authorize 仍围栏写入。
9. **Subagent / primary_interactive 派发**：仅派发 Spec 中声明的 actor；Primary 禁止代写正式 IR。Task 须带 `subagent_type`/`agent`=actor 与 `action_id`。**Task 正文只能原样使用 prepare 返回的 `task_prompt_stub`**（禁止复述 METHOD、禁止塞额外目标、禁止空 prompt）。**`host_step.tasks` ≥2：同一轮并行派发每条 `tasks[i].task_prompt_stub`，全部返回后 Primary 按各 Task 原生全文综合**；禁止只转述某一个子代理，禁止发明子代理没引用的事实。**同 Action rework 必须 resume 原 Task session**。正式产物仅 Host **finalize**。已删除的历史 Action（如 `extract_plan` / `uo-semantic-resolve` / `adjudicate_llm_tasks` 及历史 UO scope 人工确认类 Action）不得再派发。
9a. **`ARTIFACT_SESSION_MISMATCH` / identity 失败**：禁止派发「FIX ONLY 改 `action_session_id`」类非 stub 正文。合法路径二选一：(1) **resume 原 Task + 原样 stub** 让子代理按合同重写整份产物 identity；(2) 按 `retry_command` **完整 re-prepare** 后，用**新 stub** 派发，由子代理按新 session **整份重写**产物（不得只改 identity 单字段）。
10. **Debug 模式（可选）**：`acp debug enable --project <算子目录>` 后自动捕捉工具失败与过长非逻辑思考链，并在子代理结束时导出 session bundle 到 `.ascendc-pilot/debug/exports/`。排查完 `acp debug disable`。手动导出：`acp debug export-session`。
11. **关键参数不明确 → 立刻 AskQuestion**：算子路径（`--project`）、architecture、continue/reinit 缺一不可时，**同一轮**用 `question` 可点选框问清；禁止为猜答案而全库 Glob、读历史 session 考古、长篇「让我想想」。已明确则直接执行，勿重复确认。**`uo-init` / `uo-update` 启动不要求测试脚本路径**——那是历史 TG CSV 契约用的，当前默认 TG 只认 `.uo` + Host replay。UO prepare 的范围是 Clang machine scope，**禁止**人工文件列表确认。
11a. **`acp` 发现**：`acp` 由安装脚本进 PATH；禁止在 AscendC-Pilot 仓内找 `acp.exe`。只允许 `acp --help` / `Get-Command acp`；找不到则请用户重装，不要考古。
11b. **启动条件（Spec 权威）**：`requires_architecture=true` 的 workflow（`uo-init` / `uo-update`）必须同时有 `--project` 与 `--architecture`。缺 arch 时：**先**跑 `acp scan-architectures --project <算子目录>`，阅读返回的 `layout` / `architecture_option_details`，再 AskQuestion（选项原样使用 details）；也可直接 `acp start … --project …`（无 `--architecture`）拿 `ARCHITECTURE_REQUIRED` + 同结构选项。AskQuestion 后执行一次 `acp start … --project … --architecture <选中>`。**禁止**仓根 Glob `arch*`、翻 `cmake/` / `classify_rule.yaml` / `get_soc_version.py` 考古猜 arch。`requires_uo_product=true` 的 workflow 以已有 `.uo` 为准：无产物 → `UO_PRODUCT_REQUIRED`。**产物路径是确定的**（`<算子目录>/.ascendc-pilot/<arch>/uo/<op>.<arch>.uo`），禁止 Glob/dir/Grep 找 `.uo`、禁止猜 `--op-name`。查询类（`uo-query` / `uo-investigate`）AskQuestion 二选一：先 `/uo-init`，或回退源码作答（开发者决定）；TG/CE 仍须先 `/uo-init`。架构从 `.uo` 继承，不另扫 arch* 当权威。禁止编造仓内不存在的 arch，禁止静默默认 architecture。
11c. **产物根 = 对话指定的算子目录**：`.ascendc-pilot/` 只建在 `--project` 算子包下。OpenCode 可从任意 cwd 启动，但每个 `acp *` 必须带该 `--project`（或依赖 last-project cache，且 cache 只能是算子包）。禁止在 monorepo 父目录 / Pilot 仓根创建 `.ascendc-pilot/`。
11d. **Clang 探针 / CANN include 失败**：这是 CANN 包 / BuildContext 问题，不是算子 `unknown`。不要用 `UO_TEST_ALLOW_UNVERIFIED_SCOPE`。细则：`skills/operator-analysis/references/codemap-build-gotchas.md`。
11e. **人话出口**：凡 `needs_human_decision` / 阶段总结 / Goal 推进 / 失败给人看的摘要，必须意图+动作+后果（见 `human-voice-invariants.md`）。禁止把 referee 黑话贴给用户。
11f. **User Goal（全量 case）**：匹配「全量/全覆盖/tilingkey case」时走 `control/user_goal.yaml` + `acp start … --intent`；`complete` 后若有 `recommended_next_workflow` 则人话说明并 start 下一步。不是查询路由启发式。
11g. **启动失败不要考古 Pilot 仓**：`pilot_run` / `acp start` 失败时：缺 architecture 就 `acp scan-architectures` 再 AskQuestion；已带 `--architecture` 仍报 `ARCHITECTURE_MISSING_IN_RUN_STATE` 时去掉 `force_new` 再 start 一次。禁止传 `force_new`，除非用户明确要求删除重开（会 wipe `.uo`）。禁止为排障 Read Pilot 源码、禁止发明 `acp` 子命令、禁止把 `; echo` / 管道接到 `acp`。`acp doctor` 是环境预检，不需要 architecture，也不创建 arch 树。
11h. **完成态读收据再对人说**：`uo-init` / `uo-update` done 后 Primary **Read** `host_step.quality_path`（`.ascendc-pilot/<arch>/uo/checks/quality.yaml`；节点/关系在 `graph`，未闭合在 `unresolved`；桶含义见 `uo-gaps.md`），需要名单再读同树 `uo/ir/unresolved.yaml`。禁止读无 arch 的 `.ascendc-pilot/uo/`，禁止打开 `.uo` 二进制，禁止只说「workflow complete」，禁止 Host 另写一份摘要。`uo-query` 把答案正文说给人听。**`complete` 必须释放本产物族锁并（UO 写工作流）发布 digest**（归档 `runs/{run_id}/final_state.yaml`，清掉 `state/slots/{family}/workflow.yaml`；`active_run` 只是最近 exclusive 指针）。不同族（uo vs tg vs ce-*）并行，禁止再抛「活动是 uo-init、请求 tg-init → 释放全局槽」。同族未完成写 run 才 AskQuestion 继续/重开。CodeMap 更新后对人只说：上一轮结论置信度下降，需要则重新查 / 重新 pin。

12. **禁止跳步**：`acp next` 返回 `recommended_next_action` 时必须执行该 Action；禁止从 `allowed_actions` 里挑后面的步骤。确定性段优先 `acp run-action auto`；finalize / auto 后必须立刻再 `acp next`（或按返回继续），不要自行猜下一步。
13. **Lease 不变量（全局）**：Action `allowed_write_paths` **必须**可读（签发时自动并入 `allowed_read_paths`）。禁止「能 Write 产物却不能 Read 自检」；勿在个别 skill 里另开例外。

## 原生 Todo（所有 workflow 共用 · OpenCode `todowrite`）

阶段列表**不得**写死在各 Skill 里。一律以当前活动工作流为准：

1. **Agent 按 workflow skill 的 description 自行加载对应 Skill**（与其它 OpenCode skill 相同），然后 `acp start <workflow_id>`。`acp route` 仅可选用于 slash（如 `/uo-init`），**不做**口语关键词匹配。用户说「建立知识库 / 建库 / 索引算子 / 建 CodeMap」等口语时，**必须**优先匹配已有 workflow/skill（通常 `uo-init`，已有产物则 `uo-update` / `uo-query`），**禁止**改用外部 MCP 或通用代码图谱索引。
2. 响应里的 `todo.todo_sync.items`（与 `todo.native_items` 相同）即该工作流在 Spec 中的**完整**阶段（必须含 `id` + 中文 `content` + `status`）。
3. **何时 `todowrite`（执行规则，禁止纠结旁白）**：
   - `acp start` 成功后：**必须**立刻同步一次（`merge` 取 JSON 布尔值；新 start 为 `false`）。
   - **`acp run-action auto` 返回后：必须立刻 `todowrite`（merge=true）**——auto 在一次调用内跑完多步确定性 Action，中间不会回到 Host；返回体里的 `todo.todo_sync`（常带 `force`/`after_auto`）是权威进度，禁止拖到下一轮再同步。
   - `advance` / `rework` / `complete` 成功后：若 `todo.todo_sync.items` 相对本轮上次已同步内容有任一 `id`/`status`/`content` 变化 → **必须**同步（`merge: true`）。
   - 纯查询型 `acp next` / `status`：仅当 items 相对上次同步有变化时才同步；**完全相同则跳过**，直接执行 Action。
   - **禁止**在思考/回复里讨论「要不要同步」「是否冗余」「严格来说该不该」——有变化就静默 `todowrite`，无变化就跳过。
   - 需要同步时：与下一步 `acp`/`run-action` **同一轮并行**调用，勿拆成「先纠结同步 → 再行动」两轮。
4. **硬约束（违反即视为控制面违规）**：
   - 一旦调用 `todowrite`：`todos` **必须等于** `todo.todo_sync.items` 全量（长度与每个 `id` 一致；须含 `priority`，勿自行删减字段）。
   - **禁止**只写当前阶段、禁止省略 `id`/`priority`、禁止子集覆盖导致其它阶段从面板消失。
   - 任意时刻最多一个 `in_progress`。
5. 状态映射（若只有 `phases[].status`）：`done`→`completed`，`current`→`in_progress`，`pending`→`pending`。工作流 `passed` 后全部 `completed`。
6. **禁止**向用户粘贴或复述：`Workflow TODO`、`todo_md`、`.ascendc-pilot/todo.md`、`状态：running`、`当前阶段`、阶段 checklist、`下一步 Action`、`正在执行 …`。进度只出现在右侧 Todo 面板。

## Runtime loop (primary only)

1. 加载匹配的 workflow skill → `acp start`（**`uo-query` 禁止 start / `pilot_run`**：主控先对人说出可见路由，再自己 `acp uo-query --mode` 或原生 Task）。若返回 `needs_human_decision`：用 `question`/AskQuestion 可点选框 → `--decision continue|reinit` → 立刻 `todowrite`（全量）
2. 确定性段：`acp run-action auto` → **同一轮立刻 `todowrite`（merge=true，全量 `todo.todo_sync.items`）**；若返回 `ask_question` / `needs_human_decision` → **同一轮 AskQuestion**（选项原样使用 `ask_question.options`）
3. 交互边界：按 `recommended_next_action` / `interactive_steps` 执行 subagent 或 primary_interactive → `--finalize` → 再 `auto` 或 `acp next`；**禁止**从 `allowed_actions` 跳步
3a. **`uo-query` / `kb_lookup`（原生 Task 传话）**：子代理最终消息用完整自然语言作答（Cursor Explore：结论 + file:line + snippet），**不要把证据压进 yaml**。OpenCode Task 把全文交回主控；主控综合/对人转述以这篇原生返回为准。文末可选很短的 `kb-answer-v1` 状态头（status/adequacy/citations），只给 Runtime 收据。**不得 Write `answer.yaml` / scratch**。Host adapter 捕获 Task 全文后，Primary 优先无文件执行 `acp run-action kb_lookup --finalize`；仅当插件/环境未注入时才用 `--result-file` fallback。禁止 Primary 为 finalize 手写 scratch yaml。`answer.yaml` 仅由 Runtime 从这篇原生物化并注入 identity。缺 `uo/checks/integrity.yaml` 从来不是 kb_lookup 的修复目标；那是 uo-init verify 收据。**`host_step.tasks` ≥2 时切片 Task 不注入 return_value**；Primary 按各 Task 原生全文综合后再 finalize。
3b. **`uo-query` 硬约束**：禁止 `pilot_run` / `acp start uo-query`。若 `host_step.tasks` ≥2，同一轮原样并行派发每条 stub，全部返回后按各 Task 原生全文综合。短问/深问怎么拆只看 `skills/operator-analysis/capabilities/uo-query-router/METHOD.md`。子答 `UNKNOWN`/`PARTIAL` 不得抬成 high；禁止跨 architecture 证据闭合。未闭合再开一轮 Task，不要问「要不要继续」。
3c. Task 正文只用 prepare 返回的 `task_prompt_stub`；用户问题已由控制面注入 stub / `prompt.md` 的 `USER QUESTION` / `## User question`。Primary **禁止**在 stub 外另塞长篇分析目标。`host_step.tasks` ≥2 时同一轮并行派发每条 stub，全部返回后综合，禁止只转述某一个。
4. `advance` / `rework` / `complete` 后若阶段状态变了 → 再 `todowrite`；否则继续下一步
