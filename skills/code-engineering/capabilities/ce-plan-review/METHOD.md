# CE plan review — 独立审查特性分解

把 producer 的特性分解草稿提升为可定位的 canonical 特性清单。本阶段在 `anchor_locate` 之前，不要求 `ce/intent/anchors.yaml`。

详见 `references/gotchas.md`、`references/slice-primitives.md`、`references/evidence-discipline.md`。

## 方法

1. 验证每个特性都有目标、约束、候选锚点（符号/实体名即可）和可验证的验收条件。
2. 拒绝无候选锚点、越界范围或不可验证的完成条件。名称近似命中只能作为 Tier C 线索。
3. 通过时将审查结论写入 `ce/intent/plan_review.yaml`（含已接受特性清单）。canonical 特性清单由后续确定性动作根据本审查结果写出。

## 禁止

- 另写 `feature_decomposition.yaml`
- 代替 locate 去解析 CodeMap span
