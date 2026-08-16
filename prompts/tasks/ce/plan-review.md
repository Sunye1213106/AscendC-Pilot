<task>
独立审查特性分解草稿，并提升为可定位的 canonical 特性清单。
</task>

<context>
- Feature draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/feature_decompose`
- Intent: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/intent.yaml`

本阶段在 `anchor_locate` 之前。CodeMap span 解析由后续 locate 完成，这里不要求 `ce/intent/anchors.yaml`。
</context>

<instructions>
1. 若意图里仍有未决问题，拒绝。否则验证每个特性都有目标、约束、候选锚点（符号/实体名即可）和可验证的验收条件。
2. 拒绝无候选锚点、越界范围或不可验证的完成条件。名称近似命中只能作为 Tier C 线索。
3. 通过时将审查结论写入 `ce/intent/plan_review.yaml`（含已接受特性清单）。canonical 特性清单由后续确定性动作根据本审查结果写出。不要另写 `feature_decomposition.yaml`。
</instructions>

<output>
写入 `ce/intent/plan_review.yaml`，包含 `status`、`accepted`、`rejected`、`source_citations` 和 `referee_id`。
</output>
