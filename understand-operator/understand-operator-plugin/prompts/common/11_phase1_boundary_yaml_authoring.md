# Phase 1 Boundary Candidate JSON Authoring Contract

This document replaces the legacy YAML batch instructions below. The boundary
agent emits only candidate JSON using `candidate_batch.schema.json`, validates
it with `validate_candidate_batch.py`, and compiles it with
`compile_candidate_facts.py`. It must not produce IDs, YAML headers, `sources`,
`source_text`, `code_hash`, `file_hash`, or `SRC_*`. The remaining YAML examples
are historical structure notes only and must not be used as output instructions.

This contract is the executable authoring guide for `uo-boundary-agent`. The
operator schemas remain the source of truth. Examples below show structure
only; never copy their DemoOp paths, symbols, line numbers, hashes, or facts
into a target operator.

## What The Model May Write

The model may write small temporary YAML batch files for
`merge_fact_entries.py --batch <file>`. It must not write or replace the final
fact documents directly. `prepare_fact_file.py` owns the catalog header and
snapshot, and `merge_fact_entries.py` owns atomic updates to these files:

- `facts/operator/interface.yaml`
- `facts/operator/source_files.yaml`
- `facts/operator/entrypoints.yaml`

A batch contains only these optional list sections and no document header:

```yaml
items: []
relations: []
unresolved: []
```

Omit empty sections if convenient. Each batch must contain 1-10 total entries.
Use a temporary path outside `PROJECT_ROOT` and `UO_ROOT`, for example under
`$env:TEMP`, so a batch is never mistaken for a KB artifact.

## Schema Cards

Every confirmed item has `id`, an allowed `kind`, `status: confirmed`, and a
non-empty `sources` list. Interface and entrypoint items also require `name`.
Every confirmed relation has `id`, `type`, `source_id`, `target_id`,
`status: confirmed`, and `sources`.

`interface.yaml` item kinds and required kind-specific fields:

- `input_tensor`, `output_tensor`: `name`, `dtype`, `layout`, `rank`,
  `shape_symbols`.
- `optional_input`, `optional_output`: all tensor fields plus `optional` and
  `presence_condition`.
- `attribute`: `name`, `attr_type`, `default`, `domain`.
- `dtype_domain`, `layout_domain`, `rank`, `shape_symbol`: the common item
  fields; include only values proven by the anchor.
- `interface_constraint`: common fields plus `constraint_text`, `source_refs`.
- `format_conversion`: common fields plus `from_format`, `to_format`,
  `source_refs`.

`source_files.yaml` item kinds and required kind-specific fields:

- `source_file`, `generated_file`: `path`, `role`, `file_hash`,
  `include_reason`.
- `dependency_file`: `path`, `role`, `discovered_from`, `discovery_chain`,
  `dependency_type`, `included_because`, `outside_operator_directory`,
  `file_hash`.
- `external_system_file`, `third_party_file`: `path`, `dependency_type`,
  `discovered_from`.
- `excluded_file`: `path`, `role`, `exclude_reason`.
- `uncertain_file`: `path`, `reason`.
- `architecture_variant`: `name`, `files`.
- `include_rule`, `exclude_rule`, `branch_skip`, `source_hint`: use only fields
  directly supported by the schema and source evidence.

`entrypoints.yaml` allows `registration_entry`, `api_definition`,
`proto_definition`, `host_entry`, `tiling_entry`, `tiling_key_setter`,
`kernel_launch_site`, `kernel_global_entry`, `kernel_class_entry`,
`golden_entry`, and `unresolved_entry`. Every confirmed entrypoint requires
`name`, repo-relative `file`, `symbol`, and `entry_kind` in addition to the
common fields.

Read the three exact schema files before authoring. These cards are a fast
checklist, not permission to invent fields or facts.

## Source Anchor Contract

Every confirmed item and relation embeds at least one source anchor:

```yaml
sources:
  - id: SRC_DEMO_HOST
    file: op_host/demo.cpp
    symbol: DemoOpHost
    span:
      start_line: 1
      end_line: 1
    source_text: void DemoOpHost() {}
    code_hash: sha256:e61acccbab36dfbf9eecf76661c03aa5cc5f3a8165ae94eb5a903520327195dd
    anchor_kind: definition
```

