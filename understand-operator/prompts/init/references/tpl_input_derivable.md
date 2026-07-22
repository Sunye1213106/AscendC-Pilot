```text
## Task
Follow agents/uo-semantic-resolve.md task E. Complete input_derivable broken-edge
closure for the KEY subset only. Do not discover extra keys.

## Target
KEY ids: <KEY_IDS>

## Context
- UO_ROOT: <UO_ROOT>
- Read: <UO_ROOT>/ir/input_derivable_gaps.yaml (subset above)
- Read: KEY neighbors via kb_graph (writes/derives/determined_by) + Host file_path
- CBM: prompts/common/cbm.md (search_graph → get_code_snippet, one-hop)
- Detail: skills/uo-init/references/uo-input-derivable-resolve.md
- Schema: agents/references/semantic-resolve-tasks.md §E

## Authoritative Sources
1. gaps + graph Host parent / file_path
2. MCP snippet / qualified_name
3. Patch schema below

Non-authoritative: memory, naming guesses, broad Grep, uo-query.

## Required Procedure
1. For each gap: read host_parent / gap_kind / tried_frontier / set_by.
2. CBM snippet on parent / assignee symbol (no whole-file dump).
3. Classify:
   - reaches Attr/Input/Optional/Shape/DType/Layout → input_derivable true
     + derivation_roots + one-hop host_parent
   - kernel-local / batch index → not_input_derivable
   - insufficient evidence → do NOT write true; leave open
4. Merge-write patch; stop. Parent runs classify_input_derivable.py.

## Hard Constraints
- MUST: confidence high only to close true/false/not_input_derivable
- MUST NOT: full host_derivation_chain; invent edges; suggest uo-query; rewrite unrelated keys
- ONLY write: <UO_ROOT>/ir/input_derivable_patch.yaml
- Cap ~12 tool calls

## Output Schema
version: 1
keys:
  - key_id: KEY_...
    confidence: high
    input_derivable: true | false | not_input_derivable
    host_parent: SYM::...
    derivation_roots: [HOST_ATTR_..., HOST_START_...]
    reason: <中文>
    evidence: ["path:line"]

## Acceptance Criteria
- Every listed KEY attempted; each high-closed item has evidence
- No chain dump; no low-confidence true
- Dialogue reports: batch size, high closed, still open, patch path

## Failure Handling
Cannot prove → omit true closure; reason in dialogue. Never fake high.
```
