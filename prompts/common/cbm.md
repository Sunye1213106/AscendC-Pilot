# CBM（MCP codebase-memory）

## Task

在已确认 scope 的窄索引上，为**具名函数/类/方法**取源码与调用边证据。  
不做 KEY 语义闭合主路径；不索引父仓；不改 CBM 库。

## Target

- 读：`$UO_ROOT/cbm/index_meta.json` → `cbm_project`
- 索引：仅 `$UO_ROOT/cbm/index_stage`（`indexed_via: mcp`）
- 工具：`index_repository` · `search_graph` · `search_code` · `get_code_snippet` · `trace_path`（`query_graph`/`get_architecture` 少用）

## Authoritative Sources

1. `index_meta.json` 的 `cbm_project` / `indexed_via: mcp`
2. MCP 返回的 `qualified_name` + `file_path` + snippet
3. 范围内按行 Read（宏表 / 注册宏 / Host 谓词）

非权威：模型记忆、命名直觉、全仓 Grep、本地 CBM CLI、`$OP_NAME`/`PROJECT_ROOT` 冒充 `project`。

## Tool Policy

### MUST use CBM

| 目的 | 工具 |
|---|---|
| Phase0 建窄图 | `index_repository`（scope 确认后一次） |
| 具名符号定义 | `search_graph` → 再 `get_code_snippet` |
| 文本/宏**名**定位 | `search_code`（定位后须 Read） |
| 真实函数调用边 | `trace_path`（`calls`；depth≤5） |

### MUST NOT 用 CBM 当主路径（改用 rg + 按行 Read）

| 模式 | 例子 | 主路径 |
|---|---|---|
| TilingKey 位域宏表 | `ASCENDC_TPL_*_DECL` / `ASCENDC_TPL_SEL` | `*_template_tiling_key.h` |
| 打包宏 | `GET_TPL_TILING_KEY(...)` | Host `GetTilingKey()` 实参序 ↔ DECL 序 |
| Host 谓词赋值 | `keepProb < 1` → drop / `isNzOut` | `GetTilingKey` / `DoOpTiling` / `SaveToTilingData` |
| 模板/Op 工厂注册 | `REGISTER_TILING_TEMPLATE_WITH_ARCH` / `IMPL_OP_OPTILING` / `OpDef` | rg 注册宏 → 对应 Tiling 类（按 arch） |
| Kernel 注册宏 | `REGISTER_TILING_FOR_TILINGKEY` | `op_kernel/*.cpp` 注册块 |
| 空 tensor 旁路 | `RunEmptyTiling*` / `*EmptyTensor*` | 仅作旁路；须再查 normal 主路径 |
| 编译期 dtype 隔离 | `ORIG_DTYPE_QUERY` + `ASCENDC_TPL_SEL` | 宏表 + Host 运行时 dtype 谓词 |

路径 / include / CMake → Glob / rg / Read（见 `tools.md`）。

## Required Procedure

```text
1. 读 index_meta → cbm_project
2. search_graph | search_code → qualified_name + file_path
3. get_code_snippet(qualified_name=..., project=...)
4. 需要调用边 → trace_path
5. 若命中上表「MUST NOT 主路径」模式 → 立刻切范围内 Read；禁止停在 snippet/trace
```

KEY / `input_derivable` 闭合另循 `uo-input-derivable-resolve.md`：主路径 = Host `file_path` Read；CBM = **MAY**。

KEY 语义锚点（按序，缺一则未完成）：

1. `GetTilingKey`（或同角色 key_writer）
2. `GET_TPL_TILING_KEY`（或等价打包）
3. `*_template_tiling_key.h` 中对应 `ASCENDC_TPL_*_DECL`
4. 必要时 `SaveToTilingData` / `DoOpTiling`

## Hard Constraints

- MUST：`project` = `index_meta.cbm_project`
- MUST：先 step 2 再 `get_code_snippet`；参数名必须是 `qualified_name`
- MUST：`semantic_query` 为字符串数组
- MUST NOT：`index_repository(repo_path=父仓)`；本地 CBM CLI
- MUST NOT：跳过 step 2 猜 qn；用宽 Grep 顶替符号查找
- MUST NOT：CBM 空结果 / 仅 empty 路径 producer → 宣称 KEY「bit-pack / 跨编译边界不可解」或主路径已闭合
- ONLY：MCP `codebase-memory-mcp`；禁止整文件 dump、改 CBM 库

## Parameter Cheatsheet

### `index_repository`

```yaml
repo_path: <$UO_ROOT/cbm/index_stage 绝对路径>
mode: fast
name: <op>-phase0-scope
```

成功后：`prepare_operator.py --write-index-meta --cbm-project <返回名>`。

### `search_graph`

`project` 必填。主查询三选一（有 `query` 时 **忽略** `name_pattern`）：

```yaml
project: <cbm_project>
name_pattern: ".*GetTilingKey.*"   # 或 query: "..." / semantic_query: ["a","b"]
label: Function                      # 可选
limit: 20
```

### `search_code`

```yaml
project: <cbm_project>
pattern: "IsNzOut"                   # 或 regex: true
path_filter: "op_host"               # 可选
mode: compact
limit: 15
```

### `get_code_snippet`

```yaml
project: <cbm_project>
qualified_name: "<search_graph 完整 qn>"
include_neighbors: false
```

禁止：`symbol` / `name` / `function` 代替 `qualified_name`。

### `trace_path`

```yaml
project: <cbm_project>
function_name: "GetTilingKey"        # 短名或 qn
direction: both
depth: 3
mode: calls
```

对 `REGISTER_*` / `GET_TPL_*`：勿指望完整工厂选择链。

## Acceptance Criteria

- 每次 MCP 调用带正确 `project`
- 具名符号证据含 `qualified_name` + `file_path`（或明确空结果 + 已改查询）
- KEY 相关结论不单靠 CBM；宏/注册/谓词有 Read 行号证据
- empty-only producer 未标为主路径闭合

## Failure Handling

| 情况 | 动作 | reason_code（建议） |
|---|---|---|
| meta 缺 / 非 mcp | STOP；先 Phase0 索引 | `CBM_INDEX_MISSING` |
| `project` 错导致空 | 重读 meta；禁止换仓路径蒙对 | `CBM_PROJECT_MISMATCH` |
| 符号查询空 | 换 `name_pattern`/label；查 `has_more`；仍空 → 范围内 Read | `CBM_SYMBOL_NOT_FOUND` |
| 仅宏/注册/位域需求 | 不升级 CBM；rg+Read | `USE_SOURCE_READ` |
| 仅 empty 有写入 | escalate；查 normal `GetTilingKey`/`SaveToTilingData` | `EMPTY_PATH_ONLY_PRODUCER` |
| Host 谓词可读仍写「不可解」 | 拒绝该结论 | `HOST_PREDICATE_READABLE` |

禁止：用猜测填满证据；扩大到父仓索引；伪造 qn。
