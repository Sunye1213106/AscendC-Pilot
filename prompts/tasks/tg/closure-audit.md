## Task

Bundle identity is authoritative.
Do not replace, infer, normalize, or copy identity from old artifacts.

Perform `closure_audit` for the targets provided by the Pilot action.

Follow the assigned role contract and loaded capabilities.
Do not manage workflow state or declare completion.

## Mode

- mode: `task`
- task_id: `closure-audit`
- workflow_id: `tg-solve`
- action_id: `closure_audit`
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

1. Load capability `tilingkey-closure` METHOD.md invariants.
2. Inspect ledger state (R / E / open / violation) and certificate preconditions.
3. Confirm approximate models did not exclude keys; E entries have citations.
4. If gap≠0 or I1–I4 fail, write rework reasons (`AUDIT_REWORK` / `LEMMA_REWORK`).
5. Write only `runs/<run_id>/actions/closure_audit/review.yaml`.
6. Stop; do not issue the certificate (`closure_certify` does that).

## Hard Constraints

- MUST NOT: write `tg/closure/certificate.yaml`.
- MUST NOT: write excluded set.
- MUST NOT: declare workflow complete.
- MUST NOT: invent ledger numbers — read artifacts only.

## Output Contract

Contract id: `closure-audit-v1`

## Acceptance Criteria

- Invariants checked against real artifacts.
- Failures produce explicit rework reason codes.
- Output stays inside review write scope.
