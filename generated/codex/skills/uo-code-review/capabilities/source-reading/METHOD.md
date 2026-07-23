# 定向源码阅读

## Purpose

在已知路径上读取最小窗口，为语义结论提供 `path:line` 证据。

## Method

1. 仅打开当前 Action 相关路径。
2. 优先函数/宏块附近窗口，禁止整文件倾倒。
3. 记录行号与结论关系。

## Hard Constraints

- MUST NOT：无边界全仓 Read。
- MUST NOT：根据变量名猜测含义而不读实现。
