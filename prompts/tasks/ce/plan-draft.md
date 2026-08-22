<task>
把已记录的变更意图问清并写成 `{slug}_plan.md`。边查图边问决策，当场写计划。
</task>

<inputs>
- UO product root: `<UO_ROOT>`
- Plan dir: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/plan/`
- Shape reference: session refs 中的 deter-band-schedule 例
</inputs>

<instructions>
事实走 `uo-query`。当前可问决策一轮问完，每题带推荐答案。写出实现分析、计划、可勾选 todo、测试内容。路径写反引号。不要写 yaml。不要以 PR 为输入。不要先写 staging。
</instructions>

<output>
写入 `ce/plan/{slug}_plan.md`。
</output>
