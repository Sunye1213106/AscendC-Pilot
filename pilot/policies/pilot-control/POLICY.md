# Policy: pilot-control

Pilot 独占状态、合法边、门禁与完成态。自然语言先规划再执行。传输由 Host 工具 `pilot_run` / `dispatch-result` 持有，不要自己发明协议。对人怎么说见 `human-voice`。

工作流没有取消 slash。用户聊天仍是 `/uo-init`。`pilot_run(workflow=uo-init)` 只写 id。入口会剥掉 `/`，两边是同一条工作流。本阶段不读 Skill。先写完整 Todo，再逐项处理。不要把整场任务丢给一条 `auto` 链。`intent` 是本回合载荷，不是读懂用户句子：`auto` 含 PR URL；`bind_review` 后 `PASS` / `REWORK bind`；`tg-plan` ingest 为 YAML。其它格省略。

## 合法边

1. 只能执行 `pilot_run` / `dispatch-result` 返回的 Action。`pilot_cli next` 是诊断只读，不推进工作流。
2. Skill、Prompt、Agent、Capability、Action Method **不得**推进工作流状态。
3. 终态只认 Host `complete`；禁止自行宣布 `done` / `passed`。
4. Gate fail ≠ 立即 `blocked`；保持 phase，进入 `rework_required` / `human_required`。`rework_required` 由 Host `pilot_run` 重试失败 Action，禁止 bash / `pilot_cli` `run-action`。进入 `human_required` 后必须弹出可点选框。`host_owned_ask` / pending / `ask_human` JSON **不等于**确认框已弹出。`ask_ui_shown=false` 或屏幕上没有可点选框时：用户已经给过仓外路径或 git URL 就用该值 answer；否则立刻用 `question` 并原样传递 `ask_question.options`。禁止用文字告诉用户「框应该已经弹出」。屏幕上已有可点选框时，不要再开同一个 `question`。用户打断确认框并在对话里另作回复时，取消该 pending（`interpret-user-turn`），不要重问上一题。
5. 禁止直调领域 CLI；须经 `pilot_run` / `pilot_cli`。正式产物须 Pilot 签发收据。
6. 禁止跳步：必须执行 `recommended_next_action`。OpenCode 上确定性段由 Host `pilot_run` 驱动。`host_step.tasks`≥2 时主控同一条回复里并行原生 Task 子代理；禁止 `session.create` 开新对话；禁止等一个完成再派下一个。`task_prompt_stub` 原样，不要改写。
7. Lease：Action `allowed_write_paths` **必须**可读。写入落在 `write_scopes` ∩ lease ∩ `write_roots`。
8. **`uo-query` 不是 Host Session Driver 工作流**：禁止 `pilot_run workflow=uo-query`。简单查询主控直接调用 `pilot_cli` `uo-query`（stdout）；复杂查询同一轮分别派 Task，主控综合。禁止 Write `answer.yaml`。
9. `uo-init` / `uo-update` 必须同时有 `--project` 与 `--architecture`。禁止静默默认 architecture，禁止在仓库根目录搜索以猜测 arch。
10. 产物根 = `--project` 算子目录。`.ascendc-pilot/` 只建在算子包下。
11. 查询/TG/CE 无 `.uo` 时路径是确定的；AskQuestion（查询：先 `uo-init` 或源码作答；TG/CE 先 `uo-init`），禁止 Glob 找产物。过期图走 `uo-update`。
12. User Goal（全量 case）走 `control/user_goal.yaml` + `pilot_run` 的 `--intent`；不是查询路由启发式。
13. `complete` 必须释放本产物族锁；（UO 写工作流）发布 digest。不同族并行。

## 判断当前状态

执行前确认：用户最终要什么；磁盘上已有什么产物；对话里已有什么结论；下一步还缺什么。

术语以 `CONTEXT` 为准。计划 ≠ 测试用例。`CONTEXT` 要求的输入不存在 = 真缺口。已有可用且一致的结论就复用。

## 获取代码

缺代码：`pilot_run(workflow=auto, intent=<用户目标 + PR URL>)`。首次 `auto`：`project` 用当前打开目录，省略 `architecture`，`intent` 保留用户目标和 PR URL。由 `auto` 拉代码，不要自行 `git clone`。clone 完成前不猜算子路径、architecture 或测试仓；完成后以回执为准。回执唯一确定 `(operator, architecture)` 时后续直接复用。

仓外测试路径或 git URL 用户已给出时，写入 `pilot_run(test_script_root=…)`，Host 不要再问三项。未提供时由 `tg-init` 的 Host 询问。

看 PR 页面用 `webfetch`。

## 执行顺序

**init 先于调查与消费。** 缺什么先补上。用户已明确选择 `tg-solve` 或 `tg-plan` 后，TaskPlan Engine 做确定性依赖闭包（补 `tg-init`、缺的 `tg-plan`、以及按缺口二选一的 `uo-init` 或 `uo-update`）。这不是猜用户意图，不要因此加入 `ce-review`。其余交付仍按产物缺口选当前格，不要背固定黄金链。

CodeMap（按缺口二选一，不要当固定串）：

* 无 `.uo`：`uo-init`。`auto` 拉到的是 PR 新代码，建库就是对新代码建库。
* 已有 `.uo` 且过期：`uo-update`。过期指 `pilot_cli status` 或 `uo-query --status-only` 显示 stale，或 `ce-apply` 刚改过源码。
* 刚完成 `uo-init`，或 `.uo` 与当前源码一致：不要再跑 `uo-update`。
* 禁止把 `uo-update` 紧挨着排在刚完成的 `uo-init` 后面。
* 不要为理解 PR diff 去跑 `uo-update`。

