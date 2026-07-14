# Human Review UX

Current `/uo-init` has one required human review gate:

| Gate | `--gate` | Purpose |
|---|---|---|
| Phase 0 Macro Scope | `macro_scope` | Approve frozen include/exclude scope before Phase 1 |

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

1. `continue`
2. `revise`
3. `stop`
4. `manual_supplement`

There is no Phase 3.5 dispatch gate in the active workflow. Kernel slice
planning, slice extraction, validation, and review are handled by Phase 3
artifacts and validators.
