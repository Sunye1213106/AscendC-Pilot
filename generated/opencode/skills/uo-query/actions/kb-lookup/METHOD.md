# kb_lookup (migrated domain method)

> Domain content migrated from skills-src/uo-query/references/question-taxonomy.md. Do not advance Harness state from this file.

# uo-query 问题分类（分层 IR）

先对用户问题分类；sqlite fresh 时 **优先 graph CLI**。
始终从：

```powershell
python -X utf8 "$QUERY_CLI" "$PROJECT_ROOT" --op-name "$OP_NAME" --status-only
```

开始，然后在 Grep/Read YAML **之前**至少跑一个 `--pattern`（`neighbors_of` / `entity_of` /
`list_templates` / `templates_for_key` / `constraints_for` / `branches_for_key` /
`entities_in_files` / `affected_shapes`）。YAML 用于在 graph 给出 entity ID /
`detail_ref` 之后展开正文。

`$QUERY_CLI` = `$PLUGIN_ROOT/engines/uo/uo/scripts/uo_kb_query.py`  
（勿以 `skills/uo-query/scripts/` 为主路径；该处仅有 forwarder）。
CLI：positional `repo`=`$PROJECT_ROOT`，标志 `--op-name` + `--target`（禁止 `--uo-root` / `--entity`）。

**YAML 何时可读：**
- `overview`：`--status-only` 后可读 `summary/human_overview.md` / `keys_table.yaml`
- 其它类型：须先跑 ≥1 次 `--pattern`；再只打开返回的 `detail_ref`
- `query/routes.yaml` / `terminology.yaml`：**仅** `sqlite_ready=false`（yaml_fallback）时使用

## 类型表

| 类型 | 意图示例 | 主路径（graph 优先） | 再展开 |
|---|---|---|---|
| `overview` | 这个算子 KB 概览 | `--status-only` | `summary/human_overview.md`, `summary/keys_table.yaml` |
| `tiling_key_what` | 这个 key 是什么 / 取值域 | `entity_of` on key | `tiling/key_space.yaml` |
| `tiling_key_hit` | 何时置 1 / 什么 shape 易命中 | `neighbors_of` on KEY / Host `SYM::*`（`writes`/`derives`/`determined_by`） | 源码 `file_path`/`start_line` via `detail_ref` |
| `key_shape_expr` | 复杂 unresolved / bind：要 shape 表达式 | `branches_for_key` + `affected_shapes` + `neighbors_of`（必跑） | 沿边到 Host 源码 + MCP→high；TG 写 `realization/uo_query_resolve/<KEY>.yaml` |
| `tiling_combinations` | 一共多少种合法模板 | `list_templates` / `templates_for_key` | `ir/tilingkey_space.yaml`；exhaustive 仅 summary |
| `entrypoint` | Host/Kernel 入口是谁 | `neighbors_of --target EP_*` / entrypoint_graph nodes | `ir/entrypoint_graph.yaml` |
| `host_pipeline` | DoOpTiling 链路 | `neighbors_of` from `EP_*` / identity-stable `SYM_*` | `ir/host_subgraph.yaml`, `ir/entrypoint_graph.yaml` |
| `runtime_branch` | 运行时分支 / sparseMode | graph on condition / branch symbols | `kernel/runtime_conditions.yaml`, then `kernel/branches.yaml` |
| `runtime_cover` | 覆盖要多少用例 | graph coverage entities if present | `kernel/runtime_conditions.yaml` |
| `compile_template` | 模板族 / KTPL | `list_templates` / `templates_for_key` | `ir/tilingkey_space.yaml`, `kernel/compile_model.yaml` |
| `impact` | 改字段影响哪条 kernel | `neighbors_of` / `affected_shapes` | `cross_layer/tiling_to_kernel.yaml` |
| `golden` | 参考实现 / 入参键 | graph if present | `ir/golden.yaml`, `flow/golden_model.yaml` |
| `contract` | 测什么 / coverage | `entity_of` / neighbors on `COV_*` | `tiling/coverage_model.yaml`, `tiling/key_space.yaml` |
| `unresolved` | KB 缺口 | `--status-only` + quality | `ir/unresolved.yaml`, `checks/final.yaml` |
| `quality` | KB 是否可信 | `--status-only` | `quality.yaml`, `checks/final.yaml`, `checks/artifact_hashes.yaml` |

## 硬规则

1. **禁止**打开已退役路径（`ir/operator_graph.yaml`、UO 侧 `contracts/**`）或
   `cross_layer/impact_graph.yaml`，除非所有热路径都未命中事实。测项合同只在 TG。
2. 热路径未命中时再读冷 YAML；不要漫游无关目录。
3. 对 `tiling_key_hit` / `entrypoint`：**graph CLI 优先**。沿 `writes`/`derives`/
   `determined_by` 摸瓜到源码；**不要**依赖 `key_cards`。使用 sqlite 时答案须设
   `query_backend: kb_graph`。
4. 对 `tiling_key_hit` / `key_shape_expr`：未达 high 按
   `complex-unresolved-escalation.md` 升级 — **禁止**返回裸 unsolved。
5. 合法模板实例 = `KTPL_*` 数量（非笛卡尔积）；查 `list_templates` / `fixes_flag`。
6. entity 查找的 CLI 标志是 `--target`，禁止 `--entity`。
7. **`/uo-init` 建库期禁止派发 uo-query**；建库 `input_derivable` / KEY 闭合用 `uo-key-resolve`（triage→分流）。定稿后 TG bind 可读 gaps 作证据，闭合只写 `$OUT_ROOT`。
