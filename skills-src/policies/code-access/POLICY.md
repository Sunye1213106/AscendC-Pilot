# Policy: code-access

## Purpose

约束代码语义查阅方式，禁止无边界全仓扫描。

## Rules

1. 理解普通函数/类/调用关系时优先使用 CBM（MCP codebase-memory）。
2. 已有明确 `file_path` 时可直接打开目标源码窗口。
3. Grep / rg 只用于定位，不可单独作为复杂语义结论的唯一证据。
4. 不允许无边界扫描整个仓库或父仓。
5. CBM 空结果不代表符号不存在；须回退定向源码阅读或受控 source_closure。
6. 禁止索引父仓；`project` 必须等于 `index_meta.cbm_project`。
7. 宏表 / 注册宏 / Host 谓词 / CMake / 模板参数绑定：以确定性脚本 + 范围内 Read 为主路径，CBM 为 MAY。
8. 官方文档只提供接口/宏契约；权威序：算子源码 → 目标 CANN 版本文档 → latest → 其它。文档不得创建无源码边。
9. CMake/构建文件不得进入 CBM source index；走 `extract_build_evidence`。
10. 符号身份使用 `semantic_identity` / `entrypoint_graph` 稳定 id，禁止短名唯一键。

## Hard Constraints

- MUST NOT：`index_repository(repo_path=父仓)`。
- MUST NOT：整文件 dump 或无关大段源码加载。
- MUST NOT：把 CBM 空结果当作「不可解」的唯一证据。
- MUST NOT：把 BuildConfig / CompileMacro / PlatformInfo 伪装成 CSV 可控输入。
- MUST NOT：恢复 `roles.*.selected` 单入口契约。
- MUST NOT：candidate 边假闭合主链；patch 直接改写派生图。
- MUST NOT：因评分低自动把主链必需缺口降为 informational。
- MUST：LLM 消歧仅在候选窗内；过期 snapshot/candidate hash 的 patch 必须拒绝。
