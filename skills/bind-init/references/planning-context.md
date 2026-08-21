# Planning Context

`/tg-plan` 的覆盖范围必须在派发前已经确定。本 skill 定义如何把该范围写成义务，不负责编排审查或查询。

合法来源：

- 同一会话 `/ce-review` 结论
- `{slug}_plan.md` 的「测试内容」
- 用户已陈述的测试范围
- `session_handoff.md`
- 最终产物是用例、审查不是交付物时，主控综合的 `/uo-query` 结论

缺 Planning Context 时不要进入 `/tg-plan`。最终产物是用例、审查不是交付物时，Planning Context 来自主控综合的 `/uo-query`，不要把 `/ce-review` 推理成前置。只有审查本身是交付物时才用审查结论。
