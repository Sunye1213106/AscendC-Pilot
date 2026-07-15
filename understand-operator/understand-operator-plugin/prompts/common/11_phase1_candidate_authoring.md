# Phase 1 Candidate JSON Authoring

This is the only Phase 1 authoring contract. Boundary extraction emits
Candidate JSON V2 batches, validates them locally, and compiles them through the
deterministic Python compiler. Agents never write Formal Facts YAML directly.

## Allowed Model Output

The model may write only small Candidate JSON V2 batches containing:

- `target` as an object. Partitioned files use `path` plus a non-empty
  `section`, for example:

```json
{
  "target": {
    "path": "facts/host.yaml",
    "section": "variables"
  }
}
```

Non-partitioned files must omit `section`; never emit `section: ""`.

- item `local_id`
- item `kind`
- display `name`
- structured `identity`
- semantic `fields`
- `source_locations`
- structured local, entity, or symbol references
- relation `type`
- relation `source` and `target` reference objects
- relation `fields`
- explicit `unresolved` entries

Use the schema at
`skills/understand-operator/spec/schemas/candidate/candidate_batch.schema.json`.
Read `skills/understand-operator/spec/file_catalog.yaml`, ownership rules, and
the exact target schema before producing a batch.

## Python-Owned Fields

Python writes all Formal Facts material:

- Formal YAML header
- stable fact ID
- stable relation ID
- canonical identity
- location-only `sources`

The compiler derives identity and evidence from structured Candidate JSON and
source locations. If a claim cannot be proven from the approved Phase 0 scope,
write it under `unresolved` instead of inventing a confirmed fact.

Formal Facts source anchors contain only `id`, `file`, `symbol`, `span`, and
`anchor_kind`. No Formal YAML may store `source_text`, `code_hash`,
`file_hash`, `encoding`, `newline`, or `bom`.

## Required Commands

For each 5-10 item batch:

```powershell
python "$SCRIPT_DIR/run_candidate_batch.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --batch <candidate.json>
```

After a failed run, repair only the fields identified in the structured error
output. The repair controller permits at most three attempts for the same
semantic candidate batch repair key in the same run. Changing `task_id`,
candidate filename, or dispatch wording does not reset the attempt count.
`task_id` is readable metadata, not repair identity. Stop and report
`CANDIDATE_REPAIR_EXHAUSTED` after the third failed attempt.

After all Phase 1 boundary targets compile, run:

