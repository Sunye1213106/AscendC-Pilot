---
name: tg-solve
description: 执行已批准 TG Plan：对 target set T 构造/replay case，用真实 Host witness 扩大 R，对残差按需推导源码引理扩大
  E，直到 T=(R∩T)∪E。未指定目标由 tg-plan 默认 T=D。
---

# tg-solve

Pilot workflow entry. Orchestration authority: `pilot/.../workflows/specs.py`.

Domain method: `skills/testcase-generation/SKILL.md`.

Run via `acp start` / `next` / `run-action` / `advance` / `complete`.

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `solve_precheck` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/solve-precheck` | `-` | `solve-precheck-v1` |
| `oracle_probe` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/oracle-probe` | `-` | `oracle-probe-v1` |
| `closure_ledger` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/closure-ledger` | `-` | `closure-ledger-v1` |
| `closure_search` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/closure-search` | `-` | `closure-search-v1` |
| `closure_residual` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/closure-residual` | `-` | `closure-residual-v1` |
| `closure_construct` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/closure-construct` | `-` | `closure-construct-v1` |
| `closure_explain` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/closure-explain` | `-` | `closure-explain-v1` |
| `lemma_leads` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/lemma-leads` | `-` | `lemma-leads-v1` |
| `lemma_evidence` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/lemma-evidence` | `-` | `lemma-evidence-v1` |
| `lemma_mine` | `subagent` | `tg-lemma-producer` | `producer` | `tg-solve/lemma-mine` | `tg/lemma-mine` | `lemma-mine-v1` |
| `lemma_verify` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/lemma-verify` | `-` | `-` |
| `lemma_review` | `subagent` | `tg-closure-referee` | `referee` | `tg-solve/lemma-review` | `tg/lemma-review` | `lemma-review-v1` |
| `lemma_apply` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/lemma-apply` | `-` | `lemma-apply-v1` |
| `lemma_loop` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/lemma-loop` | `-` | `lemma-loop-v1` |
| `closure_audit` | `subagent` | `tg-closure-referee` | `referee` | `tg-solve/closure-audit` | `tg/closure-audit` | `closure-audit-v1` |
| `closure_certify` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/closure-certify` | `-` | `closure-certify-v1` |
| `z3_solve` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/z3-solve` | `-` | `z3-solve-v1` |
| `cover_confirm` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-solve/cover-confirm` | `-` | `cover-confirm-v1` |

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
| `solve_precheck` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-solve/solve-precheck` | `-` | `deterministic-tg-engine` |
| `oracle_probe` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-solve/oracle-probe` | `-` | `deterministic-tg-engine` |
| `closure_ledger` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-solve/closure-ledger` | `-` | `deterministic-tg-engine` |
| `closure_search` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-solve/closure-search` | `-` | `deterministic-tg-engine` |
| `closure_residual` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-solve/closure-residual` | `-` | `deterministic-tg-engine` |
| `closure_construct` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-solve/closure-construct` | `-` | `deterministic-tg-engine` |
| `closure_explain` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-solve/closure-explain` | `-` | `deterministic-tg-engine` |
| `lemma_leads` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-solve/lemma-leads` | `-` | `deterministic-tg-engine` |
| `lemma_evidence` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-solve/lemma-evidence` | `-` | `deterministic-tg-engine` |
| `lemma_mine` | source-authority,code-access,evidence,language,pilot-control,output-quality | source-reading,source-navigation | `tg-solve/lemma-mine` | `tg/lemma-mine` | `tg-lemma-producer` |
| `lemma_verify` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-solve/lemma-verify` | `-` | `deterministic-tg-engine` |
| `lemma_review` | source-authority,code-access,evidence,language,pilot-control,output-quality | source-reading | `tg-solve/lemma-review` | `tg/lemma-review` | `tg-closure-referee` |
| `lemma_apply` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-solve/lemma-apply` | `-` | `deterministic-tg-engine` |
| `lemma_loop` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-solve/lemma-loop` | `-` | `deterministic-tg-engine` |
| `closure_audit` | source-authority,code-access,evidence,language,pilot-control,output-quality | source-reading | `tg-solve/closure-audit` | `tg/closure-audit` | `tg-closure-referee` |
| `closure_certify` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-solve/closure-certify` | `-` | `deterministic-tg-engine` |
| `z3_solve` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-solve/z3-solve` | `-` | `deterministic-tg-engine` |
| `cover_confirm` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-solve/cover-confirm` | `-` | `deterministic-tg-engine` |

## Action runtime index

| action_id | method_path | prompt_path | output_contract | role |
|---|---|---|---|---|
| `solve_precheck` | `actions/solve-precheck/action.yaml` | `-` | `solve-precheck-v1` | `deterministic_engine` |
| `oracle_probe` | `actions/oracle-probe/action.yaml` | `-` | `oracle-probe-v1` | `deterministic_engine` |
| `closure_ledger` | `actions/closure-ledger/action.yaml` | `-` | `closure-ledger-v1` | `deterministic_engine` |
| `closure_search` | `actions/closure-search/action.yaml` | `-` | `closure-search-v1` | `deterministic_engine` |
| `closure_residual` | `actions/closure-residual/action.yaml` | `-` | `closure-residual-v1` | `deterministic_engine` |
| `closure_construct` | `actions/closure-construct/action.yaml` | `-` | `closure-construct-v1` | `deterministic_engine` |
| `closure_explain` | `actions/closure-explain/action.yaml` | `-` | `closure-explain-v1` | `deterministic_engine` |
| `lemma_leads` | `actions/lemma-leads/action.yaml` | `-` | `lemma-leads-v1` | `deterministic_engine` |
| `lemma_evidence` | `actions/lemma-evidence/action.yaml` | `-` | `lemma-evidence-v1` | `deterministic_engine` |
| `lemma_mine` | `actions/lemma-mine/action.yaml` | `prompts/tasks/tg/lemma-mine.md` | `lemma-mine-v1` | `producer` |
| `lemma_verify` | `actions/lemma-verify/action.yaml` | `-` | `-` | `deterministic_engine` |
| `lemma_review` | `actions/lemma-review/action.yaml` | `prompts/tasks/tg/lemma-review.md` | `lemma-review-v1` | `referee` |
| `lemma_apply` | `actions/lemma-apply/action.yaml` | `-` | `lemma-apply-v1` | `deterministic_engine` |
| `lemma_loop` | `actions/lemma-loop/action.yaml` | `-` | `lemma-loop-v1` | `deterministic_engine` |
| `closure_audit` | `actions/closure-audit/action.yaml` | `prompts/tasks/tg/closure-audit.md` | `closure-audit-v1` | `referee` |
| `closure_certify` | `actions/closure-certify/action.yaml` | `-` | `closure-certify-v1` | `deterministic_engine` |
| `z3_solve` | `actions/z3-solve/action.yaml` | `-` | `z3-solve-v1` | `deterministic_engine` |
| `cover_confirm` | `actions/cover-confirm/action.yaml` | `-` | `cover-confirm-v1` | `deterministic_engine` |
