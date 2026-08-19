# Control invariants (model-facing, short)
#
# Host Session Driver (`pilot_run` + `dispatch-result`)
# owns transport **except `uo-query`**. Models only need these hard constraints:

1. Only run Actions / `host_step` returned by `pilot_run` / `dispatch-result`; never invent phases or declare `done` / `passed`.
2. Workflows: Host tool `pilot_run` only. If `pilot_run` is missing, tell the user to reinstall the plugin. **Never** `pilot_run` for `uo-query`. Query routing is `skills/operator-analysis/routing/uo-query.md`. Simple query: primary `pilot_cli` `uo-query`. Complex: parallel `Task(agent=uo-query)`, primary synthesizes. Never `--mode` in a Task stub. 非 primary 不得再派发 Task（`TASK_NON_PRIMARY`）。`/ce-review` 双轴与复杂 uo-query 必须留在主线；意图只是一次审查或一次查询时不要再包 coordinator。If a *Host-driver* `host_step.tasks` has ≥2 entries (e.g. CE review Spec∥Standards), launch **all** of them in the **same turn** (each prompt=`tasks[i].task_prompt_stub` verbatim). Plugin ACKs native Task text; Primary 勾 Todo 再 `pilot_run` 下一格. Primary merges the two Task bodies for the user (审查完成 / 做什么 / 改了什么 / 问题 / 要测变量), not `kb-answer-v1`. For other workflows: when Driver returns `dispatch_subagent`, Task body is **exactly** `task_prompt_stub`. Primary never writes formal `uo/**` / `tg/**` IR. Never pass `force_new` unless the user explicitly asked to wipe/reinit. On start failure: retry without `force_new`; do not read Pilot source. Never `--help` to discover protocol. Diagnose with `pilot_cli` `status` / `inspect-failure` / `scan-architectures`.
3. Missing `--architecture` → AskQuestion with **verbatim** on-disk `arch*` options; do not guess; never default arch35 without evidence. Engine clone 回执若已用 changed-files 路径令牌唯一确定 `(算子, architecture)`，将该对作为事实用于后续 `pilot_run`，不要再问架构。禁止把 changed-files 静默当成自动开 `/uo-init` 的输入。Empty `project` is the **clone anchor** only. Do not write `.ascendc-pilot` on an empty open-directory. Allowlisted PR URL → Engine clone into `<open-dir>/.ascendc-pr/...`; do not treat a local fork as the PR head. Primary **may** bash git. Isolation PR checkout 优先 Engine；`git clone` / `git worktree add` / 其它未 allow 的 bash 走 OpenCode `ask`。Unique legal `arch*` already named by the user or uniquely pinned by changed-files: use it, do not AskQuestion. 不要为理解语义通读全量 git diff（仅 name-only / `--stat`）。Chat interrupt supersedes pending (`interpret-user-turn`). 自由 NL：思考里按产物缺口选 slash（计划不是用例；派发前写清算子路径 / architecture / 有无测试脚本；occupancy 不冲突可并行），对用户只陈述目标、现状与下一步，再 Todo 按格 `pilot_run`；只有「获取 PR 代码」才 `auto`。Do not phrase-route.
4. Writes stay inside Agent `write_scopes` ∩ Action lease ∩ workflow `write_roots`. Lease invariant: Write ⊆ Readable.
5. When `host_step.kind=done` for uo-init/update: 用 `pilot_cli` `uo-query --status-only` 看产物是否就绪；勾掉 Todo，再 `pilot_run` 下一格。不要 Read quality.yaml。 For uo-query: 简单查询将 `pilot_cli` `uo-query` stdout 向用户陈述（禁止单独一轮只宣布路数）；复杂查询将子代 Task 返回向用户陈述后由 Primary 综合。综合后立即 `pilot_run` 下一格；禁止把卡片全文写入 `tg-init` / 其它 slash 的 intent。MUST NOT Write `answer.yaml` (children). Do not paste Todo/stage panels or compress the child's answer into YAML. If any child is PARTIAL / 未闭合 / contradicts another / skipped CodeMap **and the gap is still on the graph**, Primary **must** launch another same-conversation round of Task(`agent=uo-query`) (FOCUS=the named gap) before closing — do not replace that round with a content-free confirmation. After children have conclusions but the remaining choice is which gap to explore, AskQuestion with labelled options and a recommended answer.
11. `uo-init`/`uo-update` 必须带 `--project` 与 `--architecture`；TG/CE/查询以已有 `.uo` 为准。无 `.uo` 时路径是确定的，AskQuestion（查询：`/uo-init` 或源码作答；TG/CE 先 `/uo-init`），禁止 Glob 找产物。

# Driver-owned (do not re-implement in prompts)
# - AskQuestion UI when Host exposes it (`host_owned_ask`)
# - live progress bar on `pilot_run` (OpenCode `ctx.metadata`); do not paste stage panels in chat
# - `host_step.done` / `complete`: archive run, release this family lock
# - Host injects ASCENDC_SESSION_ID + ASCENDC_WORKFLOW_ID on every harness spawn
# - Shared workflows never occupy product locks
# - return_value finalize (`dispatch-result` / ASCENDC_ACTION_RESULT)
# - subagent cwd / skill materialization / authorize identity tickets
# - uo-query is NOT driver-owned
# - OpenCode 侧栏 Todo 由 Primary `todowrite`；Driver 不得用引擎 public_plan 覆盖

Full detail: `pilot/policies/pilot-control/POLICY.md` and `host-runtime-contract.md`.
