<task>
根据 `tg/init.yaml` 与紧凑改动包写出这次测什么。不要写正式 `tg/plan.md`，不要枚举全量 Key。
</task>

<input>
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Change packet: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/plan_scope_packet.yaml`
- Optional intent: `ce/plan/*_plan.md`、`session_handoff.md`、用户意图
- UO: `<UO_ROOT>`
</input>

<delta_constraints>
1. 只写 `runs/<RUN_ID>/actions/plan_scope/parts/purpose.md`。
2. 改动包已预取标识符；禁止 around。无 diff 时用途来自意图 / L0。
3. 身份字段由框架写入，不要从 stub 抄进文首 YAML。
</delta_constraints>

<output>
写入 `parts/purpose.md`：这次测什么、碰到哪些维/路径、哪些是编码控制面。
</output>
