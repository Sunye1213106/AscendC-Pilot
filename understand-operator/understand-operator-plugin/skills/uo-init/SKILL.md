---
name: uo-init
description: >-
  End-to-end AscendC operator source-fact KB build for a target repo.
  Use when the user runs /uo-init, understand_operator_init, or asks to build
  an operator KB. The workflow is Phase 0 through Phase 3 only.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] [--full]"
---

# uo-init - Source-Fact Operator KB Build

Build an evidence-backed operator KB under:

```text
.understand-operator/<op_name>/
```

The active user-visible milestones are:

```text
Phase 0: lightweight scope discovery, human confirmation, confirmed-file CBM indexing
Phase 1: CBM-backed Host/Tiling and Kernel execution subgraphs
Phase 2: Host, Compute, and Kernel Overview facts in parallel
Phase 3: Kernel slices only
Final: validation, raw graph, derived graph, query, final gate
```

Do not execute or recreate any workflow beyond Final. Final completion ends the
run.

## Variables

- `SCRIPT_DIR`: this skill's sibling `../understand-operator`, containing `prepare_operator.py`.
- `PLUGIN_ROOT`: the installed plugin root.
- `PROMPT_DIR`: `$PLUGIN_ROOT/prompts`.
- `PROJECT_ROOT`: the target operator repository root.
- `OP_NAME`: `--op-name`, otherwise a safe repository-derived name.
- `UO_ROOT`: `$PROJECT_ROOT/.understand-operator/$OP_NAME`.
- `CBM_MODE`: `full` only when the user passes `--full`; otherwise `fast`.

Never search the whole disk for scripts. If `prepare_operator.py` is missing,
ask the user to reinstall the plugin and stop.

Before the first specialized subagent dispatch, run
`verify_required_subagents.py` from `SCRIPT_DIR`. If a required specialized
agent is missing or not declared as an OpenCode `subagent`, stop. Never route a
UO internal task to a general fallback agent.

Every specialized subagent dispatch uses a stable identity:

```text
<run_id>:<phase-or-step>:<owner>:<target-path-or-slice-id>
```

If that identity already exists in the current run, resume the same subagent
context for all continuation and repair work.
This applies to every phase, not only Phase 1. If the runtime cannot resume it, stop with
`SUBAGENT_RESUME_UNAVAILABLE` and include the identity plus failed report path;
do not open a duplicate subagent for the same owner and target.

Pass `PLUGIN_ROOT`, `PROMPT_DIR`, and `SCRIPT_DIR` to every subagent. Subagents
must read common prompts from `PROMPT_DIR`; when running from this source tree,
the fallback plugin root is
`D:\PR-review\Ascendc-PR-test-agent-upload\understand-operator\understand-operator-plugin`.

## Phase 0

Phase 0 is a lightweight scope discovery and confirmation phase. It writes:

```text
runs/<run_id>/phase0/context.yaml
runs/<run_id>/phase0/installed_skill_check.yaml
runs/<run_id>/phase0/ignore_rules.yaml
runs/<run_id>/phase0/scope_proposal.yaml
runs/<run_id>/phase0/scope_scan.yaml
```

After the user explicitly confirms the proposed scope, Phase 0 writes:

```text
runs/<run_id>/phase0/scope_review.yaml
runs/<run_id>/phase0/scope_confirmed.yaml
cbm/index_meta.json
runs/<run_id>/phase0/entry_points.yaml
```

`semantic_enrichment.yaml` may remain `pending`; Phase 0 no longer performs
targeted semantic enrichment before CBM. `scope_review.yaml` and
`scope_confirmed.yaml` are written only after the user chooses a review
decision. `receipt.yaml` is written only after `continue`, confirmed-file CBM
indexing, and `finalize_phase0.py`.
No `facts/**`, `checks/**`, `graphs/**`, or `indexes/**` fact/graph artifacts
may be created before the Phase 0 receipt is `status: pass`.

Required order:

1. Resolve `PROJECT_ROOT`, `OP_NAME`, and `SCRIPT_DIR`.
2. Run `prepare_operator.py` to create the clean KB layout and Phase 0 metadata.
3. Run lightweight scope discovery with:

   ```powershell
   python -X utf8 "$SCRIPT_DIR/macro_scope_scan.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
   ```

   Phase0 intentionally only performs lightweight scope discovery. Deep
   operator understanding starts after CBM indexing. The scanner may use only
   path-level exploration (`rg`, `glob`, `find`, `ls`, `tree`) and must not do
   source-wide reads, AST analysis, call/reference graph construction,
   dependency closure, or all-source scanning.
