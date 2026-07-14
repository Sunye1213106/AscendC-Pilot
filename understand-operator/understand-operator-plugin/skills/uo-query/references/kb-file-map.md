# uo-query KB File Map

Read-only query uses the new source-fact KB layout.

## Resolve

Use `manifest.yaml`, `op_name`, and aliases/terms from:

- `indexes/terminology.yaml`
- `indexes/symbol_index.yaml`
- `registry/aliases.yaml` only when present in migrated KBs

## Read Order

1. `indexes/terminology.yaml`
2. `indexes/symbol_index.yaml`
3. `graphs/derived/nodes.yaml`
4. `graphs/derived/edges.yaml`
5. `graphs/derived/expansions.yaml`
6. `graphs/raw/nodes.yaml`
7. `graphs/raw/edges.yaml`
8. `graphs/raw/paths.yaml`
9. YAML fact files under `facts/**`
10. source anchors embedded in fact YAML

Query does not write files and does not modify CBM.
