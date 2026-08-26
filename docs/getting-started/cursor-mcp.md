# AscendC-Pilot → Cursor

OpenCode 的 `pilot_cli` 不能原样装进 Cursor。Cursor 侧原生入口是 **MCP**。

当前 MCP 服务器名：`ascendc-pilot`  
当前工具：`uo_query`（四种形态：无参索引 / 标识符 / `Dim=V|Name=Value` / `file`+`line`）

以后 UO 引擎自己的 MCP 可以并列再加一个 server，不必改这个查询合同。

实现锚点：`cursor-plugin/`（`mcp.json`、`run_mcp.py`、`skills/uo-query/`）。

## 已写入的位置

| 位置 | 作用 |
| --- | --- |
| `%USERPROFILE%\.cursor\mcp.json` | 装进 Cursor（全局） |
| `PR-review/.cursor/mcp.json` | 本仓库（可带默认 `--project`） |
| `%USERPROFILE%\.cursor\plugins\local\ascendc-pilot` | 本地插件：skill + 同一 MCP |

## 启用

1. 点安装链接（Cursor 会弹出确认）
2. 或打开 **Customize → MCP**，打开 `ascendc-pilot`
3. 新开一个 Agent 对话（当前对话不一定热加载）
