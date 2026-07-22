```text
## Task
Follow agents/uo-kb-review.md. Final KB product review after integrity pass.

## Target
Single operator KB at <UO_ROOT>. Do not modify ir/**.

## Context
- Read: summary/human_overview.md, checks/integrity.yaml, checks/final.yaml
- Read: ir/resolution_ledger.yaml, ir/unresolved.yaml (must be empty)
- Read: ir/entrypoints.yaml, ir/input_derivable.yaml, ir/input_derivable_gaps.yaml
- Read: checks/confidence_gate.yaml
  if status=reported → summary/confidence_report.md reasons must not be TODO
- Run: uo_kb_query.py --status-only; optional 1–2 determined_by/reaches_input
- Gate rules: skills/uo-init/references/confidence-gate.md

## Authoritative Sources
checks/* · listed ir/* · overview · confidence_report · status-only CLI

Non-authoritative: memory, dumping operator_graph / full testcase.

## Required Procedure
1. Verify integrity already passed.
2. Checklist: unresolved empty; ledger rationale; entrypoints confirmed;
   overview↔integrity; sqlite fresh; confidence high on closed keys;
   confidence_gate in {pass,reported}; compact host_parent/derivation_roots spot-check.
3. Write ONLY review/kb_product_review.yaml then stop.

## Hard Constraints
- MUST NOT: rebuild KB; edit ir/**; search cbm/index_stage; dump large YAML
- Cap ~15 tool calls; findings in 中文

## Output Schema
version: 1
verdict: pass | fail
summary: <中文一句>
findings:
  - id: KBR_...
    severity: error | warning
    rework_stage: phase0_scope | entrypoints | extract_plan | residual_resolve | input_derivable | confidence_gate | export_graph | none
    message: <中文>
    evidence: <path>

## Acceptance Criteria
- Fail if closed KEY confidence≠high
- Fail if unsolved leftovers lack filled confidence_report reasons
- Every error has routable rework_stage

## Failure Handling
Parent routes rework_stage (max 2). input_derivable/confidence_gate →
task E + classify + check_final_confidence + export.
On pass: parent runs export_human_views.py.
```
