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
- `THIS_SKILL` / `SCRIPT_DIR`: 同 uo-init，优先 `THIS_SKILL/../understand-operator`；禁止全盘搜脚本。
- `PROMPT_DIR`: `$SCRIPT_DIR/../../prompts`。
- `OP_NAME` / `UO_ROOT`: `$PROJECT_ROOT/.understand-operator/$OP_NAME`。

## Current behavior (preserve)

1. If `$UO_ROOT` is missing, report that and suggest `/uo-init`.
2. Run CBM change detection via MCP and print a concise summary:

   - MCP server: `codebase-memory-mcp`
   - Tool: `detect_changes`
   - Arg: `repo_path` = `$PROJECT_ROOT`

3. If `cbm/change_set.yaml` or related detect_changes artifacts already exist (from update/prefetch), summarize that file instead of inventing diffs.
4. Do **not** modify KB artifacts in this command (read-only). Incremental KB patching belongs to `/uo-update`.

## Global rule

If any source lookup is needed beyond the change API, follow `prompts/00_cbm_first_rule.md` (**MCP first**, then source on failure). Do not use `cbm_query.py`.

## Out of scope for now

- Do not redesign flags, output schema, or merge this into `uo-update`.
- Do not remove this command.
