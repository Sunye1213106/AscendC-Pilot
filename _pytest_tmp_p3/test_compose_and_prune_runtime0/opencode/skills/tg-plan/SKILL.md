---
name: tg-plan
description: 制定 TG 测试目标并冻结 target set。用户未指定目标时默认计划全部源码声明 TilingKey；指定 packed keys
  或维度过滤条件时只计划该子集。Plan 不构造 case、不做可达性求解。
---

# tg-plan

Pilot workflow entry. Orchestration authority: `pilot/.../workflows/specs.py`.

Domain method: `skills/testcase-generation/SKILL.md`.

Run via `acp start` / `next` / `run-action` / `advance` / `complete`.

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `plan_intent` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-plan/plan-intent` | `tg/plan-intent` | `plan-intent-v1` |
| `plan_scope` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-plan/plan-scope` | `-` | `plan-scope-v1` |
| `plan_precheck` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-plan/plan-precheck` | `-` | `plan-precheck-v1` |
| `plan_build` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-plan/plan-build` | `-` | `plan-build-v1` |
| `plan_approve` | `primary_interactive` | `ascendc-pilot` | `controller` | `tg-plan/plan-approve` | `tg/plan-approve` | `plan-approved-v1` |

<!-- END GENERATED ACTIONS -->

## Composed: policy-invariants

Follow pilot policies (short invariants). Full text: `pilot/policies/*/POLICY.md`.

# Control invariants (model-facing, short)

1. Only run Actions returned by `acp next`; never advance Pilot state yourself.
2. Never declare workflow `done` / `passed`; only `acp complete` may finish.
3. Do not call domain CLIs directly; use `acp run-action`.
4. Writes must stay inside Agent `write_scopes` ∩ Action lease ∩ workflow `write_roots`.
5. Primary never writes formal `uo/**` / `tg/**` IR products for a declared sub-actor.
6. Lease invariant: anything you may Write is also Readable.
7. Missing required params → AskQuestion immediately; do not repo-archaeology to guess.
8. Progress only via host Todo sync from `todo.todo_sync.items` — never paste status panels to the user.

Full detail: `pilot/policies/pilot-control/POLICY.md`.

# Evidence invariants (model-facing, short)

1. Search / UO graph locate ≠ proof. High confidence needs a disk source window.
2. `confidence: high` / `source_verified: true` requires **both**:
   - `evidence_window_sha256` for the cited `path:line` window
   - continuous `evidence_snippet` that is a substring of that window
3. Never invent hashes, line numbers, or pasted non-contiguous snippets.
4. Neighbor / wrong-window sha reuse is fabrication → reject.
5. Absence claims need machine-checkable negative evidence, not “I searched a lot”.
6. Intermediate locals are never input roots; ungrounded surfaces stay unresolved.

Full detail: `pilot/policies/evidence/POLICY.md`.

# Code-access invariants (model-facing, short)

1. Locate (graph / Grep) → then windowed Read of the minimal function/macro block.
2. No unbounded repo / parent-repo scans; no whole-file dumps into context.
3. Empty UO graph ≠ symbol does not exist; fall back to scoped source read.
4. Shallow ABI `set_*` writers without value-defining sites → PARTIAL/UNKNOWN, not “unreachable”.

Full detail: `pilot/policies/code-access/POLICY.md` (host/Windows path tips live in docs).

# Authority invariants (model-facing, short)

Priority (high → low): current source window → signed Pilot artifacts → current UO/TG KB → verified local memory → model memory / naming intuition.

MUST NOT close KEY/contract fields from naming guesses or stale memory.

Full detail: `pilot/policies/source-authority/POLICY.md`.

# Output-quality invariants (model-facing, short)

1. Producer write surface ∩ Referee write surface = ∅.
2. Do not forge high confidence; keep unresolved / needs_human explicit.
3. Write only declared output-contract paths.

Full detail: `pilot/policies/output-quality/POLICY.md`.

# Language invariants (model-facing, short)

- User-facing text: 简体中文.
- IDs / status / reason_code / schema field names: English.
- Findings / rationale narrative: 简体中文.

Full detail: `pilot/policies/language/POLICY.md`.

## Composition index

| action_id | policies | capabilities | method | prompt | agent |
|---|---|---|---|---|---|
| `plan_intent` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-plan/plan-intent` | `tg/plan-intent` | `deterministic-tg-engine` |
| `plan_scope` | source-authority,code-access,evidence,language,pilot-control,output-quality | kb-query | `tg-plan/plan-scope` | `-` | `deterministic-tg-engine` |
| `plan_precheck` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-plan/plan-precheck` | `-` | `deterministic-tg-engine` |
| `plan_build` | source-authority,code-access,evidence,language,pilot-control,output-quality | kb-query | `tg-plan/plan-build` | `-` | `deterministic-tg-engine` |
| `plan_approve` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-plan/plan-approve` | `tg/plan-approve` | `ascendc-pilot` |

## Action runtime index

| action_id | method_path | prompt_path | output_contract | role |
|---|---|---|---|---|
| `plan_intent` | `actions/plan-intent/action.yaml` | `prompts/tasks/tg/plan-intent.md` | `plan-intent-v1` | `deterministic_engine` |
| `plan_scope` | `actions/plan-scope/action.yaml` | `-` | `plan-scope-v1` | `deterministic_engine` |
| `plan_precheck` | `actions/plan-precheck/action.yaml` | `-` | `plan-precheck-v1` | `deterministic_engine` |
| `plan_build` | `actions/plan-build/action.yaml` | `-` | `plan-build-v1` | `deterministic_engine` |
| `plan_approve` | `actions/plan-approve/action.yaml` | `prompts/tasks/tg/plan-approve.md` | `plan-approved-v1` | `controller` |
