---
name: uo-update
description: >-
  Incrementally update an AscendC operator knowledge base from code changes since
  the last KB snapshot. Use when the user runs /uo-update, understand_operator_update,
  or asks to refresh/patch the KB after code changes.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>]"
---

# uo-update — Incremental KB Update

Detect code changes since the last KB state and **incrementally** update affected artifacts. Prefer patching over full rebuild.

## Variables

- `PROJECT_ROOT`: AscendC repository root.
- `PLUGIN_ROOT`: two levels up from this skill directory (`.../understand-operator-plugin`).
- `PROMPT_DIR`: `$PLUGIN_ROOT/prompts`.
- `SCRIPT_DIR`: `$PLUGIN_ROOT/skills/understand-operator`.
- `OP_NAME`: `--op-name` or repository name.
- `UO_ROOT`: `$PROJECT_ROOT/.understand-operator/$OP_NAME`.

## Global rule

Follow `$PROMPT_DIR/00_cbm_first_rule.md`:
**CBM first for source lookups; on CBM failure, then read source (whole file allowed as last resort).**

## Preconditions

- `$UO_ROOT` must exist (from a prior `/uo-init`). If missing → tell user to run `/uo-init`.
- Prefer existing `route.md` + `cbm/index_meta.json` as the previous KB baseline.

## Workflow

### 1. Detect delta

Run:

```powershell
python "$SCRIPT_DIR/update_operator.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

This writes/updates:

- `cbm/change_set.yaml` — changed files / symbols / suggested impacted areas
- `summary/update_plan.yaml` — which KB sections to refresh
- refreshes CBM index status (incremental; use `--full` only if user requests)

Also use CBM `detect_changes` via `cbm_query.py` when the script output is insufficient:

```powershell
python "$SCRIPT_DIR/cbm_query.py" "$PROJECT_ROOT" detect_changes --op-name "$OP_NAME" --phase update
```

### 2. Plan impacted phases

From `summary/update_plan.yaml` / change set, map changes to KB areas:

| Changed area | Refresh |
|---|---|
| proto / host IO / entry | Phase 1 boundary + IO |
| tiling / host dispatch | host extraction (`tiling/*`) |
| compute / data move | flow extraction (`flows/*`) |
| kernel impl / path | kernel tasks + paths |
| only docs/tests unrelated | maybe skip or light touch |

### 3. Incremental re-run (not full init)

- Re-run **only** impacted phases using the same prompts as `uo-init`.
- Keep human review gates when boundary or kernel dispatch plans materially change.
- Reuse unchanged artifacts; do not wipe the whole `$UO_ROOT` unless the user asks for full rebuild (`/uo-init --full`).
- After patches: run `quality_gate.py` and update `route.md` if the map changed.
- Append a short entry to `summary/update_history.yaml` (create if missing).

### 4. Parallel points

Same as init: only `uo-host-extraction`+`uo-flow-extraction`, and `uo-kernel-path` × N when those areas are impacted. Barrier required.

## Report

- What changed in code (summary)
- Which KB artifacts were updated vs left untouched
- New quality gate decision
- Whether a full `/uo-init` is recommended instead
