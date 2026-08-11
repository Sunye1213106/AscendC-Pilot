---
name: uo-update
description: 在已有 `.uo` 上根据源码变更执行确定性增量刷新、重建受影响 CodeMap 关系、校验完整性并输出差异摘要。用户要求刷新已有 UO/CodeMap
  或查看源码变更对 CodeMap 的影响时使用。
---

# uo-update

Pilot workflow entry. Orchestration authority: `pilot/.../workflows/specs.py`.

Domain method: `skills/operator-analysis/SKILL.md`.

Run via `acp start` / `next` / `run-action` / `advance` / `complete`.

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `detect_changes` | `deterministic` | `human` | `deterministic_engine` | `uo-update/detect-changes` | `-` | `change-detect-v1` |
| `plan_update` | `deterministic` | `human` | `deterministic_engine` | `uo-update/plan-update` | `-` | `update-plan-v1` |
| `apply_update` | `deterministic` | `human` | `deterministic_engine` | `uo-update/apply-update` | `-` | `update-apply-v1` |
| `key_triage` | `deterministic` | `human` | `deterministic_engine` | `uo-update/key-triage` | `-` | `key-triage-v1` |
| `key_resolution` | `deterministic` | `human` | `deterministic_engine` | `uo-update/key-resolution` | `-` | `input-derivable-patch-v1` |
| `confidence_report` | `deterministic` | `human` | `deterministic_engine` | `uo-update/confidence-report` | `-` | `confidence-report-v1` |
| `confidence_review` | `deterministic` | `human` | `deterministic_engine` | `uo-update/confidence-review` | `-` | `confidence-reason-review-v1` |
| `export_integrity` | `deterministic` | `human` | `deterministic_engine` | `uo-update/export-integrity` | `-` | `integrity-v1` |
| `diff_summary` | `deterministic` | `human` | `deterministic_engine` | `uo-update/diff-summary` | `-` | `diff-summary-v1` |
| `diff_only` | `deterministic` | `human` | `deterministic_engine` | `uo-update/diff-only` | `-` | `diff-summary-v1` |

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
| `detect_changes` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-update/detect-changes` | `-` | `human` |
| `plan_update` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-update/plan-update` | `-` | `human` |
| `apply_update` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-update/apply-update` | `-` | `human` |
| `key_triage` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-update/key-triage` | `-` | `human` |
| `key_resolution` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-update/key-resolution` | `-` | `human` |
| `confidence_report` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-update/confidence-report` | `-` | `human` |
| `confidence_review` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-update/confidence-review` | `-` | `human` |
| `export_integrity` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-update/export-integrity` | `-` | `human` |
| `diff_summary` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-update/diff-summary` | `-` | `human` |
| `diff_only` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-update/diff-only` | `-` | `human` |

## Action runtime index

| action_id | method_path | prompt_path | output_contract | role |
|---|---|---|---|---|
| `detect_changes` | `actions/detect-changes/action.yaml` | `-` | `change-detect-v1` | `deterministic_engine` |
| `plan_update` | `actions/plan-update/action.yaml` | `-` | `update-plan-v1` | `deterministic_engine` |
| `apply_update` | `actions/apply-update/action.yaml` | `-` | `update-apply-v1` | `deterministic_engine` |
| `key_triage` | `actions/key-triage/action.yaml` | `-` | `key-triage-v1` | `deterministic_engine` |
| `key_resolution` | `actions/key-resolution/action.yaml` | `-` | `input-derivable-patch-v1` | `deterministic_engine` |
| `confidence_report` | `actions/confidence-report/action.yaml` | `-` | `confidence-report-v1` | `deterministic_engine` |
| `confidence_review` | `actions/confidence-review/action.yaml` | `-` | `confidence-reason-review-v1` | `deterministic_engine` |
| `export_integrity` | `actions/export-integrity/action.yaml` | `-` | `integrity-v1` | `deterministic_engine` |
| `diff_summary` | `actions/diff-summary/action.yaml` | `-` | `diff-summary-v1` | `deterministic_engine` |
| `diff_only` | `actions/diff-only/action.yaml` | `-` | `diff-summary-v1` | `deterministic_engine` |
