## Task

Bundle identity is authoritative.
Do not replace, infer, normalize, or copy identity from old artifacts.

Mine Case-mutation recipes that close open TilingKey gaps for **this shard only**.

Follow the assigned role contract and loaded capabilities.
Do not manage workflow state or declare completion.

## Mode

- mode: `task`
- task_id: `mine-recipe`
- workflow_id: `tk-cover`
- action_id: `mine_recipe`
- run_id: `RUN_20260803_162337_29193cd2`
- shard_id: `(see dispatch_tasks[].shard_id)`

## Target

Read:

- `uo/tk/derive_fields.yaml`
- `uo/tk/residual.yaml` (if present — residual blockers are NOT recipe targets)
- `uo/ir/host_codemap.yaml`
- gap / obligation clusters supplied in the session bundle
- `.probe_cache/replay/coverage_closure.yaml` for `open_gap_sound`

Write one part file for this shard:

`runs/{run_id}/actions/mine_recipe/parts/part_(see dispatch_tasks[].shard_id).yaml`

## Output shape

```yaml
schema: tk-recipe-part/v1
recipes:
  - dim: <DimensionName>
    want: "<value>"
    rationale: <one line>
    case_patch:
      <Case field>: <value>
```

Prefer Binding write knobs (`pse`, `atten_mask`, `keep_prob`, `rope`, `dtype`, sizes)
over inventing host-state. Never claim sound unreachability without a solver-grade rule.
Never “close” residual blockers (bandIdx / invalidS1Array / L2 / blockOuter) by deleting them.

## Forbidden

- Writing `uo/tk/recipe.yaml` (finalizer only)
- Declaring workflow passed
- Migrating FAG proof_rules to another operator
- Inventing `excluded_sound` rules to fake `open_gap_sound = 0`
