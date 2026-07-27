## Task

Bundle identity is authoritative.
Do not replace, infer, normalize, or copy identity from old artifacts.

Perform `extract_plan` for the Pilot-prepared action.

You are the **producer** actor `<ACTOR_ID>` (not primary).  
Do not manage workflow state or declare completion.

## Mode

- mode: `task`
- task_id: `extract-plan`
- workflow_id: `<WORKFLOW_ID>`
- action_id: `<ACTION_ID>`
- actor_id: `<ACTOR_ID>`
- run_id: `<RUN_ID>`

## Target

Confirm **only** the extraction-plan work items prepared below.  
Do **not** expand into `llm_tasks` / `mark_missing` / `dispatches_to` adjudication.

## Context

- Project root: `<PROJECT_ROOT>`
- UO root: `<UO_ROOT>`
- TG root: `<TG_ROOT>`
- Topic: `<TOPIC>`
- Context pack: `<CONTEXT_PACK_PATH>`
- CBM project (MCP `project` / `acp cbm lookup`): `<CBM_PROJECT>`
- Architecture preference: `<ARCHITECTURE>`
- **candidates_sha256 (copy verbatim into decision_report):** `<CANDIDATES_SHA256>`

## Required Procedure

1. Read session `prompt.md` / `method.md` / `bundle.yaml`.
2. Read **decision_worklist** first:
   `runs/<RUN_ID>/actions/extract_plan/inputs/decision_worklist.yaml`
   (or `uo/ir/extract_plan_decision_worklist.yaml`).  
   Use `acp inspect extract-plan-worklist` / `acp inspect extract-plan-coverage` for counts —
   **FORBIDDEN** to hand-count candidates YAML.
3. Follow public **large-IR** read order when a source window is needed:
   summary → rework_hints → targeted candidate windows only.
4. For each `required_decision: true` work item: decide `accept` / `reject` / `defer`
   using public Policy/Capability/Gates (not inventing local rules).
5. Write **only**:
   `runs/<RUN_ID>/actions/extract_plan/staging/decision_report.yaml`
   (legacy `staging/output.yaml` accepted temporarily).  
   **FORBIDDEN**: write `uo/ir/extract_plan.yaml` / aliases / receiver_bindings
   (finalizer materializes slim IR + sidecars).
6. Run `acp inspect validate --what extract-plan-staging --run-id <RUN_ID>` and fix Gate errors.
7. Stop. Do **not** finalize / next / advance / complete.

## Schema (hard) — decision_report only

```yaml
version: 1
actor_id: <ACTOR_ID>
run_id: <RUN_ID>
workflow_id: <WORKFLOW_ID>
candidates_sha256: <CANDIDATES_SHA256>
accepted:
  - candidate_id: CAND_xxx
    role: tiling_writer
rejected:
  - candidate_id: CAND_yyy
    reason_code: helper_or_out_of_scope
deferred:
  - candidate_id: CAND_zzz
    reason_code: unreachable_or_ambiguous
receiver_binding_confirmations:
  - candidate_id: CAND_bbb
    binding_ref: RB_001
```

## Hard Constraints

- MUST NOT invent writers/receivers outside decision_worklist candidate_ids
- MUST NOT put evidence_snippet / decision_reason / full candidate lists into canonical IR
- MUST NOT finalize or write `uo/ir/**` plan files
- MUST cover every `required_decision: true` work item (accept ∪ reject ∪ defer, exclusive)
- MUST NOT treat macro/binding kinds as automatic reject solely for “not a function”
- MUST NOT read `uo/ir/llm_tasks.yaml` / `semantic_patches.yaml` / ledger

## Stop

After writing decision_report and passing staging validate, return a short summary.
Primary runs `acp run-action extract_plan --finalize`.
