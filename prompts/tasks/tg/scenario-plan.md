<task>
把已确认的精度/性能 ScenarioSet 冻结为规划目标。不构造用例、不跑 Host、不断言可达性。
</task>

<context>
- Project: `<PROJECT_ROOT>`
- TG: `<TG_ROOT>`
- Scenario set: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/scenarios/scenario_set.yaml`

方法细节见打包 Skill `testcase-generation`。本 overlay 冻结的是场景集合，不是全部声明 Key。
AskQuestion 文案由控制面生成。
</context>

<instructions>
1. 存在已确认 ScenarioSet → 规划目标为其中的场景 id，不是全部声明 Key。
2. 不要在规划阶段跑全量笛卡尔。
3. 场景与全覆盖目标混用或缺失 ScenarioSet 时显式标出，禁止静默扩大范围。
4. Host 弹出 AskQuestion；选项必须原样使用控制面返回的 `ask_question.options`。
5. Primary 禁止 Write `tg/plan/scenario_plan.yaml`。确认后由 Host `--finalize` 写入。
</instructions>

<output>
不写文件。确认后由 Host finalize 写入 `tg/plan/scenario_plan.yaml`。
</output>
