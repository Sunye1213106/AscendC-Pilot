<task>
根据对话意图与 `tg/init.yaml` 列出独立测试变量。未指定方向时用 TilingKey 维。
</task>

<input>
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Change packet: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/plan_scope_packet.yaml`
- Optional intent: `ce/plan/*_plan.md`、`session_handoff.md`、用户意图
- UO: `<UO_ROOT>`
</input>

<output>
写入 `parts/targets.yaml`。不要写正式 `tg/plan.md`。
</output>
