<task>
把已记录的变更意图分解为可定位、可审查、可验证的特性单元。
</task>

<context>
- Intent: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/intent.yaml`
- UO product root: `<UO_ROOT>`
- Staging root: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/feature_decompose`
</context>

<instructions>
1. 先查询 CodeMap，再读取最小必要源码窗口。
2. 每个特性给出目标、约束、候选锚点、验收条件和未知项。
3. 不确定内容标记 `UNRESOLVED`；仅写 staged parts，不写 canonical CE 计划。
</instructions>

<output>
写入 `runs/<RUN_ID>/actions/feature_decompose/parts/part_0.yaml`，并保持 staging contract 字段完整。
</output>
