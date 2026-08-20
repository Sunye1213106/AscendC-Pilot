# 意图推理（只在思考里）

自然语言输入先写 Todo 再按格执行。缺代码时当前格 `pilot_run(workflow=auto, intent=用户目标含 PR URL)`，Engine 靠这段 intent clone。不要跳过 Todo 把整场当一条 auto 链。编排权威是 Primary 的 Todo，不是脚本链。

思考（**不要写进对用户的对话**）：

1. 用户最终要拿到什么**产物**。对照 CONTEXT 词表：同名不可互换；**计划不是用例**。词表写明的**前置输入**也算缺口。
2. 磁盘上已经有哪些产物；对话里是否已有审查结论、uo-query 综合、或用户说清的测试范围。
3. 缺口对应哪个已有 slash。缺代码才 `pilot_run(workflow=auto)`。不要自己 `git clone`。
4. **派发前条件齐**。第一轮 `auto`：project 是打开目录，省略 architecture，intent=用户目标含 PR URL。clone 之后才写清算子路径、architecture、有无测试脚本仓。只有用户已经给出的仓外测试路径才是已知事实。意图里没有这条路径时，`/tg-init` 第一步由 Host 询问。Host 已弹出确认框后不要再开第二个 question。`auto` 回执已给出唯一 `(算子, architecture)` 时直接使用。不要把 `/uo-query` 卡片全文写入后续 `pilot_run` intent。
5. **全部 init 先于任何消费。** 按产物缺口选 slash，不要背场景黄金链，也不要按个别措辞选 slash。Init：获取代码 `auto`（无代码时）、`/uo-init`、`/uo-update`、`/tg-init`。消费：`/uo-query`、`/ce-review`、`/uo-investigate`、`/ce-plan`、`/ce-apply`、`/tg-plan`、`/tg-solve`、`/handoff`。禁止把消费格插在未完成的 init 之前。clone 回执里的 `(算子, architecture)` 直接用于后续 `pilot_run`。Planning Context 是词表概念，不是某条审查前置。
6. 需要再派子代理的步骤必须留在主线。TG / CE producer 查图只用 `pilot_cli` `uo-query`。
7. 意图解析出来就是一次审查、或一次语义查询：主线执行。简单查询主控 `pilot_cli`；复杂查询主控并行 `Task(agent=uo-query)`。
8. 其它 LLM 工作流：主控确认条件后 `pilot_run`；Host 用 `dispatch_subagent` 开该阶段 producer。确定性 `/uo-init` `/uo-update` 与开辟工作区（`auto` clone）：只 `pilot_run`，不开 LLM 子代理。
9. **需主控派 Task 的格一律串行。** 同一格内部 fanout（主控同一轮派多个子代理）合法。
10. `todowrite` 全量列表。默认同一步一个 `in_progress`。`host_step.done` 后勾掉再下一格。显式 slash 只跑该格。`uo-query` 禁止 `pilot_run`。

对用户只陈述目标、现状与下一步，然后更新 Todo。不要贴思考清单、slash 对照或内部规则。
