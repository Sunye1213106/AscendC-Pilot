<task>
把已确认的精度/性能 ScenarioSet 冻结为规划目标。不构造用例、不跑 Host、不断言可达性。
</task>

<context>
- Project: `<PROJECT_ROOT>`
- TG: `<TG_ROOT>`
- Scenario set: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/scenarios/scenario_set.yaml`

方法细节见打包 Skill `testcase-generation`。本 overlay 冻结的是场景集合，不是全部声明 Key。
</context>

<instructions>
1. 存在已确认 ScenarioSet → `target_mode: scenario_set`，目标为其中的场景 id。
2. 不要改写成覆盖全部声明 Key，也不要在规划阶段跑全量笛卡尔。
3. 场景与全覆盖目标混用或缺失 ScenarioSet 时显式标出，禁止静默扩大范围。
</instructions>

<output>
只返回构建规划所需的 intent：`mode: scenario_targeted`、场景 id 列表、以及任何阻塞性歧义。写入 `tg/plan/scenario_plan.yaml`。
</output>
