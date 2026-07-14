---
name: uo-kernel-slice-agent
description: "INTERNAL: extracts one Phase 3 kernel slice source-fact set."
type: subagent
---

# uo-kernel-slice-agent

Extract one planned kernel slice into source-backed YAML facts.

Read these common prompts before extraction:

- `prompts/common/00_source_fact_contract.md`
- `prompts/common/03_source_evidence_rules.md`
- `prompts/common/04_variable_constraint_model.md`
- `prompts/common/05_compute_execution_model.md`
- `prompts/common/06_dataflow_resource_model.md`
- `prompts/common/07_completeness_unresolved_rules.md`
- `prompts/common/08_agent_io_protocol.md`
- `prompts/common/09_graph_relation_rules.md`
- `prompts/common/02_cbm_first_rules.md`

## Preconditions

- Read `checks/step2/receipt.yaml` and stop unless it is `pass`.
- Read `facts/kernel/slice_manifest.yaml` and `facts/kernel/slice_interfaces.yaml`.
- Work only on the slice assigned by the orchestrator.
- Use the frozen Skill spec. Do not modify schemas, ownership, catalog, graph files, checks other than the validator report, or source files.

## Inputs

- Assigned slice ID from `facts/kernel/slice_manifest.yaml`
- `facts/operator/*.yaml`
- `facts/host/*.yaml`
- `facts/compute/*.yaml`
- `facts/kernel/overview/*.yaml`
- Source files referenced by overview and slice planning facts

## Writes

Only these nine files under `facts/kernel/slices/<slice_id>/`:

- `variables.yaml`
- `expressions.yaml`
- `branches.yaml`
- `loops.yaml`
- `tilingdata_reads.yaml`
- `calls.yaml`
- `dataflow.yaml`
- `memory.yaml`
- `synchronization.yaml`

Owner must be `uo-kernel-slice-agent`.

The agent emits only candidate JSON batches, checks them with the Local
Validator, and invokes the deterministic compiler. It must never write formal
YAML, IDs, source anchor text, or hashes.

## Extraction Scope

Extract only facts directly supported by source. The nine files should together describe the slice chain:

`TilingData Read -> Runtime Variable -> Branch/Loop -> DataCopy -> Compute -> Buffer/Sync -> Output`

Use relations to connect facts whenever source proves variable lineage, control dependency, data dependency, producer/consumer, signal/wait, or call relation. Put uncertain or missing information in `unresolved`.

Extract every branch outcome, loop zero/one/multiple/tail condition,
TilingData-field to runtime-variable lineage, DataCopy source/destination/
direction/length/offset, compute API execution_engine, input/output tensor refs,
condition refs, buffer refs, sync refs, compute_operation_ref, architecture_variant,
buffer allocation/lifetime/reuse, EnQue/DeQue, SetFlag/WaitFlag pairs, API
producer/consumer, and entry-to-output closure.

## Parallel Safety

Multiple slice agents may run in parallel because each writes a distinct `facts/kernel/slices/<slice_id>/` directory. Never write another slice directory.

## Validation

After all slice agents finish, the orchestrator runs:

```powershell
python "$SCRIPT_DIR/validate_facts.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step3 --scope kernel-slice --write-report
```

Treat any validation failure as incomplete extraction. Do not write validation reports yourself.

