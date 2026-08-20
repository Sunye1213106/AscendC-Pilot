# Policy: code-access

## Purpose

约束代码语义查阅方式，禁止无边界全仓扫描。与 `evidence` 配套：查到 ≠ 已比对。

## Rules

1. 理解函数 / 类 / 调用关系时优先使用 UO 图查询（`pilot_cli` `uo-query`）。
2. 已有明确 `file_path` 时可直接打开目标源码窗口。
3. Grep / rg / 只读搜索只用于定位，不可单独作为复杂语义结论的唯一证据。
4. 不允许无边界扫描整个仓库或父仓。禁止整文件倾倒进上下文。只读当前结论所需最小窗口。
5. UO 图空结果不代表符号不存在；须回退定向源码阅读或受控 source_closure。
6. 读取必须位于 confirmed scope。宏表 / 注册宏 / Host 谓词 / CMake / 模板参数绑定：以确定性脚本 + 范围内 Read 为主路径。
7. 官方文档只提供接口 / 宏契约；权威序：算子源码 → 目标 CANN 版本文档 → latest。文档不得创建无源码边。
8. 符号身份使用稳定 id，禁止短名唯一键。
9. `uo-query` 只有四种参数形态，禁止 `--mode`（含 Task 正文）以及 `explain-*` / `search` / `locate`：无参数索引（默认首次）；一个标识符；`Dim=V[,Other=V]`；`--file PATH --line N`（只从上一张卡复制）。
10. 高置信源码比对要求见 `evidence`。语义表面与浅 writer 见 `semantic-grounding`。本策略不另开例外。

## Hard Constraints

- MUST：语义结论前完成「定位 → 窗口读」。
- MUST NOT：无边界 `index_repository` 父仓、整文件 dump、把空图当作「不可解」的唯一证据。
- MUST NOT：仅用 search 命中标 `source_verified` / `confidence: high`。
- MUST NOT：`--mode` / `explain-*` / `search` / `locate`，或四种形态之外的 `uo-query` 参数。
