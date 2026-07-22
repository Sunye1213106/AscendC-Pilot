```text
## Task
Follow agents/uo-semantic-resolve.md task C. Confirm extract_plan from candidates
only. Do not invent writers/receivers/aliases absent from candidate lists.

## Target
ir/extract_plan_candidates.yaml → ir/extract_plan.yaml

## Context
- UO_ROOT: <UO_ROOT>
- Read only: <UO_ROOT>/ir/extract_plan_candidates.yaml
- Optional: one MCP get_code_snippet for a thin candidate (prompts/common/cbm.md)
- Schema: agents/references/semantic-resolve-tasks.md §C

## Authoritative Sources
candidate lists · one MCP snippet · role rules below

Non-authoritative: memory of other operators; whole-tree Glob.

## Required Procedure
1. Confirm real tiling writers / sinks / aliases from candidates.
2. Assign role ∈ tiling_writer|key_writer|workspace_writer|provenance_helper|ignore
   - tiling_writer required when evidence has has_set_field|recv_set_call|sink_set_writer
   - provenance_helper: on-chain helper without sink writes (do not use if set_field evidence)
3. Write extract_plan.yaml; stop. Parent: apply_extract_plan.py --check.

## Hard Constraints
- MUST NOT: invent names absent from candidates
- MUST NOT: rewrite contracts/tiling/kernel
- ONLY write: <UO_ROOT>/ir/extract_plan.yaml
- Cap ~12 tool calls

## Output Schema
version: 1
confirmed_by: llm
writers: [{name, file_path, start_line, role}]
receivers: [{name, is_tiling_sink}]
aliases: [{local, tdf_leaf}]
non_sink_roots: []
extra_host_entries: []
derived_roots: []

## Acceptance Criteria
- Every name ⊆ candidates
- Roles consistent with evidence flags
- Parent check script accepts or returns actionable rejects

## Failure Handling
Ambiguous candidate → prefer missing/ignore with rationale over invention.
If all kernel candidates wrong → missing-style note; do not fabricate paths.
```
