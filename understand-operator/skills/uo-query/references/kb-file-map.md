# uo-query KB File Map (layered IR)

Read-only. Prefer small routed files. Do **not** default-read the full `ir/operator_graph.yaml`.

## Resolve KB

1. `$PROJECT_ROOT/.understand-operator/<op_name>/manifest.yaml`
2. Prefer `summary/human_overview.md` + `indexes/kb_graph.sqlite` via `uo-kb-query` / `uo_query_readonly` when fresh
3. Else `query/routes.yaml` + `query/terminology.yaml`
4. Fallback: this map + `question-taxonomy.md`

## Graph index (preferred)

| Path | Use |
|---|---|
| `indexes/kb_graph.sqlite` | Derived semantic graph; rebuild with `export_kb_graph.py` |
| CLI `uo-kb-query` | `entity_of` / `neighbors_of` / `constraints_for` / `branches_for_key` / `entities_in_files` / `affected_shapes` |

Only open `detail_ref` hot YAML returned by the graph. Do **not** dump `ir/operator_graph.yaml`.

## Hot files (default reads when graph misses)

| Path | Use |
|---|---|
| `summary/human_overview.md` | Human/AI orientation + keys table |
| `summary/keys_table.yaml` | Compact tiling-key list |
| `query/routes.yaml` | Question type → files (`never_default` hard gate) |
| `query/terminology.yaml` | Alias → stable id |
| `ir/entrypoints.yaml` | Host/Kernel role entry |
| `tiling/key_predicates.yaml` | All key cards summary |
| `tiling/key_cards/KEY_*.yaml` | One tiling-key set_by card |
| `tiling/key_space.yaml` | Key domains |
| `kernel/runtime_conditions.yaml` | Deduped runtime conditions (samples truncated in lean) |
| `flow/golden_model.yaml` / `ir/golden.yaml` | Numeric oracle |
| `tiling/coverage_model.yaml` | Coverage obligations |
| `ir/unresolved.yaml` | Known gaps |
| `checks/final.yaml` / `quality.yaml` | Trust / validation |
| `checks/artifact_hashes.yaml` | Canonical artifact hashes (lean; not in testcase.yaml) |

## Cold files (only when hot files miss)

| Path | Use |
|---|---|
| `kernel/branches.yaml` | Full branch list |
| `tiling/exhaustive_key_space.yaml` | Combination **summary** in lean; full blocks only with `--profile full` |
| `cross_layer/tiling_to_kernel.yaml` | Host↔Kernel links (prefer over raw impact) |
| `ir/host_subgraph.yaml` | Host helpers / predicates |
| `ir/kernel_subgraph.yaml` | Kernel nodes |
| `ir/bridge.yaml` | Bridge diagnostics |
| `ir/tilingkey_space.yaml` | Raw SEL / dimensions |

## Never default (整读禁止)

| Path | Why |
|---|---|
| `ir/operator_graph.yaml` | Full merge; last resort only |
| `contracts/testcase.yaml` | Large TG contract; use kb_graph / coverage / key_space |
| `cross_layer/impact_graph.yaml` | Machine IDs; use kb_graph / tiling_to_kernel |
| `tiling/exhaustive_key_space.yaml` (full dump) | Use `summary` / `combination_summary` fields only |
| `facts/**`, `graphs/**` | Obsolete layouts |

## Lean vs full export

- Default `/uo-init` export profile is **lean** (`--profile lean` / `UO_KB_EXPORT_PROFILE=lean`).
- Lean: hashes in `checks/artifact_hashes.yaml`; runtime `sample_branch_ids` ≤3; exhaustive without full `template_blocks`.
- Full: historical bulky materialization for L2 / debugging (`--profile full`).

## Removed / obsolete (ignore)

`facts/**`, `graphs/**`, old Phase1–3 `indexes/**` layouts (except `indexes/kb_graph.sqlite`).
