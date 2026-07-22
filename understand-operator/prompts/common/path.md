# 路径

权威全文见同目录 `runtime.md`「路径」节。

禁止全盘搜脚本。

| 变量 | 含义 |
|---|---|
| `SCRIPT_DIR` | `$PLUGIN_ROOT/uo/scripts` |
| `PLUGIN_ROOT` | 插件根（含 `prompts/` `agents/` `skills/` `uo/`） |
| `PROMPT_DIR` | `$PLUGIN_ROOT/prompts` |
| `PROJECT_ROOT` | 算子包目录（非插件目录） |
| `UO_ROOT` | `$PROJECT_ROOT/.understand-operator/$OP_NAME` |

缺脚本/prompt → 停，请用户 `.\install.ps1 opencode`。
