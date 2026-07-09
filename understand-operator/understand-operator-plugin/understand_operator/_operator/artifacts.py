from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ARTIFACT_DIR = ".understand-operator"


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
        "cbm",
        "summary",
        "tiling",
        "flows",
        "kernel/paths",
        "evidence",
        "testing_hints",
    ]:
        (base / rel).mkdir(parents=True, exist_ok=True)

    write_text(
        base / "summary" / "operator_manifest.yaml",
        f"""op_name: {op_name}
repo_path: "{repo_root.as_posix()}"
operator_type: AscendC
entry:
  host_entry: unknown
  tiling_entry: unknown
  kernel_entry: unknown
source_files:
  host: []
  tiling: []
  kernel: []
  golden: []
  test: []
  shared_util: []
confidence: low
""",
    )
    write_text(
        base / "summary" / "operator_io.yaml",
        """operator_io:
  required_inputs: []
  optional_inputs: []
  outputs: []
  attributes: []
  constraints:
    dtype_constraints: []
    shape_constraints: []
    layout_constraints: []
""",
    )
    write_text(
        base / "summary" / "operator_boundary.md",
        f"""# Operator Boundary

## Operator
{op_name}

## Required Inputs
unknown

## Optional Inputs
unknown

## Outputs
unknown

## Host Files
unknown

## Tiling Files
unknown

## Kernel Files
unknown

## Golden Files
unknown

## Test Files
unknown

## Shared Utils
unknown

## Uncertain Files
unknown
""",
    )
    write_text(
        base / "summary" / "analysis_plan.yaml",
        """source_hints:
  tiling: []
  compute_dataflow: []
  kernel_paths: []
cbm_on_demand:
  read: prompts/00_cbm_on_demand.md
  cli: cbm_query.py
  journal: cbm/query_journal.jsonl
open_questions: []
""",
    )
    write_text(
        base / "summary" / "ontology.yaml",
        """canonical_terms:
  shape_dims:
    B: batch size
    S1: query sequence length
    S2: key/value sequence length
    Nq: query head count
    Nkv: key/value head count
    D: head dimension
  input_kinds:
    - required_input
    - optional_input
    - attribute
    - output
  feature_flags:
    - has_mask
    - has_rope
    - has_alibi
    - has_kvcache
    - sparse_mode
  compute_step_types:
    - matmul
    - scale
    - mask
    - softmax
    - reduce
    - cast
    - copy
    - fixpipe
    - load
    - store
  memory_levels:
    - GM
    - L1
    - L0A
    - L0B
    - L0C
    - UB
  path_status:
    - implemented
    - skipped_by_condition
    - fused
    - unknown
id_policy:
  rule: sort by stable_key before assigning display ids
  examples:
    input: IN001
    optional_input: OPT001
    output: OUT001
    branch: B001
    compute_step: C001
    dataflow_edge: D001
    kernel_path: K001
    buffer: BUF001
    sync_event: S001
""",
    )
    for rel, body in {
        "tiling/tiling_frontier.yaml": "version: 1\nstatus: pending\nfrontier_nodes: []\nunresolved_frontier: []\n",
        "tiling/dispatch_variables.yaml": "version: 1\nstatus: pending\nvariables: []\nunknown_variables: []\n",
        "tiling/tiling_predicate_space.yaml": "version: 1\nstatus: pending\npredicate_atoms: []\npredicate_relations: []\n",
        "tiling/tiling_branch_families.yaml": "version: 1\nstatus: pending\nfamilies: []\nexcluded_families: []\nblocking_questions: []\n",
        "tiling/tiling_route.yaml": "version: 1\nstatus: pending\nroutes: []\nrouting_summary:\n  normal_count: 0\n  needs_review_count: 0\n  excluded_count: 0\n  unknown_count: 0\n",
        "tiling/tiling_key.yaml": "version: 1\nstatus: pending\ntiling_keys: []\nunresolved_symbols: []\n",
        "tiling/tiling_data_signature.yaml": "version: 1\nstatus: pending\nsignatures: []\nunresolved_symbols: []\n",
        "tiling/tiling_data_map.yaml": "version: 1\nstatus: pending\ntiling_data_fields: []\nwriter_reader_alignment: []\n",
        "tiling/branch_matrix.yaml": "version: 1\nstatus: pending\nbranches: []\nunresolved_symbols: []\nblocking_questions: []\n",
        "tiling/tiling_decision_tree.md": "# Tiling Decision Tree\n\nunknown\n",
        "flows/compute_flow.yaml": "compute_steps: []\nrisks: []\n",
        "flows/compute_flow.md": "# Compute Flow\n\nunknown\n",
        "flows/dataflow.yaml": "dataflow_edges: []\nbuffers: []\nsync_events: []\n",
        "flows/dataflow.md": "# Dataflow\n\nunknown\n",
        "kernel/kernel_task_plan.yaml": "version: 1\nstatus: pending\nkernel_tasks: []\nexcluded_families: []\nneeds_review_families: []\ntask_generation_summary:\n  source_family_count: 0\n  normal_task_count: 0\n  needs_review_count: 0\n  excluded_count: 0\n  merge_count: 0\n  split_count: 0\n",
        "kernel/kernel_path_matrix.yaml": "kernel_paths: []\nbranch_alignment: []\nmissing_kernel_paths: []\n",
        "kernel/sync_buffer_map.yaml": "buffers: []\nsync_events: []\nrisks: []\n",
        "evidence/evidence_check.yaml": "status: warning\nchecks: []\n",
        "evidence/consistency_report.md": "# Consistency Report\n\nNot audited yet.\n",
        "evidence/missing_items.yaml": "missing_items: []\n",
        "evidence/conflict_items.yaml": "conflict_items: []\n",
        "evidence/confidence_report.yaml": "overall_confidence: low\nitems: []\n",
        "testing_hints/golden_hint.yaml": "golden_hints: []\n",
        "testing_hints/accuracy_case_hint.yaml": "accuracy_case_hints: []\n",
        "testing_hints/performance_case_hint.yaml": "performance_case_hints: []\n",
        "testing_hints/coverage_hint.yaml": "coverage_hints: []\n",
        "summary/overview.md": "# Operator Overview\n\nunknown\n",
        "summary/workflow_progress.yaml": """op_name: unknown
updated_at: null
current_phase: uo-p0
notes: Workflow not started.
todos:
  - id: uo-p0
    status: pending
  - id: uo-p1
    status: pending
  - id: uo-p15
    status: pending
  - id: uo-p2a
    status: pending
  - id: uo-p2b
    status: pending
  - id: uo-p3
    status: pending
  - id: uo-p35
    status: pending
  - id: uo-p4a
    status: pending
  - id: uo-p4b
    status: pending
  - id: uo-p5
    status: pending
  - id: uo-p6
    status: pending
  - id: uo-p7
    status: pending
  - id: uo-p8
    status: pending
""",
        "summary/boundary_review.yaml": """checkpoint: boundary
status: pending
decision: pending
reviewer: null
reviewed_at: null
comments: ""
summary:
  required_input_count: 0
  optional_input_count: 0
  output_count: 0
  open_question_count: 0
  low_confidence_items: []
  blocking_issues: []
""",
        "kernel/kernel_dispatch_review.yaml": """checkpoint: kernel_dispatch
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
summary:
  high_priority_tasks: []
  unknown_kernel_entry_tasks: []
  uncovered_families: []
  uncovered_compute_steps: []
""",
    }.items():
        write_text(base / rel, body)

    write_json(
        base / "route.json",
        {
            "op_name": op_name,
            "status": {
                "boundary": "warning",
                "io": "warning",
                "tiling_branch_families": "warning",
                "tiling_route": "warning",
                "kernel_alignment": "warning",
                "golden_consistency": "warning",
            },
            "routes": {
                "io": "summary/operator_io.yaml",
                "boundary": "summary/operator_boundary.md",
                "tiling": "tiling/tiling_branch_families.yaml",
                "tiling_frontier": "tiling/tiling_frontier.yaml",
                "dispatch_variables": "tiling/dispatch_variables.yaml",
                "tiling_predicate_space": "tiling/tiling_predicate_space.yaml",
                "tiling_branch_families": "tiling/tiling_branch_families.yaml",
                "tiling_route": "tiling/tiling_route.yaml",
                "branch_matrix": "tiling/branch_matrix.yaml",
                "kernel": "kernel/kernel_path_matrix.yaml",
                "quality": "quality_gate.yaml",
            },
        },
    )
    write_text(
        base / "route.md",
        f"""# Operator Route: {op_name}

## Status
- boundary: warning
- io: warning
- tiling branch families: warning
- tiling route: warning
- kernel alignment: warning
- golden consistency: warning

## Operator IO Summary
| Kind | Name | Required | Shape | DType | Notes |
|---|---|---|---|---|---|
| unknown | unknown | unknown | unknown | unknown | Fill from summary/operator_io.yaml |

## Fast Task Routes
| Task | Read First | Then Read |
|---|---|---|
| Understand IO | summary/operator_io.yaml | summary/operator_boundary.md |
| Debug tiling | tiling/tiling_branch_families.yaml | tiling/tiling_route.yaml, tiling/branch_matrix.yaml, tiling/tiling_predicate_space.yaml, tiling/dispatch_variables.yaml |
| Debug kernel task | kernel/kernel_task_plan.yaml | kernel/paths/Kxxx_kernel_path.yaml, kernel/kernel_path_matrix.yaml |
| Debug kernel path | kernel/paths/Kxxx_kernel_path.yaml | kernel/kernel_path_matrix.yaml |
| Generate golden plan | flows/compute_flow.yaml | testing_hints/golden_hint.yaml |
| Generate accuracy tests | tiling/tiling_branch_families.yaml | tiling/branch_matrix.yaml, testing_hints/accuracy_case_hint.yaml |
| Generate performance tests | kernel/kernel_path_matrix.yaml | testing_hints/performance_case_hint.yaml |
| Debug sync | kernel/sync_buffer_map.yaml | kernel/paths/Kxxx_kernel_path.yaml |

## Tiling Route Notes
- `branch_matrix.yaml` is a representative sample table, not a full tiling_key enumeration.
- Judge kernel task granularity from `tiling/tiling_branch_families.yaml` and `kernel/kernel_task_plan.yaml`.
- `kernel/kernel_task_plan.yaml` traceability and downstream_preparation prepare later impact analysis; they do not mean tests were generated.

## Family -> Tiling -> Kernel Map
unknown

## Hot Risks
- Macro Boundary Agent has not filled evidence yet.

## Suggested Next Read
- summary/operator_manifest.yaml
- summary/operator_io.yaml
- cbm/cbm_query_log.md
""",
    )
    write_text(
        base / "quality_gate.yaml",
        """io_confidence: low
boundary_confidence: low
tiling_family_confidence: low
tiling_route_confidence: low
dispatch_variable_confidence: low
predicate_space_confidence: low
branch_matrix_materialization_status: warning
compute_flow_confidence: low
kernel_alignment_confidence: low
evidence_consistency_status: warning
unknown_ratio: 1.0
decision: red
blockers:
  - Macro Boundary Agent has not produced evidence-backed IO yet.
warnings: []
next_actions:
  - Run Macro Boundary Agent.
  - Run Tiling Extraction Agent and Compute/Dataflow Agent in parallel.
""",
    )
    write_json(
        base / "summary" / "run_manifest.json",
        {
            "op_name": op_name,
            "repo_path": str(repo_root),
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "artifact_root": str(base),
        },
    )
