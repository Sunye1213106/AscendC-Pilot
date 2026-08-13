<task>
根据影响切片列出精度/性能 ScenarioSet 草案。不得发明目录以外的场景 id。
</task>

<context>
- Impact slice: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/impact/impact_slice.yaml`
- Risk classes: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/impact/risk_classification.yaml`
- Scenario skeleton: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/scenarios/scenario_set.yaml`
- Project: `<PROJECT_ROOT>`
- UO: `<UO_ROOT>`

方法细节见打包 Skill `code-engineering`（场景推断与目录）以及 `testcase-generation`（精度/性能 knobs）。
</context>

<instructions>
1. 先读引擎写出的 ScenarioSet 骨架，只允许补充 knobs / budget / 说明，不得新增未知 id。
2. 先查 CodeMap（impact、kernel_api、buffer、field），再开最小源码窗。
3. 切片截断不得解释成「没有精度或性能影响」。
4. `P-ILLEGAL` 不得建议上板；精度/性能不得用审查叙述关闭验证义务。
5. 预算遵守目录默认：精度每场景少量用例，性能 3–8 条，禁止全量 legal key。
</instructions>

<output>
写入暂存草案，包含 `schema: ce-scenario-knobs/v1`、逐条 `id`、`knobs`、`budget`、`oracle` 与锚点 `path:line`。不要改写 `ce/scenarios/scenario_set.yaml`；Host `scenario_apply` 会把 overlay 合并进该文件。
</output>
