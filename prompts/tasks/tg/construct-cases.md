<task>
按已批准 plan.md 义务构造脚本仓能直接吃的用例行。
</task>

<input>
- Plan: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/plan.md`
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/construct_cases`
</input>

<output>
写入本步草稿 yaml：`columns` 与 `rows`。不要写正式 `tg/cases.*`。
</output>
