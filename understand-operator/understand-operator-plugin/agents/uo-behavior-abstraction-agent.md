# uo-behavior-abstraction-agent

Define reversible behavior abstractions from the compiled raw graph.

Read these common prompts before writing abstraction rules:

- `prompts/common/00_source_fact_contract.md`
- `prompts/common/08_agent_io_protocol.md`
- `prompts/common/09_graph_relation_rules.md`

## Preconditions

- Read `checks/compile_gate.yaml`; stop unless it is `pass`.
- Read `graphs/raw/*.yaml` and `indexes/*.yaml`.
- Do not modify facts, raw graphs, indexes, source files, CBM data, or checks.

## Inputs

- `graphs/raw/manifest.yaml`
- `graphs/raw/nodes.yaml`
- `graphs/raw/edges.yaml`
- `graphs/raw/paths.yaml`
- `indexes/graph_to_yaml.yaml`
- `indexes/yaml_to_graph.yaml`
- `indexes/source_index.yaml`

## Writes

Only:

- `graphs/derived/abstraction_rules.yaml`

Owner must be `uo-behavior-abstraction-agent`.

## Rule Contract

Each abstraction rule must be reversible:

- `id`
- `reversible: true`
- `node_id` or `edge_id`
- `abstract_type`
- `abstract_name`
- `raw_node_refs` and/or `raw_edge_refs`
- `yaml_refs`
- `reason`

Do not hide source details. A query must be able to expand every derived node or edge back to raw graph IDs and then to YAML/source anchors.

## Materialization

After writing rules, run:

```powershell
python "$SCRIPT_DIR/materialize_derived_graph.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

Stop on any validation error in `checks/derived_validation.yaml`.

