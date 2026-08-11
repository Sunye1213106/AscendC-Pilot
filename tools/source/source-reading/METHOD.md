# 定向源码阅读

## When to use

在已知路径上读取最小窗口，为语义结论提供可核验的 `path:line` + snippet。

## Tools

- `Read` / `source_open`：函数/宏块附近有界窗口（禁止整文件倾倒）
- 校验：`uo.scripts.source_evidence`（高置信 snippet 须与磁盘窗口匹配）

## Output shape

- `code_evidence`：`file` + `line` + 窗口内真实 `evidence_snippet`
- 结论与行号的对应关系写进产物

证据硬规则见 policy `evidence`，勿复述。
