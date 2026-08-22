<task>
按用户补充需求修订当前 `{slug}_plan.md`。
</task>

<context>
- 当前计划：`<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/plan/`
- Delta：`runs/<RUN_ID>/actions/plan_revise/delta.md`
- Baseline todos：`runs/<RUN_ID>/actions/plan_revise/baseline.yaml`
</context>

<output>
覆盖写入同一份 `ce/plan/{slug}_plan.md`。不要另起 slug。
</output>
