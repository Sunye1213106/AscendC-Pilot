# Source Fact Contract

All facts YAML files use the catalog header: `version`, `artifact`, `snapshot`, `items`, `relations`, and `unresolved`.

Use real typed `kind` values from the target schema. Do not use `kind: source_fact`.

`confirmed` means the claim is directly supported by exact source anchors. `not_applicable` means the category was checked and does not apply. `unresolved` means the claim cannot be proven.

Stable IDs must follow the Skill ID rules. Relations must use `relation_types.yaml`. Agents must not modify specs, graphs, other agent files, source code, or validator reports.
