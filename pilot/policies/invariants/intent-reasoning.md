# Intent reasoning（只在思考里）

自由 NL 禁止第一轮把用户原文塞进 `pilot_run(workflow=auto)`。编排权威是 Primary 的 Todo，不是脚本链。

思考（**不要写进对用户的对话**）：

1. 用户最终要拿到什么**产物**（可执行用例、审查结论、改好的代码…）。对照 CONTEXT 词表：同名不可互换；**计划不是用例**。词表写明的**前置输入**也算缺口，不要只按最终文件名选 slash。
2. 磁盘上已经有哪些产物；对话里是否已有审查结论、uo-query 综合、或用户说清的测试范围。
3. 缺口对应哪个用户 slash（看 workflow 目录与 CONTEXT，不要背任何场景黄金链）。缺代码才 `pilot_run(workflow=auto)`（Engine clone）。不要自己 `git clone` 建 PR 仓。
4. **派发前条件齐**。每一步 prompt / `pilot_run` 写明：算子绝对路径、architecture、本步已知事实（有无测试脚本仓及路径）。不确定的先 AskQuestion，不要让子代理猜。缺测试脚本等条件时回到主控处理，不要把半截任务派出去。`auto` 回执已给出唯一 `(算子, architecture)` 时直接使用，不要再问架构，不要为理解语义通读全量 git diff（仅在需要标题时用 name-only / `--stat`）。不要把 `/uo-query` 卡片全文写入后续 `pilot_run` intent。
5. **测试范围来自尚未理解的改动**、且用户未选定完整审查或只要生成测试用例 → AskQuestion。完整审查：主线 `/ce-review`（双轴由主控派 Task）后再 `/tg-plan`。只要用例：主线 `/uo-query` 落根语义，用用户已给范围作 Planning Context，不假装做过审查。这不是「PR 必须先审查」的黄金链。
6. **嵌套 Task 不支持。** authorize `TASK_NON_PRIMARY`：只有主控能 `Task`。需要自己再派子代理的步骤必须留在主线：`/ce-review` 双轴、复杂 `/uo-query` 多路。禁止把整个 `/ce-review` 或 `/uo-query` 再包一层 coordinator。TG / CE producer 查图只用 `pilot_cli` `uo-query`，禁止再 `Task(agent=uo-query)`。
7. **单一 workflow 不包 coordinator。** 意图解析出来就是一次审查、或一次语义查询：主线执行。简单查询主控 `pilot_cli`；复杂查询主控并行 `Task(agent=uo-query)`；审查主控 `pilot_run` 后按 `host_step.tasks` 同一轮两个 `ce-reviewer`。
8. 其它 LLM 工作流：主控确认条件后 `pilot_run`；Host 用 `dispatch_subagent` 开该阶段 producer，隔离领域上下文，避免主控过长、结论交叉污染。确定性 `/uo-init` `/uo-update` 与开辟工作区（`auto` clone）：只 `pilot_run`，不开 LLM 子代理。
9. **occupancy 不冲突的同一轮派发**：`/uo-query`（shared、非 Host drain）可与 `/tg-init` 并行；`/ce-review`（shared）与 `/tg-init`（tg 锁）可并行。抢同一锁（`uo` / `tg` / `ce-plan` / `ce-apply`）必须串行。Host 一次只收一个 `pilot_run` 时，先起一侧，另一格 `pending`。
10. `todowrite` 全量列表。默认同一步一个 `in_progress`；真正并行的步可多个 `in_progress`。当前格 `pilot_run` 或 `uo-query` 的 CLI/Task。`host_step.done` 后勾掉再下一格。显式 slash 只跑该格。`uo-query` 禁止 `pilot_run`。

对用户只陈述目标、现状与下一步，然后更新 Todo。不要贴思考清单、slash 对照或内部规则。
