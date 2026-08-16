<task>
把已记录的变更意图分解为可定位、可审查、可验证的特性单元。
</task>

<inputs>
- Intent: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/intent.yaml`
- UO product root: `<UO_ROOT>`
- Draft root: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/feature_decompose`
</inputs>

<output>
写入本步草稿分解（parts）。每张特性是一张垂直切片：目标、约束、候选锚点、验收、未知项。
没有 diff 时不要假设改动已经存在。不要提交正式 CE 计划。
</output>
