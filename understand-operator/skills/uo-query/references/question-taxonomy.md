# uo-query Question Taxonomy (layered IR)

Classify the user question, then use **graph CLI first** when sqlite is fresh.
Always start with:

```powershell
python -X utf8 "$QUERY_CLI" "$PROJECT_ROOT" --op-name "$OP_NAME" --status-only
```

Then run at least one `--pattern` (`neighbors_of` / `entity_of` / `constraints_for` /
`branches_for_key` / `entities_in_files` / `affected_shapes`) **before** Grep/Read of
key_cards or views. YAML/key cards are for expanding text after you have entity IDs /
detail_ref from the graph.

`$QUERY_CLI` = `$PLUGIN_ROOT/uo/scripts/uo_kb_query.py`  
(not `skills/uo-query/scripts/` as primary; that path only has a forwarder).
CLI: positional `repo`=`$PROJECT_ROOT`, flags `--op-name` + `--target` (never `--uo-root` / `--entity`).

Also skim `summary/human_overview.md` (if present) + `query/routes.yaml` /
`query/terminology.yaml` when helpful.

## Types

| Type | Intent examples | Primary (graph first) | Then expand |
|---|---|---|---|
| `overview` | 这个算子 KB 概览 | `--status-only` | `summary/human_overview.md`, `summary/keys_table.yaml` |
| `tiling_key_what` | 这个 key 是什么 / 取值域 | `entity_of` on key / `SYM::*` | `tiling/key_space.yaml`, `key_cards/KEY_*.yaml` |
| `tiling_key_hit` | 何时置 1 / 什么 shape 易命中 | `entity_of` / `neighbors_of` on key or setter `SYM::*` | `key_cards` `set_by` + Host `file_path` via `detail_ref` |
| `key_shape_expr` | 复杂 unresolved / bind：要 shape 表达式 | `branches_for_key` + `affected_shapes` + `neighbors_of`（必跑） | key_card `set_by.expr_raw` + MCP→high；写入 `ir/key_shape_resolve/<KEY>.yaml` |
| `tiling_combinations` | 一共多少种组合 | (optional graph) | `tiling/exhaustive_key_space.yaml` → **only** `combination_summary` / `summary` |
| `entrypoint` | Host/Kernel 入口是谁 | `neighbors_of --target ENTRY::host_tiling` (or other `ENTRY::*`) | `ir/entrypoints.yaml` |
| `host_pipeline` | DoOpTiling 链路 | `neighbors_of` from `ENTRY::*` / `SYM::*` | `ir/host_subgraph.yaml`, `ir/entrypoints.yaml` |
| `runtime_branch` | 运行时分支 / sparseMode | graph on condition / branch symbols | `kernel/runtime_conditions.yaml`, then `kernel/branches.yaml` |
| `runtime_cover` | 覆盖要多少用例 | graph coverage entities if present | `kernel/runtime_conditions.yaml`（勿整读 testcase） |
| `compile_template` | 模板族 / KTPL | graph if linked | `tiling/exhaustive_key_space.yaml` (summary), `kernel/compile_model.yaml` |
| `impact` | 改字段影响哪条 kernel | `neighbors_of` / `affected_shapes` | `cross_layer/tiling_to_kernel.yaml`（勿整读 impact_graph） |
| `golden` | 参考实现 / 入参键 | graph if present | `ir/golden.yaml`, `flow/golden_model.yaml` |
| `contract` | 测什么 / coverage | `entity_of` / neighbors on `COV_*` | `tiling/coverage_model.yaml`, `tiling/key_space.yaml` |
| `unresolved` | KB 缺口 | `--status-only` + quality | `ir/unresolved.yaml`, `checks/final.yaml` |
| `quality` | KB 是否可信 | `--status-only` | `quality.yaml`, `checks/final.yaml`, `checks/artifact_hashes.yaml` |

## Hard rules

1. Do **not** open `ir/operator_graph.yaml`, full `contracts/testcase.yaml`, or
   `cross_layer/impact_graph.yaml` unless every hot path missed the fact.
2. Do **not** walk `facts/**` / `graphs/**` / old derived→raw ladders.
3. For `tiling_key_hit` / `entrypoint`: **graph CLI first**. Only after CLI JSON
   (or explicit `sqlite_ready=false`) may you Grep/Read key_cards. Answer must
   set `query_backend: kb_graph` when sqlite was used.
4. For `tiling_key_hit` / `key_shape_expr` expansion: use `set_by.expr_raw` + source
   anchor; if `host_reachable`/`hit_recipe` are `unknown`, escalate via
   `complex-unresolved-escalation.md` (per-KEY subagent + MCP to high) — **do not**
   return bare unsolved. Optionally verify anchored source lines via
   source-lookup-gate.
5. Distinguish combination layers: `template_block_count` vs `args_sel_count` vs `declared_dim_product`.
6. Lean KB may omit full `template_blocks` in exhaustive; say so and suggest `--profile full` if L2 needs them.
7. CLI flag for entity lookup is `--target`, never `--entity`.
