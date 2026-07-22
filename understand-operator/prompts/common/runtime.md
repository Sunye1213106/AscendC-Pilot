# 语言 · 路径 · 非 CBM 工具（runtime）

本文件为 `language` / `path` / `tools` 的合并权威说明；短文件名仍保留为入口指针时可转述至此。

## 语言（原 language.md）

全程简体中文：对用户话术、Todo、产物 `rationale`/`reason`/`summary`，以及**思考过程**。

保持英文：YAML 键、稳定 ID、路径、命令、源码摘录、机器码 / reason_code。

除非用户明确要求，勿用英文写长段思考。

## 路径（原 path.md）

禁止全盘搜脚本。

| 变量 | 含义 |
|---|---|
| `PLUGIN_ROOT` | 插件根（含 `prompts/` `agents/` `skills/` `uo/`） |
| `SCRIPT_DIR` | `$PLUGIN_ROOT/uo/scripts` |
| `PROMPT_DIR` | `$PLUGIN_ROOT/prompts` |
| `PROJECT_ROOT` | 算子包目录（非插件目录；禁抬到多算子父仓） |
| `OP_NAME` | 算子名 |
| `UO_ROOT` | `$PROJECT_ROOT/.understand-operator/$OP_NAME` |

缺脚本/prompt → 停，请用户 `.\install.ps1 opencode`。  
子代理解析 prompts：**只用**宿主传入的 `PROMPT_DIR`/`PLUGIN_ROOT`，禁止相对 `PROJECT_ROOT`。

## 工具执行 · 非 CBM（原 tools.md）

读源码前用已确认范围（`scope_confirmed` / receipt），禁止宽递归重扫仓库。

优先：① 范围事实（YAML/receipt）→ ② 范围内 Glob / rg / 按行 Read → ③ 符号与语义查证走 **`cbm.md`（MCP）**。

| 场景 | 用 |
|---|---|
| 路径、include、CMake、文件是否存在 | Glob / rg / Read |
| 已知文件的小段文本 | 按行 Read（禁整文件 dump） |
| 函数/类/调用/宏语义 | **仅** `cbm.md` |

禁止：整盘扫描；范围已知仍枚举全仓；PS 嵌套 `powershell -Command`；同一失败调用重试超过 1 次；本地 CBM CLI 顶替 MCP。

Windows：`python -X utf8 ...`；路径用 `-LiteralPath`。

## 与 CBM 的边界

索引与符号查找的参数/正误示例 → **`cbm.md`**（勿在本文件重复造一套参数）。
