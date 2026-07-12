# CBM On-Demand Query Protocol (MCP)

CBM graph DB 由 MCP **`index_repository`** 生成并维护。  
语义查询在各 phase **按需**调用 **`codebase-memory-mcp` MCP 工具**。

## 强制：全程 MCP

| 场景 | 做法 |
|---|---|
| `/uo-init` Phase 0 建库 | MCP `index_repository`（自动，必做） |
| `/uo-update` 刷新 / 变更 | MCP `index_repository`（若需要）+ `detect_changes` |
| 查符号 / 片段 / 调用链 | MCP `search_graph` / `search_code` / `get_code_snippet` / `trace_path` |
| KB 布局 | `prepare_operator.py`（**不**建 DB） |
| 记录 project 名 | `prepare_operator.py --write-index-meta --cbm-project ...` |

**禁止** agent 为索引或查询去跑：

- `cbm_query.py` / `uo-cbm`
- `codebase-memory-mcp cli ...`
- `prepare_operator.py --cli-cbm`（除非用户明确要求应急离线）

全局规则见 `prompts/00_cbm_first_rule.md`。Setup 见 `docs/cbm-mcp-setup.md`。

## /uo-init 自动索引（Phase 0）

```text
prepare_operator.py          → 只建 .understand-operator/<op>/ 目录
MCP index_repository         → 生成/更新 MCP 本地 graph DB
MCP list_projects/index_status → 确认成功，取 project 名
prepare_operator.py --write-index-meta --cbm-project <name> → 写入 cbm/index_meta.json
```

DB 落在 MCP 缓存目录（通常 `~/.cache/codebase-memory-mcp/`），不是手写 SQLite。  
`cbm/index_meta.json` 只记录 `repo_root` / `cbm_project` / `indexed_via: mcp`，方便后续 phase 对齐。

## 常用 MCP 查询工具

| 目的 | tool | 参数示例 |
|---|---|---|
| 建库/刷新索引 | `index_repository` | `repo_path`, `mode`=`fast`\|`full` |
| 列项目 | `list_projects` | （无参或按服务约定） |
| 索引状态 | `index_status` | `repo_path` |
| 找符号 | `search_graph` | `name_pattern`, `label` |
| 找字符串 | `search_code` | `pattern` |
| 函数片段 | `get_code_snippet` | qualified `symbol` |
| 调用链 | `trace_path` | `function_name`, `depth` |
| 变更 | `detect_changes` | `repo_path` |

## 证据获取顺序

1. 先调 MCP  
2. 提取符号、文件、行号  
3. 成功后可小范围 `Read` 核对  
4. 仅 MCP 失败才整文件 `Read` / Grep  
5. 禁止未查 MCP 就读源码；禁止用 CLI 代替 MCP  

## evidence 写法

```yaml
evidence:
  - type: cbm_mcp
    tool: search_graph
    phase: query
    args:
      name_pattern: ".*MyOpTiling.*"
      label: Function
    symbol: MyOpTiling
    file: op_host/my_op_tiling.cpp
    confidence: high
```

## MCP 未连接

1. 提示 `docs/cbm-mcp-setup.md`  
2. 配置 OpenCode / Cursor MCP 后重启  
3. **不要**用 CLI 索引后继续假装 MCP 可用  
