# Human Review UX

Current `/uo-init` has **one required** human review gate:

| Gate | `--gate` | Purpose |
|---|---|---|
| Phase 0 Macro Scope | `macro_scope` | Approve frozen include/exclude scope before CBM indexing / Extract |

This gate is a **hard stop**. The orchestrator must present the scope proposal
and wait for an explicit user decision. Do not auto-`continue`.

Run decisions through:

```powershell
python -X utf8 "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate macro_scope --decision <continue|revise|stop|manual_supplement> [--notes "..."]
```

When the runtime has a question/AskQuestion UI, use it for this gate so the user
sees buttons. Present exactly these choices as buttons:

- `continue`
- `revise`
- `stop`
- `manual_supplement`

Only fall back to printing the CLI command when the button UI is unavailable.

Allowed `macro_scope` decisions:

1. `continue` — write `scope_review.yaml` + `scope_confirmed.yaml`, then index
2. `revise` — adjust scope and review again
3. `stop` — end `/uo-init`
4. `manual_supplement` — record notes; orchestrator must re-review before indexing

Retired gates (do **not** recreate): Phase1.5 boundary human review, Phase2/3
fact-review receipts, graph-review human menus.
