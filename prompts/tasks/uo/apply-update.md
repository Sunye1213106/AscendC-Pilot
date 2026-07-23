## Task

Perform `apply_update` for the targets provided by the Pilot action.

Follow the assigned role contract and loaded capabilities.
Do not manage workflow state or declare completion.

## Mode

- mode: `task`
- task_id: `apply-update`
- workflow_id: `uo-update`
- action_id: `apply_update`
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

1. Apply loaded capabilities in order.
2. Evaluate each listed target independently.
3. Record evidence for every accepted conclusion.
4. Preserve unresolved items when evidence is insufficient.
5. Write only the declared output artifact.
6. Stop after producing the artifact and concise task result.

## Hard Constraints

- MUST NOT: modify Pilot state.
- MUST NOT: process IDs outside the supplied target set.
- MUST NOT: invent evidence or confidence.
- MUST NOT: write referee verdicts when acting as producer.
- MUST NOT: modify reviewed artifacts when acting as referee.

## Output Contract

Contract id: `update-apply-v1`

## Acceptance Criteria

- Every target was attempted.
- Every closed conclusion has required evidence.
- Output conforms to the declared schema.
- No undeclared file was modified.
- Unresolved items are explicit and honest.

## Failure Handling

When evidence is insufficient: retain unresolved or needs_human;
include the missing evidence type; do not guess; stop and return the blocking reason.
