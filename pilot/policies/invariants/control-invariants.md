# Control invariants (model-facing, short)
#
# Host Session Driver (`pilot_run` / `acp run-action auto` + `dispatch-result`)
# owns transport **except uo-query**. Models only need these hard constraints:

1. Only run Actions / `host_step` returned by ACP (`next` / `auto` / `dispatch-result`); never invent phases or declare `done` / `passed`.
2. Prefer Host tool `pilot_run` (or `acp start` → `acp run-action auto`) over hand-chaining ACP **except `uo-query`**. Query is a visible Primary LLM router: speak 路由（自查 / N 个 Task）in the user-visible message, then `acp uo-query` or native Task(`agent=uo-query`). **Never** `pilot_run` / `acp start` for `uo-query`. For other workflows: when Driver returns `dispatch_subagent`, Task body is **exactly** `task_prompt_stub` (OpenCode Task card is the jump into child thinking). If `host_step.tasks` has ≥2 entries, launch **all** of them in the **same turn** (each prompt=`tasks[i].task_prompt_stub` verbatim), wait, then Primary synthesizes from each child's **native Task text**; do not invent facts children did not cite. Primary never writes formal `uo/**` / `tg/**` IR. Never pass `force_new` unless the user explicitly asked to wipe/reinit. On start failure: retry without `force_new`; do not read Pilot source or chain bash onto `acp`.
3. Missing required params (`--project`, `--architecture`, resume decision) → AskQuestion immediately; do not repo-archaeology. If `pilot_run` returns `host_owned_ask` / `ask_question`, options must be used **verbatim**.
4. Writes stay inside Agent `write_scopes` ∩ Action lease ∩ workflow `write_roots`. Lease invariant: Write ⊆ Readable.
5. When `host_step.kind=done` for uo-init/update: Read `host_step.quality_path` (`.ascendc-pilot/<arch>/uo/checks/quality.yaml`; never the unscoped `.ascendc-pilot/uo/` tree) and tell the user node/relation counts plus unclosed buckets and why. For uo-query: speak `acp uo-query` stdout or the native Task return; do not Glob/Read `answer.yaml`. MUST NOT Write `answer.yaml`. Do not paste Todo/stage panels or compress the child's answer into YAML.
11. `uo-init`/`uo-update` 必须带 `--project` 与 `--architecture`；TG/CE/查询以已有 `.uo` 为准。无 `.uo` 时路径是确定的，AskQuestion（查询：`/uo-init` 或源码作答；TG/CE 先 `/uo-init`），禁止 Glob 找产物。

# Driver-owned (do not re-implement in prompts)
# - todowrite sync after auto (`todo.todo_sync`)
# - AskQuestion UI when Host exposes it (`host_owned_ask`)
# - live progress bar on `pilot_run` (OpenCode `ctx.metadata`); do not paste stage panels in chat
# - `host_step.done` / `complete`: archive run, release this family lock (slots/{family} or shared live_state); UO writers publish digest
# - Host injects ASCENDC_SESSION_ID + ASCENDC_WORKFLOW_ID on every acp spawn
# - Shared workflows never occupy product locks; different families run in parallel
# - return_value finalize (`dispatch-result` / ASCENDC_ACTION_RESULT)
# - subagent cwd / skill materialization / authorize identity tickets
# - uo-query is NOT driver-owned: Primary visible classify → DIY or Task

Full detail: `pilot/policies/pilot-control/POLICY.md`.
