# Host runtime contract (model-facing)

`host_driver=False` means the Session Driver does **not** auto start/drain.
It does **not** mean the Action has no METHOD, Prompt, or session bundle.

## Transport

- Workflows: Host tool `pilot_run` only (live progress on the tool row). Natural language: 思考里按产物缺口选 slash（计划不是用例；词表写明的前置输入也是缺口）；对用户只陈述目标、现状与下一步，再 `todowrite` 后 `pilot_run(workflow=<current slash>)`. Only the 「获取 PR 代码」 todo uses `workflow=auto` (Engine clone). `auto` 回执已唯一确定 `(算子, architecture)` 时直接用于后续格。`host_step.done` returns to Primary; do not Host-`continue_goal` the next user workflow. Dual-axis review ACKs from native Task text. Explicit slash: `workflow=<existing id>`. Driver must not overwrite Primary Todos with engine `todo.todo_sync`. Do not use OpenCode native `skill` for Pilot orchestration. 非 primary 不得再派发 Task。`/ce-review` 双轴与复杂 `uo-query` 留在主线；意图只是一次审查或一次查询时不要再包 coordinator。派发前写清算子路径、architecture、有无测试脚本。occupancy 不冲突的步骤同一轮派发。不要把 `/uo-query` 卡片全文写入后续 `pilot_run` intent。
- If `pilot_run` is missing from the tool list: tell the user to fully quit OpenCode and reinstall the plugin.
- Exception: **never** `pilot_run` for `uo-query`.
- When Driver returns `dispatch_subagent`, Task body is **exactly** `task_prompt_stub`. If a Host-driver `host_step.tasks` ≥2 (review dual-axis, not uo-query keyword fanout), launch all in the same turn. Plugin ACKs each child's **native Task text** and returns `done` to Primary. Primary synthesizes the two Task bodies for the user as: 审查完成 / PR 做什么 / 改了哪些文件 / 问题 1… / 要测的变量. Do not emit `kb-answer-v1` as the review merge. Primary 勾 Todo 后再 `pilot_run` 下一格.
- Same-Action rework resumes the original Task session. Formal IR is Host **finalize** only.

## Shell / OpenCode

- Short CLI: plugin tool `pilot_cli`. Do not pipe through PowerShell `Select-Object -Last` / `Out-String` or bash `tail`.
- Do not call `--help` / `-h` / `help` to discover protocol. Diagnose with `pilot_cli` `status` / `inspect-failure` / `scan-architectures`. Workflows: `pilot_run`. Query: `pilot_cli` `uo-query --project <abs>`. Environment repair: `pilot_cli` `retry-after-environment-fix`.
- Do not write `.ascendc-pilot/**` via bash / `>` / `Set-Content` / `tee`.
- Children must not use OpenCode `skill` (read session `method.md`). Children must not spawn Task (authorize `TASK_NON_PRIMARY`). CodeMap lookup from a producer is `pilot_cli` `uo-query` only. Primary must not use OpenCode native `skill` to load Pilot orchestration. Domain methods come from session `method.md` / cognitive skills.
- Read / Glob / list of operator source is allow for Primary. Semantic lookup still uses `uo-query`. Grep of operator source remains denied for `uo-query` children when a CodeMap exists. Primary Write/edit is ask. Children: empty `write_scopes` → `edit`/`write` ask (lease still fences).
- Primary bash: readonly inspect + git auto-allow. Everything else (clone / `Remove-Item` / unknown commands) is OpenCode `ask`. Authorize 确认后放行。仍禁止写入或删除 `.ascendc-pilot`、领域 CLI、工作流 drain。隔离 PR 半成品由 Engine 自己清理。不要为理解语义通读全量 git diff。
- Containment (`human_required` / `blocked` / `failed`) applies only to the **current OpenCode session** bound live run. Leftover failed `auto` from another session, `no_active_workflow`, or a mismatched `session_id` is MODE_NORMAL. Pending AskQuestion: Primary may `Read` / `Glob` / `Grep`, `ls` / `dir` / `Get-ChildItem`, diagnostic python, and ask-gated bash. Still deny Write, engine scripts, and `pilot_run` **while the confirm UI is waiting**. `uo-query` Task is not denied by leftover containment. If the user interrupts and replies in chat, pending is superseded (`interpret-user-turn`); follow that message and do not re-ask. Interrupt is not wipe/reinit. Prefer `pilot_cli` `inspect-failure` / `status`. Children stay contained.

## uo-query lifecycle

- **简单查询**：主控直接调用 `pilot_cli` `uo-query`；stdout 即答案。禁止单独一轮只宣布路数。无 prepare / Task / finalize。
- **复杂查询**：主控按独立查询目标同一轮并行 `Task(agent=uo-query)`，主控综合。Task 正文的建议首次调用只能是四种参数形态之一，禁止 `--mode`。无 `kb_lookup` prepare / finalize。子代不得 Write `answer.yaml`，不得自己 finalize。
- **Delegated Task**（TG/CE）：Task 正文是 `task_prompt_stub`. Follow its `prompt` / `method` / `bundle` pointers; do not search additional session files.
