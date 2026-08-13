<task>
向用户展示推断出的精度/性能测试场景与条数预算，并请求明确确认。
</task>

<context>
- Scenario set: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/scenarios/scenario_set.yaml`
</context>

<instructions>
1. 用人话列出每个场景要测什么、大概几条、走精度比对还是性能采集。不要把全量 TilingKey 闭环说成这一步的目标。
2. 只有用户明确确认后才记录 confirmed；不得推断同意。
3. 用户要求增删场景时保持未确认，并说明回到推断步骤。
</instructions>

<output>
写入 `ce/scenarios/confirmation.yaml`，包含 `status`、`confirmed_by`、`confirmed_at` 和已确认的场景 id 列表。
</output>
