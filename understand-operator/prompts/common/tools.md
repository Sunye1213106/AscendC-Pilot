# 工具执行（非 CBM）

权威全文见同目录 `runtime.md`「工具执行」节。符号语义查证见 `cbm.md`。

读源码前用已确认范围（`scope_confirmed` / receipt），禁止宽递归重扫仓库。

优先：① 范围事实（YAML/receipt）→ ② 范围内 Glob / rg / 按行 Read → ③ MCP CBM（`cbm.md`）。

| 场景 | 用 |
|---|---|
| 路径、include、CMake、文件是否存在 | Glob / rg / Read |
| 已知文件的小段文本 | 按行 Read（禁整文件 dump） |
| 函数/类/调用/宏语义 | **仅** `cbm.md` |

禁止：整盘扫描；范围已知仍枚举全仓；PS 嵌套 `powershell -Command`；同一失败调用重试超过 1 次；用本地 CBM CLI 顶替 MCP。

Windows：`python -X utf8 ...`；路径用 `-LiteralPath`。
