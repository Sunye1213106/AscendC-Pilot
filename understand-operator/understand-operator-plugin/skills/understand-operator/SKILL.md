---
name: understand-operator
description: Build an evidence-backed AscendC operator KB with CBM queries, operator IO, tiling, compute/dataflow, kernel path alignment, route, and quality gate.
argument-hint: "[path] [--op-name <name>] [--full]"
---

# Understand Operator

Generate a stable AscendC operator knowledge base. The host coding agent orchestrates the workflow and runs most phases directly. **Only two parallel points** use Cursor subagents via the **Task** tool: host+flow extraction, and multi-kernel path analysis.

## Router Contract

On activation, use this `SKILL.md` as the only required startup context. Do **not** pre-read `prompts/00_*.md` or phase prompt files. Load prompt files lazily, only when entering the matching phase or dispatching the matching subagent.

## Variables

- `PROJECT_ROOT`: repository root, default current workspace.
- `SKILL_DIR`: this skill directory.
- `PLUGIN_ROOT`: two directories above `SKILL_DIR`.
- `PROMPT_DIR`: `$PLUGIN_ROOT/prompts`.
- `OP_NAME`: value from `--op-name`, or repository name if omitted.
- `UO_ROOT`: `$PROJECT_ROOT/.understand-operator/$OP_NAME`.

## Hard Rules

- **Subagent dispatch only at two parallel points.** Use the inline Subagent Dispatch Protocol below as the startup routing rule. Read `prompts/00_subagent_dispatch.md` only when entering Phase 2 or Phase 4 and the inline protocol is insufficient.
  - **Parallel point 1:** `uo-host-extraction` + `uo-flow-extraction` in one message (two Task calls).
  - **Parallel point 2:** one `uo-kernel-path` Task per approved `task_id` in one message.
  - All other phases (1, 3, 5, 6, 7) are executed **by the host agent** following the phase prompts. Do not spawn subagents for them.
- **Host/subagent sync barrier is mandatory.** After dispatching parallel Tasks, **end the turn and wait** for all Task results. Then run `verify_subagent_barrier.py` before reading subagent artifacts or starting the next host phase. Never continue in the same turn as Task dispatch.
- Use CBM/codebase-memory-mcp for structure and code intelligence. Do not implement AST, call graph, reference graph, or symbol graph in this plugin.
- **CBM-first (mandatory for host AND every subagent).** Every "find code / find symbol / read implementation / trace calls" step MUST start with a `cbm_query.py` call. Read `prompts/00_cbm_on_demand.md` only when entering a code-lookup phase or when detailed CBM syntax is needed. Do NOT read a whole `.cpp/.h` source file "for speed/reliability" before querying CBM. `Read` source only (and line-scoped) when CBM already returned a file+line to verify, when macros/templates/string-attrs are not fully covered by CBM, or when a CBM query came back empty/error (log that query first).
- **CBM on-demand:** Phase 0 is index-only; phases/subagents run `cbm_query.py` with custom tool/payload. Do not bulk-write `cbm/*.json` unless `--save` or `--prefetch-queries`.
- **Pass a runnable CBM command to subagents.** In every Task prompt, fill `CBM_QUERY` with the absolute-path command (resolved real `cbm_query.py` path), never a `<SKILL_DIR>` placeholder — otherwise the subagent cannot run it and falls back to raw `Read`.
- Do not generate `.understand/knowledge-graph.json`, AST directories, call graph directories, reference graph directories, or symbol graph directories.
- Do not equate `tiling_key` with `kernel_path`.
- Before accepting any tiling branch, resolve the relevant template instantiation, macro guards, `constexpr`/`const`/enum/type-trait values, platform flags, and branch reachability (`taken` / `not_taken` / `runtime_conditional` / `skipped_by_review` / `unknown`).
- Do not invent IO, branches, kernel paths, or evidence.
- `route.md` is a map, not a long report.
- `testing_hints/` contains test-design hints only, not real tests.
- Three human review checkpoints are mandatory gates: Macro Scope Review after Phase 0, Boundary Review after Phase 1, and Kernel Dispatch Review after Phase 3. Do not auto-continue past them without explicit user approval.
- **Progress must be visible in the current chat.** Use the Progress Visibility section below at startup. Read `prompts/00_progress_visibility.md` only if the current phase needs extra progress-format detail. Before any work: create the full workflow **TodoWrite** list. After each phase: update todos and post a short progress block. **Default is continuous execution until the next human review gate**; do not ask the user to confirm every phase. **Never** use background Tasks for `uo-*` subagents. Do not silently run Phase 0→7 or cross Phase 0.5 / Phase 1.5 / Phase 3.5 without explicit user approval.

