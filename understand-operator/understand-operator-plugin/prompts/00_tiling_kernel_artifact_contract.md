# Tiling / Kernel Task Artifact Contract

This is a schema contract, not a workflow phase. It prepares traceability and downstream impact analysis only.

Do not generate tests, do not run tests, do not add coverage, and do not add instrumentation.

## Shared Rules

- `tiling_branch_families.yaml` is the primary tiling dispatch artifact.
- `branch_matrix.yaml` is a representative sample table, not a full tiling key enumeration.
- Tiling-side kernel facts are hints unless tiling source explicitly selects kernel entry, kernel type, or template instance.
- Numeric tiling data variants do not split kernel tasks by themselves.
- `source_spans`, `trigger_preconditions`, `traceability`, and `downstream_preparation` are indexes for later analysis, not test cases.

## Tiling Family Schema

Each `families[]` item in `tiling/tiling_branch_families.yaml` must include:

```yaml
family_id: TF001
stable_key: ""
name: ""
guard_signature:
  predicates: []
  normalized: ""
reachability:
  status: taken | not_taken | runtime_conditional | skipped_by_review | unknown
  reason: ""
  evidence: []
template_context:
  templates: []
  compile_time_bindings: []
  unresolved_symbols: []
dispatch_variables:
  hard_dispatch: []
  optional_io_gate: []
  performance_knob: []
  tiling_data_value: []
  unknown: []
structural_tiling_signature:
  signature_id: ""
  fields: {}
  reason: ""
numeric_variants:
  fields: []
  observed_or_predicted_ranges: {}
  note: "numeric variants do not split kernel task unless evidence says they change structural path"
related_branches: []
source_spans:
  - span_id: SP_TILING_001
    file: ""
    function: ""
    line_range: []
    role: guard_condition | key_setter | tiling_data_writer | compile_time_binding | optional_io_gate | unknown
    evidence: []
trigger_preconditions:
  dtype_constraints: []
  shape_constraints: []
  layout_constraints: []
  optional_input_constraints: []
  attr_constraints: []
  compile_time_constraints: []
  negative_constraints: []
  satisfiable: true | false | unknown
tiling_key_expectation:
  mode: single | set | range | expression | unknown
  values: []
  expression: ""
  role: witness | exact | hint | unknown
predicted_kernel_path_hint:
  status: known | unknown | conflicting
  possible_entries: []
  reason: ""
kernel_entry_hint:
  status: known | unknown | conflicting
  possible_entries: []
  reason: ""
needs_alignment: true | false
downstream_preparation:
  needs_kernel_task: true | false
  needs_alignment: true | false
  likely_affected_compute_steps: []
  likely_affected_dataflow_edges: []
  unresolved_for_downstream: []
impact_trace:
  affected_by_change_types:
    - tiling_condition_change
    - tiling_key_change
    - tiling_data_structural_change
    - optional_io_gate_change
    - compile_time_binding_change
  downstream_artifacts:
    kernel_tasks: []
    kernel_paths: []
    route_entries: []
representative_cases: []
split_risks: []
evidence: []
confidence: high | medium | low
```

Top-level companion fields:

```yaml
version: 1
status: analyzed
families: []
excluded_families: []
blocking_questions: []
```

## Branch Representative Schema

Each `branches[]` item in `tiling/branch_matrix.yaml` must include:

```yaml
id: B001
family_id: TF001
materialization_role: representative | boundary | risk | unknown | manual_keep
representative_case_id: TF001_R1
representative_reason: ""
condition_snapshot:
  raw: ""
  normalized: ""
  kind: compile_time | runtime | mixed | macro_guard | template_specialization | unknown
reachability:
  status: taken | not_taken | runtime_conditional | skipped_by_review | unknown
  reason: ""
  evidence: []
predicate_refs: []
dispatch_variable_refs: []
structural_tiling_signature_id: ""
tiling_key_witness:
  mode: single | set | range | expression | unknown
  values: []
  expression: ""
  role: witness | exact | hint | unknown
trigger_preconditions:
  dtype_constraints: []
  shape_constraints: []
  layout_constraints: []
  optional_input_constraints: []
  attr_constraints: []
  compile_time_constraints: []
  negative_constraints: []
  satisfiable: true | false | unknown
boundary_values: {}
source_spans:
  - span_id: SP_BRANCH_001
    file: ""
    function: ""
    line_range: []
    role: branch_condition | key_setter | tiling_data_writer | unknown
    evidence: []
numeric_variant_refs: []
risk_refs: []
evidence: []
confidence: high | medium | low
```

