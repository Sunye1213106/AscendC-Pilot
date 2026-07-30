## Task

Bundle identity is authoritative.
Do not replace, infer, normalize, or copy identity from old artifacts.

Perform `resolve_gaps` for blockers listed in **this shard's batch only**.

Follow the assigned role contract and loaded capabilities
(`bounded-semantic-batch`, `sharded-llm-producer`, `semantic-resolution`).
Do not manage workflow state or declare completion.

## Mode

- mode: `task`
- task_id: `resolve-gaps`
- workflow_id: `<WORKFLOW_ID>`
- action_id: `<ACTION_ID>`
- run_id: `<RUN_ID>`
- shard_id: `<SHARD_ID>`

## Target

`<TARGET_IDS_OR_FILES>`

Only process the listed blocker ids from the assigned batch file.
Write one part file for this shard:

`runs/{run_id}/actions/resolve_gaps/parts/part_<SHARD_ID>.yaml`

## Context

- Project root: `<PROJECT_ROOT>`
- UO root: `<UO_ROOT>`
- Topic: `<TOPIC>`
- Context pack: `<CONTEXT_PACK_PATH>`
- Batch: `runs/{run_id}/actions/resolve_gaps/inputs/batches/batch_<SHARD_ID>.yaml`

## Closed vocabulary (mandatory)

Each patch MUST use:

```yaml
blocker_id: BLK_…
classification: scheduling | input_derived | validation_assumption | genuinely_unknown
binding:   # required when classification == input_derived
  var_id: <from batch closed_vocabulary / declared vars only>
  op: eq | ne | lt | le | gt | ge | in
  value: <literal or enum member inside the var domain>
evidence:
  - file: <path>
    line: <int>
    snippet: "<must match source; quote if contains ! & *>"
```

## Required Procedure

1. Read **only** this shard's batch YAML (and session prompt/method/bundle).
2. For each assigned blocker, propose a source-backed patch inside the closed vocabulary.
3. Do not invent TILING_DATA / INPUT_* / VAR_* symbols absent from the whitelist.
4. Do not read other batches, other parts, or write `uo/ir/**`.
5. Write `parts/part_<SHARD_ID>.yaml` with a top-level `patches: [...]` list.
6. Stop after producing the part and a concise task result. Do not finalize.

## Output

Staging part only under `runs/{run_id}/actions/resolve_gaps/parts/part_<SHARD_ID>.yaml`.
