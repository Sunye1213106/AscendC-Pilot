---
name: uo-diff
description: >-
  Reserved read-only AscendC operator change summary against an existing KB.
  Use when the user runs /uo-diff or asks for a diff-style summary of operator
  code changes vs the last understand-operator state. Kept as-is; not redesigned.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>]"
---

# uo-diff — Reserved Diff API (keep as-is)

Provide a **read-only** change summary for an AscendC operator relative to the existing KB. Do **not** redesign this command in the current refactor.

## Variables

- `PROJECT_ROOT`: 算子仓库根。
- `PLUGIN_ROOT` / `SCRIPT_DIR`: 同 uo-init（`$PLUGIN_ROOT/uo/scripts`）；禁止全盘搜脚本。
- `PROMPT_DIR`: `$PLUGIN_ROOT/prompts`。
- `OP_NAME` / `UO_ROOT`: `$PROJECT_ROOT/.understand-operator/$OP_NAME`。

## Current behavior (preserve)

1. If `$UO_ROOT` is missing, report that and suggest `/uo-init`.
2. Produce a concise change summary **without** depending on CRG or a CBM `detect_changes` tool (may be absent):

```powershell
python -X utf8 "$SCRIPT_DIR/detect_kb_changes.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

   Prefer printing `diff/change_set.yaml` if `/uo-update` already ran; otherwise the detect script output is enough for a read-only summary.

3. Do not write durable review products here. For PR-oriented `diff/` product use `/uo-update`; for dual-path review use `/uo-code-review`.
4. Do **not** modify KB artifacts in this command (read-only). Incremental KB patching lives in `/uo-update`.

## Global rule

If any source lookup is needed beyond the change API, follow `prompts/00_cbm_first_rule.md` (**MCP first**, then source on failure). Do not use local CBM CLI fallback commands. Do not install code-review-graph.

## Out of scope for now

- Do not redesign flags, output schema, or merge this into `uo-update`.
- Do not remove this command.
