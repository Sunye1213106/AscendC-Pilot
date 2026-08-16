<task>
向用户展示推断出的精度/性能测试场景与条数预算，并请求明确确认。
</task>

<context>
- Scenario set: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/scenarios/scenario_set.yaml`
</context>

<instructions>
1. 用人话列出每个场景要测什么、大概几条、走精度比对还是性能采集。不要把全量 TilingKey 闭环说成这一步的目标。
2. 弹出 AskQuestion；选项必须原样使用控制面返回的 `ask_question.options`。
3. 只有用户明确确认后才完成本步；不得推断同意，不要自行提交正式确认。
4. 用户要求增删场景时保持未确认，并说明回到推断步骤。
</instructions>

<output>
不写文件。不要自行提交正式确认。
</output>
