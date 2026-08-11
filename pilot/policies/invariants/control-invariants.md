# Control invariants (model-facing, short)

1. Only run Actions returned by `acp next`; never advance Pilot state yourself.
2. Never declare workflow `done` / `passed`; only Pilot completion may finish.
3. Do not call domain CLIs directly; use `acp run-action`. Prefer `acp run-action auto` after start/finalize to drain consecutive deterministic Actions; it must stop before subagent or primary-interactive work.
4. Deterministic engine identities are internal ACP actors, never OpenCode Task agents. When auto stops at an interaction boundary, dispatch exactly the returned LLM actor / primary interaction.
5. Writes must stay inside Agent `write_scopes` ∩ Action lease ∩ workflow `write_roots`.
6. Primary never writes formal `uo/**` / `tg/**` IR products for a declared sub-actor.
7. Lease invariant: anything you may Write is also Readable.
8. Missing required params → AskQuestion immediately; do not repo-archaeology to guess.
9. Progress only via host Todo sync from `todo.todo_sync.items` — never paste status panels to the user.

Full detail: `pilot/policies/pilot-control/POLICY.md`.
