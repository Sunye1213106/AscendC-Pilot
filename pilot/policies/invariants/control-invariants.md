# Control invariants (model-facing, short)

1. Only run Actions returned by `acp next`; never advance Pilot state yourself.
2. Never declare workflow `done` / `passed`; only Pilot completion may finish.
3. Do not call domain CLIs directly; use `acp run-action`. Prefer `acp run-action auto` after start/finalize to drain consecutive deterministic Actions; it must stop before subagent or primary-interactive work. **`auto` 返回后必须立刻 `todowrite` 同步 `todo.todo_sync.items`（`force`/`after_auto`）**——auto 内部多步不会回到 Host，不能等下一轮再同步。
4. Deterministic engine identities are internal ACP actors, never OpenCode Task agents. When auto stops at an interaction boundary, dispatch exactly the returned LLM actor / primary interaction.
5. Writes must stay inside Agent `write_scopes` ∩ Action lease ∩ workflow `write_roots`.
6. Primary never writes formal `uo/**` / `tg/**` IR products for a declared sub-actor.
7. Lease invariant: anything you may Write is also Readable.
8. Missing required params → AskQuestion immediately; do not repo-archaeology to guess.
8a. `human_required` → AskQuestion immediately (`retry_after_environment_fix` / `inspect_failure` / `abort_run`); do not only narrate.
9. Progress only via host Todo sync from `todo.todo_sync.items` — never paste status panels to the user.
10. `acp` is installed on PATH by `install.ps1` / `install.sh`. Always invoke the bare command `acp …` — **never** an absolute `…\Scripts\acp.exe` path (OpenCode frontmatter only allows `acp *`). Never hunt for `acp.exe` inside the AscendC-Pilot repo. Probe once with `acp --help` (or `Get-Command acp`); if missing, tell the user to reinstall — do not Glob the Pilot tree.
11. `uo-init` / `tg-*` 启动必须同时有 `--project`（算子目录）与 `--architecture`（仓内 `arch*`）。缺一 → AskQuestion（arch 选项只来自扫描结果，禁止编造）；齐了 → `acp start … --project … --architecture …` 一次启动。所有后续 `acp *` 带同一 `--project`；`.ascendc-pilot/` 只允许在该算子目录下。
12. `clang_probe_unclean` / `CANN_ENV_NOT_READY` / 探针 `file not found`：先 `acp doctor`；再对照算子仓官方编译文件（`build.sh`、`**/CMakeLists.txt` 的 include）修正 Pilot `engines/understand-operator/spec/build_context.yaml`，清 probe 缓存后重试 prepare。细节见 `skills/operator-analysis/references/codemap-build-gotchas.md`。

Full detail: `pilot/policies/pilot-control/POLICY.md`.
