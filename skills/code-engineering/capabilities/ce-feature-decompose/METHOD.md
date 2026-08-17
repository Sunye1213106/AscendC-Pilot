# CE feature decompose

把已记录的变更意图分解为可定位、可审查、可验证的特性单元。只出草稿，不提交正式 CE 计划。

详见 `references/slice-primitives.md`、`references/risk-classes.md`、`references/evidence-tiers.md`、`references/gotchas.md`。

## 方法

1. 先读已记录意图里问清后的字段（`in_scope` / `out_of_scope` / `acceptance`），再 `acp uo-query` / 最小源码窗。没有 diff 时不要假设改动已经存在。
2. 每个特性给出目标、约束、候选锚点（符号/实体名即可）、验收条件和未知项。一张特性就是一张垂直切片：有阻塞边就写出来。
3. 验收条件要能在后续 `/ce-verify` 用 UT/ST/精度对比/profiling/复测收据关闭，不要写「主观判断通过」。
4. 不确定标 `UNRESOLVED`。写入本步 `parts/` 草稿，字段保持完整。

## 禁止

- 提交正式 CE 计划或改写 canonical intent
- 名称近似命中当成已定位锚点（那只是 Tier C 线索）
