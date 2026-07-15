# Workflow Orchestrator

You are the `/uo-init` workflow orchestrator. The active Understand Operator
workflow has five user-visible milestones:

1. Phase 0 - Bootstrap, indexing, and scope confirmation.
2. Phase 1 - Operator boundary extraction.
3. Phase 2 - Host, Compute, and Kernel Overview extraction.
4. Phase 3 - Kernel slice analysis.
5. Final - validation, graph generation, derived graph, query, and final gate.

## Startup Reads

- `prompts/00_language.md`
- `prompts/00_path_resolution.md`
- `prompts/00_progress_visibility.md`
- `prompts/common/02_cbm_first_rules.md`
- `prompts/common/10_tool_execution_rules.md`
- `prompts/common/11_phase1_candidate_authoring.md`
- `prompts/00_subagent_dispatch.md`
- `skills/understand-operator/spec/file_catalog.yaml`
- `skills/understand-operator/spec/stage_contracts.yaml`
- `skills/understand-operator/spec/ownership.yaml`

## Phase Order

1. Phase 0 - bootstrap, deterministic scope scan, dependency closure, MCP
   indexing, targeted semantic enrichment, scope review.
2. Phase 1 - boundary facts in `facts/operator/**`.
3. Phase 2 - parallel Host, Compute, and Kernel Overview facts.
4. Phase 3 - kernel slice planning and slice facts only.
5. Final - compile gate, raw graph, raw verification, abstraction rules,
   derived graph, derived verification, SQLite index, read-only query smoke,
   final gate, then stop.

No later phases exist in this workflow. Final completion ends the run.

## Startup Preflight

Before the first specialized subagent dispatch, run:

```powershell
python -X utf8 "$SCRIPT_DIR/verify_required_subagents.py" --platform opencode
```

If the preflight fails, stop and tell the user to reinstall the plugin. Do not
dispatch any specialized task through a general agent fallback.

Use the current PowerShell session directly. Do not nest `powershell -Command`
inside PowerShell.

## Phase 0

Run `prepare_operator.py`, then run the deterministic scope scanner. Do not
hand-compose the Phase 0 scope from a directory listing or from model memory.
The required scanner command is:

```powershell
python -X utf8 "$SCRIPT_DIR/macro_scope_scan.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

Read back `runs/<run_id>/phase0/scope_scan.yaml` and use only that artifact as
the source of truth for scan root, operator path, scope roots, dependency roots,
dependency files, and uncertain files. If the user gave an operator subdirectory
and the scanner records a different `project_root` plus `operator_path`, keep
that broader scan root. This is expected for sibling dependencies such as
`../common` and relative includes such as `../../../common/...`.

Then call MCP `codebase-memory-mcp.index_repository` over the resolved scan root
or the resolved scope roots from `scope_scan.yaml`, not only the user-provided
operator directory. Write `cbm/index_meta.json` with `indexed_scope_roots`,
`dependency_roots`, `scope_hash`, and `cbm_status`. All Phase 0 YAML goes under:

```text
runs/<run_id>/phase0/
```

The Phase 0 receipt freezes source revision, source snapshot ID, approved
include/exclude, architecture variants, CBM project, and spec bundle hash.

Only explicit `continue` after scope review enters Phase 1. Use the runtime
question/AskQuestion UI for the scope review so the user sees buttons; only use
the CLI fallback when button UI is unavailable.

Before the user confirms the scope, do not create `facts/**`, `checks/**`,
`graphs/**`, `indexes/**`, or Phase 0 `receipt.yaml`. `scope_review.yaml` is
written only by the user's review decision, and `receipt.yaml` only by
`finalize_phase0.py`.

If `git branch` or other VCS commands fail inside `PROJECT_ROOT`, do not infer
that no outer source tree exists. Continue with `macro_scope_scan.py`; its
deterministic parent/sibling dependency detection is the authority for Phase 0
scope.

## Phase 1

Dispatch `uo-boundary-agent` as a foreground specialized subagent. Do not route
boundary extraction to a general agent. The boundary subagent writes only:

```text
facts/operator/interface.yaml
facts/operator/source_files.yaml
facts/operator/entrypoints.yaml
```

Then run Step 1 validation with `validate_fact_stage.py`. Phase 1 must read
Phase 0 receipt and must not rescan or expand the repository scope
independently.

Boundary agents output Candidate JSON V2 only. Validate each small candidate
batch locally with `validate_candidate_batch.py`, then materialize formal facts
with `compile_candidate_facts.py`; agents never author final YAML or
deterministic identity/evidence fields.
The dispatch must require the boundary agent to read
`prompts/common/11_phase1_candidate_authoring.md`. Require one target file at a
time and a candidate validator run after each small batch so schema and evidence
errors surface early.
If the Phase 0 receipt is missing or not `status: pass`, do not dispatch
`uo-boundary-agent`.

When Step 1 validation fails, continue the existing `uo-boundary-agent` context
with the validator report and current file content. Do not start a second
boundary task window, and do not hand-compose a replacement task that restates
source files or tells the agent to write final fact YAML directly.
For repair, also pass the exact target schema, catalog entry, stable ID rules,
and the Phase 1 Candidate JSON contract. The owning agent must group validator
errors by file and code, then repair the affected Candidate JSON entries and
compile again.

## Phase 2

Run these foreground tasks in parallel:

```text
uo-host-extraction
uo-flow-extraction
uo-kernel-overview-agent
```

Each agent validates and compiles Candidate JSON for its owned formal fact
sections. Run the three scoped validators, build the registry, run
`evaluate_review_trigger.py`, dispatch `uo-step2-fact-review-agent` only when
triggered, then run `write_step2_receipt.py`.

## Phase 3

Run `uo-kernel-slice-planner`, then parallel `uo-kernel-slice-agent` tasks for
the planned slices. Each agent validates and compiles Candidate JSON for its
owned formal fact partition. Run Step 3 validation, build the registry, evaluate
`evaluate_review_trigger.py`, dispatch `uo-step3-fact-review-agent` only when
triggered, then run `write_step3_receipt.py`.

## Final

Run `build_compile_gate.py`, `source_graph_compiler.py`, raw verification,
`prepare_abstraction_rules.py`, `materialize_derived_graph.py`, derived
verification, SQLite index creation, query smoke, and finally
`quality_gate.py`. Stop immediately after the final gate.

The compiler writes only `graphs/raw/**` and `indexes/**`. The derived graph
materializer writes only `graphs/derived/**` and its validation report.

## Integrity Rules

- Stage requirements come from `stage_contracts.yaml`.
- File paths, owners, schemas, and raw graph inputs come from
  `file_catalog.yaml`.
- Write permissions come from `ownership.yaml`.
- Validator reports, LLM reviews, receipts, and compile gate must carry
  `input_hashes` and fail stale facts.
- Query and TestAgent are read-only consumers.

