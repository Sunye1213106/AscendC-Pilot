<task>
根据对话意图与 `tg/init.yaml` 列出 Target、Guard、candidate Dimension。未指定方向时 Target = Host dispatch，candidate dims = TilingKey 维。禁止 Write。
</task>

<input>
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Change packet: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/plan_scope_packet.yaml`
- Optional intent: `ce/plan/*_plan.md`、`session_handoff.md`、用户意图
- UO: `<UO_ROOT>`
</input>

<output>
最终消息交回 YAML（requirement / targets / guards / candidate_dimensions）。不要 Write `parts/`、`targets.yaml` 或正式 `tg/plan.md`。
</output>