clone 成功后候选事实只在算子 `.ascendc-pilot/control/clone_receipt.yaml`。后续 workflow 还要用这次改动时，引擎从 clone_receipt promote 成 `change_contract.yaml`（`plan_precheck` 自动 pin；诊断仍可用 `pilot_cli pin-facts --project <算子绝对路径>`）。`tg-plan` 只读这份 pin。禁止 `git diff HEAD` 当 PR 信号。禁止手改 clone_receipt 的 SHA。禁止手传 `--changed-files` 或空默认写盘。已有 PR clone_receipt 时禁止 `kind=implementation_coverage` / `enumerate: legal_keys`。PR 源且没有 clone_receipt → `plan_precheck` FAIL `PLAN_PR_CHANGE_REQUIRED`。base 与 head 相同或两 SHA 对不出 hunk → 问人一次（重新 clone 或中止），不要 git 考古循环。`user_goal.kind` 是交付物标签，不是 `pr_regression`；PR 针对性看 `source.kind=pull_request`。

需要测试契约时再 `tg-init`。

消费工作流（有对应产物才跑）：`ce-review`、`uo-investigate`、`ce-plan`、`ce-apply`（完成后若还要查图或生成测试，先 `uo-update`）、`tg-plan`、`tg-solve`、`handoff`。

查询用 `pilot_cli uo-query`。`auto` 返回的 `(operator, architecture)` 用于后续 `pilot_run`；`status` / `uo-query --status-only` 也必须带算子路径。

`Planning Context` 就是 `tg-plan` 的 Coverage IR。不要求先 Code Review，也不要求 Host 在 init 与 plan 之间自己跑一遍 `uo-query`。

## 按用户目标

用户只要求 Code Review：只跑 `ce-review`。

用户只要生成用例、未要求完整审查：不要默认加入 `ce-review`。Engine 会把 `tg-solve` 闭包成 `uo-*` → `tg-init` → `tg-plan` → `tg-solve`；`plan_precheck` 后回到 Primary，按改动摘要一路 Owner 或最多 5 路 fragment，不要在中间再派自由查询，不要通读 packet。

用户只要求语义查询：先保证 `.uo`（无图 `uo-init`，过期 `uo-update`），再 `pilot_cli uo-query`，不进入 `tg-plan`。

其它 LLM producer：Primary 检查前置 → `pilot_run` → Host 按需要 `dispatch_subagent`。编排留在 Primary。TG / CE producer 查图只用 `pilot_cli uo-query`。

`auto`、`uo-init`、`uo-update` 是确定性步骤，只跑 `pilot_run`，不额外开 LLM 子代理。用户显式调用某个 workflow 时，只执行该步。

## Todo 与并行

`todowrite` 保存完整任务列表。默认同时只有一个 `in_progress`。`host_step.done` 后先完成当前项。不同格之间默认串行。同一格 `host_step.tasks`≥2 必须同一条回复里并行原生 Task（切片 FOCUS 隔离，共享父对话），禁止逐个补派，禁止开新对话。

## 语义调查

调查只取下一步真正需要的事实。`tg-init` 完成后直接 `tg-plan`。`plan_precheck` 写出改动包后 host_step 回到 Primary，不要在 init 与 plan 之间再派自由 `uo-query`。bind 列由引擎按每路 ≤20 切开；主控同一条回复里并行原生 Task 拉起 1 路 harness + N 路 bind，不要改路数，不要开新对话。

从用户原话提取可查询的起始点。两个问题能各自独立查完就分开。Host 函数、Kernel 宏、TilingKey 家族通常分开。同一符号的多个子问或家族别名可以合并。不要仅因为同一业务就合并。相关 ≠ 单域。是否分开只看查询之间有没有信息依赖。

一路且短：Primary 直接 `pilot_cli uo-query`。不要单独一轮只宣布路数。多路或会撑窗口：同一轮最多 5 路分别派 `Task(agent=uo-query)`，每路一个明确目标，只返回短结论 + 出处。综合只在主控。不要把卡片全文复制进后续 `pilot_run` intent。

`ce-apply` 只改码（或改测试脚本缺口），不查图、不审 diff。

结论冲突时不凭直觉选一个。UO 语义与测试脚本列不一致也是冲突。新开一路只核对冲突点，`FOCUS` 只描述该矛盾。证据不足就记录缺口，不猜测。每轮最多 5 路；仍有独立缺口再开下一轮。`task_result` 为空时用同一问题补查一次；一次空结果不能证明图上没有。

## tg-plan 路由

`plan_precheck` 之后 Host **回到 Primary**，不发 `dispatch_subagent` / `task_prompt_stub`。禁止单独 `plan_route` action，也不用文件数/LOC 脚本分类。拆路只看 `plan_precheck` 回执里的改动摘要（文件簇 / 删除符号 / 写入点），像 `uo-query` 一样：一路且短直接派，多簇同一轮最多 5 路。禁止 Read `plan_scope_packet.yaml`。不要按测试列能不能构造来拆路。

* 一个簇：立刻原生 `Task(agent=tg-analyst)` 当 Plan Owner。Task 正文即全部（packet 路径 + FOCUS + 只交 `tg-plan/v3` YAML），不要让子代去找 session `prompt.md`。
* 多个簇：同一轮最多 5 路 FOCUS fragment（`coverage-fragment/v1`），再一个 Owner 汇总。fragment 必须 `pilot_run` ingest 落盘；空 fragment → `PLAN_FRAGMENT_REQUIRED`。
* Owner / fragment **禁止再派 Task**。Primary **禁止 Write `tg/plan.md`**。下一发 `pilot_run(workflow=tg-plan)` intent=YAML。

向用户说明将派 1 个 Owner 还是 N 路 FOCUS 后立刻派。
