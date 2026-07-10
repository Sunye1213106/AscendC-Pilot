# Path Resolution

| Variable | Meaning |
|---|---|
| `THIS_SKILL` | Current skill directory |
| `SCRIPT_DIR` | `THIS_SKILL/../testcase-generator` (must contain tg_init.py) |
| `PLUGIN_ROOT` | Contains `prompts/00_language.md` |
| `PROMPT_DIR` | `$PLUGIN_ROOT/prompts` |
| `PROJECT_ROOT` | AscendC operator repo root |
| `OP_NAME` | `--op-name` or repo name |
| `UO_ROOT` | `$PROJECT_ROOT/.understand-operator/$OP_NAME` |
| `TG_ROOT` | `$PROJECT_ROOT/.testcase-generator/$OP_NAME` |

Do not search the whole disk for scripts. Run `./install.ps1 cursor` if SCRIPT_DIR is missing.
