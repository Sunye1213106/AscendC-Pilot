<task>
把已记录的变更意图分解为可定位、可审查、可验证的特性单元。
</task>

<context>
- Intent: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/intent.yaml`
- UO product root: `<UO_ROOT>`
- Draft root: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/feature_decompose`
</context>

<instructions>
1. 先查询 CodeMap，再读取最小必要源码窗口。没有 diff 时不要假设改动已经存在。
2. 每个特性给出目标、约束、候选锚点、验收条件和未知项。
3. 不确定内容标记 `UNRESOLVED`；只产出草稿分解，不要提交正式 CE 计划。
4. 验收条件要能在后续 `/ce-verify` 用 UT/ST/精度对比/profiling/复测收据关闭，不要写「看起来没问题」。
</instructions>

<output>
写入本步草稿分解（parts），保持草稿字段完整。不要提交正式 CE 计划。
</output>
