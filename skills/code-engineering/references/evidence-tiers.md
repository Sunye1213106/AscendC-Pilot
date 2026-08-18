# Evidence Tiers

- **Tier A — 权威事实：** compiler/AST、精确源码 span、已 commit 的 CodeMap 卡片、测试/构建结果。
- **Tier B — 可复现推导：** 由 Tier A 经 `uo-query` 四种形态得到的邻居 / `Dim=V` 覆盖。记下查询形态与边界。
- **Tier C — 假说：** 名称近似、模型判断、未核验报告。

Tier C 可以当线索写进计划的未决决策，不能当成已经定位或已经测过。CE 没有 `V` / `X` 账本；闭合测试义务是 TG 的 `worklog.md`。
