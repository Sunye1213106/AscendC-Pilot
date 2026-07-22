# CBM（MCP codebase-memory）用法

KB 给实体/变量 id；要源码证据时用 MCP **`codebase-memory-mcp`**，禁止整文件 dump、本地 CBM CLI、改 CBM 库。

**`project` 必填且易错**：只读 `$UO_ROOT/cbm/index_meta.json` 的 `cbm_project`。  
禁止用 `PROJECT_ROOT` 路径、算子目录名、`$OP_NAME` 顶替（除非 meta 里恰好相同）。

索引范围：仅 `$UO_ROOT/cbm/index_stage`（`indexed_via: mcp`）。禁止索引多算子父仓。

---

## 何时用哪个工具

| 目的 | 工具 | 何时用 |
|---|---|---|
| 建/刷新图 | `index_repository` | Phase0 确认 scope 后一次 |
| 按符号名找定义 | `search_graph` | 函数/类/方法；**先于** snippet |
| 按文本/宏/关键字 | `search_code` | 字符串、宏、分支关键字 |
| 读函数体片段 | `get_code_snippet` | 已有精确 `qualified_name` |
| 调用/数据流 | `trace_path` | callers/callees、冲击面 |
| 复杂多跳 | `query_graph` | Cypher；日常少用 |
| 架构概览 | `get_architecture` | 粗结构；日常少用 |

路径 / include / 构建文件 → 用 Glob / rg / 按行 Read（见 `tools.md`），**不要**用 CBM。

---

## 标准调用链（强制）

```
1. 读 index_meta.json → 记下 cbm_project
2. search_graph / search_code → 拿到 qualified_name + file_path
3. get_code_snippet(qualified_name=..., project=...)
4. 需要调用关系 → trace_path(function_name=短名或 qn, project=...)
```

禁止：跳过 step 2 瞎猜 `qualified_name`；用 Grep 代替 step 2 做「语义校验」。

---

## 参数速查（按工具）

### `index_repository`（Phase0）

```yaml
repo_path: <绝对路径 $UO_ROOT/cbm/index_stage>   # 禁止整个父仓
mode: fast                                        # init 默认 fast
name: <op>-phase0-scope                           # 与 write-index-meta 一致
```

成功后：`prepare_operator.py --write-index-meta --cbm-project <返回的 project 名>`。

### `search_graph`

必填：`project`。三选一主查询（可组合，但 **`query` 有值时会忽略 `name_pattern`**）：

```yaml
# 推荐：精确符号
project: <cbm_project>
name_pattern: ".*SetSplitAxis.*"    # 正则
label: Function                     # 可选：Function|Method|Class|...
limit: 20

# 或：自然语言 / 关键字（BM25）
project: <cbm_project>
query: "compute tiling split axis"
label: Function

# 或：语义（必须是字符串数组，禁止单个字符串）
project: <cbm_project>
semantic_query: ["tiling", "split", "axis"]
```

看返回的 `qualified_name`、`file_path`；`has_more=true` 时加 `offset` 翻页或收窄 `label`/`file_pattern`。

### `search_code`

```yaml
project: <cbm_project>
pattern: "IsTndSwizzle"          # 或正则 + regex: true
file_pattern: "*.cpp"            # 可选
path_filter: "op_host"           # 可选，路径正则
mode: compact                    # compact|full|files；默认 compact
limit: 15
```

### `get_code_snippet`

```yaml
project: <cbm_project>
qualified_name: "<search_graph 返回的完整 qn>"   # 参数名必须是 qualified_name
include_neighbors: false
```

**错误示例（禁止）：** `symbol` / `name` / `function` / 只传短名却期望唯一命中。

### `trace_path`

```yaml
project: <cbm_project>
function_name: "SetSplitAxis"    # 短名或 qn
direction: both                  # inbound|outbound|both
depth: 3                         # 默认 3；需要时 ≤5
mode: calls                      # calls|data_flow|cross_service
```

---

## 常见错误（对照）

| 错误 | 正确 |
|---|---|
| `project`=仓库路径或 `$OP_NAME` | `project`=`index_meta.cbm_project` |
| `get_code_snippet({symbol: ...})` | `qualified_name`，且先 `search_graph` |
| `semantic_query: "send publish"` | `semantic_query: ["send","publish"]` |
| 同时传 `query`+`name_pattern` 指望两者生效 | 只用其一；有 `query` 则 `name_pattern` 被忽略 |
| `index_repository(repo_path=父仓)` | `repo_path=$UO_ROOT/cbm/index_stage` |
| 本地 `cbm_query.py` / CLI index | 只用 MCP |
| 宽 Grep 全仓当符号查找 | `search_graph` / `search_code` |
| 空结果立刻放弃 | 换 `name_pattern`、放宽 `label`、查 `has_more` |

空结果：先确认 meta 里 `project_confirmed` 与 `indexed_via: mcp`，再改查询；仍空再范围内按行 Read。
