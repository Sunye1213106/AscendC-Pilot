# 黄金 NL：分析 PR 并生成用例

用户只说「分析这个 PR 并生成对应测试用例」并贴 PR URL。交付节点是 `/ce-review` + `/tg-plan` + `/tg-solve`。

对照 I/O 补当前缺的一步：无 `.uo` 则 `/uo-init`，有 `.uo` 且有 diff 则 `/uo-update`，TG 前补 `/tg-init`。每步语义走 `/uo-query`。不要 `workflow=auto`，不要插入 `goal-impact`。
