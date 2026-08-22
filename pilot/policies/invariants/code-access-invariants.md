# 源码访问不变量（面向模型，短）

1. 语义查询用 `uo-query`。Primary 与子代可以 Read / Glob / Grep 算子源码、测试脚本仓、`.ascendc-pr` worktree。Grep 只用于定位。
2. 禁止无界扫仓 / 扫父仓；禁止把整文件倒进上下文。
3. 空 UO 图 ≠ 符号不存在；回退到有范围的源码阅读。
4. `uo-query` 禁止 `--mode`（含 Task 正文）以及 `explain-*` / `search` / `locate`，禁止四种形态之外的参数。形态细则见 `uo-query` Skill。0 命中不把全集 `dim_coverage` 当成成功。around 是该行实体 + 1 跳，不是 2-hop impact。

全文：`pilot/policies/code-access/POLICY.md`。
