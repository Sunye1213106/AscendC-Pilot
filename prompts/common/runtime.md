# 语言 · 路径 · 非 CBM 工具（runtime）

本文件为 `language` / `path` / `tools` 的合并权威说明。

## 语言

用户可见输出与产物 `rationale`/`reason`/`summary`/`findings`：简体中文。  
保持英文：YAML 键、稳定 ID、路径、命令、源码摘录、机器码 / reason_code。  
不强制「思考过程必须中文」。

## 路径

禁止全盘搜脚本。权威见 `skills/PATHS.md`。

| 变量 | 含义 |
|---|---|
| `PLUGIN_ROOT` | 统一 plugin 根（含 `prompts/` `agents/` `skills/` `engines/` `harness/`） |
| `SCRIPT_DIR` | `$PLUGIN_ROOT/engines/uo/uo/scripts` |
| `PROMPT_DIR` | `$PLUGIN_ROOT/prompts` |
| `PROJECT_ROOT` | 算子仓 |
| `OP_NAME` | 算子名（写入 manifest；产物不再按 op 嵌套） |
| `AGENT_ROOT` | `$PROJECT_ROOT/.ascendc-agent` |
| `UO_ROOT` | `$AGENT_ROOT/uo` |
| `TG_ROOT` | `$AGENT_ROOT/tg` |

缺脚本/prompt → 停，请用户 `.\install.ps1 opencode`。  
完成态由 `harness` 门禁迁移。

## 工具执行 · 非 CBM

读源码前用已确认范围（`scope_confirmed` / receipt），禁止宽递归重扫仓库。  
短合同：`tools.md`；符号 MCP：`cbm.md`。

优先：① 范围事实 → ② 范围内 Glob / rg / 按行 Read → ③ 具名符号走 MCP。

| 场景 | 用 |
|---|---|
| 路径 / include / CMake | Glob / rg / Read |
| 宏表 / `REGISTER_*` / KEY 谓词 | 范围内 rg + Read（CBM=MAY） |
| 具名函数/类/方法 | MCP（`cbm.md`） |

禁止：整盘扫描；本地 CBM CLI；用 CBM 空结果宣称 KEY 不可解。
Windows：`python -X utf8`；路径用 `-LiteralPath`。