## Tiling Route Schema

Each `routes[]` item in `tiling/tiling_route.yaml` must include:

```yaml
route_id: TR001
family_id: TF001
action: normal_kernel_task | needs_review | excluded | needs_alignment
dispatchable: true | false
reason: ""
task_priority: high | medium | low | needs_review | excluded
required_human_review: true | false
required_cbm_followup: []
required_followups:
  - kernel_task_builder
  - kernel_alignment
  - evidence_consistency
  - downstream_preparation
blocks_downstream_preparation: true | false
evidence: []
```

Route semantics:

- `normal_kernel_task`: generate a normal kernel task.
- `needs_alignment`: generate a kernel task with split risks and review questions.
- `needs_review`: generate a task draft only; do not auto-dispatch.
- `excluded`: do not generate a normal kernel task.

## Kernel Task Plan Schema

Each `kernel_tasks[]` item in `kernel/kernel_task_plan.yaml` must include:

```yaml
task_id: K_TASK_001
source_family: TF001
stable_key: ""
route_action: normal_kernel_task | needs_review | needs_alignment
dispatchable: true | false
task_priority: high | medium | low | needs_review
dispatch_signature:
  predicates: []
  hard_dispatch_variables: []
  optional_io_gates: []
  structural_tiling_signature_id: ""
  structural_tiling_signature: {}
  numeric_variants: []
reachability:
  status: taken | runtime_conditional | unknown
  reason: ""
  evidence: []
family_template_context:
  templates: []
  compile_time_bindings: []
  unresolved_symbols: []
io_scope:
  inputs: []
  optional_inputs: []
  outputs: []
kernel_entry_hints: []
compute_scope:
  required_steps: []
  dataflow_edges: []
representative_cases: []
traceability:
  source_family: TF001
  related_branches: []
  related_tiling_keys:
    mode: single | set | range | expression | unknown
    values: []
    expression: ""
    role: witness | exact | hint | unknown
  source_spans: []
  predicate_refs: []
  dispatch_variable_refs: []
  tiling_data_signature_refs: []
  route_id: ""
downstream_preparation:
  trigger_preconditions:
    dtype_constraints: []
    shape_constraints: []
    layout_constraints: []
    optional_input_constraints: []
    attr_constraints: []
    compile_time_constraints: []
    negative_constraints: []
    satisfiable: true | false | unknown
  expected_tiling_key:
    mode: single | set | range | expression | unknown
    values: []
    expression: ""
    role: witness | exact | hint | unknown
  expected_compute_steps: []
  expected_dataflow_edges: []
  unresolved_for_kernel_path_agent: []
  unresolved_for_alignment: []
review_questions: []
split_risks: []
evidence: []
```

Top-level companion fields:

```yaml
version: 1
status: analyzed
kernel_tasks: []
excluded_families: []
needs_review_families: []
task_generation_summary:
  source_family_count: 0
  normal_task_count: 0
  needs_review_count: 0
  excluded_count: 0
  merge_count: 0
  split_count: 0
```

## Dispatch Review Fields

`kernel/kernel_dispatch_review.yaml` must include:

```yaml
dispatchable_task_ids: []
non_dispatchable_task_ids: []
needs_review_task_ids: []
approved_task_ids: []
```

For `decision: dispatch_all`, `approved_task_ids` must equal `dispatchable_task_ids`.
