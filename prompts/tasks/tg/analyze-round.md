<task>
对照本轮 Replay 与义务预期，写 worklog 草稿：一致进 R，不一致分类并推引理。文首 `open:` 列出未闭合义务 id。
</task>

<input>
- Plan: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/plan.md`
- Cases: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/cases.*`
- Replay: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/replay_round.yaml`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/analyze_round`
</input>

<delta_constraints>
1. 先切「预期一致 / 不一致」，不要按 case 写四段。
2. replay 与 derived 可同时存在，两项证据都要有。
3. `Replay reject ≠ E`。引理 span 来自 uo-query。
4. 需要改构造时不要假装闭合。
</delta_constraints>

<output>
写入本步草稿 markdown。文首先写 `open: [...]`。不要写正式 `tg/worklog.md`。
</output>
