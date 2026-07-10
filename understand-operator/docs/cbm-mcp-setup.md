# codebase-memory-mcp MCP Setup

`understand-operator` agent 侧（`/uo-query`、`/uo-init` 分析 phase、subagent）**只通过 MCP** 调用 CBM，不再使用 `cbm_query.py`。

上游项目：[DeusData/codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp)

## 1. 安装 binary

任选其一：

```powershell
# 官方安装脚本
Invoke-WebRequest -Uri https://raw.githubusercontent.com/DeusData/codebase-memory-mcp/main/install.ps1 -OutFile install.ps1
Unblock-File .\install.ps1
.\install.ps1
```

或使用本仓库已有 binary：

```text
understand-operator/thirdparty/codebase-memory-mcp.exe
```

确认可运行：

```powershell
codebase-memory-mcp --help
```

## 2. OpenCode

编辑 `~/.config/opencode/opencode.json`，在 `mcp` 中增加：

```json
"codebase-memory-mcp": {
  "type": "local",
  "command": [
    "C:/Users/sunye/bin/codebase-memory-mcp.cmd"
  ],
  "enabled": true
}
```

若不用 `.cmd` 包装，可直接指向 exe：

```json
"command": [
  "D:/PR-review/Ascendc-PR-test-agent-upload/understand-operator/thirdparty/codebase-memory-mcp.exe"
]
```

重启 OpenCode，确认 MCP 列表里有 `search_graph` / `search_code` / `get_code_snippet` / `trace_path`。

## 3. Cursor

创建或合并 `~/.cursor/mcp.json`（或项目 `.cursor/mcp.json`）：

```json
{
  "mcpServers": {
    "codebase-memory-mcp": {
      "command": "C:/Users/sunye/bin/codebase-memory-mcp.cmd",
      "args": []
    }
  }
}
```

重启 Cursor，在 MCP 面板确认 `codebase-memory-mcp` 已连接。

## 4. 首次索引（/uo-init 自动）

**正常路径：跑 `/uo-init`。** Phase 0 会自动：

1. `prepare_operator.py` — 只建 KB 目录  
2. MCP `index_repository(repo_path=算子仓库根, mode=fast|full)` — **生成 graph DB**  
3. `list_projects` / `index_status` — 确认成功  
4. `prepare_operator.py --write-index-meta --cbm-project <name>` — 写入 `cbm/index_meta.json`

DB 由 MCP 服务写入本地 cache（如 `~/.cache/codebase-memory-mcp/`），不是 `cbm_query.py`。

也可手动对仓库说 **Index this project**，但 `/uo-init` 不应依赖你手工再索引一遍。

## 5. 常用工具

| Tool | 用途 |
|---|---|
| `search_graph` | 按名字/label 找 Function/Class |
| `search_code` | 在已索引文件中搜字符串 |
| `get_code_snippet` | 按 qualified name 取函数片段 |
| `trace_path` | 调用链 |
| `list_projects` / `index_status` | 确认项目已索引 |

## 6. 故障排查

| 现象 | 处理 |
|---|---|
| agent 仍在跑 `cbm_query.py` / CLI index | 确认 skill 已更新；新开会话；检查 MCP 是否已连接；`/uo-init` 应调 MCP `index_repository` |
| MCP 无工具 | 重启 agent；检查 `command` 路径是否指向真实 exe |
| `project not found` | 对算子仓库跑 `index_repository` 或 `/uo-init --full` |
| 查询空结果 | 先 `search_graph` 找精确符号名，再 `get_code_snippet` / `trace_path` |
