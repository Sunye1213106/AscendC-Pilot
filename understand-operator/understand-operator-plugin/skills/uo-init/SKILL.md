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

The only active phases are:

```text
Phase 0: bootstrap, indexing, deterministic scope confirmation
Phase 1: operator boundary facts
Phase 2: Host, Compute, and Kernel Overview facts in parallel
Phase 3: Kernel slices, fact review, raw graph, derived graph, query, final gate
```

Do not execute or recreate Phase 3.5, Phase 4+, proposal promotion, canonical v2,
tiling archive workflows, route builders, contracts/testcase generation, impact
graphs, or an old standalone quality phase.

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

## Phase 0

Phase 0 is a single bootstrap/index/scope-review phase. It writes:

```text
runs/<run_id>/phase0/context.yaml
runs/<run_id>/phase0/installed_skill_check.yaml
runs/<run_id>/phase0/ignore_rules.yaml
runs/<run_id>/phase0/scope_scan.yaml
runs/<run_id>/phase0/semantic_enrichment.yaml
runs/<run_id>/phase0/scope_review.yaml
runs/<run_id>/phase0/receipt.yaml
cbm/index_meta.json
```

Required order:

1. Resolve `PROJECT_ROOT`, `OP_NAME`, and `SCRIPT_DIR`.
2. Run `prepare_operator.py` to create the clean KB layout and Phase 0 metadata.
3. Call MCP `codebase-memory-mcp.index_repository`.
4. Confirm the indexed CBM project via MCP `list_projects` or `index_status`.
5. Re-run `prepare_operator.py --write-index-meta --cbm-project <project>`.
6. Run deterministic scope scanning bounded to `PROJECT_ROOT`.
7. Use targeted MCP semantic enrichment for candidate entries, registrations,
   host/kernel symbols, and architecture variants.
8. Show include, exclude, architecture variants, and uncertain items. Stop.
   Continue to Phase 1 only after explicit `continue`.

Phase 0 receipt freezes source revision, source snapshot ID, approved scope,
architecture variants, CBM project, and spec bundle hash.

## Phase 1

Run `uo-boundary-agent`. It reads Phase 0 receipt, scope scan, semantic
enrichment, and `cbm/index_meta.json`. It writes only:

```text
facts/operator/interface.yaml
facts/operator/source_files.yaml
facts/operator/entrypoints.yaml
```

Then run:

```powershell
python "$SCRIPT_DIR/validate_facts.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step1 --write-report
```

Empty boundary files must fail; unresolved entries must be explicit.

## Phase 2

After Phase 1 validation passes, run these foreground tasks in parallel:

```text
uo-host-extraction
uo-flow-extraction
uo-kernel-overview-agent
```

They write only:

```text
facts/host/**
facts/compute/**
facts/kernel/overview/**
```

Run the three scoped validators:

```powershell
python "$SCRIPT_DIR/validate_facts.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step2 --scope host --write-report
python "$SCRIPT_DIR/validate_facts.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step2 --scope compute --write-report
python "$SCRIPT_DIR/validate_facts.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step2 --scope kernel-overview --write-report
```

Then run `uo-step2-fact-review-agent`. It writes only:

```text
checks/step2/review.yaml
```

When all reports pass and input hashes match current facts:

```powershell
python "$SCRIPT_DIR/write_step2_receipt.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

## Phase 3

Phase 3 starts only after Step 2 receipt is valid.

1. `uo-kernel-slice-planner` writes `facts/kernel/slice_manifest.yaml` and
   `facts/kernel/slice_interfaces.yaml`.
2. Parallel `uo-kernel-slice-agent` tasks write the fixed nine YAML files under
   `facts/kernel/slices/<slice_id>/`.
3. Run Step 3 validation and `uo-step3-fact-review-agent`.
4. Seal Step 3:

```powershell
python "$SCRIPT_DIR/write_step3_receipt.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python "$SCRIPT_DIR/build_compile_gate.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python "$SCRIPT_DIR/source_graph_compiler.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

5. `uo-behavior-abstraction-agent` writes only
   `graphs/derived/abstraction_rules.yaml`.
6. Materialize derived graph and run the final Phase 3 gate:

```powershell
python "$SCRIPT_DIR/materialize_derived_graph.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python "$SCRIPT_DIR/quality_gate.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

Read-only query order is fixed:

```text
indexes/terminology.yaml -> graphs/derived -> graphs/raw -> YAML facts -> source anchors
```

Use:

```powershell
python "$SCRIPT_DIR/uo_query_readonly.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --entity "<ID_OR_LABEL>"
```

## Hard Rules

- Agents write only paths allowed by `spec/ownership.yaml`.
- Validators and reviews must record `input_hashes`.
- Receipts and compile gate become invalid after any fact/report/review change.
- Raw graph compiler reads only catalog entries with `raw_graph_input: true`.
- Query and future TestAgent are read-only consumers. They must not modify UO KB
  or CBM data.
- User-facing language is Chinese unless the user asks otherwise.
