# Control invariants (model-facing, short)
#
# Host Session Driver (`pilot_run` + `dispatch-result`)
# owns transport **except `uo-query`**. Models only need these hard constraints:

1. Only run Actions / `host_step` returned by `pilot_run` / `dispatch-result`; never invent phases or declare `done` / `passed`.
2. Workflows: Host tool `pilot_run` only. If `pilot_run` is missing, tell the user to reinstall the plugin. **Never** `pilot_run` for `uo-query`. Query routing is `skills/operator-analysis/routing/uo-query.md`. Simple query: primary `pilot_cli` `uo-query`. Complex: parallel `Task(agent=uo-query)`, primary synthesizes. Never `--mode` in a Task stub. If a *Host-driver* `host_step.tasks` has ≥2 entries (e.g. CE review Spec∥Standards), launch **all** of them in the **same turn** (each prompt=`tasks[i].task_prompt_stub` verbatim), wait, then Primary synthesizes from each child's **native Task text**. For other workflows: when Driver returns `dispatch_subagent`, Task body is **exactly** `task_prompt_stub`. Primary never writes formal `uo/**` / `tg/**` IR. Never pass `force_new` unless the user explicitly asked to wipe/reinit. On start failure: retry without `force_new`; do not read Pilot source. Never `--help` to discover protocol. Diagnose with `pilot_cli` `status` / `inspect-failure` / `scan-architectures`.
3. Missing required params (`--project`, `--architecture`, resume decision) → AskQuestion immediately with **verbatim** options; do not guess architecture. Empty `project` uses the OpenCode host directory as the control plane (never `~/.cache/.../sessions/auto`). Operator root is the worktree pin after Workspace Manager acquires an allowlisted PR. Primary may bash `git`; do not rmtree another run's worktree lock. If the current user message already names a **unique legal** option (one on-disk `arch*`), use it and do not AskQuestion; echo the choice. If the user interrupts or replies in chat instead of clicking, the latest message wins: map it onto an existing option or supersede the pending confirmation (`interpret-user-turn`). Do not re-ask. Do not treat interrupt as wipe/reinit. Natural-language next step is the orchestration skill: do not phrase-route.
4. Writes stay inside Agent `write_scopes` ∩ Action lease ∩ workflow `write_roots`. Lease invariant: Write ⊆ Readable.
5. When `host_step.kind=done` for uo-init/update: 用 `pilot_cli` `uo-query --status-only` 看产物是否就绪；对照编排 skill 选择下一步。不要 Read quality.yaml。 For uo-query: 简单查询将 `pilot_cli` `uo-query` stdout 向用户陈述（禁止单独一轮只宣布路数）；复杂查询将子代 Task 返回向用户陈述后由 Primary 综合。MUST NOT Write `answer.yaml` (children). Do not paste Todo/stage panels or compress the child's answer into YAML. If any child is PARTIAL / 未闭合 / contradicts another / skipped CodeMap **and the gap is still on the graph**, Primary **must** launch another same-conversation round of Task(`agent=uo-query`) (FOCUS=the named gap) before closing — do not replace that round with a content-free confirmation. After children have conclusions but the remaining choice is which gap to explore, AskQuestion with labelled options and a recommended answer.
11. `uo-init`/`uo-update` 必须带 `--project` 与 `--architecture`；TG/CE/查询以已有 `.uo` 为准。无 `.uo` 时路径是确定的，AskQuestion（查询：`/uo-init` 或源码作答；TG/CE 先 `/uo-init`），禁止 Glob 找产物。

# Driver-owned (do not re-implement in prompts)
# - todowrite sync after auto (`todo.todo_sync`)
# - AskQuestion UI when Host exposes it (`host_owned_ask`)
# - live progress bar on `pilot_run` (OpenCode `ctx.metadata`); do not paste stage panels in chat
# - `host_step.done` / `complete`: archive run, release this family lock (slots/{family} or shared live_state); UO writers publish digest
# - Host injects ASCENDC_SESSION_ID + ASCENDC_WORKFLOW_ID on every harness spawn
# - Shared workflows never occupy product locks; different families run in parallel
# - return_value finalize (`dispatch-result` / ASCENDC_ACTION_RESULT)
# - subagent cwd / skill materialization / authorize identity tickets
# - uo-query is NOT driver-owned: 简单查询直接 `pilot_cli` `uo-query`（禁止单独一轮只宣布路数）/ 复杂查询同一轮 Task + Primary 综合

Full detail: `pilot/policies/pilot-control/POLICY.md` and `host-runtime-contract.md`.
