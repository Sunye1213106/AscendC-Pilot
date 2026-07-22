# uo-query KB 文件地图（分层 IR）

只读。**查询入口是 sqlite 图，不是本表 YAML。**

```text
uo_kb_query.py --status-only
  → uo_kb_query.py --pattern …   # indexes/kb_graph.sqlite
  → 仅打开返回的 detail_ref 热文件
```

**禁止**默认整读 `ir/operator_graph.yaml`；**禁止**未跑 `--pattern` 就 Grep/Read `tiling/key_cards/**`（非默认产物）。

## 定位 KB

1. `$PROJECT_ROOT/.understand-operator/<op_name>/manifest.yaml`
2. **主路径**：`indexes/kb_graph.sqlite`（经 `uo_kb_query.py`）
3. 回退（仅 `sqlite_ready=false`）：`query/routes.yaml` + `query/terminology.yaml`
4. 再回退：按 `question-taxonomy.md` 的冷文件表

## 图索引（主路径 · MUST）

| 路径 | 用途 |
|---|---|
| `indexes/kb_graph.sqlite` | 派生语义图；用 `export_kb_graph.py` 重建 |
| CLI `uo_kb_query.py` | `entity_of` / `neighbors_of` / `list_templates` / `templates_for_key` / `constraints_for` / `branches_for_key` / `entities_in_files` / `affected_shapes` |

仅打开 graph 返回的 `detail_ref` 热 YAML。**禁止** dump `ir/operator_graph.yaml`。

合法编译期模板实例数 = `KTPL_*` 实体数（`list_templates`）；KEY 赋值经 `fixes_flag`。

## 热文件（仅 detail_ref / sqlite 不可用时）

| 路径 | 用途 |
|---|---|
| `summary/human_overview.md` | 人机导向 + keys 表 |
| `summary/keys_table.yaml` | 紧凑 tiling-key 列表 |
| `query/routes.yaml` | 问题类型 → 文件（`never_default` 硬门禁） |
| `query/terminology.yaml` | 别名 → 稳定 id |
| `ir/entrypoints.yaml` | Host/Kernel 角色入口 |
| `tiling/key_space.yaml` | Key 取值域 |
| `tiling/key_predicates.yaml` | key 谓词摘要（若有） |
| `kernel/runtime_conditions.yaml` | 去重运行时条件（sample 截断） |
| `ir/tilingkey_space.yaml` | template_aliases / KEY dims（KTPL 源） |
| `flow/golden_model.yaml` / `ir/golden.yaml` | 数值 oracle |
| `tiling/coverage_model.yaml` | Coverage 义务 |
| `ir/unresolved.yaml` | 已知缺口 |
| `checks/final.yaml` / `quality.yaml` | 信任 / 校验 |
| `checks/artifact_hashes.yaml` | 规范 artifact 哈希 |

## 冷文件（热文件未命中时才读）

| 路径 | 用途 |
|---|---|
| `kernel/branches.yaml` | 完整分支列表 |
| `tiling/exhaustive_key_space.yaml` | 仅 **summary** / `ktpl_instance_count`；无笛卡尔 `template_blocks` |
| `cross_layer/tiling_to_kernel.yaml` | Host↔Kernel 链接（优先于 raw impact） |
| `ir/host_subgraph.yaml` | Host helper / predicate |
| `ir/kernel_subgraph.yaml` | Kernel 节点 |
| `ir/bridge.yaml` | Bridge 诊断 |

## 禁止默认整读

| 路径 | 原因 |
|---|---|
| `ir/operator_graph.yaml` | 全量 merge；仅最后手段 |
| `contracts/**`（retired） | 历史残留；测项合同在 TG |
| `cross_layer/impact_graph.yaml` | 机器 ID；用 kb_graph / tiling_to_kernel |
| `tiling/key_cards/**` | 非默认产物；用 graph 边 + 源码 `file_path` |
| `tiling/exhaustive_key_space.yaml`（全量 dump） | 仅用 summary；模板实例查 sqlite KTPL |

## 单态导出

- `/uo-init` 只有一条导出路径（无 lean/full profile）。
- 哈希在 `checks/artifact_hashes.yaml`；不写 `contracts/**` / `key_cards/**`。
- 合法模板 = sqlite `KTPL_*` + `fixes_flag`；下游自行组合展开。

## 忽略

勿依赖不在本表中的路径。sqlite 图仅为 `indexes/kb_graph.sqlite`。
