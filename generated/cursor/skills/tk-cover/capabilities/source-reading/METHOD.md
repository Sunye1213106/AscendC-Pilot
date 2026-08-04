# 定向源码阅读

## Purpose

在已知路径上读取最小窗口，为语义结论提供可核验的 `path:line` + snippet 证据。
服从公共策略：`evidence`、`code-access`、`source-authority`（禁止在个别 Action 另立例外）。

## Method

1. 仅打开当前 Action 相关路径。
2. 优先函数/宏块附近窗口，禁止整文件倾倒。
3. 记录行号与结论关系；写入产物时附上窗口内真实 `evidence_snippet`。
4. 凡标 `confidence: high` / `source_verified: true`：snippet 必须与磁盘该窗口匹配（校验见 `uo.scripts.source_evidence`）。

## Hard Constraints

- MUST NOT：无边界全仓 Read。
- MUST NOT：根据变量名猜测含义而不读实现。
- MUST NOT：编造或占位 snippet / 行号。
- MUST：高置信结论完成源码窗口比对（见 `evidence` 策略）。
