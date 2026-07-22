```text
## Task
Follow agents/uo-semantic-resolve.md task A. Confirm host/kernel entrypoints from
candidates only. Do not invent symbols absent from the candidate list.

## Target
Roles requiring LLM in ir/entrypoint_candidates.yaml
(llm_required_roles / status: needs_llm) → ir/entrypoint_confirm.yaml

## Context
- UO_ROOT: <UO_ROOT>
- Read only: <UO_ROOT>/ir/entrypoint_candidates.yaml
- Optional: one MCP get_code_snippet for a thin candidate (prompts/common/cbm.md)
- Schema: agents/references/semantic-resolve-tasks.md §A

## Authoritative Sources
candidate name / qualified_name / file_path / confidence / signature_snippet

Non-authoritative: memory of other operators; whole-tree Glob; guessing QNs.

## Required Procedure
1. For each llm_required role, pick exactly one candidate OR mark missing with rationale.
2. kernel_entry: prefer op_kernel/<arch>/ names ending Kernel / Regbase* / *Entry.
3. Write entrypoint_confirm.yaml; stop. Parent continues resolve_entrypoints / extract.

## Hard Constraints
- MUST NOT: invent symbols outside candidates (unless all wrong → missing fields)
- MUST NOT: rewrite contracts/tiling/kernel or source tree
- ONLY write: <UO_ROOT>/ir/entrypoint_confirm.yaml
- Cap ~12 tool calls

## Output Schema
version: 1
roles:
  host_tiling_entry:
    qualified_name: ...
    name: ...
    file_path: ...
    start_line: ...
    confirmed_by: llm
    rationale: <中文>

## Acceptance Criteria
- Every llm_required role has one selection or missing
- Names ⊆ candidates (or explicit missing)
- Parent can proceed without re-scanning the repo

## Failure Handling
Ambiguous → missing + 中文 rationale; never fabricate paths.
```
