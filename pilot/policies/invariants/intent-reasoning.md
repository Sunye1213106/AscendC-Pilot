# 意图推理（只在思考里）

自然语言输入先写 Todo 再按格执行。缺代码时当前格 `pilot_run(workflow=auto, intent=用户目标含 PR URL)`，Engine 靠这段 intent clone。不要跳过 Todo 把整场当一条 auto 链。编排权威是 Primary 的 Todo，不是脚本链。本步不读 Skill。

思考（**不要写进对用户的对话**）：

1. 用户最终要拿到什么**产物**。对照 CONTEXT 词表：同名不可互换；**计划不是用例**。词表写明的**前置输入**也算缺口。
2. 磁盘上已经有哪些产物；对话里是否已有审查结论、调查综合、或用户说清的测试范围。
3. 缺口对应哪个已有 slash。缺代码才 `pilot_run(workflow=auto)`。不要自己 `git clone`。
4. **派发前条件齐**。第一轮 `auto`：project 是打开目录，省略 architecture，intent=用户目标含 PR URL。clone 之后才写清算子路径、architecture、有无测试脚本仓。只有用户已经给出的仓外测试路径才是已知事实。意图里没有这条路径时，`/tg-init` 第一步由 Host 询问。Host 已弹出确认框后不要再开第二个 question。`auto` 回执已给出唯一 `(算子, architecture)` 时直接使用。
5. **init 先于调查与消费。** 缺什么先 `pilot_run` 补上，再调查，再消费。Init：获取代码 `auto`（无代码时）、`/uo-init`、`/uo-update`、`/tg-init`。消费：`/ce-review`、`/uo-investigate`、`/ce-plan`、`/ce-apply`、`/tg-plan`、`/tg-solve`、`/handoff`。`/uo-query` 是调查 Command，不是消费工作流，禁止 `pilot_run`。clone 回执里的 `(算子, architecture)` 直接用于后续 `pilot_run`。Planning Context 是调查综合（语义 + `tg/init.yaml`），不是必须先审查。
6. 需要再派子代理的步骤必须留在主线。TG / CE producer 查图只用 `pilot_cli` `uo-query`。
7. 意图只是一次审查：主线 `pilot_run /ce-review`。意图只是一次语义查询：先保证 `.uo`，再走下方调查拆路，不要进 `/tg-plan`。
8. 其它 LLM 工作流：主控确认条件后 `pilot_run`；Host 用 `dispatch_subagent` 开该阶段 producer。确定性 `/uo-init` `/uo-update` 与开辟工作区（`auto` clone）：只 `pilot_run`，不开 LLM 子代理。
9. **需主控派 Task 的格一律串行。** 同一格内部 fanout（主控同一轮派多个子代理）合法，用来隔离上下文。
10. `todowrite` 全量列表。默认同一步一个 `in_progress`。`host_step.done` 后勾掉再下一格。显式 slash 只跑该格。

## 调查拆路（隔离主控窗口）

目的是得到测试意图：把 PR/语义和已 init 的 `tg/init.yaml`（列、harness、精度/性能入口）合成全面、不冲突的意图，再交给 `/tg-plan`。已有可用测试意图则不要重复调查。

从原话抽出能作为**首次调用**的起始点。判定：这个起始点能否在不依赖另一路结论的情况下单独查完？能 → 单独一路。

**分别派：** 不同层的起始名（Host 函数、Kernel 宏、TilingKey 家族）；用户并列的多问。

**收成一路：** 同一家族别名、同一符号的多个子问。交叉综合、共享场景、相关业务 **不能** 用来减少路数。相关 ≠ 单域。

- 一路且短：主控直接 `pilot_cli` `uo-query`，根据 stdout 作答。不要单独一轮只宣布路数。
- 多路或会撑主控窗口：同一轮 `Task(agent=uo-query)`，上限 5，每路隔离。子代只回短结论 + 出处。综合只在主控。
- 不要把查询卡片全文写入后续 `pilot_run` intent。
- 子代之间、或语义与脚本列对不上：再派一路，FOCUS 只核对冲突点，直到不冲突。闭合不了就写缺口。
- 每轮最多 5 路。图上还能查的独立缺口自动开下一轮（路数=缺口数，≤5）。空 `task_result` 补一轮保留，不要当成图空。

对用户只陈述目标、现状与下一步，然后更新 Todo。不要贴思考清单、slash 对照或内部规则。
