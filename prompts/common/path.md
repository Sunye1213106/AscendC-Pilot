# 路径

权威全文见 `skills/PATHS.md` 与 `runtime.md`。

禁止全盘搜脚本。

| 变量 | 含义 |
|---|---|
| `PLUGIN_ROOT` | 统一 plugin 根（含 `prompts/` `agents/` `skills/` `engines/` `harness/`） |
| `SCRIPT_DIR` | `$PLUGIN_ROOT/engines/uo/uo/scripts` |
| `PROMPT_DIR` | `$PLUGIN_ROOT/prompts` |
| `PROJECT_ROOT` | 算子仓 |
| `AGENT_ROOT` | `$PROJECT_ROOT/.ascendc-agent` |
| `UO_ROOT` | `$AGENT_ROOT/uo` |
| `TG_ROOT` | `$AGENT_ROOT/tg` |

缺脚本/prompt → 停，请用户 `.\install.ps1 opencode`。  
Legacy → `harness migrate-legacy`。
