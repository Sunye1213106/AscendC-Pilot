---
name: uo-init
description: >-
  End-to-end AscendC operator knowledge-base build for a target repo.
  Use when the user runs /uo-init, understand_operator_init, or asks to initialize
  / build a full operator KB in a new or existing AscendC repository.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] [--full]"
---

# uo-init — End-to-End Operator KB Build

Build a complete evidence-backed operator KB under `.understand-operator/<op_name>/` for the target AscendC repo.

## Variables

- `PROJECT_ROOT`: target AscendC repository root (argument path, else workspace).
- `PLUGIN_ROOT`: two levels up from this skill directory (`.../understand-operator-plugin`).
- `PROMPT_DIR`: `$PLUGIN_ROOT/prompts`.
- `SCRIPT_DIR`: `$PLUGIN_ROOT/skills/understand-operator` (shared scripts).
- `OP_NAME`: `--op-name` or repository name.
- `UO_ROOT`: `$PROJECT_ROOT/.understand-operator/$OP_NAME`.

## Global rule

Before any source-code lookup, follow `$PROMPT_DIR/00_cbm_first_rule.md`:
**CBM first; only on CBM failure may you read source (whole file allowed as last resort).**

## What this command does

Runs the **full** KB pipeline in the target repo (not a partial prepare-only step):

1. Phase 0 — prepare layout + CBM index (`prepare_operator.py`, use `--full` when requested)
2. Phase 0.5 — Macro Scope Human Review → **STOP**; print options, wait for **chat** reply (`continue` / `revise` / …), then `--decision` to record. Do **not** open stdin/arrow popups in OpenCode.
3. Phase 1 — Macro Boundary (host) → IO / boundary artifacts（**无 1.5 闸门**，完成后直接进 Phase 2）
4. Phase 2 — parallel Task: `uo-host-extraction` + `uo-flow-extraction` → barrier
5. Phase 3 — Kernel Path Task Builder
6. Phase 3.5 — Kernel Dispatch Human Review → **STOP**；摘要必须含完整 tiling/family 信息（见 `05a`）
7. Phase 4 — parallel `uo-kernel-path` × approved tasks → barrier
8. Phase 5–7 — alignment, evidence consistency, route builder
9. Phase 8 — `quality_gate.py`

Load phase prompts lazily from `$PROMPT_DIR` only when entering that phase. Do **not** pre-read all prompts.

Orchestration details: `$PROMPT_DIR/01_workflow_orchestrator.md` (load when starting).
Subagent dispatch: `$PROMPT_DIR/00_subagent_dispatch.md` (load at Phase 2 / 4).
Progress: `$PROMPT_DIR/00_progress_visibility.md` (load at start).

## Hard rules

- Subagents only at the two parallel points (host+flow; kernel-path × N). Never background `uo-*` Tasks.
- After parallel Tasks return, run `verify_subagent_barrier.py` before reading subagent artifacts.
- Do not invent IO / branches / kernel paths without evidence.
- `route.md` is a map, not a long report. `testing_hints/` are hints only, not real tests.
- Do not cross human review gates (**only 0.5 and 3.5**) without explicit user approval. Use **chat-first** review (`00_review_menu.md`): print options → user types in chat → `--decision` to record. Never use `--interactive`/`--arrows` in agent shells (blocks chat input). Phase 1.5 is retired. Phase 3.5 must present full tiling/family info before asking.

## Startup

1. Resolve `PROJECT_ROOT` / `OP_NAME`.
2. TodoWrite phase list（**不要**再创建 `uo-p15`；Phase 1.5 已取消）。
3. Run:

```powershell
python "$SCRIPT_DIR/prepare_operator.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --full
```

(Omit `--full` only if the user explicitly wants incremental index reuse.)

4. Stop at Phase 0.5 Macro Scope Review. Continue the pipeline only after user approval.

## Report when done

- `$UO_ROOT` path
- review decisions
- `quality_gate.yaml` decision
- point user to `route.md` then `summary/operator_io.yaml`
