# 意图推理与工作流编排

自然语言请求先由 Primary 规划，再执行。先写完整 Todo，再逐项处理。Todo 是编排依据，不要把整场任务直接交给一条 `auto` 链。本阶段不读取 Skill。

## 判断当前状态

执行前确认：

* 用户最终要拿到什么；
* 磁盘上已有什么产物；
* 对话中已有什么结论或测试范围；
* 下一步还缺什么。

术语和前置输入以 `CONTEXT` 为准。名称相近的概念不要互换，例如计划不等于测试用例。`CONTEXT` 要求的输入不存在时，视为真实缺口。

已有可用且一致的结论时直接复用，不重复调查。

## 获取代码

缺代码时执行：

`pilot_run(workflow=auto, intent=<用户目标 + PR URL>)`

首次 `auto`：

* `project` 使用当前打开目录；
* 省略 `architecture`；
* `intent` 保留用户目标和 PR URL。

由 `auto` 获取代码，不要自行 `git clone`。clone 完成前，不猜算子路径、`architecture` 或测试仓；完成后以回执为准。

若回执唯一确定 `(operator, architecture)`，后续直接复用，不再确认。

仓外测试路径或 git URL 用户已给出时，写入 `pilot_run(test_script_root=…)`；Host 不得再问三项。未提供时，由 `tg-init` 的 Host 询问，不自行推断。

`host_owned_ask` / pending / `ask_human` JSON **不等于**确认框已弹出。`ask_ui_shown=false` 或屏幕上没有可点选框时：用户已经给过仓外路径或 git URL 时用该值 answer，不要再问用户；否则立刻用 `question` 并原样传递 `ask_question.options`。这是用户能看见的第一问。禁止用文字告诉用户「框应该已经弹出」，禁止让用户去点看不见的框。

仅当用户屏幕上已经出现可点选框时，不要再开同一个 `question`。

需要查看 PR 页面时使用 `webfetch`。

## 执行顺序

**init 先于调查与消费。** 缺什么先补上，再调查，再消费。不要先跑后续流程再回头补初始化。用户已明确选择 `/tg-solve` 或 `/tg-plan` 后，TaskPlan Engine 做确定性依赖闭包（补 `/tg-init`、缺的 `/tg-plan`、以及按缺口二选一的 `/uo-init` 或 `/uo-update`）。这不是猜用户意图，不要因此加入 `/ce-review`。其余交付工作流仍按产物缺口选 slash，不要背固定黄金链。

CodeMap 准备（按缺口二选一，不要当固定串）：

* 无 `.uo`：`/uo-init`。`auto` 拉到的是 PR 新代码，建库就是对新代码建库。
* 已有 `.uo` 且过期：`/uo-update`。过期指 `pilot_cli status` 或 `uo-query --status-only` 显示 stale，或 `/ce-apply` 刚改过源码。
* 刚完成 `/uo-init`，或 `.uo` 与当前源码一致：不要再跑 `/uo-update`。
* 禁止把 `/uo-update` 紧挨着排在刚完成的 `/uo-init` 后面。

不要为理解 PR diff 去跑 `/uo-update`。clone 成功后候选事实只在算子 `.ascendc-pilot/control/clone_receipt.yaml`。后续 workflow 还要用这次改动时，Primary 显式 `pilot_cli pin-facts --project <算子绝对路径>`，从 clone_receipt **promote** 成 `change_contract.yaml`。`/tg-plan` 只读这份 pin。禁止 `git diff HEAD` 当 PR 信号。禁止手传 `--changed-files` 或空默认写盘。

```text
pin-facts --project <算子> = 读 clone_receipt → 写 change_contract（kind=pr_regression，files/sha 原样 promote）
无 clone_receipt → ok=false，不写盘
已有 PR clone_receipt 时禁止 kind=implementation_coverage / enumerate=legal_keys
IF clone_receipt/user_goal 表明 PR 源 AND（change_contract 非法或 changed_files 为空）
THEN plan_precheck FAIL PLAN_PR_CHANGE_REQUIRED（可重试，回 Primary pin；不进入 plan_ingest）
generic TilingKey fallback 仅无 PR 候选且 change_contract.kind == implementation_coverage
enumerate: legal_keys 仅上述本地覆盖 pin
```

`user_goal.kind` 是交付物标签（`generate_change_tests`），不是 `pr_regression`。PR 针对性看 `source.kind=pull_request`。不要用 pin 去改写 `user_goal.kind`。

需要测试契约时再 `/tg-init`。

消费工作流（有对应产物才跑）：

* `/ce-review`
* `/uo-investigate`
* `/ce-plan`
* `/ce-apply`（完成后若还要查图或生成测试，先 `/uo-update`）
* `/tg-plan`
* `/tg-solve`
* `/handoff`

`uo-query` 是调查 Command，不是消费工作流，禁止 `pilot_run`；查询 UO 使用 `pilot_cli uo-query`。

`auto` 返回的 `(operator, architecture)` 直接用于后续 `pilot_run`。`status` / `uo-query --status-only` 也必须带上该算子路径，不要对着打开目录根判断 `.uo`。

`Planning Context` 就是 `/tg-plan` 的 Coverage IR（Plan Owner YAML）。不要求先执行 Code Review，也不要求 Host 在 init 与 plan 之间自己跑一遍 `uo-query`。

## 按用户目标选择流程

用户只要求 Code Review 时，只执行 `/ce-review`。

