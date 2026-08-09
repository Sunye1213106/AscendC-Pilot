## Task

Bundle identity is authoritative.
Do not replace, infer, normalize, or copy identity from old artifacts.

Perform `resolve_gaps` for blockers listed in **this shard's batch only**.

Follow the assigned role contract and Action-composed capabilities
(Composition index / Action Bundle — do not hardcode a capability list here).
Do not manage workflow state or declare completion.

Domain procedure: `skills/actions/uo-init/resolve-gaps/METHOD.md`.

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

## Output contract (`resolve-gaps-v1` / staging)

Each patch MUST use:

```yaml
blocker_id: BLK_…
classification: scheduling | input_derived | validation_assumption | genuinely_unknown
binding:   # one test — use when classification == input_derived
  var_id: <from this blocker's own readable_vars list — nothing else exists>
  op: eq | ne | lt | le | gt | ge | in
  value: <literal or enum member inside the var domain>
evidence:
  - file: <path>
    line: <int>
    snippet: "<must match source; quote if contains ! & *>"
```

When one test is not the answer, give `condition` **instead of** `binding`
(never both). Same rules at every leaf — declared `var_id`, value in domain:

```yaml
condition:
  op: and            # and | or  → args: [...]
  args:              # not       → arg: {...}
    - {op: eq, var: VAR_ATTR_SPARSE_MODE, value: 3}
    - op: not
      arg: {op: in, var: VAR_DTYPE_QUERY, value: [DT_FLOAT8_E5M2, DT_FLOAT8_E4M3FN]}
```

At most 64 nodes, 6 deep. If the answer does not fit, say `genuinely_unknown` and write why in `notes`.

Staging part only under `runs/{run_id}/actions/resolve_gaps/parts/part_<SHARD_ID>.yaml`.