4. Read `runs/<run_id>/phase0/scope_proposal.yaml`. Show the proposed
   `candidate_files`, excluded groups, and warnings to the user. Stop for human
   confirmation. The user must choose one of: confirm, modify range, add files,
   or stop.
5. Record the scope decision with `review_checkpoint.py --gate macro_scope`.
   Only `--decision continue` may proceed; `stop`, `revise`, or
   `manual_supplement` stops the workflow until the user supplies a new
   confirmed scope.
6. After `scope_confirmed.yaml` exists, call MCP
   `codebase-memory-mcp.index_repository` with only
   `confirmed_file_list`. Do not pass `repository_root` for indexing and do not
   rescan the repository. CBM input must be the human-confirmed file list.
7. Confirm the indexed CBM project via MCP `list_projects` or `index_status`.
8. Re-run `prepare_operator.py --write-index-meta --cbm-project <project>`.
   `cbm/index_meta.json` must record `index_input: confirmed_file_list` and
   `indexed_files` exactly matching `scope_confirmed.yaml`.
9. Run `finalize_phase0.py` to validate and write
   `runs/<run_id>/phase0/receipt.yaml` plus `entry_points.yaml`. Phase0 output
   may record only shallow input/output/attribute/host/tiling/kernel entry
   hints; deep code facts belong to Phase1 and later.

If VCS commands fail inside `PROJECT_ROOT`, continue with the deterministic
scope scanner instead of treating the user path as the complete source tree.

Phase 0 receipt freezes source revision, source snapshot ID, approved file
scope, confirmed CBM project, and spec bundle hash.

## Phase 1

Phase 1 reads only Phase 0 outputs and CBM metadata:

```text
runs/<run_id>/phase0/scope_confirmed.yaml
runs/<run_id>/phase0/entry_points.yaml
runs/<run_id>/phase0/receipt.yaml
cbm/index_meta.json
```

It does not rediscover the repository and does not run the old broad boundary
fact extraction flow. Use the connected `codebase-memory-mcp` project recorded
in `cbm/index_meta.json` to obtain raw candidate graph nodes and edges around
Phase 0 anchors. When the current runtime exposes no codebase-memory MCP graph
tool, record the missing MCP graph in `graph/graph_issues.yaml`; do not install
npm packages and do not scan the whole repository.

Run:

```powershell
python "$SCRIPT_DIR/phase1_graph.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --architecture arch35 --show-raw-graph --show-processed-graph
```

Phase 1 writes only:

```text
graph/raw_candidate_graph.yaml
graph/raw_candidate_nodes.yaml
graph/raw_candidate_edges.yaml
graph/host_tiling_graph.yaml
graph/host_tiling_paths.yaml
graph/kernel_execution_graph.yaml
graph/kernel_execution_paths.yaml
graph/removed_nodes.yaml
graph/removed_edges.yaml
graph/graph_comparison.yaml
graph/graph_pruning_report.yaml
graph/graph_issues.yaml
```

The deterministic implementation performs:

```text
Phase0 anchor loading
CBM project metadata validation
arch35 filtering
BFS reachability search
bidirectional reachability pruning
Host/Tiling graph output
Kernel execution graph output
raw-to-processed node/edge mapping
removed node/edge reporting
```

Do not dispatch `uo-boundary-agent` for Phase 1 in this workflow. Phase 2 and
Phase 3 remain unchanged and must not be refactored as part of this Phase 1
graph extraction.

## Phase 2

After Phase 1 validation passes, run these foreground tasks in parallel:

```text
uo-host-extraction
uo-flow-extraction
uo-kernel-overview-agent
```

They write only:

```text
facts/host.yaml sections
facts/compute.yaml sections
facts/kernel/overview.yaml sections
```

Run the three scoped validators:

```powershell
python "$SCRIPT_DIR/validate_fact_stage.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step2 --scope host --write-report
python "$SCRIPT_DIR/validate_fact_stage.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step2 --scope compute --write-report
python "$SCRIPT_DIR/validate_fact_stage.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step2 --scope kernel-overview --write-report
python "$SCRIPT_DIR/build_fact_registry.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

If any scoped validator fails, stop and return the report to the owning fact
agent. Do not run `evaluate_review_trigger.py`, do not dispatch a review agent,
and do not write the Step 2 receipt.

Only after all scoped validators pass, evaluate the deterministic review
trigger:

```powershell
python "$SCRIPT_DIR/evaluate_review_trigger.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --step step2
```

`uo-step2-fact-review-agent` runs only when
`checks/step2/review_trigger.yaml status: triggered`. It writes only:

```text
checks/step2/review.yaml
```

Read `checks/step2/review_trigger.yaml`. If `status: skipped`, do not dispatch
`uo-step2-fact-review-agent`. If `status: triggered`, dispatch it and require
`checks/step2/review.yaml status: pass`, empty `blocking_findings`, and
`input_hashes` exactly copied from the trigger.

When all reports pass and input hashes match current facts:

```powershell
python "$SCRIPT_DIR/write_step2_receipt.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

## Phase 3

Phase 3 starts only after Step 2 receipt is valid.

1. `uo-kernel-slice-planner` writes `facts/kernel/slice_manifest.yaml` and
   `facts/kernel/slice_interfaces.yaml`.
   Run planner preflight validation without writing the final Step 3 report:

   ```powershell
   python "$SCRIPT_DIR/validate_fact_stage.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step3 --scope kernel-slice-planner
   ```

2. Parallel `uo-kernel-slice-agent` tasks write assigned slice partitions
   `facts/kernel/slices/<slice_id>.yaml`.
3. Run the single final Step 3 validation report after all slice agents finish:

   ```powershell
   python "$SCRIPT_DIR/validate_fact_stage.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step3 --scope all --write-report
   ```

   If validation fails, stop and return the report to the owning fact agent. Do
   not run review trigger or review agent.
4. Build the registry and evaluate review trigger:

   ```powershell
   python "$SCRIPT_DIR/build_fact_registry.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
   python "$SCRIPT_DIR/evaluate_review_trigger.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --step step3
   ```

   Read `checks/step3/review_trigger.yaml`. If `status: skipped`, do not
   dispatch `uo-step3-fact-review-agent`. If `status: triggered`, dispatch it
   and require `checks/step3/review.yaml status: pass`.
5. Seal Step 3:

```powershell
python "$SCRIPT_DIR/write_step3_receipt.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

## Final

Final starts only after Step 3 receipt is valid. Run:

```powershell
python "$SCRIPT_DIR/validate_fact_stage.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step3 --scope all
python "$SCRIPT_DIR/build_fact_registry.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python "$SCRIPT_DIR/validate_semantic_completeness.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python "$SCRIPT_DIR/build_compile_gate.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python "$SCRIPT_DIR/source_graph_compiler.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python "$SCRIPT_DIR/verify_raw_graph.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python "$SCRIPT_DIR/prepare_abstraction_rules.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

Then dispatch `uo-behavior-abstraction-agent`. It may modify only
`graphs/derived/abstraction_rules.yaml#/rules`; it must not edit `snapshot`,
`input_hashes`, `artifact`, or `version`.

Materialize the derived graph, build the query index, run query smoke, and run
the final gate:

```powershell
python "$SCRIPT_DIR/materialize_derived_graph.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python "$SCRIPT_DIR/verify_derived_graph.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python "$SCRIPT_DIR/prepare_graph_review.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

Then dispatch `uo-graph-review-agent` exactly once. It is read-only except for
`checks/graph_review.yaml` and must not repair facts, graphs, rules, schemas,
indexes, or CBM. Validate its report before query index construction:

```powershell
python "$SCRIPT_DIR/validate_graph_review.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python "$SCRIPT_DIR/build_query_index.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python "$SCRIPT_DIR/uo_query_readonly.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --smoke
python "$SCRIPT_DIR/quality_gate.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

Read-only query order is fixed:

```text
indexes/terminology.yaml -> graphs/derived -> graphs/raw -> YAML facts -> source anchors
```

Use smoke mode:

```powershell
python "$SCRIPT_DIR/uo_query_readonly.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --smoke
```

The final gate writes only `checks/final.yaml`. After the final gate passes, stop. There are no workflow stages after Final.

## Hard Rules

- Agents write only paths allowed by `spec/ownership.yaml`.
- Validators and reviews must record `input_hashes`.
- Receipts and compile gate become invalid after any fact/report/review change.
- Raw graph compiler reads only catalog entries with `raw_graph_input: true`.
- Query and future TestAgent are read-only consumers. They must not modify UO KB
  or CBM data.
- User-facing language is Chinese unless the user asks otherwise.