用户只要生成用例、未要求完整审查时，不要默认加入 `/ce-review`。Engine 会把 `/tg-solve` 闭包成 `/uo-*` → `/tg-init` → `/tg-plan` → `/tg-solve`；`plan_precheck` 后回到 Primary，原生 Task 派 Plan Owner，不要在中间再派自由查询。

用户只要求语义查询时：

* 先保证 `.uo` 已存在（无图 `/uo-init`，图过期 `/uo-update`）；
* 使用 `pilot_cli uo-query`；
* 根据结果回答；
* 不进入 `/tg-plan`。

其它需要 LLM producer 的工作流：

1. Primary 检查前置条件；
2. Primary 调用 `pilot_run`；
3. Host 按需要用 `dispatch_subagent` 启动该阶段 producer。

编排始终留在 Primary。子代理只完成分配给它的任务，不接管后续流程。

TG 和 CE producer 查询 UO 只使用 `pilot_cli uo-query`。

`auto`、`uo-init`、`uo-update` 是确定性步骤，只运行 `pilot_run`，不额外启动 LLM 子代理。

## Todo 与并行

使用 `todowrite` 保存完整任务列表。默认同时只有一个 Todo 为 `in_progress`。

收到 `host_step.done` 后，先完成当前项，再开始下一项。

需要 Primary 分别派 Task 的不同步骤默认串行。

同一步中的独立任务可以并行，以隔离上下文；存在依赖的任务保持串行，不猜测尚未产生的输入。

用户显式调用某个 workflow 时，只执行该步骤，不自动继续后续 workflow。

## 语义调查

调查只获取下一步真正需要的事实。

`/tg-init` 完成后直接 `/tg-plan`。`plan_precheck` 写出改动包后 host_step 回到 Primary，不要在 init 与 plan 之间再派自由 `uo-query` 调查 slash。bind 列由引擎按每路 ≤20 切开；Primary 原样派 Host 给出的 1 路 harness + N 路 bind，不要自己再拆或加路。

用户只要求语义查询、不要生成用例时，仍用 `pilot_cli uo-query`，不进入 `/tg-plan`。

从用户原话中提取可以直接查询的起始点。两个问题若能各自独立查完，就分开查询。

不同层级的起始对象通常分开，例如 Host 函数、Kernel 宏、TilingKey 家族。

用户并列提出的独立问题也分别查询。

同一符号的多个子问，或同一家族别名，可以合并。

不要仅因为属于同一业务、同一场景或最终要一起综合就合并查询。相关 ≠ 单域。

是否分开只看查询之间是否存在信息依赖。

## 调查执行

只有一个简单问题时，Primary 直接运行 `pilot_cli uo-query`，根据 stdout 继续处理。

不要单独增加一轮只用于说明查询路数。

有多个独立问题，或结果可能明显占用 Primary 上下文时，使用 `Task(agent=uo-query)`。

每轮最多 5 路独立查询。

每个子代理只处理一个明确目标，并保持上下文隔离，只返回：

* 简短结论；
* 对应出处。

综合只在主控。

不要把完整查询卡片或大段 UO 输出复制进后续 `pilot_run intent`，只传该工作流真正需要的结论。

`/ce-apply` 只改码（或改测试脚本缺口），不查图、不审 diff。需要语义时先走查询。

## 处理冲突和缺口

不同查询结论冲突时，不凭直觉选一个。UO 语义与测试脚本列不一致时，也视为需要核实的冲突。

新增一个查询，只检查冲突点。`FOCUS` 只描述该矛盾，不重新调查整个问题。

根据新证据继续判断，直到得到一致结论，或现有证据不足以继续判断。

证据不足时明确记录缺少什么，不猜测。

每轮最多 5 个独立查询。若仍有可从图中继续确认的独立缺口，再开下一轮。

下一轮只处理剩余独立缺口，最多 5 路。

`task_result` 为空时，用同一问题补查一次。

一次空结果不能证明 UO 中没有相关信息；补查后仍不足，再记录为缺口。

## `/tg-plan` 路由（对齐 uo-query）

`plan_precheck` 之后 Host **回到 Primary**，不发 `dispatch_subagent` / `task_prompt_stub`。禁止单独 `plan_route` action，也不用文件数/LOC 脚本分类。

拆路只看**独立测试因果链**（不是文件层、不是 Host/Kernel/Tiling 目录）。相关 ≠ 单域。每轮最多 5 路。

* 一条主行为：立刻原生一个 `Task(agent=tg-analyst)` 当 Plan Owner。Task 正文即全部（packet 路径 + FOCUS + 只交 `tg-plan/v3` YAML），不要让子代去找 session `prompt.md`。本 FAG 类 PR（一个 `deterBandScheduleMode` 行为）走这条。
* 多条独立行为：同一轮最多 5 路 FOCUS fragment Task（`coverage-fragment/v1`），再一个 Owner Task 汇总。fragment 必须 `pilot_run` ingest 落盘；空 fragment → `PLAN_FRAGMENT_REQUIRED`，禁止 Owner 再扫一遍 PR。
* Owner / fragment **禁止再派 Task**。
* Primary **禁止 Write `tg/plan.md`**。下一发 `pilot_run(tg-plan)` intent=YAML，Engine merge / validate / 确定性 narrate。

向用户说明将派 1 个 Owner 还是 N 路 FOCUS 后立刻派，不要空转一轮只宣布路数。

## 对用户输出

执行过程中只告诉用户：

* 当前目标；
* 已确认的事实；
* 下一步动作。

随后更新 Todo。

不要向用户展示内部思考清单、workflow 路由表、查询拆分依据、编排规则，或不影响用户决策的控制细节。

这些规则只用于内部执行。
