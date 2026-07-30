## Task

Bundle identity is authoritative.
Do not replace, infer, normalize, or copy identity from old artifacts.

Perform `resolve_gaps` for blockers listed in `uo/ir/unresolved.yaml`.

Follow the assigned role contract and loaded capabilities.
Do not manage workflow state or declare completion.

## Mode

- mode: `task`
- task_id: `resolve-gaps`
- workflow_id: `<WORKFLOW_ID>`
- action_id: `<ACTION_ID>`
- run_id: `<RUN_ID>`

## Target

`<TARGET_IDS_OR_FILES>`

Only process the listed blockers. One patch file per blocker under
`runs/{run_id}/actions/resolve_gaps/parts/`.

## Context

- Project root: `<PROJECT_ROOT>`
- UO root: `<UO_ROOT>`
- Topic: `<TOPIC>`
- Context pack: `<CONTEXT_PACK_PATH>`

## Required Procedure

1. Read `uo/ir/unresolved.yaml` and quality metrics.
2. For each assigned blocker, propose a source-backed closure patch with evidence path:line.
3. Do not invent TILING_DATA / INPUT_* roots without write-site evidence.
4. Write only under the declared staging paths.
5. Stop after producing patches and a concise task result.

## Output

Staging patches under `runs/{run_id}/actions/resolve_gaps/parts/**`.
