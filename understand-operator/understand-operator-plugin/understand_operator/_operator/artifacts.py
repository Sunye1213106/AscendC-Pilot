from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ARTIFACT_DIR = ".understand-operator"

CANONICAL_ROOT_FILES = [
    "index.yaml",
    "route.md",
    "operator.yaml",
    "quality.yaml",
    "human/review.md",
]

CANONICAL_TILING_FILES = [
    "tiling/route.md",
    "tiling/index.yaml",
    "tiling/variables.yaml",
    "tiling/key_space.yaml",
    "tiling/constraints.yaml",
    "tiling/families.yaml",
    "tiling/data_model.yaml",
    "tiling/coverage_model.yaml",
    "tiling/evidence_index.yaml",
]

# Intermediate tiling analysis — REQUIRED on disk during /uo-init host extraction
# (anti-laziness). Canonical 9 files remain the query/TestGenerate SoT; these
# archive files force macros / constexpr / predicates / decision tree to land
# before merge. kernel_evidence_backfill.yaml is Phase 5 only — not in this list.
REQUIRED_TILING_ARCHIVE_FILES = [
    "tiling/archive/frontier.yaml",
    "tiling/archive/dispatch_variables.yaml",
    "tiling/archive/predicate_space.yaml",
    "tiling/archive/compile_time_bindings.yaml",
    "tiling/archive/decision_tree.md",
]

CANONICAL_FLOW_FILES = [
    "flow/index.yaml",
    "flow/compute_graph.yaml",
    "flow/dataflow.yaml",
    "flow/golden_model.yaml",
    "flow/numerical_model.yaml",
]

CANONICAL_KERNEL_FILES = [
    "kernel/index.yaml",
    "kernel/paths.yaml",
    "kernel/pipeline.yaml",
    "kernel/resources.yaml",
]

CANONICAL_TEST_FILES = [
    "test/index.yaml",
    "test/contract.yaml",
]

CANONICAL_EVIDENCE_FILES = [
    "evidence/source_index.yaml",
    "evidence/fact_index.yaml",
    "evidence/artifact_dependencies.yaml",
    "evidence/issues.yaml",
]


def safe_op_name(name: str | None, repo_root: Path) -> str:
    raw = (name or "").strip() or repo_root.name
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
    return cleaned or "unknown_operator"


