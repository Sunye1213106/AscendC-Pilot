<task>
按已批准 plan.md 义务构造脚本仓能直接吃的用例行。
</task>

<input>
- Plan: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/plan.md`
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/construct_cases`
</input>

<delta_constraints>
1. 行必须填满 init.yaml 列；现有 runner 能直接跑。
2. 每个义务写 `why` 对应的控制列取值。
3. 不要改算子仓。
</delta_constraints>

<output>
写入本步草稿 yaml：`columns` 与 `rows`。不要写正式 `tg/cases.*`。
</output>
