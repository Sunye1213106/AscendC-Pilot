# Host 运行时契约（人 / CI；不 compose 进模型）

工作流没有取消 slash。用户聊天仍是 `/uo-init`。`pilot_run(workflow=...)` 只写 id：`uo-init`。入口会把 `/uo-init` 剥成 `uo-init`，两边是同一条工作流。主控编排见 `pilot/policies/pilot-control/POLICY.md`。

`host_driver=False` 表示 Session Driver **不**自动 start/drain。这不等于该 Action 没有 METHOD、Prompt 或 session bundle。

## 传输

- 工作流只用 Host 工具 `pilot_run`。自然语言：思考里按产物缺口选**当前格 id**，对用户只说目标 / 现状 / 下一步，`todowrite` 后 `pilot_run(workflow=<id>)`。只有「获取 PR 代码」用 `workflow=auto`。`intent` 是本回合载荷：`auto` 含 PR URL；`bind_review` 后 `PASS` / `REWORK`；`tg-plan` ingest 为 YAML；其它格省略。`auto` 回执已唯一确定 `(算子, architecture)` 时直接用于后续格。
- `host_step.done` 回到 Primary。不要 Host-`continue_goal` 跨用户 slash。Driver 不得用引擎 `todo.todo_sync` 覆盖 Primary Todo。不要用 OpenCode 原生 `skill` 做 Pilot 编排。
- 需主控派 Task 的 workflow **串行**；同一格 `host_step.tasks` ≥2 由主控同一轮 fanout。不要把 `uo-query` 卡片全文写入后续 `pilot_run` intent。
- 工具列表里没有 `pilot_run`：请用户完全退出 OpenCode 并重装插件。
- **禁止**对 `uo-query` 调用 `pilot_run`。
- Driver 返回 `dispatch_subagent` 时，Task 正文必须是 `task_prompt_stub` 原文。`host_step.kind=primary_review` 时不要改口径、不开 question；下一发 intent 仅 `PASS` 或 `REWORK bind` / `REWORK harness,bind`。YAML 无法解析时主控可 Edit `bind_init/parts` 只修缩进，再用 `pilot_cli inspect yaml` 确认。REWORK 后现稿留在磁盘上，子代理按原因 patch。勾 Todo 后再 `pilot_run` 下一格。
- 同一 Action 返工恢复原 Task 会话。正式 IR 只由 Host **finalize** 写入。

## Shell / OpenCode

- 短 CLI：插件工具 `pilot_cli`。不要经 PowerShell `Select-Object -Last` / `Out-String` 或 bash `tail` 管道截断。不要用 `--help` 发现协议。诊断：`status` / `inspect-failure` / `scan-architectures`。查询：`uo-query --project <abs>`。跨格复用 clone 事实：`pin-facts --project <算子绝对路径>`。环境修复：`retry-after-environment-fix`。
- 不要用 bash / `>` / `Set-Content` / `tee` 写 `.ascendc-pilot/**`。
- 子代禁止用 OpenCode `skill`（读 session `method.md`）。producer 查图只用 `pilot_cli` `uo-query`。领域方法来自 session `method.md` / 认知 skill。
- 只读工具 authorize 不拦截。算子语义走 `code-access`。Primary 的 Write/edit 为 ask。子代 `write_scopes` 为空时 `edit`/`write` 为 ask。只读 inspect bash 与只读 git 允许。其它命令由 OpenCode `ask`。不要为理解语义通读全量 git diff。
- 围栏只作用于当前 OpenCode 会话绑定的活 run。确认框等待期间禁止 Write、引擎脚本、`pilot_run`。pending 不等于框已可见：规则与主控补 `question` 见 `pilot-control`。打断不是删除重开。诊断用 `pilot_cli` `inspect-failure` / `status`。

## uo-query 生命周期

- **简单查询**：主控直接 `pilot_cli` `uo-query`；stdout 即答案。无 prepare / Task / finalize。
- **复杂查询**：同一轮并行 `Task(agent=uo-query)`，主控综合。Task 正文禁止 `--mode`。子代不得 Write `answer.yaml`，不得自己 finalize。
- **Delegated Task**（TG/CE）：Task 正文是 `task_prompt_stub`。按其中 `prompt` / `method` / `bundle` 指针读文件。