def operator_root(repo_root: Path, op_name: str) -> Path:
    path = repo_root / ARTIFACT_DIR / op_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def init_operator_layout(base: Path, op_name: str, repo_root: Path) -> None:
    for rel in [
        "cbm",  # live CBM working dir (tooling); not a uo-query default read
        "tiling/archive",
        "flow",
        "kernel",
        "test",
        "evidence",
        "human",
        "archive/cbm",
        "archive/runs",
        "archive/legacy",
        "archive/raw_agents/kernel_paths",
    ]:
        (base / rel).mkdir(parents=True, exist_ok=True)

    for keep in [
        "tiling/archive/.gitkeep",
        "archive/cbm/.gitkeep",
        "archive/runs/.gitkeep",
        "archive/legacy/.gitkeep",
        "archive/raw_agents/.gitkeep",
        "archive/raw_agents/kernel_paths/.gitkeep",
    ]:
        write_text(base / keep, "")

    write_text(
        base / "operator.yaml",
        f"""version: 1
op_name: {op_name}

scope:
  arch: unknown
  platform: unknown
  include: []
  exclude: []
  assumptions: []
  confidence: low
  evidence_refs: []

entrypoints:
  api: []
  host_tiling: []
  kernel: []
  golden: []
  tests: []

source_files:
  api: []
  host: []
  tiling: []
  kernel: []
  golden: []
  test: []
  common: []
  excluded: []

io:
  required_inputs: []
  optional_inputs: []
  outputs: []
  attrs: []

shape_ontology:
  dims: {{}}
  derived_dims: {{}}
  layout_rules: {{}}

dtype_layout_constraints:
  dtypes: []
  layouts: []
  constraints: []

feature_flags: []

analysis_plan:
  required_agents: []
  skipped_agents: []
  source_hints:
    tiling: []
    compute_dataflow: []
    kernel_paths: []
  open_questions: []
  review_focus: []
  notes: []
""",
    )

    write_text(
        base / "index.yaml",
        f"""version: 1
op_name: {op_name}
status: draft

scope:
  arch: unknown
  platform: unknown
  path_group: unknown
  excluded: []

canonical_files:
  route: route.md
  operator: operator.yaml
  tiling: tiling/index.yaml
  flow: flow/index.yaml
  kernel: kernel/index.yaml
  test: test/index.yaml
  evidence_source: evidence/source_index.yaml
  evidence_fact: evidence/fact_index.yaml
  artifact_dependencies: evidence/artifact_dependencies.yaml
  issues: evidence/issues.yaml
  quality: quality.yaml
  human_review: human/review.md

qa_routes:
  overview:
    read: [route.md]
  operator_boundary:
    read: [operator.yaml]
  io_optional_dtype_layout:
    read: [operator.yaml, tiling/key_space.yaml, tiling/data_model.yaml]
  tiling:
    read: [tiling/index.yaml]
  tiling_mechanism_variables:
    read: [tiling/variables.yaml]
  tiling_key:
    read: [tiling/key_space.yaml, tiling/families.yaml]
  tiling_key_constraints:
    read: [tiling/constraints.yaml, tiling/key_space.yaml]
  tiling_key_pruning_merging:
    read: [tiling/constraints.yaml, tiling/families.yaml]
  tilingdata:
    read: [tiling/data_model.yaml, tiling/families.yaml]
  compute_flow:
    read: [flow/index.yaml, flow/compute_graph.yaml]
  dataflow:
    read: [flow/index.yaml, flow/dataflow.yaml]
  golden_generation:
    read: [flow/golden_model.yaml, flow/numerical_model.yaml, operator.yaml, tiling/data_model.yaml]
  numerical_accuracy:
    read: [flow/numerical_model.yaml, flow/golden_model.yaml, test/contract.yaml]
  kernel_path:
    read: [kernel/index.yaml, kernel/paths.yaml, tiling/families.yaml, flow/compute_graph.yaml]
  kernel_pipeline:
    read: [kernel/pipeline.yaml, kernel/resources.yaml, flow/dataflow.yaml]
  buffer_sync:
    read: [kernel/resources.yaml, flow/dataflow.yaml]
  test_generation:
    read: [test/index.yaml, test/contract.yaml, tiling/coverage_model.yaml, flow/golden_model.yaml, kernel/paths.yaml]
  evidence:
    read: [evidence/fact_index.yaml, evidence/source_index.yaml]
  issues:
    read: [evidence/issues.yaml, quality.yaml]
  human_review:
    read: [human/review.md, quality.yaml]

export_views:
  tiling-test:
    read:
      - tiling/variables.yaml
      - tiling/key_space.yaml
      - tiling/constraints.yaml
      - tiling/families.yaml
      - tiling/data_model.yaml
      - tiling/coverage_model.yaml
      - quality.yaml
  golden-gen:
    read:
      - operator.yaml
      - tiling/data_model.yaml
      - flow/compute_graph.yaml
      - flow/dataflow.yaml
      - flow/golden_model.yaml
      - flow/numerical_model.yaml
      - evidence/fact_index.yaml
      - quality.yaml
  testgenerate:
    read:
      - operator.yaml
      - tiling/variables.yaml
      - tiling/key_space.yaml
      - tiling/constraints.yaml
      - tiling/families.yaml
      - tiling/data_model.yaml
      - tiling/coverage_model.yaml
      - flow/compute_graph.yaml
      - flow/golden_model.yaml
      - flow/numerical_model.yaml
      - kernel/paths.yaml
      - kernel/pipeline.yaml
      - kernel/resources.yaml
      - test/contract.yaml
      - quality.yaml
      - evidence/issues.yaml
  kernel-debug:
    read:
      - kernel/paths.yaml
      - kernel/pipeline.yaml
      - kernel/resources.yaml
      - flow/compute_graph.yaml
      - flow/dataflow.yaml
      - evidence/fact_index.yaml
  human:
    read:
      - route.md
      - human/review.md
      - quality.yaml
      - evidence/issues.yaml

artifact_dependencies:
  operator.yaml:
    affects:
      - tiling/index.yaml
      - flow/compute_graph.yaml
      - flow/golden_model.yaml
      - test/contract.yaml
  tiling/variables.yaml:
    affects:
      - tiling/key_space.yaml
      - tiling/constraints.yaml
  tiling/key_space.yaml:
    affects:
      - tiling/constraints.yaml
      - kernel/paths.yaml
      - test/contract.yaml
  tiling/constraints.yaml:
    affects:
      - tiling/coverage_model.yaml
      - test/contract.yaml
  tiling/families.yaml:
    affects:
      - kernel/paths.yaml
      - kernel/pipeline.yaml
      - test/contract.yaml
  tiling/data_model.yaml:
    affects:
      - flow/golden_model.yaml
      - kernel/resources.yaml
      - test/contract.yaml
  flow/compute_graph.yaml:
    affects:
      - flow/golden_model.yaml
      - kernel/pipeline.yaml
      - test/contract.yaml
  flow/dataflow.yaml:
    affects:
      - kernel/resources.yaml
      - kernel/pipeline.yaml
      - test/contract.yaml
  flow/golden_model.yaml:
    affects:
      - test/contract.yaml
  kernel/paths.yaml:
    affects:
      - kernel/pipeline.yaml
      - test/contract.yaml
  kernel/resources.yaml:
    affects:
      - test/contract.yaml
""",
    )

    write_text(
        base / "route.md",
        f"""# Operator KB Route: {op_name}

## Status
- boundary: draft
- tiling: draft
- flow: draft
- kernel: draft
- golden model: draft
- test contract: draft
- evidence: draft
- quality: red

## Scope
- arch: unknown
- platform: unknown
- included: unknown
- excluded: unknown

## Fast Task Routes

| Task | Read First | Then Read | Evidence |
|---|---|---|---|
| Understand IO | operator.yaml | tiling/key_space.yaml | evidence/fact_index.yaml |
| Understand tiling mechanism/variables | tiling/variables.yaml | tiling/route.md | tiling/evidence_index.yaml |
| Understand tiling key | tiling/index.yaml | tiling/key_space.yaml | tiling/evidence_index.yaml |
| Key constraints / pruning / merging | tiling/constraints.yaml | tiling/key_space.yaml | tiling/evidence_index.yaml |
| Understand tilingdata | tiling/data_model.yaml | flow/golden_model.yaml | evidence/fact_index.yaml |
| Generate golden later | flow/golden_model.yaml | flow/numerical_model.yaml | evidence/fact_index.yaml |
| Generate accuracy tests later | test/contract.yaml | flow/golden_model.yaml | evidence/issues.yaml |
| Analyze kernel path | kernel/paths.yaml | kernel/pipeline.yaml | evidence/fact_index.yaml |
| Debug buffer/sync | kernel/resources.yaml | flow/dataflow.yaml | evidence/fact_index.yaml |
| Check source evidence | evidence/fact_index.yaml | evidence/source_index.yaml | source code via CBM |

## High-Level Map
operator.yaml -> tiling/* -> flow/* -> kernel/* -> test/contract.yaml

## Hot Risks
- Macro Boundary Agent has not filled evidence yet.

## Notes
- route.md is a map, not a full report.
- Detailed explanations should be generated by uo-query from canonical YAML.
- Do not default-read archive/.
""",
    )

    write_text(
        base / "human" / "review.md",
        """# Human Review

## Boundary Review
- status: pending
- decisions: []
- extra_description:

## Tiling Review
- status: pending
- decisions: []
- risks: []

## Flow / Golden Model Review
- status: pending
- decisions: []
- risks: []
- golden generation blockers: []

## Kernel Alignment Review
- status: pending
- decisions: []
- risks: []

## Test Contract Review
- status: pending
- decisions: []
- risks: []

## Open Questions
""",
    )

    write_text(
        base / "human" / "kernel_dispatch_review.yaml",
        """checkpoint: kernel_dispatch
status: pending
decision: pending
reviewer: null
reviewed_at: null
comments: ""
task_count: 0
dispatchable_task_ids: []
non_dispatchable_task_ids: []
needs_review_task_ids: []
approved_task_ids: []
rejected_task_ids: []
family_coverage_summary:
  total_families: 0
  task_mapped_families: []
  excluded_families: []
  needs_review_families: []
tiling_brief:
  frontier_entries: []
  key_predicates: []
  key_logic_relations:
    variable_count: 0
    relation_type_counts: {}
    input_realization_count: 0
    key_relation_obligation_count: 0
    key_unreachable_count: 0
    tiling_key_pruning: unknown
    tiling_key_merging: unknown
    evidence_gap_stubs: []
  coverage_obligation_summary: []
summary:
  high_priority_tasks: []
  unknown_kernel_entry_tasks: []
  uncovered_families: []
  uncovered_compute_steps: []
""",
    )

    # --- tiling canonical (do not redesign) ---
    for rel, body in {
        "tiling/route.md": """# Tiling Route

## Status
pending

## Scope
unknown

## Tiling Entry
unknown

## Step 1 summary (variable model)
- see variables.yaml

## Step 2 summary (constraint model)
- see constraints.yaml

## Notes
- Family coverage != tiling_key coverage.
- Seed cases / branch samples != full key enumeration.
- Step 1: tiling_mechanism + variables + impact_classification (variables.yaml).
- Step 2: relations / tiling_key_pruning / tiling_key_merging / input_realization (constraints.yaml).
- Key logic for TestGenerate: constraints.relations + input_realization + coverage_model.key_relation_obligations.
- Key-level unreachable (constraints.key_unreachable) != family-level unreachable (families.yaml).
- Machine files: index.yaml, variables.yaml, key_space.yaml, constraints.yaml, families.yaml, data_model.yaml, coverage_model.yaml, evidence_index.yaml
""",
        "tiling/index.yaml": f"""version: 1
op_name: {op_name}
scope:
  arch: unknown
  path_group: unknown
  excluded: []

canonical_files:
  route: route.md
  variables: variables.yaml
  key_space: key_space.yaml
  constraints: constraints.yaml
  families: families.yaml
  data_model: data_model.yaml
  coverage_model: coverage_model.yaml
  evidence: evidence_index.yaml

qa_routes:
  overview:
    read: [route.md]
  entry_or_dispatch:
    read: [route.md, families.yaml]
  tiling_mechanism:
    read: [variables.yaml, route.md]
  tiling_variables:
    read: [variables.yaml]
  tiling_key:
    read: [key_space.yaml, families.yaml]
  key_constraints_relations:
    read: [constraints.yaml, key_space.yaml]
  tiling_key_pruning_merging:
    read: [constraints.yaml, key_space.yaml, families.yaml]
  input_realization:
    read: [constraints.yaml, key_space.yaml]
  optional_input:
    read: [variables.yaml, key_space.yaml, data_model.yaml]
  dtype_layout_shape:
    read: [key_space.yaml, families.yaml]
  tilingdata:
    read: [data_model.yaml, families.yaml]
  coverage:
    read: [coverage_model.yaml, constraints.yaml, key_space.yaml, families.yaml]
  evidence:
    read: [evidence_index.yaml]

testgenerate_contract:
  required_files:
    - variables.yaml
    - key_space.yaml
    - constraints.yaml
    - families.yaml
    - data_model.yaml
    - coverage_model.yaml
  rules:
    - "Do not treat family coverage as full tiling_key coverage."
    - "Do not treat seed_cases as full enumeration."
    - "Use variables.yaml for the variable inventory and impact classification."
    - "Use key_space.yaml as tiling_key encoding truth."
    - "Do not blind-cartesian fields; apply constraints.relations + key_unreachable + pruning first."
    - "Honor tiling_key_pruning (skip pruned combos) and tiling_key_merging (merged combos are one key)."
    - "Use constraints.input_realization to construct inputs for key patterns."
    - "Treat derived_fields / independent:false as computed, not free dimensions."
    - "Use key_relation_obligations.must_cover for relation witnesses, not full key enum."
    - "Use data_model.yaml for varlen and numeric tilingdata coverage."
    - "Use families.yaml for reachability and structural family coverage."
""",
        "tiling/variables.yaml": f"""version: 1
op_name: {op_name}
scope: unknown

# STEP 1 — variable model: how tiling is computed + variables classified by impact scope.
tiling_mechanism:
  entry: {{file: unknown, symbol: unknown, lines: []}}
  key_setter: {{macro: unknown, file: unknown, symbol: unknown, lines: []}}
  produces: []
  flow_summary: ""
  registry_dispatch: []

variables: {{}}
# Vxxx: {{name, meaning, raw_domain, domain_source, kind, impact_scope: [],
#        influences: [], enters_tiling_key, maps_to, source, evidence_refs}}

impact_classification:
  tiling_key: []
  template_compile_time: []
  family_structural: []
  tilingdata_numeric: []
  core_split: []
  buffer_workspace: []
  optional_io_gate: []
  derived: []
  constant: []
  unknown: []

unresolved_variables: []
""",
        "tiling/key_space.yaml": f"""version: 1
op_name: {op_name}
scope: unknown

# tiling_key ENCODING truth only. Constraints / pruning / input construction -> constraints.yaml
encoding:
  macro: unknown
  source:
    file: unknown
    lines: []
  fields_order: []

fields: {{}}
# name: {{domain, domain_source, independent, affects, kind, set_when, variable_ref, source}}

constants: {{}}

derived_fields: {{}}
# name: {{from, rule, rule_kind, enters_key_bit, affects, variable_ref, source}}
""",
        "tiling/constraints.yaml": f"""version: 1
op_name: {op_name}
scope: unknown

# STEP 2 — constraint model: value/range/relation constraints + tiling_key pruning + merging.
variable_constraints: []
# - {{id, variable, legal_values, boundary_values, independent, reason, evidence_refs}}

relations: []
# - {{id, type (mutex|implies|requires|compatible_set|compile_time_fixed|runtime_guard|other),
#     variables, expr, when, reason, case_impact, evidence_refs}}

tiling_key_pruning:      # 剪枝: combos the code makes impossible / folds away
  performed: unknown     # true | false | unknown  (must be answered)
  pruned_combinations: []
  # - {{id, pattern, reason, proof_kind, evidence_refs}}
  notes: ""

tiling_key_merging:      # 合并: distinct variable combos sharing one key / family
  performed: unknown     # true | false | unknown  (must be answered)
  merged_groups: []
  # - {{id, merged_into, source_combinations, reason, differs_in, evidence_refs}}
  notes: ""

input_realization: {{}}
# IR ids -> matches.key_pattern / inputs / shape_intent / dtype_layout_intent

key_unreachable: []
# - {{id, level: key, constraint, reason, proof_kind, evidence_refs}}
""",
        "tiling/families.yaml": f"""version: 1
op_name: {op_name}
scope: unknown

dispatch_tree:
  entry: unknown
  top_level: []

families: {{}}
""",
        "tiling/data_model.yaml": f"""version: 1
op_name: {op_name}
scope: unknown

structs:
  EmptyTensor: {{}}
  RegbaseTemplate: {{}}

family_to_struct: {{}}

numeric_overlay: {{}}
""",
        "tiling/coverage_model.yaml": f"""version: 1
op_name: {op_name}
scope: unknown

coverage_policy:
  family_coverage: required
  key_field_value_coverage: required
  key_relation_coverage: required
  tilingdata_coverage: required
  unreachable_proof: required
  observed_key_audit: required
  input_realization_coverage: required

family_obligations: []

key_field_obligations: {{}}

key_relation_obligations: []
# Each: id / name / relation_type / fields / must_cover /
#   linked_relations / linked_input_realization / min_cases / reason

tilingdata_obligations: []

seed_cases: []

audit_requirements:
  expected_key_required: true
  observed_key_required: true
  mismatch_is_failure: true
  report_missing_field_values: true
  report_missing_relations: true
  report_missing_input_realization: true
  report_illegal_cartesian_without_constraints: true
""",
        "tiling/evidence_index.yaml": f"""version: 1
op_name: {op_name}

symbols: {{}}

evidence_policy:
  default_read: false
  use_when:
    - "user asks for source evidence"
    - "user asks exact source line"
    - "quality gate detects conflict"
    - "TestGenerate requires traceability report"
""",
    }.items():
        write_text(base / rel, body)

    # --- tiling/archive REQUIRED intermediates (must be filled before barrier) ---
    for rel, body in {
        "tiling/archive/frontier.yaml": f"""version: 1
op_name: {op_name}
status: pending
# REQUIRED intermediate: locate every host tiling decision site before merging
# into key_space / families. Empty frontier_nodes => host_flow barrier fail.

frontier_nodes: []
# Each node:
#   id: FR001
#   role: guard | key_setter | tilingdata_writer | compile_time_binding | optional_io_gate | kernel_hint | template_inst | other
#   symbol: ""
#   file: ""
#   lines: []
#   affects: [key, family, tilingdata, template, kernel_hint]
#   notes: ""
#   evidence_refs: []

unresolved_frontier: []
#   - {{id, symbol_or_pattern, why_unresolved, impact}}
""",
        "tiling/archive/dispatch_variables.yaml": f"""version: 1
op_name: {op_name}
status: pending
# REQUIRED intermediate: classify every dispatch / shape / dtype / deter variable
# before writing key_space.fields / constants / derived_fields.

variables: []
# Each:
#   name: ""
#   kind: hard_dispatch | optional_io_gate | performance_knob | derived | constant | tiling_data_value | unknown
#   domain: []
#   domain_source: enum_macro | constexpr | runtime_branch | derived | unknown
#   set_when: ""
#   enters_tiling_key: true | false
#   affects: [key, struct, tilingdata, kernel_template]
#   source: {{file, lines, symbol}}
#   maps_to_key_space: ""   # field / constant / derived_fields name after merge

unknown_variables: []
""",
        "tiling/archive/predicate_space.yaml": f"""version: 1
op_name: {op_name}
status: pending
# REQUIRED intermediate: normalize host conditions into stable predicates + relations
# (mutex / implies / compile_time_fixed) before constraints.relations merge.

predicate_atoms: []
# Each:
#   id: P001
#   expr: ""
#   kind: runtime_guard | compile_time | optional_io | dtype_layout | shape | deter | other
#   source: {{file, lines, symbol}}
#   related_fields: []

predicate_relations: []
# Each:
#   id: PR001
#   type: mutex | implies | requires | compatible_set | compile_time_fixed | runtime_guard | other
#   atoms: []
#   expr: ""
#   case_impact: exclude | force_combo | narrow_domain
#   maps_to_legal_constraint: ""   # LC id after merge into key_space
#   evidence_refs: []
""",
        "tiling/archive/compile_time_bindings.yaml": f"""version: 1
op_name: {op_name}
status: pending
# REQUIRED intermediate: macros / constexpr / templates / if constexpr reachability.
# This is the anti-laziness file for FASG-like ops (DeterType, arch switches, etc.).

macros: []
# Each:
#   name: ""
#   value: "" | unknown
#   kind: define | enum | feature_flag | arch_switch | dtype_switch | other
#   expands_to: ""
#   affects_branches: []
#   source: {{file, lines}}
#   evidence_refs: []

constexpr_constants: []
# Each:
#   name: ""
#   value: "" | unknown
#   type: ""
#   affects: [key, family, template, tilingdata]
#   source: {{file, lines, symbol}}

templates:
  instantiations: []
  # Each:
  #   id: TI001
  #   template_name: ""
  #   args: {{}}
  #   call_site: {{file, lines, symbol}}
  #   specialization: primary | partial | full | unknown
  #   selected_when: ""
  #   maps_to_families: []

if_constexpr_sites: []
# Each:
#   id: IC001
#   condition: ""
#   reachability: taken | not_taken | runtime_conditional | unknown
#   proof_kind: compile_time_fold | template_arg | macro | evidence_gap
#   folds_to_family: "" | null
#   source: {{file, lines, symbol}}
#   evidence_refs: []

unresolved_symbols: []
blocking_questions: []
""",
        "tiling/archive/decision_tree.md": f"""# Tiling Decision Tree

op_name: {op_name}
status: pending

## How to read
- Mark each node as **compile-time** (macro / constexpr / template) or **runtime**.
- Leaves must point to `family_id` (TFxxx) and optional `seed_case` id.
- Unreachable subtrees stay in the tree with `not_taken` + proof.

## Entry
unknown

## Tree
```
(unknown — host extraction must replace this skeleton)
```

## Compile-time nodes
- none yet

## Runtime nodes
- none yet

## Unreachable / folded subtrees
- none yet

## Unknown nodes (must not be empty-silent if macros unresolved)
- pending host extraction
""",
    }.items():
        write_text(base / rel, body)

    # --- flow ---
    write_text(
        base / "flow" / "index.yaml",
        f"""version: 1
op_name: {op_name}

canonical_files:
  compute_graph: compute_graph.yaml
  dataflow: dataflow.yaml
  golden_model: golden_model.yaml
  numerical_model: numerical_model.yaml

qa_routes:
  compute_overview:
    read: [compute_graph.yaml]
  formula:
    read: [compute_graph.yaml, golden_model.yaml]
  data_movement:
    read: [dataflow.yaml]
  golden_generation:
    read: [golden_model.yaml, numerical_model.yaml, compute_graph.yaml]
  accuracy:
    read: [numerical_model.yaml, golden_model.yaml]
  evidence:
    read: [../evidence/fact_index.yaml, ../evidence/source_index.yaml]
""",
    )
    write_text(
        base / "flow" / "compute_graph.yaml",
        f"""version: 1
op_name: {op_name}

compute_steps: {{}}

compute_edges: []

outputs: []
""",
    )
    write_text(
        base / "flow" / "dataflow.yaml",
        f"""version: 1
op_name: {op_name}

dataflow_edges: {{}}

tensor_lifecycle: []

dataflow_risks: []
""",
    )
    write_text(
        base / "flow" / "golden_model.yaml",
        f"""version: 1
op_name: {op_name}

purpose: "golden generation model only; no generated golden code"

golden_inputs: []

golden_outputs: []

golden_steps: {{}}

golden_variants: []

golden_generation_contract:
  can_generate_reference: needs_review
  required_external_inputs: []
  unsupported_cases: []
  must_match_outputs: []
  known_differences_from_kernel: []
  review_required_for: []
""",
    )
    write_text(
        base / "flow" / "numerical_model.yaml",
        f"""version: 1
op_name: {op_name}

dtype_policy: []

cast_points: []

numerical_sensitive_steps: []

tolerance_policy:
  default: {{}}
  by_dtype: {{}}
  by_output: {{}}
  by_variant: {{}}

randomness_policy:
  dropout:
    deterministic_seed_required: unknown
    mask_input_behavior: ""
    evidence_refs: []
""",
    )

    # --- kernel ---
    write_text(
        base / "kernel" / "index.yaml",
        f"""version: 1
op_name: {op_name}

canonical_files:
  paths: paths.yaml
  pipeline: pipeline.yaml
  resources: resources.yaml

qa_routes:
  path_mapping:
    read: [paths.yaml]
  compute_alignment:
    read: [pipeline.yaml, ../flow/compute_graph.yaml]
  buffer_sync:
    read: [resources.yaml, pipeline.yaml, ../flow/dataflow.yaml]
  evidence:
    read: [../evidence/fact_index.yaml, ../evidence/source_index.yaml]
""",
    )
    write_text(
        base / "kernel" / "paths.yaml",
        f"""version: 1
op_name: {op_name}
status: pending

kernel_paths: {{}}

excluded_families: []

needs_review: []

task_generation_summary:
  source_family_count: 0
  normal_task_count: 0
  needs_review_count: 0
  excluded_count: 0
  merge_count: 0
  split_count: 0
""",
    )
    write_text(
        base / "kernel" / "pipeline.yaml",
        f"""version: 1
op_name: {op_name}

pipelines: {{}}

compute_step_alignment: []

pipeline_risks: []
""",
    )
    write_text(
        base / "kernel" / "resources.yaml",
        f"""version: 1
op_name: {op_name}

buffers: {{}}

workspaces: {{}}

sync_events: {{}}

resource_risks: []
""",
    )

    # --- test ---
    write_text(
        base / "test" / "index.yaml",
        f"""version: 1
op_name: {op_name}

canonical_files:
  contract: contract.yaml

qa_routes:
  coverage:
    read: [contract.yaml, ../tiling/coverage_model.yaml]
  golden:
    read: [contract.yaml, ../flow/golden_model.yaml, ../flow/numerical_model.yaml]
  performance:
    read: [contract.yaml, ../kernel/resources.yaml, ../kernel/pipeline.yaml]
  evidence:
    read: [../evidence/fact_index.yaml, ../evidence/issues.yaml]
""",
    )
    write_text(
        base / "test" / "contract.yaml",
        f"""version: 1
op_name: {op_name}

purpose: "coverage obligations and generation hints only; no generated tests"

inputs:
  operator: ../operator.yaml
  tiling_variables: ../tiling/variables.yaml
  tiling_key_space: ../tiling/key_space.yaml
  tiling_constraints: ../tiling/constraints.yaml
  tiling_families: ../tiling/families.yaml
  tiling_data_model: ../tiling/data_model.yaml
  tiling_coverage_model: ../tiling/coverage_model.yaml
  compute_graph: ../flow/compute_graph.yaml
  dataflow: ../flow/dataflow.yaml
  golden_model: ../flow/golden_model.yaml
  numerical_model: ../flow/numerical_model.yaml
  kernel_paths: ../kernel/paths.yaml
  kernel_pipeline: ../kernel/pipeline.yaml
  kernel_resources: ../kernel/resources.yaml

coverage_obligations:
  family_coverage:
    source: ../tiling/families.yaml
    required: true
  tiling_key_field_value_coverage:
    source: ../tiling/key_space.yaml
    required: true
  tiling_key_relation_coverage:
    source: ../tiling/coverage_model.yaml
    required: true
    notes: "Use key_relation_obligations.must_cover + constraints.relations; not seed_cases."
  tiling_key_pruning_merging:
    source: ../tiling/constraints.yaml
    required: true
    notes: "Skip tiling_key_pruning combos; treat tiling_key_merging groups as one key."
  tiling_key_input_realization:
    source: ../tiling/constraints.yaml
    required: true
    notes: "Map key_pattern / relation combos to operator.yaml IO via input_realization."
  tilingdata_numeric_coverage:
    source: ../tiling/data_model.yaml
    required: true
  compute_step_coverage:
    source: ../flow/compute_graph.yaml
    required: true
  golden_variant_coverage:
    source: ../flow/golden_model.yaml
    required: true
  numerical_sensitive_coverage:
    source: ../flow/numerical_model.yaml
    required: true
  kernel_path_coverage:
    source: ../kernel/paths.yaml
    required: true
  resource_sync_risk_coverage:
    source: ../kernel/resources.yaml
    required: true

generation_order:
  - "Read tiling/variables.yaml for the variable inventory + impact classification."
  - "Read tiling/key_space.yaml fields + derived_fields (skip independent:false / derived as free dims)."
  - "Apply constraints.relations + key_unreachable + tiling_key_pruning before any cartesian product."
  - "Collapse tiling_key_merging groups to a single key (differ only in overlay)."
  - "Select must_cover combos from coverage_model.key_relation_obligations."
  - "Build inputs from constraints.input_realization (required/optional_present/absent + shape/dtype intent)."
  - "Attach family reachability from families.yaml; numeric overlays from data_model.yaml."
  - "Never treat family count or seed_cases as full tiling_key coverage."

oracle_contract:
  golden_model: ../flow/golden_model.yaml
  numerical_model: ../flow/numerical_model.yaml
  golden_required_steps: []
  tolerance_policy: {{}}
  numerical_risks: []

accuracy_generation_hints: []
performance_generation_hints: []

audit_requirements:
  expected_tiling_key_required: true
  observed_tiling_key_required: true
  mismatch_is_failure: true
  report_missing_key_field_values: true
  report_missing_key_relations: true
  report_missing_input_realization: true
  report_illegal_cartesian_without_constraints: true
  report_missing_kernel_paths: true
  report_missing_compute_steps: true
  report_missing_golden_variants: true
  report_uncovered_resource_risks: true

forbidden_fields:
  - generated_cases
  - actual_test_result
  - observed_coverage
  - case_csv
""",
    )

    # --- evidence ---
    write_text(
        base / "evidence" / "source_index.yaml",
        f"""version: 1
op_name: {op_name}

source_spans: {{}}

symbols: {{}}
""",
    )
    write_text(
        base / "evidence" / "fact_index.yaml",
        f"""version: 1
op_name: {op_name}

facts: {{}}

evidence_refs: {{}}
""",
    )
    write_text(
        base / "evidence" / "artifact_dependencies.yaml",
        f"""version: 1
op_name: {op_name}

dependencies: []

artifact_to_source:
  operator.yaml: []
  tiling/variables.yaml: []
  tiling/key_space.yaml: []
  tiling/constraints.yaml: []
  flow/compute_graph.yaml: []
  flow/golden_model.yaml: []
  kernel/paths.yaml: []
  kernel/pipeline.yaml: []
  kernel/resources.yaml: []
  test/contract.yaml: []
""",
    )
    write_text(
        base / "evidence" / "issues.yaml",
        f"""version: 1
op_name: {op_name}

missing: []
conflicts: []
warnings: []
unknowns: []

issue_schema:
  id: ""
  severity: high | medium | low
  artifact: ""
  target: ""
  description: ""
  affects:
    - uo_query
    - golden_generation
    - testgenerate
    - kernel_path
    - oracle
  suggested_action: ""
  evidence_refs: []
""",
    )

    write_text(
        base / "quality.yaml",
        f"""version: 1
op_name: {op_name}

status: red

scores:
  boundary_confidence: 0.0
  tiling_confidence: 0.0
  compute_confidence: 0.0
  dataflow_confidence: 0.0
  golden_model_confidence: 0.0
  kernel_confidence: 0.0
  evidence_confidence: 0.0
  test_contract_confidence: 0.0

checks:
  yaml_parse: fail
  canonical_files_present: fail
  route_integrity: fail
  domain_index_integrity: fail
  evidence_refs_resolve: fail
  source_locators_present_for_key_facts: fail
  artifact_dependencies_present: fail
  no_legacy_required_outputs: pass
  no_generated_tests_in_uo: pass
  no_generated_golden_code_in_uo: pass
  family_not_equal_key_coverage_rule: pass
  branch_matrix_not_full_enum_rule: pass
  tiling_variables_present: fail
  key_relations_present: fail
  input_realization_present: fail
  tiling_key_pruning_documented: fail
  tiling_key_merging_documented: fail
  key_relation_obligations_executable: fail
  key_vs_family_unreachable_separated: pass
  golden_model_has_compute_mapping: fail
  kernel_pipeline_has_compute_alignment: fail
  resources_have_producer_consumer: fail

blockers:
  - Macro Boundary Agent has not produced evidence-backed operator.yaml yet.
warnings: []
decision: not_usable
""",
    )

    write_text(
        base / "archive" / "runs" / "workflow_progress.yaml",
        f"""op_name: {op_name}
updated_at: null
current_phase: uo-p0
language: zh-CN
notes: 工作流尚未开始。
todos:
  - id: uo-p0
    title: 阶段 0 — 预检布局与 MCP 自动索引
    status: pending
  - id: uo-p05
    title: 阶段 0.5 — 宏观执行范围人工审阅（闸门）
    status: pending
  - id: uo-p1
    title: 阶段 1 — 宏观边界分析
    status: pending
  - id: uo-p2a
    title: 阶段 2a — 并行下发 host 与 flow 子代理
    status: pending
  - id: uo-p2b
    title: 阶段 2b — 屏障校验并读取 tiling/flow
    status: pending
  - id: uo-p3
    title: 阶段 3 — Kernel 任务规划
    status: pending
  - id: uo-p35
    title: 阶段 3.5 — Kernel 分发人工审阅（闸门，含全量 tiling/family）
    status: pending
  - id: uo-p4a
    title: 阶段 4a — 并行下发 kernel path 子代理
    status: pending
  - id: uo-p4b
    title: 阶段 4b — 屏障校验并读取 kernel paths
    status: pending
  - id: uo-p5
    title: 阶段 5 — Kernel 对齐矩阵
    status: pending
  - id: uo-p6
    title: 阶段 6 — 证据一致性审计
    status: pending
  - id: uo-p7
    title: 阶段 7 — 路由与知识库地图
    status: pending
  - id: uo-p8
    title: 阶段 8 — 质量门禁
    status: pending
""",
    )

    write_json(
        base / "archive" / "runs" / "run_manifest.json",
        {
            "op_name": op_name,
            "repo_path": str(repo_root),
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "artifact_root": str(base),
            "kb_layout": "canonical_v1",
        },
    )
