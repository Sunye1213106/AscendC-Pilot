<task>
独立审查 staged 特性分解与 CodeMap 锚点，并裁决是否可提交人工确认。
</task>

<context>
- Feature staging: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/feature_decompose`
- Anchors: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/anchors.yaml`
- Intent: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/intent.yaml`
</context>

<instructions>
1. 验证每个特性均可追溯到意图、源码锚点和验收条件。
2. 拒绝无证据锚点、越界范围或不可验证的完成条件。
3. 通过时将已审内容提升为 `ce/intent/feature_decomposition.yaml`。
</instructions>

<output>
写入 `ce/intent/plan_review.yaml`，包含 `status`、`accepted`、`rejected`、`source_citations` 和 `referee_id`。
</output>
