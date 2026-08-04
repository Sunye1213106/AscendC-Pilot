## Task

Bundle identity is authoritative.
Do not replace, infer, normalize, or copy identity from old artifacts.

Perform `lemma_review` for the targets provided by the Pilot action.

Follow the assigned role contract and loaded capabilities.
Do not manage workflow state or declare completion.

## Mode

- mode: `task`
- task_id: `lemma-review`
- workflow_id: `tg-solve`
- action_id: `lemma_review`
- run_id: `<RUN_ID>`

## Target

`<TARGET_IDS_OR_FILES>`

Only process the listed targets. Do not expand scope unless the Action Method explicitly permits it.

## Context

- Project root: `<PROJECT_ROOT>`
- UO root: `<UO_ROOT>`
- TG root: `<TG_ROOT>`
- Topic: `<TOPIC>`
- Context pack: `<CONTEXT_PACK_PATH>`

## Required Procedure

1. Load capability `tilingkey-closure` (LEMMA.md soundness rules).
2. Read staging candidates under `runs/<run_id>/actions/lemma_mine/parts/**`.
3. For each candidate, verify implication checklist and source citations.
4. Accept only grades that may enter E (`source_lemma` / `solver_derived`).
5. Write verdicts to `runs/<run_id>/actions/lemma_review/review.yaml`.
6. Stop; never apply rules into excluded set (that is `lemma_apply`).

## Hard Constraints

- MUST NOT: write excluded set or active_rules.
- MUST NOT: invent missing citations.
- MUST NOT: accept `human` / uncited grades into accepted list.
- MUST NOT: modify producer staging parts.

## Output Contract

Contract id: `lemma-review-v1`

## Acceptance Criteria

- Every candidate is accepted, rejected, or deferred with reason.
- Accepted items have non-empty source citations.
- Output conforms to review schema.
