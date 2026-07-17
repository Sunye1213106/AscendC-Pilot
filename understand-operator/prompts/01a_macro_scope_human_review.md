# Phase 0 Scope Review (hard gate)

Review the Phase 0 scope discovery artifacts:

```text
runs/<current_run_id>/phase0/scope_proposal.yaml
runs/<current_run_id>/phase0/scope_scan.yaml
```

The review must show the proposed candidate files by category, candidate
directories, excluded groups, and warnings. Phase0 intentionally only performs
lightweight scope discovery; deep operator understanding starts after CBM
indexing.

## Hard stop rules

Before the user confirms:

- do not call CBM (`index_repository`)
- do not read source files at scale
- do not start Extract (`resolve_entrypoints` / `build_layered_kb`)
- do not write Phase 0 `receipt.yaml`

Use AskQuestion / question UI with: `continue` | `revise` | `stop` |
`manual_supplement`. Never invent a silent `continue`.

Record decisions only through:

```powershell
python -X utf8 "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate macro_scope --decision <continue|revise|stop|manual_supplement>
```

That command writes (on `continue`):

```text
runs/<current_run_id>/phase0/scope_review.yaml
runs/<current_run_id>/phase0/scope_confirmed.yaml
```

It must not write a Phase 0 receipt. The receipt is written only by
`finalize_phase0.py` after confirmed-file CBM indexing and Phase 0 checks pass.