```powershell
python "$SCRIPT_DIR/validate_fact_stage.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step1 --write-report
python "$SCRIPT_DIR/build_fact_registry.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

## Forbidden

Do not create or use:

- non-JSON intermediate fact batches
- old merge scripts
- model-provided `id`
- model-provided `status`
- model-provided `sources`
- model-provided `source_text`
- model-provided `code_hash`
- model-provided `file_hash`
- model-provided `encoding`, `newline`, or `bom`
- model-provided stable IDs
- model-provided canonical IDs
- Formal YAML direct writes
- whole-file replacement of formal fact documents

Do not express Candidate targets as fragment strings. Non-partitioned Phase 1
targets must use only `path`:

```json
{
  "target": {
    "path": "facts/operator/interface.yaml"
  }
}
```

## Phase 1 Targets

Boundary extraction may compile only:

- `facts/operator/interface.yaml`
- `facts/operator/source_files.yaml`
- `facts/operator/entrypoints.yaml`

Each target is processed through Candidate local validation first, then
deterministic compilation. Validator failures are repaired in the same
Candidate JSON batch shape, not by editing Formal Facts YAML.

## Span Format

All identity span fields use the same object shape:

```json
{
  "source_span": {
    "start_line": 121,
    "end_line": 121
  }
}
```

Do not emit `"source_span": "121-121"`, `[121, 121]`, or prose such as
`"line 121"`.

## Complete Candidate Examples

Before writing a Candidate batch, read `candidate_batch.schema.json`,
`entity_types.yaml`, the target schema, and the target entry in
`file_catalog.yaml`.

```json
{
  "version": 2,
  "task": {"run_id": "UO_RUN_EXAMPLE", "stage": "step1", "owner": "uo-boundary-agent", "task_id": "BOUNDARY_SOURCE"},
  "target": {"path": "facts/operator/source_files.yaml"},
  "items": [{"local_id": "host_file", "kind": "source_file", "identity": {"path": "op_host/demo.cpp"}, "fields": {"path": "op_host/demo.cpp", "role": "host", "include_reason": "operator registration and host entry"}, "source_locations": [{"file": "op_host/demo.cpp", "symbol": "DemoOp", "start_line": 1, "end_line": 1, "anchor_kind": "file"}]}],
  "relations": [],
  "unresolved": []
}
```

```json
{
  "version": 2,
  "task": {"run_id": "UO_RUN_EXAMPLE", "stage": "step1", "owner": "uo-boundary-agent", "task_id": "BOUNDARY_IO"},
  "target": {"path": "facts/operator/interface.yaml"},
  "items": [
    {"local_id": "input_x", "kind": "input_tensor", "identity": {"operator_name": "DemoOp", "direction": "input", "index": 0}, "fields": {"name": "x", "dtype": ["float16"], "layout": ["ND"], "rank": 2, "shape_symbols": ["N", "C"]}, "source_locations": [{"file": "op_host/demo.cpp", "symbol": "DemoOp", "start_line": 122, "end_line": 122, "anchor_kind": "declaration"}]},
    {"local_id": "output_y", "kind": "output_tensor", "identity": {"operator_name": "DemoOp", "direction": "output", "index": 0}, "fields": {"name": "y", "dtype": ["float16"], "layout": ["ND"], "rank": 2, "shape_symbols": ["N", "C"]}, "source_locations": [{"file": "op_host/demo.cpp", "symbol": "DemoOp", "start_line": 123, "end_line": 123, "anchor_kind": "declaration"}]}
  ],
  "relations": [],
  "unresolved": []
}
```

```json
{
  "version": 2,
  "task": {"run_id": "UO_RUN_EXAMPLE", "stage": "step1", "owner": "uo-boundary-agent", "task_id": "BOUNDARY_ENTRY"},
  "target": {"path": "facts/operator/entrypoints.yaml"},
  "items": [{"local_id": "host_entry", "kind": "host_entry", "identity": {"qualified_symbol": "DemoOpHost"}, "fields": {"name": "DemoOpHost", "file": "op_host/demo.cpp", "symbol": "DemoOpHost", "entry_kind": "host_entry"}, "source_locations": [{"file": "op_host/demo.cpp", "symbol": "DemoOpHost", "start_line": 130, "end_line": 130, "anchor_kind": "definition"}]}],
  "relations": [],
  "unresolved": []
}
```

```json
{
  "version": 2,
  "task": {"run_id": "UO_RUN_EXAMPLE", "stage": "step1", "owner": "uo-boundary-agent", "task_id": "BOUNDARY_CONSTRAINT"},
  "target": {"path": "facts/operator/interface.yaml"},
  "items": [{"local_id": "constraint_dtype", "kind": "interface_constraint", "identity": {"source_file": "op_host/demo.cpp", "scope_symbol": "DemoOpHost", "source_span": {"start_line": 140, "end_line": 142}}, "fields": {"constraint_text": "input x supports float16", "source_refs": []}, "source_locations": [{"file": "op_host/demo.cpp", "symbol": "DemoOpHost", "start_line": 140, "end_line": 142, "anchor_kind": "validation"}]}],
  "relations": [],
  "unresolved": []
}
```

```json
{
  "version": 2,
  "task": {"run_id": "UO_RUN_EXAMPLE", "stage": "step1", "owner": "uo-boundary-agent", "task_id": "BOUNDARY_ATTR"},
  "target": {"path": "facts/operator/interface.yaml"},
  "items": [{"local_id": "attr_seed", "kind": "attribute", "identity": {"operator_name": "DemoOp", "name": "seed"}, "fields": {"name": "seed", "attr_type": "Int", "default": 0}, "source_locations": [{"file": "op_host/demo.cpp", "symbol": "DemoOp", "start_line": 121, "end_line": 121, "anchor_kind": "declaration"}]}],
  "relations": [],
  "unresolved": []
}
```

Type/default declarations can prove declared type and default value. Domains,
ranges, allowed values, and cross-field constraints require explicit validation
logic or source-backed documentation. Without that evidence, use a conservative
description or `unresolved`; do not invent a domain.
