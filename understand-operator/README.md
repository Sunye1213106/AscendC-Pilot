# Understand Operator

`understand-operator` is a local plugin for building an evidence-backed knowledge base for AscendC operators. It uses `codebase-memory-mcp` (CBM) as the code intelligence backend and lets the host coding agent perform the semantic analysis through staged prompts.

The plugin does not implement its own AST parser, call graph, reference graph, or symbol graph.

## What It Builds

For each operator, artifacts are written to:

```text
<repo>/.understand-operator/<op_name>/
  route.md
  route.json
  quality_gate.yaml
  cbm/
  summary/
  tiling/
  flows/
  kernel/
  evidence/
  testing_hints/
```

The output is designed to support later accuracy-test and performance-test design. It does not generate real tests.

## Workflow

```text
Preflight full/incremental + ignore rules
  -> CBM index/query cache
  -> Macro Boundary Agent
  -> Boundary Human Review (user approval required)
  -> Parallel:
       Tiling Extraction Agent
       Compute/Dataflow Agent
  -> Kernel Path Task Builder
  -> Kernel Dispatch Human Review (user approval required)
  -> Parallel Kernel Path Agents (approved tasks only)
  -> Kernel Alignment Builder
  -> Evidence Consistency Agent
  -> Operator KB / Route Builder
  -> Quality Gate
```

Two mandatory human review gates pause the workflow until the user explicitly approves:

- After Macro Boundary Agent: review IO, file boundaries, and open questions in `summary/boundary_review.yaml`.
- Before Kernel Path dispatch: review `kernel/kernel_task_plan.yaml` and approve tasks in `kernel/kernel_dispatch_review.yaml`.

## Quick Start - Cursor

1. Open Cursor Settings > Plugins > Add local plugin.
2. Select this repository root: `D:\PR-review\understand-operator`.
3. Optional: install skill + subagents into your user directory:

```powershell
./install.ps1 cursor
```

This links the skill to `~/.cursor/skills/understand-operator` and subagents to `~/.cursor/agents/uo-*.md`.

4. Invoke `/understand-operator` in **Agent mode**.

Analysis phases use Cursor **subagents only at two parallel points**:

- **Parallel point 1:** `uo-host-extraction` + `uo-flow-extraction` (host-side tiling/branch info + compute/dataflow)
- **Parallel point 2:** multiple `uo-kernel-path` (one per approved kernel task)

All other phases run in the host agent. You should see subagent windows only at those two parallel points.

Example request:

```text
/understand-operator D:\path\to\ascendc-repo --op-name FlashAttentionScore --full
```

## Quick Start - OpenCode / Codex

```powershell
./install.ps1 opencode
```

Then invoke the `understand-operator` skill from your agent.

## Manual Commands

Prepare artifact layout and CBM query cache:

```powershell
python understand-operator-plugin/skills/understand-operator/prepare_operator.py D:\path\to\repo --op-name MyOp --full
```

Run the lightweight quality gate after the agent has generated artifacts:

```powershell
python understand-operator-plugin/skills/understand-operator/quality_gate.py D:\path\to\repo --op-name MyOp
```

Editable package entry points are also available:

```powershell
uo-prepare D:\path\to\repo --op-name MyOp --full
uo-quality D:\path\to\repo --op-name MyOp
```

## CBM

Phase 0 only indexes the repo and writes `cbm/index_meta.json`. Semantic lookups use on-demand queries:

```powershell
# PowerShell: use shorthand flags (no JSON quoting)
python understand-operator-plugin/skills/understand-operator/cbm_query.py D:\path\to\repo search_graph --op-name MyOp --name-pattern ".*MyOpTiling.*" --label Function --phase phase1

# Complex payload: write JSON file, then --payload-file
uo-cbm D:\path\to\repo get_code_snippet --op-name MyOp --file op_host/foo.cpp --symbol MyOpTiling
```

