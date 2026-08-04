# CBM 代码图导航

## Purpose

围绕当前 topic 获取最小、可追溯的代码上下文，不进行无边界仓库探索。

CBM **只负责**：符号候选定位、普通调用关系、类/方法导航、最小源码片段。  
CBM **不负责**：宏展开、注册语义、CMake/构建条件、模板参数级数据流、TilingKey 位置绑定。这些由确定性源码闭包脚本完成。

## Use When

- 需要理解具体实现、分支、数据流或调用关系
- KB 只提供了 `file_path`、symbol 或邻接关系
- 需要验证已有语义结论

## Inputs

- `target_symbols`：目标符号或查询模式
- `topic`：当前问题主题
- `cbm_project`：来自 `index_meta.json`
- `architecture`：目标架构（如 `arch35`）；搜索排序可偏好该架构，但不得过滤架构中立入口

## Method

1. 读 `index_meta` → `cbm_project`；`project` 参数必须匹配。
2. **OpenCode 工具全名**（直接调用，禁止经 `invalid` / 别名猜测）：
   - 定位：`codebase-memory-mcp_search_graph` / `codebase-memory-mcp_search_code`
   - 取窗：`codebase-memory-mcp_get_code_snippet`（`qualified_name` + `project`）
   - 边：`codebase-memory-mcp_trace_path`（depth≤5）
3. 一次 MCP 调用失败：用正确全名重试一次；仍失败则 `acp cbm lookup`，或定向 `source-reading` 窗口 Read；**不得**放弃源码窗口却标 `source_verified`。
4. 若 prepare 已挂 `source_window.text`：可原样拷贝为 `evidence_snippet`（等同已核验窗口）。
5. 宏表 / 注册 / Host 谓词 / CMake / TilingKey 模板：立即切范围内 Read + 确定性脚本，不以 CBM 为主路径。
6. CBM 无结果时回退定向源码阅读或触发受控 source_closure restage，不得直接认定「符号不存在」。
7. 官方文档只提供宏/接口契约，不代替源码定位，不创建项目内连接边。

## Hard Constraints

- MUST NOT：无边界扫描；索引父仓；猜 `qualified_name`；把 CMake 送进 CBM 源码索引。
- MUST NOT：把 CBM 空结果当作不存在的证据。
- MUST NOT：仅用短函数名作为符号身份；身份见 `semantic_identity` / `entrypoint_graph` 节点 id。
- MUST NOT：用 `file_contains=op_name` / architecture 对 confirmed-scope 文件做硬过滤；`op_name` 只做排序加分。
- MUST NOT：让 `confidence=candidate` 边满足 host/kernel 主链闭合。
- MUST NOT：仅 `search_*` 命中就标 `source_verified` / `confidence: high`（必须再 `get_code_snippet` 或定向 Read；见公共策略 `evidence` + `code-access`）。
- MUST NOT：把 MCP 调用失败当成「CBM 不可用」后跳过取窗；必须走重试 / `acp cbm lookup` / 窗口 Read 之一。
- MUST：查询硬边界 = confirmed source scope；复杂宏优先 LLM 任务而非堆正则。
- MUST：每个关键结论记录路径、行号或 CBM symbol reference；高置信另附可核验 snippet；缺口写结构化 unresolved。

## Result

- 相关 symbols、代码证据、支持结论、仍需补充的证据。

## Stop Conditions

- 已满足当前 Action 输出合同；达到工具预算；缺少必要证据；需人工确认。
