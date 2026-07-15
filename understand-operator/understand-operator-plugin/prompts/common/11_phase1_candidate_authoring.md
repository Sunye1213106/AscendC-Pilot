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
python "$SCRIPT_DIR/validate_candidate_batch.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --batch <candidate.json>
python "$SCRIPT_DIR/compile_candidate_facts.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --batch <candidate.json>
```

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
