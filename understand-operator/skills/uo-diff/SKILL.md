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
2. Run CBM change detection via MCP and print a concise summary:

   - MCP server: `codebase-memory-mcp`
   - Tool: `detect_changes`
   - Arg: `repo_path` = `$PROJECT_ROOT`

3. Print the MCP result as a concise summary. Do not write `cbm/change_set.yaml`
   or any other persisted diff artifact. For the durable PR-oriented `diff/`
   product, use `/uo-update` instead.
4. Do **not** modify KB artifacts in this command (read-only). Incremental KB
   patching lives in `/uo-update`.

## Global rule

If any source lookup is needed beyond the change API, follow `prompts/00_cbm_first_rule.md` (**MCP first**, then source on failure). Do not use local CBM CLI fallback commands.

## Out of scope for now

- Do not redesign flags, output schema, or merge this into `uo-update`.
- Do not remove this command.
