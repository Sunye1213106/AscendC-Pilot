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
Phase 0: bootstrap, indexing, deterministic scope confirmation
Phase 1: operator boundary facts
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

Phase 0 is a single bootstrap/index/scope-review phase. It writes:

```text
runs/<run_id>/phase0/context.yaml
runs/<run_id>/phase0/installed_skill_check.yaml
runs/<run_id>/phase0/ignore_rules.yaml
runs/<run_id>/phase0/scope_scan.yaml
runs/<run_id>/phase0/semantic_enrichment.yaml
cbm/index_meta.json
```

`scope_review.yaml` is written only after the user chooses a review decision.
`receipt.yaml` is written only after `continue` and `finalize_phase0.py`.
No `facts/**`, `checks/**`, `graphs/**`, or `indexes/**` fact/graph artifacts
may be created before the Phase 0 receipt is `status: pass`.

Required order:

1. Resolve `PROJECT_ROOT`, `OP_NAME`, and `SCRIPT_DIR`.
2. Run `prepare_operator.py` to create the clean KB layout and Phase 0 metadata.
3. Run deterministic scope scanning and dependency closure with:

   ```powershell
   python -X utf8 "$SCRIPT_DIR/macro_scope_scan.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
   ```

   Then read back `runs/<run_id>/phase0/scope_scan.yaml`. Do not hand-compose
   include/exclude scope from directory listings, CBM snippets, or model
   memory. If `PROJECT_ROOT` is an operator directory with sibling dependencies
   such as `../common`, or source includes resolve to paths such as
   `../../../common/...`, keep the common parent recorded by `scope_scan.yaml`
   as the scan root and include the sibling dependency roots.
4. Call MCP `codebase-memory-mcp.index_repository` on the resolved scope roots,
   not only the operator directory. Use `scope_scan.yaml` as the source of truth
   for `project_root`, `operator_path`, `scope_roots`, and `dependency_roots`.
5. Confirm the indexed CBM project via MCP `list_projects` or `index_status`.
6. Re-run `prepare_operator.py --write-index-meta --cbm-project <project>`.
7. Use targeted MCP semantic enrichment for candidate entries, registrations,
   host/kernel symbols, and architecture variants.
   Write `runs/<run_id>/phase0/semantic_enrichment.yaml` with the single
   contract fields `architecture_filter`, `cbm_queries`,
   `architecture_variants`, `excluded_architectures`,
   `confirmed_scope_additions`, `unresolved`, `warnings`, and `fallback`.
   `cbm_queries` replaces any legacy `queries` field. Each query record must
   include `tool`, one of `payload` or `query`, and one of `result_summary`,
   `result`, `error`, or `reason`. `confidence` and `fallback_used` are
   optional; MCP failures must be recorded as degraded records instead of
   blocking scope confirmation.
8. Show include, exclude, architecture variants, and uncertain items with the
   question/AskQuestion button UI. Stop.
   Continue to Phase 1 only after explicit `continue`.
9. Record the scope decision with `review_checkpoint.py --gate macro_scope --decision continue`.
10. Run `finalize_phase0.py` to validate and write `runs/<run_id>/phase0/receipt.yaml`.

If VCS commands fail inside `PROJECT_ROOT`, continue with the deterministic
scope scanner instead of treating the user path as the complete source tree.

Phase 0 receipt freezes source revision, source snapshot ID, approved scope,
architecture variants, CBM project, and spec bundle hash.

## Phase 1

Run `uo-boundary-agent` as a foreground specialized subagent. It reads Phase 0
receipt, scope scan, semantic enrichment, and `cbm/index_meta.json`. It writes
only:

```text
facts/operator/interface.yaml
facts/operator/source_files.yaml
facts/operator/entrypoints.yaml
```

Each agent emits only candidate JSON (never final YAML/IDs/source text/hashes)
and processes each 5-10-entry batch with `run_candidate_batch.py`, which
runs `validate_candidate_batch.py`, repair-tracks with the candidate runner, and
atomically compiles successful batches through `compile_candidate_facts.py` into
the formal target. Then run the Stage Validator:

```powershell
python "$SCRIPT_DIR/validate_fact_stage.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step1 --write-report
python "$SCRIPT_DIR/build_fact_registry.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

Empty boundary files must fail; unresolved entries must be explicit.
Formal facts are created only by the deterministic Candidate runner/compiler;
do not overwrite formal fact files by hand.
Before authoring, the boundary agent must read
`$PROMPT_DIR/common/11_phase1_candidate_authoring.md`. It writes Candidate JSON
V2 batches only. Process one boundary target at a time through
`run_candidate_batch.py` before expanding the target.
Do not dispatch this subagent until `runs/<run_id>/phase0/receipt.yaml` exists
with `status: pass`.
If Step 1 validation fails, resume the same `uo-boundary-agent` context with the
validator report, current target content, exact schema, catalog entry, stable ID
rules, and the Phase 1 authoring contract. Do not open a second boundary
subagent window to redo the same files, and do not hand-write a task prompt that
asks for direct final-document YAML writes or ad hoc generator scripts.
Repair attempts are limited to three tries for the same semantic candidate
batch repair key in the same run. Changing `task_id`, candidate filename, or
dispatch wording does not reset the counter.

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

