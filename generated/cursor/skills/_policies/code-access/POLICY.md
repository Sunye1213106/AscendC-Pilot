# Policy: code-access

## Purpose

约束代码语义查阅方式，禁止无边界全仓扫描。

## Rules

1. 理解代码语义时优先使用 CBM（MCP codebase-memory）。
2. 已有明确 `file_path` 时可直接打开目标源码窗口。
3. Grep / rg 只用于定位，不可单独作为复杂语义结论的唯一证据。
4. 不允许无边界扫描整个仓库或父仓。
5. CBM 空结果不代表符号不存在；须回退定向源码阅读。
6. 禁止索引父仓；`project` 必须等于 `index_meta.cbm_project`。
7. 宏表 / 注册宏 / Host 谓词等模式以范围内 Read 为主路径，CBM 为 MAY。

## Hard Constraints

- MUST NOT：`index_repository(repo_path=父仓)`。
- MUST NOT：整文件 dump 或无关大段源码加载。
- MUST NOT：把 CBM 空结果当作「不可解」的唯一证据。
