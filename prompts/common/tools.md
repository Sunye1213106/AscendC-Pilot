# 工具执行（非 CBM）

## Task

在已确认分析范围内取路径/文本证据。符号语义走 `cbm.md`；宏表与 KEY 谓词走本文件主路径。

## Authoritative Sources

1. `scope_confirmed` / Phase0 receipt
2. 范围内 Glob / rg / 按行 Read
3. `cbm.md`（仅具名函数/类/方法）

非权威：全仓扫描、模型记忆、本地 CBM CLI。

## Required Procedure

```text
1. 范围事实（YAML / receipt）
2. 范围内 Glob / rg / 按行 Read
3. 具名符号 → MCP（cbm.md）
```

## Tool Policy

| 场景 | MUST use |
|---|---|
| 路径、include、CMake、文件是否存在 | Glob / rg / Read |
| 已知文件小段文本 | 按行 Read（禁整文件 dump） |
| 具名函数/类/方法与调用边 | MCP（`cbm.md`） |
| `ASCENDC_TPL_*` / `GET_TPL_*` / `REGISTER_*` / 模板位域 | 范围内 rg + Read（CBM 仅可定位） |
| KEY 谓词（`GetTilingKey` 实参 ↔ 宏 DECL） | Host 定向 Read；CBM=MAY |

## Hard Constraints

- MUST：先确认 scope，再读源码
- MUST NOT：整盘扫描；范围已知仍枚举全仓
- MUST NOT：PS 嵌套 `powershell -Command`；同一失败调用重试 >1
- MUST NOT：本地 CBM CLI 顶替 MCP
- MUST NOT：CBM 空结果宣称 KEY「跨编译边界 / bit-pack 不可解」
- ONLY：Windows 用 `python -X utf8`；路径用 `-LiteralPath`

## Failure Handling

范围外才能找到证据 → STOP，回 Phase0 / 扩 scope，禁止擅自全仓搜。  
细节与 CBM 失败码：`cbm.md`。权威长文：`runtime.md`。
