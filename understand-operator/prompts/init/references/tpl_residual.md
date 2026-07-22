```text
## Task
Follow agents/uo-semantic-resolve.md task B (+ optional D). Residual resolve and
optional branch consistency. Process only ids present in unresolved.yaml.

## Target
Simple FP / host-only sample ≤12 representative diagnostics. Complex KEY gaps
→ escalate_keys (parent task E). Do not invent ids.

## Context
- UO_ROOT: <UO_ROOT>
- Read only: <UO_ROOT>/ir/unresolved.yaml (snippets therein)
- Optional skim: <UO_ROOT>/ir/kernel_subgraph.yaml branch rows
- Schema: agents/references/semantic-resolve-tasks.md §B §D
- CBM if needed: prompts/common/cbm.md (one symbol)

## Authoritative Sources
unresolved.yaml ids · embedded snippets · MCP snippet

Non-authoritative: memory; hand-counting coverage vs unresolved.

## Required Procedure
1. Group by pattern; pick 1–3 reps per pattern (≤12 total).
2. Label status: resolved|accepted|false_positive|alias with 中文 rationale.
3. Complex KEY/shape/input_derivable breaks → list escalate_keys (do not fake resolved).
4. Optional D: consistency_diffs for suspicious branch rows.
5. Write resolution_patch.yaml; stop. Parent: apply_resolution.py --check.

## Hard Constraints
- MUST NOT: residuals:/resolutions:/decision:accept_warning; invent ids
- MUST NOT: suggest uo-query during /uo-init; silent complex gaps
- MUST NOT: claim full unresolved.yaml coverage by hand
- ONLY write: <UO_ROOT>/ir/resolution_patch.yaml
- Cap ~15 tool calls

## Output Schema
version: 1
node_patches: []
unresolved_resolutions:
  - id: <id from unresolved.yaml>
    status: resolved | accepted | false_positive | alias
    rationale: <中文简述>
consistency_diffs: []
escalate_keys: []

## Acceptance Criteria
- Every emitted id exists in unresolved.yaml
- Complex leftovers appear in escalate_keys or were out of sample with note
- Check script can validate patch

## Failure Handling
Insufficient evidence → accepted/false_positive only with rationale, or skip id.
Never empty escalate_keys while leaving known complex KEY gaps unmarked.
```

