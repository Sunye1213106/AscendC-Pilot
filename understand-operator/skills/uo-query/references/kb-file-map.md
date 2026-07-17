# uo-query KB File Map (layered IR)

Read-only. Prefer small routed files. Do **not** default-read the full `ir/operator_graph.yaml`.

## Resolve KB

1. `$PROJECT_ROOT/.understand-operator/<op_name>/manifest.yaml`
2. Prefer `query/routes.yaml` + `query/terminology.yaml` when present
3. Fallback: this map + `question-taxonomy.md`

## Hot files (default reads)

| Path | Use |
|---|---|
| `query/routes.yaml` | Question type → files |
| `query/terminology.yaml` | Alias → stable id |
| `ir/entrypoints.yaml` | Host/Kernel role entry |
| `tiling/key_predicates.yaml` | All key cards summary |
| `tiling/key_cards/KEY_*.yaml` | One tiling-key set_by card |
| `tiling/key_space.yaml` | Key domains |
| `tiling/exhaustive_key_space.yaml` | Combination counts / template blocks |
| `kernel/runtime_conditions.yaml` | Deduped runtime conditions |
| `kernel/branches.yaml` | Full branch list (only if needed) |
| `flow/golden_model.yaml` / `ir/golden.yaml` | Numeric oracle |
| `cross_layer/impact_graph.yaml` | Host↔Kernel impact |
| `contracts/testcase.yaml` | Test-agent contract |
| `ir/unresolved.yaml` | Known gaps |
| `checks/final.yaml` / `quality.yaml` | Trust / validation |

## Cold files (only when hot files miss)

| Path | Use |
|---|---|
| `ir/host_subgraph.yaml` | Host helpers / predicates |
| `ir/kernel_subgraph.yaml` | Kernel nodes |
| `ir/bridge.yaml` | Bridge diagnostics |
| `ir/tilingkey_space.yaml` | Raw SEL / dimensions |
| `ir/operator_graph.yaml` | Full merge (last resort) |
| `runs/*/phase0/*` | Scope / indexing process only |

## Removed / obsolete (ignore)

`facts/**`, `graphs/**`, `indexes/**` from old Phase1–3 layouts.
