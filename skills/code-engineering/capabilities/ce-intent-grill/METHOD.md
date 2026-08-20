# CE intent grill

把开发者提交的需求问到可以写 `{slug}_plan.md`。事实自己查 CodeMap；决策问人。只出 markdown 草稿，不写正式计划，不写 yaml。

详见 `references/gotchas.md`、`references/intent-grill-staging.md`、`examples/deter-band-schedule_plan.md`。

## 本步草稿

写入当前 action 目录，不要在 Pilot 仓做目录遍历：

- 路径：`<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/intent_grill/staging.md`
- 也可写 `parts/*.md`
- 用小节写清：范围、不做的事、验收/测试内容、未决决策（带推荐答案）

禁止 Glob / Get-ChildItem / 递归列出 Pilot 仓。超时或中止前，已完成的图查询结论仍须写入最终消息。

## 方法

1. 先读已记录意图，再插件 `pilot_cli` `uo-query`（形态见 code-access 不变量）/ 最小源码窗。不问人「这段代码在哪」。
2. 设计树只推进当前可问的决策：范围、不做的事、Kernel vs Tiling、测试应覆盖什么。
3. 验收写进人能读的测试内容，交给 `/tg-plan` 自己总结；不要编码成 yaml 意图。
4. 不确定标 `UNRESOLVED`，写入未决决策（带推荐答案）。写入本步 markdown 草稿。

## 禁止

- 改写 canonical `{slug}_plan.md` 或声称已经 apply
- 名称近似命中当成已定位
- 写任何 `.yaml`
- 传 `--mode` 或调用 `explain-*` / `search` / `locate`
- 对 Pilot 仓做目录遍历寻找契约文件
