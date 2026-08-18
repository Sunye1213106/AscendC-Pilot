# Evidence Discipline

CE 不维护账本，不签发证书。给人看的结论写在 `{slug}_plan.md`、审查对话或 `session_handoff.md`。

每条跨层结论应能追溯到：

1. `uo-query` 的一种形态（标识符 / `Dim=V` / `--file --line` / 无参数索引）；
2. 源码 `path:line` 或卡片上的定义点；
3. 失效条件（`.uo` digest 变了、计划 todo 改了、diff 范围变了）。

验证走 `/tg-plan`。不要把审查叙述写成已闭合的测试义务 yaml。
