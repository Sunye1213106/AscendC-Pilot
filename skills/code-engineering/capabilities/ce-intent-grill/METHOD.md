# CE intent grill

把开发者提交的需求问到可分解。事实自己查 CodeMap；决策问人。只出草稿，不提交正式 CE 计划。

详见 `references/gotchas.md`、`references/risk-classes.md`、`references/evidence-tiers.md`、`references/intent-grill-staging.md`。

## 本步草稿

写入当前 action 目录，不要在 Pilot 仓做目录遍历：

- 路径：`<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/intent_grill/staging.yaml`
- 也可写 `parts/*.yaml`（同 schema 字段）
- schema 见 session `refs/` 中的 `intent-grill-staging.md`（原文如下同文件）

```yaml
schema: ce-intent-grill-staging/v1
in_scope: []          # 要做的范围
out_of_scope: []      # 明确不做
acceptance: []        # 可被 /ce-verify 关闭的验收
open_questions: []    # 未决决策，每项带推荐答案
side: ""              # kernel | tiling | host | mixed
```

禁止 Glob / Get-ChildItem / 递归列出 Pilot 仓来寻找 schema。超时或中止前，已完成的图查询结论仍须写入最终消息。

## 方法

1. 先读已记录意图，再插件 `pilot_cli` `uo-query` / 最小源码窗。不问人「这段代码在哪」。
2. 设计树只推进当前可问的决策：范围、不做的事、Kernel vs Tiling、验收用哪种可关闭收据（UT / ST / 精度 / profiling / 复测）。
3. 每个验收条件必须能被后续 `/ce-verify` 用收据关闭，不要写「主观判断通过」。
4. 不确定标 `UNRESOLVED`，写入 `open_questions`（带推荐答案）。写入本步草稿。

## 禁止

- 改写 canonical 计划或声称锚点已 locate
- 名称近似命中当成已定位（那只是 Tier C 线索）
- 宣布验证已通过
- 对 Pilot 仓做目录遍历寻找契约文件
