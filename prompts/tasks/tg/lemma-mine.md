## Task

Bundle identity is authoritative.
Do not replace, infer, normalize, or copy identity from old artifacts.

Perform `lemma_mine` for the targets provided by the Pilot action.

Follow the assigned role contract and loaded capabilities.
Do not manage workflow state or declare completion.

## Mode

- mode: `task`
- task_id: `lemma-mine`
- workflow_id: `tg-solve`
- action_id: `lemma_mine`
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

1. Load capability `tilingkey-closure` (especially LEMMA.md and PROOF.md).
2. Read only `tg/closure/lemmas/leads.yaml` as the closed lead pack — never invent leads.
3. For each assigned lead, attempt a source-cited proof via paths A/B/C in LEMMA.md; writing standard in PROOF.md.
4. Write candidates only to `runs/<run_id>/actions/lemma_mine/parts/part_*.yaml`.
5. Set `grade: source_lemma` only when PROOF.md's three requirements are met (sites + chain + no later overwrite).
6. Stop after producing staging parts; do not call finalize or write excluded set.

## Hard Constraints

- MUST NOT: invent leads or keys outside the lead pack.
- MUST NOT: write `tg/closure/excluded*` or `proof_rules.yaml`.
- MUST NOT: use approximate models to exclude keys.
- MUST NOT: modify Pilot state or declare gap=0.

## Output Contract

Contract id: `lemma-mine-v1`

## Acceptance Criteria

- Every candidate carries source citations or is left unresolved.
- Output stays inside staging write scopes.
- No undeclared file was modified.
