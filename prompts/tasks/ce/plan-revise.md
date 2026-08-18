<task>
按用户补充需求修订当前 `{slug}_plan.md`。
</task>

<context>
- 当前计划：`<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/plan/`
- Delta：`runs/<RUN_ID>/actions/plan_revise/delta.md`
- Baseline todos：`runs/<RUN_ID>/actions/plan_revise/baseline.yaml`
- Shape：session refs 中的 deter-band-schedule 例
</context>

<instructions>
保留已勾选 todo。把补充需求写成新增或重开的 `- [ ]`，并更新声明文件与测试内容。不要另起 slug。不要写 yaml。
</instructions>

<output>
覆盖写入同一份 `ce/plan/{slug}_plan.md`。
</output>
