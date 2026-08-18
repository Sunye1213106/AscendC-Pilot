# Host runtime contract (model-facing)

`host_driver=False` means the Session Driver does **not** auto start/drain.
It does **not** mean the Action has no METHOD, Prompt, or session bundle.

## Transport

- Workflows: Host tool `pilot_run` only (live progress on the tool row) then `todowrite` from `todo.todo_sync.items` verbatim (full list, one `in_progress`). Skip only when items are unchanged.
- If `pilot_run` is missing from the tool list: tell the user to fully quit OpenCode and reinstall the plugin. Never bash `acp start` / `acp run-action auto`. Never search for `acp.exe`.
- Exception: **never** `pilot_run` for `uo-query`.
- When Driver returns `dispatch_subagent`, Task body is **exactly** `task_prompt_stub`. If a Host-driver `host_step.tasks` ≥2 (review dual-axis, not uo-query keyword fanout), launch all in the same turn, then Primary synthesizes each child's **native Task text**.
- Same-Action rework resumes the original Task session. Formal IR is Host **finalize** only.

## Shell / OpenCode

- Short CLI: plugin tool `pilot_cli` (`command` without a leading `acp`). Do not pipe through PowerShell `Select-Object -Last` / `Out-String` or bash `tail`. Do not use a plugin tool named `acp` (OpenCode ACP protocol).
- Do not call `--help` / `-h` / `help` to discover protocol. Diagnose with `pilot_cli` `status` / `inspect-failure` / `scan-architectures`. Workflows: `pilot_run`. Query: `pilot_cli` `uo-query --project <abs>`.
- Do not write `.ascendc-pilot/**` via bash / `>` / `Set-Content` / `tee`.
- Children must not use OpenCode `skill` (read session `method.md`). Primary may use OpenCode native skills and Pilot workflow skills.
- Read of any directory is allow in AscendC-Pilot mode. Primary Write/edit is ask. Children: empty `write_scopes` → `edit`/`write` deny; otherwise ask (ACP lease still fences).
- Containment (`human_required` / `blocked` / `failed`) and pending AskQuestion: Primary may `Read` / `Glob` / `Grep`, `ls` / `dir` / `Get-ChildItem`, and diagnostic python (`check_cann.py` / `check_env.py` / `doctor` / `cann_extract.py --fixup`). Still deny Write, Task, engine scripts, and `acp start` / `run-action auto` **while the confirm UI is waiting**. If the user interrupts and replies in chat, pending is superseded (`interpret-user-turn`); follow that message and do not re-ask. Interrupt is not wipe/reinit. Prefer `pilot_cli` `inspect-failure` / `status`. Children stay contained.

## uo-query lifecycle

- **简单查询**：主控直接调用 `pilot_cli` `uo-query`；stdout 即答案。禁止单独一轮只宣布路数。无 prepare / Task / finalize。
- **复杂查询**：主控按独立查询目标同一轮并行 `Task(agent=uo-query)`，主控综合。Task 正文的建议首次调用只能是四种参数形态之一，禁止 `--mode`。无 `kb_lookup` prepare / finalize。子代不得 Write `answer.yaml`，不得自己 finalize。
- **Delegated Task**（TG/CE）：Task 正文是 `task_prompt_stub`. Follow its `prompt` / `method` / `bundle` pointers; do not search additional session files.
