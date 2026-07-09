---
name: uo-diff
description: >-
  Reserved understand-operator diff interface. Use when the user runs /uo-diff or
  understand_operator_diff. Keep behavior stable; do not redesign this command yet.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>]"
---

# uo-diff — Reserved Diff Interface

**Status: keep as-is / reserved. Do not change the product contract in this iteration.**

## Intent

Expose a stable diff-facing entry for comparing repository / CBM / KB-related change signals. Implementation may stay thin.

## Variables

- `PROJECT_ROOT`: AscendC repository root.
- `SCRIPT_DIR`: sibling `skills/understand-operator` under the plugin.
- `OP_NAME`: `--op-name` or repository name.
- `UO_ROOT`: `$PROJECT_ROOT/.understand-operator/$OP_NAME`.

## Current behavior (preserve)

1. If `$UO_ROOT` is missing, report that and suggest `/uo-init`.
2. Run CBM change detection and print a concise summary:

```powershell
python "$SCRIPT_DIR/cbm_query.py" "$PROJECT_ROOT" detect_changes --op-name "$OP_NAME" --phase diff
```

3. If `cbm/change_set.yaml` or `cbm/30_detect_changes.json` already exists (from update/prefetch), summarize that file instead of inventing diffs.
4. Do **not** modify KB artifacts in this command (read-only). Incremental KB patching belongs to `/uo-update`.

## Global rule

If any source lookup is needed beyond the change API, follow `prompts/00_cbm_first_rule.md` (CBM first, then source on failure).

## Out of scope for now

- Do not redesign flags, output schema, or merge this into `uo-update`.
- Do not remove this command.
