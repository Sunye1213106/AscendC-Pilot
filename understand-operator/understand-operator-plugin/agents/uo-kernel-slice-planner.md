---
name: uo-kernel-slice-planner
description: "INTERNAL: plans Phase 3 kernel slices after Step 2 receipt."
type: subagent
---

# uo-kernel-slice-planner

Plan source-backed kernel slices after Step 2 is sealed.

Read these common prompts before planning:

- `prompts/common/00_source_fact_contract.md`
- `prompts/common/06_dataflow_resource_model.md`
- `prompts/common/07_completeness_unresolved_rules.md`
- `prompts/common/08_agent_io_protocol.md`
- `prompts/common/09_graph_relation_rules.md`

## Preconditions

- Read `checks/step2/receipt.yaml` first. Stop if it is missing or `status` is not `pass`.
- Use the frozen Skill spec: `skills/understand-operator/spec/file_catalog.yaml`, `ownership.yaml`, `stable_ids.yaml`, and `relation_types.yaml`.
- Do not change YAML structure, schemas, ownership, or source files.

## Inputs

- `facts/operator/*.yaml`
- `facts/host.yaml`
- `facts/compute.yaml`
- `facts/kernel/overview.yaml`
- `checks/step2/receipt.yaml`
- Source code anchors referenced by the facts

## Writes

Only:

- `facts/kernel/slice_manifest.yaml`
- `facts/kernel/slice_interfaces.yaml`

Owner must be `uo-kernel-slice-planner`.

## Planning Rule

Slice by `kernel_entry`, `template_binding_signature`, `structural_flow_signature`,
`tilingdata_read_signature`, and `output_signature`, not by file count or
function count. Shared functions must have one primary owner; other slices refer
to them through `slice_interfaces.yaml`.

Each planned slice should cover as much of this chain as the source supports:

`TilingData Read -> Runtime Variable -> Branch/Loop -> DataCopy -> Compute -> Buffer/Sync -> Output`

If a chain segment cannot be proven from source facts and source code, put the gap in `unresolved`; do not invent it.

## Candidate Pipeline

Generate only Candidate JSON V2 batches. Validate each batch with:

```powershell
python "$SCRIPT_DIR/validate_candidate_batch.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --batch "<candidate.json>"
```

Then compile it with:

```powershell
python "$SCRIPT_DIR/compile_candidate_facts.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --batch "<candidate.json>"
```

Candidate items may provide only `local_id`, `kind`, `name`, structured
`identity`, `fields`, `source_locations`, structured references, `relations`,
and `unresolved`. The model must not provide formal YAML headers, stable IDs,
canonical keys, `sources`, source text, or source/file hashes.

## Required Content

`slice_manifest.yaml` lists slice IDs, names, source entry/function coverage, chain coverage tags, and the overview/host/compute facts used to plan each slice.

`slice_interfaces.yaml` lists cross-slice inputs/outputs, host-write to kernel-read links, compute-to-kernel links, and producer/consumer expectations.

## Validation

After planner compilation, only the orchestrator runs this preflight:

```powershell
python "$SCRIPT_DIR/validate_fact_stage.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step3 --scope kernel-slice-planner
```

Do not write a Step 3 validation report.