## Progress Visibility (mandatory)

1. **TodoWrite** at start with ids `uo-p0`, `uo-p05`, `uo-p1`, `uo-p15`, `uo-p2a`, `uo-p2b`, `uo-p3`, `uo-p35`, `uo-p4a`, `uo-p4b`, `uo-p5`, `uo-p6`, `uo-p7`, `uo-p8`.
2. Mark `in_progress` before each phase; `completed` after.
3. Post a `## 进度 · …` block in chat after each major step (Chinese if user asked).
4. Update `$UO_ROOT/summary/workflow_progress.yaml` after each phase.
5. **STOP after Phase 0 at Macro Scope Review.** Show the planned Macro Boundary exploration scope, including excluded branches/files, and wait for user approval before Phase 1.
6. Subagent Tasks: **foreground only**; after they return, run barrier before reading artifacts or continuing.

## Phase 0 - Preflight, Ignore Rules, CBM Prefetch

Run:

```bash
python "$SKILL_DIR/prepare_operator.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

Use `--full` when the user requests a full rebuild. The script creates:

- `.understand-operator/<op_name>/`
- the full artifact skeleton
- `summary/ignore_rules.md`
- `cbm/index_meta.json` (CBM project + index summary)
- `cbm/cbm_query_log.md` (Phase 0 index steps only)

Phase 0 does **not** bulk-write `search_graph` / `search_code` JSON files. Use `--prefetch-queries` only for legacy bulk prefetch. All semantic lookups use `cbm_query.py`. **On Windows PowerShell use shorthand flags** (`--name-pattern`, `--code-pattern`, etc.) — do not pass JSON as a positional argument. If detailed query syntax is needed during a semantic phase, load `prompts/00_cbm_on_demand.md` then.

```bash
python "$SKILL_DIR/cbm_query.py" "$PROJECT_ROOT" search_graph --op-name "$OP_NAME" --name-pattern ".*MyOp.*" --label Function --phase phase1
```

If CBM is missing, stop and report the install/configuration issue. The user can set `UNDERSTAND_OPERATOR_CBM_BIN`, configure `[scanner].cbm_binary`, or place `codebase-memory-mcp` under `thirdparty/`.

After Phase 0: update todo `uo-p0`, write `summary/workflow_progress.yaml`, then run Phase 0.5 Macro Scope Human Review (`prompts/01a_macro_scope_human_review.md`). Write `summary/macro_scope_review.yaml` and **STOP** until the user chooses `continue`.

## Phase 0.5 - Macro Scope Human Review (mandatory gate)

**STOP after Phase 0.** Follow `prompts/01a_macro_scope_human_review.md` as the host agent.

Present a review summary covering:

- Phase 1 include scope: directories/files/symbols Macro Boundary Agent will explore
- exclude scope: directories/files/patterns/branches that should not be explored
- branch skip rules: e.g. platform/dtype/feature-flag/legacy branches to ignore
- uncertain scope needing user confirmation

Ask the user to choose one of: `continue`, `revise`, `stop`.

Write `summary/macro_scope_review.yaml` with the user's decision.

Gate rules:

- Do **not** start Phase 1 until the user explicitly chooses `continue`.
- If the user chooses `revise`, update `summary/macro_scope_review.yaml`, then repeat this review.
- If the user chooses `stop`, end the workflow and report generated artifacts.

## Subagent Dispatch Protocol

Subagent definitions: `agents/uo-host-extraction.md`, `agents/uo-flow-extraction.md`, `agents/uo-kernel-path.md` (or `~/.cursor/agents/` after `install.ps1 cursor`).

| When | Subagents | Parallel |
|---|---|---|
| After Boundary Review `continue` | `uo-host-extraction`, `uo-flow-extraction` | **yes — one message, two Task calls** |
| After Kernel Dispatch approval | `uo-kernel-path` × N | **yes — one message, N Task calls** |

All other phases: host agent follows the listed phase prompt directly. Load `prompts/00_subagent_dispatch.md` only while preparing a Phase 2 or Phase 4 dispatch.

## Phase 1 - Macro Boundary Agent

Follow `prompts/02_macro_boundary_agent.md` as the **host agent**.

Input:

- user request and extra description
- `cbm/index_meta.json` (project context)
- on-demand CBM via `cbm_query.py` (see `prompts/00_cbm_on_demand.md`)
- `summary/ignore_rules.md`
- `summary/macro_scope_review.yaml` (approved include/exclude/branch skip scope)

Output:

- `summary/operator_manifest.yaml`
- `summary/operator_io.yaml`
- `summary/operator_boundary.md`
- `summary/analysis_plan.yaml`
- `summary/ontology.yaml`

This is the first semantic phase. It must identify operator IO and file boundaries before kernel details.

## Phase 1.5 - Boundary Human Review (mandatory gate)

**STOP after Phase 1.** Follow `prompts/02a_boundary_human_review.md` as the host agent.

Present a review summary from:

- `summary/operator_manifest.yaml`
- `summary/operator_io.yaml`
- `summary/operator_boundary.md`
- `summary/analysis_plan.yaml`

Ask the user to choose one of: `continue`, `revise`, `stop`.

Write `summary/boundary_review.yaml` with the user's decision.

Gate rules:

- Do **not** start Phase 2 until the user explicitly chooses `continue`.
- If the user chooses `revise`, update Macro Boundary artifacts or rerun Phase 1, then repeat this review.
- If the user chooses `stop`, end the workflow and report generated artifacts.

## Phase 2 - Parallel Host and Flow Extraction

**Dispatch, wait, barrier, then continue**

In **one host message**, call **Task** twice in parallel (foreground):

- subagent `uo-host-extraction` — host 侧 tiling / branch / host 入口（prompt ref: `prompts/03_tiling_extraction_agent.md`）
- subagent `uo-flow-extraction` — compute/dataflow 语义（prompt ref: `prompts/04_compute_dataflow_agent.md`）

When dispatching `uo-host-extraction`, include or reference `prompts/00_tiling_kernel_artifact_contract.md` for compact schema details. Do not load it before Phase 2.

After both foreground Tasks return, run:

```bash
python "$SKILL_DIR/verify_subagent_barrier.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --phase host_flow
```

Only if exit code is 0: `Read` `tiling/*` and `flows/*`, then start Phase 3. If barrier fails: resume/retry subagents. Do not write host/flow artifacts yourself.

Do not perform host or flow analysis in the host agent during this phase.

Both agents are **CBM-first**: every tiling/kernel/flow lookup must start with `cbm_query.py`; do not open whole source files before querying CBM. Journal entries go to `cbm/query_journal.jsonl`. Do not read bulk `cbm/*.json` prefetch files unless they exist from `--prefetch-queries`.

Outputs:

- `tiling/*`
- `flows/*`

## Phase 3 - Kernel Path Task Builder

Follow `prompts/05_kernel_path_task_builder.md` as the **host agent**. Use `prompts/00_tiling_kernel_artifact_contract.md` for the compact task schema.

Output:

- `kernel/kernel_task_plan.yaml`

Task granularity is one `tiling_branch_family` by default. Split a family only for structural differences; numeric tiling data variants do not split tasks.

## Phase 3.5 - Kernel Dispatch Human Review (mandatory gate)

**STOP after Phase 3.** Follow `prompts/05a_kernel_dispatch_human_review.md` as the host agent.

Present a review summary from `kernel/kernel_task_plan.yaml` and related tiling/flow artifacts.

Ask the user to choose one of: `dispatch_all`, `dispatch_subset`, `revise`, `stop`.

Write `kernel/kernel_dispatch_review.yaml` with the user's decision and `approved_task_ids`.

Gate rules:

- Do **not** start Phase 4 until the user explicitly approves dispatch.
- If the user chooses `dispatch_subset`, only dispatch approved `task_id`s in Phase 4.
- If the user chooses `revise`, update `kernel/kernel_task_plan.yaml` or rerun Phase 3, then repeat this review.
- If the user chooses `stop`, end the workflow and report generated artifacts.

## Phase 4 - Parallel Kernel Path Agents

**Dispatch, wait, barrier, then continue**

Read `kernel/kernel_task_plan.yaml` and `kernel/kernel_dispatch_review.yaml`. In **one host message**, call **Task** once per approved `task_id` → subagent `uo-kernel-path` (foreground). Include the single task block and `task_id` in each prompt. Reference prompt: `prompts/06_kernel_path_agent.md`.

After all foreground kernel-path Tasks return, run:

```bash
python "$SKILL_DIR/verify_subagent_barrier.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --phase kernel_path
```

Only if exit code is 0: `Read` `kernel/paths/*`, then start Phase 5. If barrier fails: resume/retry the missing `uo-kernel-path` tasks. Do not write kernel path artifacts yourself.

Each subagent writes only its own path:

- `kernel/paths/Kxxx_kernel_path.yaml`
- `kernel/paths/Kxxx_kernel_path.md`
- `kernel/paths/.uo_kernel_path_Kxxx_complete.json`

Each path must align to:

- `summary/operator_io.yaml`
- `tiling/tiling_branch_families.yaml`
- `tiling/branch_matrix.yaml` representative samples
- `tiling/tiling_data_signature.yaml`
- `flows/compute_flow.yaml`

## Phase 5 - Kernel Alignment Builder

Follow `prompts/07_kernel_alignment_builder.md` as the **host agent**.

Output:

- `kernel/kernel_path_matrix.yaml`
- `kernel/sync_buffer_map.yaml`

## Phase 6 - Evidence Consistency Agent

Follow `prompts/08_evidence_consistency_agent.md` as the **host agent**.

Output:

- `evidence/evidence_check.yaml`
- `evidence/consistency_report.md`
- `evidence/missing_items.yaml`
- `evidence/conflict_items.yaml`
- `evidence/confidence_report.yaml`

## Phase 7 - Operator KB / Route Builder

Follow `prompts/09_route_builder.md` as the **host agent**.

Output:

- `route.md`
- `route.json`
- `summary/overview.md`
- `testing_hints/golden_hint.yaml`
- `testing_hints/accuracy_case_hint.yaml`
- `testing_hints/performance_case_hint.yaml`
- `testing_hints/coverage_hint.yaml`

## Phase 8 - Quality Gate

Run:

```bash
python "$SKILL_DIR/quality_gate.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

The script writes `quality_gate.yaml`. If it returns red, tell the user the KB is a draft and cannot drive automatic test generation.

## Report

Tell the user:

- changed or generated artifact paths
- macro scope review decision from `summary/macro_scope_review.yaml`
- boundary review decision from `summary/boundary_review.yaml`
- kernel dispatch review decision from `kernel/kernel_dispatch_review.yaml`
- quality gate decision
- whether host and flow extraction ran in parallel via subagents
- approved kernel task count and kernel path artifact count
- where to start reading: `route.md`, then `summary/operator_io.yaml`
