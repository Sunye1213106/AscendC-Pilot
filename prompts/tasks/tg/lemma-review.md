## Task

Bundle identity is authoritative.
Do not replace, infer, normalize, or copy identity from old artifacts.

Perform `lemma_review` for the targets provided by the Pilot action.

Follow the assigned role contract and loaded capabilities
(see Action Method + capability `tilingkey-closure`).
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
- Lemma evidence pack (if any): `<LEMMA_EVIDENCE_PATH>`

## Required Procedure

1. Read Action Method `skills/actions/tg-solve/lemma-review/METHOD.md` (fill-in checklist).
2. Load capability `tilingkey-closure` (LEMMA.md / PROOF.md).
3. If an evidence pack exists, treat its entry IDs as the only citeable sites for the five proof checks.
4. Read staging candidates under `runs/<run_id>/actions/lemma_mine/parts/**`.
5. Accept only `source_lemma` / `solver_derived` with non-empty certificate and `proof.evidence_entry_ids` when a pack is present.
6. Write verdicts to `runs/<run_id>/actions/lemma_review/review.yaml`.
7. Stop; never apply rules into the excluded set (`lemma_apply`).

## Hard Constraints

- MUST NOT: write excluded set or active_rules.
- MUST NOT: invent missing citations or evidence_entry_ids.
- MUST NOT: accept `human` / `llm` / uncited grades into accepted list.
- MUST NOT: modify producer staging parts.

## Output Contract

Contract id: `lemma-review-v1`

## Acceptance Criteria

- Every candidate is accepted, rejected, or deferred with reason.
- Accepted items have non-empty source citations; when evidence pack present, every accepted item cites `evidence_entry_ids`.
- Output conforms to review schema.
