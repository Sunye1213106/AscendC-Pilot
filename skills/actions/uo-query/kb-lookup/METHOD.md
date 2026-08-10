# kb_lookup

只读执行当前 `.uo` CodeMap 查询。

Domain：`skills/domain/uo-codemap-query/SKILL.md`。Task prompt：`uo/codemap-query`。

优先使用结构化 `CodeMapQuery`；只有当前问题的结构化证据不足时才读取最小源码窗口。输出遵循当前 Runtime Output Contract；不能可靠判断时返回 `PARTIAL` / `UNKNOWN`，不要猜测。
