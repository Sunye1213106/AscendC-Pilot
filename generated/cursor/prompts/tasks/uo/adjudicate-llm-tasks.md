## Task

Bundle identity is authoritative.
Do not replace, infer, normalize, or copy identity from old artifacts.

Perform `adjudicate_llm_tasks` for the Pilot-prepared action.

You are the **producer** actor `<ACTOR_ID>` (not primary).  
Do not manage workflow state or declare completion.

## Mode

- mode: `task`
- task_id: `adjudicate-llm-tasks`
- workflow_id: `<WORKFLOW_ID>`
- action_id: `<ACTION_ID>`
- actor_id: `<ACTOR_ID>`
- run_id: `<RUN_ID>`

## Target

Adjudicate **open blocking** entries in `ir/llm_tasks.yaml` only.  
Write **only** `ir/semantic_patches.yaml` for the deterministic `apply_semantic_patch` step.

## Context

- Project root: `<PROJECT_ROOT>`
- UO root: `<UO_ROOT>`
- TG root: `<TG_ROOT>`
- Topic: `<TOPIC>`
- Context pack: `<CONTEXT_PACK_PATH>`

## Required Procedure

1. Read `ir/llm_tasks.yaml`. Collect tasks with `status: open` and `severity: blocking`.
2. For each task, inspect its `candidates` / `allowed_actions` / evidence hints.
   - Optionally Read the cited `file_path` windows for grounding — do not rewrite graphs.
3. Emit one patch per task into `ir/semantic_patches.yaml`:
   ```yaml
   version: 1
   artifact_identity:
     run_id: <RUN_ID>
     workflow_id: <WORKFLOW_ID>
     phase: extract
     action_id: <ACTION_ID>
     actor_id: <ACTOR_ID>
     role_id: <ROLE_ID>
     action_session_id: <ACTION_SESSION_ID>
   patches:
     - run_id: <RUN_ID>
       task_id: <exact task_id>
       candidate_set_hash: <copy verbatim from llm_tasks task.candidate_set_hash>
       source_snapshot_hash: <copy verbatim from llm_tasks task.source_snapshot_hash>
       action: mark_missing   # or accept_edge / choose_one when candidates exist
       accepted_candidate_ids: []
       rejected_candidate_ids: []
       evidence: ["path:line or reason"]
   ```
4. Rules (hard):
   - **MUST** set `candidate_set_hash` (authoritative name; not `patch_candidate_set_hash`)
     by copying the matching task field from `llm_tasks.yaml`.
   - **MUST** set `source_snapshot_hash` the same way when present on the task.
   - Empty `candidates` → **only** `mark_missing` (never invent edge ids).
   - Non-empty candidates + enough evidence → `accept_edge`/`choose_one` with ids **inside** the candidate window.
   - Insufficient evidence → `mark_missing` (honest unresolved), not guess ACCEPT.
   - `mark_missing` must keep `accepted_candidate_ids: []`.
   - Do **not** invent symbols / edges absent from candidates.
5. Stop. Return a short summary. Do **not** finalize; primary runs `acp run-action <ACTION_ID> --finalize`.

## Out of scope (do NOT do)

- Do **not** write `semantic_resolution_ledger.yaml` or any derived graph.
- Do **not** modify `extract_plan.yaml` / `entrypoint_graph.yaml` / score reports.
- Do **not** run `acp`, advance phases, or call domain scripts.

## Hard Constraints

- MUST write as actor `<ACTOR_ID>` with `action_id=<ACTION_ID>` (ASCENDC_ACTION).
- MUST NOT: modify Pilot state; invent evidence; write referee verdicts; patch derived graphs.
- MUST cover every open blocking task (or leave an explicit needs_human note in evidence).

## Output Contract

Contract id: `semantic-patches-v1`  
Path: `<UO_ROOT>/ir/semantic_patches.yaml`

## Acceptance Criteria

- Every open blocking task has a corresponding patch with matching `task_id`.
- Empty-candidate tasks use `mark_missing` only.
- Accepted candidate ids are within the task window.
- No undeclared file was modified.

## Failure Handling

When evidence is insufficient: use `mark_missing` with a Chinese reason in `evidence`; do not guess; stop and return the blocking reason.
