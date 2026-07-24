## Task

Perform `extract_plan` for the Pilot-prepared action.

You are the **producer** actor `uo-semantic-resolve` (not primary).  
Do not manage workflow state or declare completion.

## Mode

- mode: `task`
- task_id: `extract-plan`
- workflow_id: `uo-init`
- action_id: `extract_plan`
- actor_id: `uo-semantic-resolve`
- run_id: `<RUN_ID>`

## Target

Confirm **only** the extraction-plan candidates listed below.  
Do **not** expand into `llm_tasks` / `mark_missing` / `dispatches_to` adjudication.

## Context

- Project root: `<PROJECT_ROOT>`
- UO root: `<UO_ROOT>`
- TG root: `<TG_ROOT>`
- Topic: `<TOPIC>`
- Context pack: `<CONTEXT_PACK_PATH>`

## Required Procedure

1. Read `ir/extract_plan_candidates.yaml` (writers / receivers / aliases / non_sink / extra).
2. Optionally skim `ir/entrypoint_graph.yaml` for identity context — do **not** rewrite it.
3. For each candidate: accept with evidence, or leave unresolved. No guessing.
4. Write **only** `ir/extract_plan.yaml` with schema fields:
   - `version: 1`
   - `writers` / `receivers` / `aliases` / `non_sink_roots` / `extra_host_entries` / `derived_roots`
   - each accepted item must carry `file_path` or `qualified_name` or `identity_key` (no short-name-only)
   - **every writer MUST include `role`**: copy `role_suggested` from the matching candidate  
     (`tiling_writer` | `key_writer` | `workspace_writer` | `provenance_helper` | `ignore`)
   - **every receiver MUST include `is_tiling_sink`**: copy `is_tiling_sink_suggested` from the matching candidate  
     (`true` = real TilingData sink; `false` = intermediate / non-sink)
5. Stop. Return a short summary. Do **not** finalize; primary runs `acp run-action extract_plan --finalize`.

## Out of scope (do NOT do)

- Do **not** read/adjudicate `ir/llm_tasks.yaml` blocking `mark_missing` / call_edge tasks here.
- Do **not** invent `call_edge_adjudications` sections inside `extract_plan.yaml`.
- Do **not** invent writer/receiver names that are absent from candidates.
- Do **not** ACCEPT empty-candidate edges (false closure). Those wait for `adjudicate_llm_tasks` then `apply_semantic_patch`.
- Do **not** run `acp`, advance phases, or write ledger / graphs other than `extract_plan.yaml`.

## Hard Constraints

- MUST write as actor `uo-semantic-resolve` with `action_id=extract_plan` (ASCENDC_ACTION).
- MUST NOT: modify Pilot state; invent evidence; write referee verdicts; patch derived graphs.
- MUST NOT: call domain scripts (`build_layered_kb.py` / `propose_extract_plan.py` / `apply_extract_plan.py`).

## Output Contract

Contract id: `extract-plan-v1`  
Path: `<UO_ROOT>/ir/extract_plan.yaml`

## Acceptance Criteria

- Every candidate class was attempted (writers/receivers/aliases/…).
- Every closed conclusion has required evidence and identity fields.
- Every accepted writer has a valid `role`; every accepted receiver has `is_tiling_sink`.
- Output matches extract_plan schema (not llm_tasks patches).
- No undeclared file was modified.
- Unresolved items are explicit and honest.

## Failure Handling

When evidence is insufficient: retain unresolved or needs_human;
include the missing evidence type; do not guess; stop and return the blocking reason.