The validator reconstructs `source_text` by joining the inclusive source lines
with `\n`, then hashes exactly those UTF-8 bytes. Therefore:

1. Read the real file at the stated lines immediately before writing a batch.
2. Preserve indentation and all text exactly; do not include a trailing newline.
3. Compute `code_hash` from that exact `source_text`; never guess it.
4. Use a repo-relative path inside `PROJECT_ROOT`.
5. If any of these values cannot be proven, emit an `UNRESOLVED_*` entry instead
   of a confirmed item.

## Minimal Structural Examples

Example `interface.yaml` batch:

```yaml
items:
  - id: ARG_DEMO_X
    kind: input_tensor
    name: x
    dtype: [float16]
    layout: [ND]
    rank: 1
    shape_symbols: [N]
    status: confirmed
    sources:
      - id: SRC_DEMO_INTERFACE_X
        file: op_host/demo.cpp
        symbol: DemoOpHost
        span: {start_line: 1, end_line: 1}
        source_text: void DemoOpHost() {}
        code_hash: sha256:e61acccbab36dfbf9eecf76661c03aa5cc5f3a8165ae94eb5a903520327195dd
        anchor_kind: definition
```

Example `source_files.yaml` batch:

```yaml
items:
  - id: SYM_DEMO_SOURCE_FILE
    kind: source_file
    path: op_host/demo.cpp
    role: host
    file_hash: sha256:d187181a9796d95646bcab9c4918191ca10be0d1ee9be98c31b7c4a7e637000f
    include_reason: contains the host entry
    status: confirmed
    sources:
      - id: SRC_DEMO_SOURCE_FILE
        file: op_host/demo.cpp
        symbol: DemoOpHost
        span: {start_line: 1, end_line: 1}
        source_text: void DemoOpHost() {}
        code_hash: sha256:e61acccbab36dfbf9eecf76661c03aa5cc5f3a8165ae94eb5a903520327195dd
        anchor_kind: definition
```

`file_hash` is the SHA-256 of the complete file bytes. It is different from an
anchor `code_hash` unless the file bytes exactly equal the anchor text.

Example `entrypoints.yaml` batch:

```yaml
items:
  - id: SYM_DEMO_HOST_ENTRY
    kind: host_entry
    name: DemoOpHost
    file: op_host/demo.cpp
    symbol: DemoOpHost
    entry_kind: host_entry
    status: confirmed
    sources:
      - id: SRC_DEMO_HOST_ENTRY
        file: op_host/demo.cpp
        symbol: DemoOpHost
        span: {start_line: 1, end_line: 1}
        source_text: void DemoOpHost() {}
        code_hash: sha256:e61acccbab36dfbf9eecf76661c03aa5cc5f3a8165ae94eb5a903520327195dd
        anchor_kind: definition
```

## Authoring And Repair Loop

Process one target file at a time:

1. Read its catalog entry, exact schema, stable ID rules, and relevant source.
2. Run `prepare_fact_file.py --path <target>` once.
3. Write one small temporary batch YAML and merge it with
   `merge_fact_entries.py --path <target> --batch <batch>`.
4. Read back the final target and run the Step 1 boundary validator.
5. Group errors by `(path, error code)`. Replace entries by reusing their IDs in
   a repair batch; add only missing entries. Never regenerate a whole document.
6. Repeat until the validator exits 0, then delete or ignore the temporary batch.

Repair priorities:

- `YAML_*`, `DOCUMENT_*`, `SCHEMA_*`: fix batch structure or required fields.
- `STABLE_ID_*`, `REFERENCE_*`, `RELATION_*`: fix IDs and graph references.
- `SOURCE_*`: reread the exact file span and recompute the hash.
- `OWNER_*`, `ARTIFACT_*`, `SNAPSHOT_*`: recreate the skeleton with the
  deterministic writer; do not repair its header by hand.
- `DOCUMENT_EMPTY_NOT_ALLOWED`, `SCHEMA_MIN_CARDINALITY`: add a proven item or
  an explicit unresolved entry.

Completion means the actual Step 1 validator report has `status: pass`, not
that the YAML looks plausible.
