# 源码访问不变量（面向模型，短）

1. 语义查询用 `uo-query`。Primary 与子代可以 Read / Glob / Grep 算子源码、测试脚本仓、`.ascendc-pr` worktree。Grep 只用于定位。
2. 禁止无界扫仓 / 扫父仓；禁止把整文件倒进上下文。
3. 空 UO 图 ≠ 符号不存在；回退到有范围的源码阅读。
4. `uo-query` 只有四种形态，禁止 `--mode`（含 Task 正文）以及 `explain-*` / `search` / `locate`：无参数索引（默认首次）；一个标识符；覆盖列表 `Dim=<维名>` 或组合 `Name=Value`（历史写法 `Dim=V[,Other=V]`）；`--file PATH --line N`（只从上一张卡复制）。0 命中不把全集 `dim_coverage` 当成成功。around 是该行实体 + 1 跳，不是 2-hop impact。

全文：`pilot/policies/code-access/POLICY.md`。
