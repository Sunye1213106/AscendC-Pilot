# uo-query Question Taxonomy (layered IR)

Classify the user question, then read **only** the files listed for that type.
Always start with `query/routes.yaml` / `query/terminology.yaml` when present.

## Types

| Type | Intent examples | Primary reads |
|---|---|---|
| `tiling_key_what` | 这个 key 是什么 / 取值域 | `tiling/key_space.yaml`, `tiling/key_predicates.yaml`, `tiling/key_cards/KEY_*.yaml` |
| `tiling_key_hit` | 何时置 1 / 什么 shape 易命中 | `tiling/key_cards/KEY_*.yaml` (`set_by`), then Host anchor via `file_path` |
| `tiling_combinations` | 一共多少种组合 | `tiling/exhaustive_key_space.yaml` → `combination_summary` |
| `entrypoint` | Host/Kernel 入口是谁 | `ir/entrypoints.yaml` |
| `host_pipeline` | DoOpTiling 链路 | `ir/host_subgraph.yaml`, `ir/entrypoints.yaml` |
| `runtime_branch` | 运行时分支 / sparseMode | `kernel/runtime_conditions.yaml`, then `kernel/branches.yaml` |
| `runtime_cover` | 覆盖要多少用例 | `kernel/runtime_conditions.yaml`, `contracts/testcase.yaml` |
| `compile_template` | 模板族 / KTPL | `tiling/exhaustive_key_space.yaml`, `kernel/compile_model.yaml` |
| `impact` | 改字段影响哪条 kernel | `cross_layer/impact_graph.yaml`, `cross_layer/tiling_to_kernel.yaml` |
| `golden` | 参考实现 / 入参键 | `ir/golden.yaml`, `flow/golden_model.yaml` |
| `contract` | 测什么 / coverage | `contracts/testcase.yaml`, `tiling/coverage_model.yaml` |
| `unresolved` | KB 缺口 | `ir/unresolved.yaml`, `checks/final.yaml` |
| `quality` | KB 是否可信 | `quality.yaml`, `checks/final.yaml` |

## Hard rules

1. Do **not** open `ir/operator_graph.yaml` unless hot files miss the fact.
2. Do **not** walk `facts/**` / `graphs/**` / old derived→raw ladders.
3. For `tiling_key_hit`: answer from `set_by.expr_raw` + source anchor first; if `host_reachable`/`hit_recipe` are `unknown`, say so and optionally verify the anchored source lines.
4. Distinguish combination layers: `template_block_count` vs `args_sel_count` vs `declared_dim_product`.