- Full JSON result prints to **stdout** (agent reads from command output).
- Audit trail appends one line per query to `cbm/query_journal.jsonl` (summary only, not full body).
- Use `--save` to optionally write `cbm/NNNN_<tool>.json`.
- Legacy bulk prefetch: `prepare_operator.py --prefetch-queries`.

The plugin expects `codebase-memory-mcp` through:

- `UNDERSTAND_OPERATOR_CBM_BIN`
- `[scanner].cbm_binary` in `.understand.toml`
- `thirdparty/codebase-memory-mcp.exe`
- `PATH`

The workflow uses CBM tools such as:

- `index_repository`
- `list_projects`
- `index_status`
- `search_graph`
- `trace_path` or CBM's compatible `trace_call_path`
- `query_graph`
- `get_graph_schema`
- `get_code_snippet`
- `get_architecture`
- `search_code`
- `detect_changes`

Every query is logged in:

```text
.understand-operator/<op_name>/cbm/query_journal.jsonl
```

Phase 0 index steps are summarized in `cbm/cbm_query_log.md`.

## Core Artifacts

`summary/operator_io.yaml` records required inputs, optional inputs, outputs, attributes, and constraints.

`summary/operator_boundary.md` records file boundaries and module responsibilities.

`tiling/tiling_frontier.yaml`, `tiling/dispatch_variables.yaml`, and `tiling/tiling_predicate_space.yaml` record tiling code frontier nodes, dispatch variable categories, and normalized predicate atoms.

`tiling/tiling_branch_families.yaml` is the primary tiling dispatch artifact. It groups equivalent tiling paths by dispatch predicates, structural tiling signature, reachability, template context, numeric variants, and representative cases.

`tiling/tiling_route.yaml` tells the task builder which families become normal kernel tasks, which need review, and which are excluded.

`tiling/branch_matrix.yaml` is only a representative sample table for branch families. It is not a full tiling key enumeration.

`flows/compute_flow.yaml` and `flows/dataflow.yaml` record compute semantics and data movement.

`kernel/kernel_task_plan.yaml` defines family-oriented kernel tasks, normally one task per `tiling_branch_family`.

`kernel/paths/Kxxx_kernel_path.yaml` aligns a concrete kernel path with IO, source family, representative case, tiling data, and compute steps.

`route.md` is an index map only. Detailed analysis belongs in the relevant artifacts.

`quality_gate.yaml` decides whether the KB is `green`, `yellow`, or `red`.

## Minimal Example Output

```text
.understand-operator/MyOp/
  route.md
  route.json
  quality_gate.yaml
  cbm/cbm_query_log.md
  summary/operator_manifest.yaml
  summary/operator_io.yaml
  summary/operator_boundary.md
  tiling/tiling_frontier.yaml
  tiling/dispatch_variables.yaml
  tiling/tiling_predicate_space.yaml
  tiling/tiling_branch_families.yaml
  tiling/tiling_route.yaml
  tiling/branch_matrix.yaml
  flows/compute_flow.yaml
  flows/dataflow.yaml
  kernel/kernel_task_plan.yaml
  kernel/kernel_path_matrix.yaml
  evidence/evidence_check.yaml
  testing_hints/accuracy_case_hint.yaml
```

Example `route.md` fragment:

```md
# Operator Route: MyOp

## Status
- boundary: warning
- io: warning
- tiling branch families: warning
- tiling route: warning
- kernel alignment: warning
- golden consistency: warning

## Fast Task Routes
| Task | Read First | Then Read |
|---|---|---|
| Understand IO | summary/operator_io.yaml | summary/operator_boundary.md |
| Debug tiling | tiling/dispatch_variables.yaml, tiling/tiling_predicate_space.yaml | tiling/tiling_branch_families.yaml, tiling/tiling_route.yaml, tiling/branch_matrix.yaml |
| Debug kernel path | kernel/kernel_path_matrix.yaml | kernel/paths/Kxxx_kernel_path.yaml |
```

Example `quality_gate.yaml` fragment:

```yaml
io_confidence: low
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
```
