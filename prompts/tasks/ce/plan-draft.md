<task>
把已问清的需求写成 `{slug}_plan.md`。
</task>

<context>
- Grill draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/intent_grill/`
- Plan dir: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/plan/`
- Shape reference: session refs 中的 deter-band-schedule 例
</context>

<instructions>
写出实现分析、计划、可勾选 todo、测试内容。路径写反引号。不要写 yaml。不要以 PR 为输入。
</instructions>

<output>
写入 `ce/plan/{slug}_plan.md`。
</output>
