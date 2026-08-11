# Control invariants (model-facing, short)

1. Only run Actions returned by `acp next`; never advance Pilot state yourself.
2. Never declare workflow `done` / `passed`; only `acp complete` may finish.
3. Do not call domain CLIs directly; use `acp run-action`.
4. Writes must stay inside Agent `write_scopes` ∩ Action lease ∩ workflow `write_roots`.
5. Primary never writes formal `uo/**` / `tg/**` IR products for a declared sub-actor.
6. Lease invariant: anything you may Write is also Readable.
7. Missing required params → AskQuestion immediately; do not repo-archaeology to guess.
8. Progress only via host Todo sync from `todo.todo_sync.items` — never paste status panels to the user.

Full detail: `pilot/policies/pilot-control/POLICY.md`.
