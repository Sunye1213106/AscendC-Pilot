# CBM 代码图导航

## Purpose

围绕当前 topic 获取最小、可追溯的代码上下文，不进行无边界仓库探索。

## Use When

- 需要理解具体实现、分支、数据流或调用关系
- KB 只提供了 `file_path`、symbol 或邻接关系
- 需要验证已有语义结论

## Inputs

- `target_symbols`：目标符号或查询模式
- `topic`：当前问题主题
- `cbm_project`：来自 `index_meta.json`

## Method

1. 读 `index_meta` → `cbm_project`；`project` 参数必须匹配。
2. `search_graph` / `search_code` 定位 `qualified_name` + `file_path`。
3. `get_code_snippet(qualified_name=...)` 取最小窗口。
4. 需要调用边时用 `trace_path`（depth≤5）。
5. 宏表 / 注册 / Host 谓词模式立即切范围内 Read，不以 CBM 为主路径。
6. CBM 无结果时回退定向源码阅读，不得直接认定「不可解」。

## Hard Constraints

- MUST NOT：无边界扫描；索引父仓；猜 `qualified_name`。
- MUST NOT：把 CBM 空结果当作不存在的证据。
- MUST：每个关键结论记录路径、行号或 CBM symbol reference。

## Result

- 相关 symbols、代码证据、支持结论、仍需补充的证据。

## Stop Conditions

- 已满足当前 Action 输出合同；达到工具预算；缺少必要证据；需人工确认。
