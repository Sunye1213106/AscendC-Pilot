## Task

Bundle identity is authoritative.
Do not replace, infer, normalize, or copy identity from old artifacts.

Perform **one extract_plan Relation shard** for the Pilot-prepared action.

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

Confirm / reject / leave unresolved **only** the semantic Relations in **your assigned batch**.  
Do **not** choose final extract-plan roles. Do **not** invent input roots.

## Required Procedure

1. Read session `prompt.md` / `method.md` / `bundle.yaml`.
2. Read **only** your batch file (`inputs/batches/batch_NNN.yaml`).
3. For each obligation: based on evidence + observations, confirm or reject candidate Relations
   (`BINDS|WRITES|READS|DERIVES|EQUIVALENT_TO|COMPOSES_KEY|CONTRIBUTES_TO_KEY|GUARDS|SELECTS_TEMPLATE|GROUNDED_IN|…`).
4. Write **only**:
   `runs/<RUN_ID>/actions/extract_plan/staging/relation_parts/part_NNN.yaml`
5. Run producer-self-check for this shard; fix Gate errors for **this part only**.
6. Stop. Do **not** finalize / next / advance / complete.

## Schema (hard) — shard part only

```yaml
version: 1
shard_id: <SHARD_ID>
action_session_id: <from batch>
source_snapshot_hash: <from batch>
decisions:
  - obligation_id: <id>
    status: confirmed   # or unresolved | rejected_batch
    relations:
      - type: BINDS
        subject: receiver:foo_
        object: tiling_field:Root.nested
        evidence_refs: [CAND:...]
        confidence: high
    rejected_relations: []
    reason_code: ""     # required when status=unresolved
```

## Hard Constraints

- MUST NOT write `uo/ir/extract_plan.yaml` or choose `tiling_writer` / `key_writer` roles.
- MUST NOT treat intermediate locals (`fBaseParams.*`) as input roots.
- MUST cite evidence_refs from the batch / source windows.
- MUST allow `unresolved` when evidence is insufficient.
- MUST NOT read full candidates.yaml or other shards' batches.

## Target (runtime)

`<TARGET>`
