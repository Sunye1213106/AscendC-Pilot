# Host runtime contract (model-facing)

`host_driver=False` means the Session Driver does **not** auto start/drain.
It does **not** mean the Action has no METHOD, Prompt, or session bundle.

## Transport

- Prefer Host tool `pilot_run` (live progress on the tool row) then `todowrite` from `todo.todo_sync.items` verbatim (full list, one `in_progress`). Skip only when items are unchanged. After `run-action auto`, sync immediately.
- Exception: **never** `pilot_run` / `acp start` for `uo-query`.
- When Driver returns `dispatch_subagent`, Task body is **exactly** `task_prompt_stub`. If a Host-driver `host_step.tasks` ≥2 (review dual-axis, not uo-query keyword fanout), launch all in the same turn, then Primary synthesizes each child's **native Task text**.
- Same-Action rework resumes the original Task session. Formal IR is Host **finalize** only.

## Shell / OpenCode

- Prefer `pilot_run` / plugin `acp` over bash. Do not pipe `acp` through PowerShell `Select-Object -Last` / `Out-String` or bash `tail`.
- Do not write `.ascendc-pilot/**` via bash / `>` / `Set-Content` / `tee`.
- Children must not use OpenCode `skill` (read session `method.md`). Primary skills come from installed `SKILL.md`, not process `rg`.
- Windows: plugin `acp` uses `spawnSync(acp.exe, shell:false)`. Session identity is the ticket (childSessionID↔actor↔action↔lease).
- Read of any directory is allow in AscendC-Pilot mode. Primary Write/edit is ask. Children: empty `write_scopes` → `edit`/`write` deny; otherwise ask (ACP lease still fences).

## uo-query lifecycle

- **简单查询**：主控直接调用 `acp uo-query`；stdout 即答案。无 prepare / Task / finalize。
- **复杂查询**：主控按独立查询目标同一轮并行 `Task(agent=uo-query)`，主控综合。Task 正文的建议首次调用只能是四种参数形态之一，禁止 `--mode`。无 `kb_lookup` prepare / finalize。子代不得 Write `answer.yaml`，不得自己 finalize。
- **Delegated Task**（TG/CE）：Task 正文是 `task_prompt_stub`。Follow its `prompt` / `method` / `bundle` pointers; do not search additional session files.
