# CE intent grill

把开发者提交的需求问到可分解。事实自己查 CodeMap；决策问人。只出草稿，不提交正式 CE 计划。

详见 `references/gotchas.md`、`references/risk-classes.md`、`references/evidence-tiers.md`。

## 方法

1. 先读已记录意图，再 `acp uo-query` / 最小源码窗。不问人「这段代码在哪」。
2. 设计树只推进当前可问的决策：范围、不做的事、Kernel vs Tiling、验收用哪种可关闭收据（UT / ST / 精度 / profiling / 复测）。
3. 每个验收条件必须能被后续 `/ce-verify` 用收据关闭，不要写「看起来没问题」。
4. 不确定标 `UNRESOLVED`，写入 `open_questions`（带推荐答案）。写入本步草稿。

## 禁止

- 改写 canonical 计划或假装锚点已 locate
- 名称近似命中当成已定位（那只是 Tier C 线索）
- 宣布验证已通过
