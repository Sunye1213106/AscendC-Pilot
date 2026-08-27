<task>
按 Analyze 交回的 `proof_requests` 写出 atomic 证书。一次一层。不要写 exclusion，不要改 plan / worklog。
</task>

<input>
- Requests: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/analyze_round.yaml`
- Plan: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/plan.md`
- Worklog: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/worklog.md`
</input>

<delta_constraints>
1. 每份证书只有一层：`domain` / `template` / `host` / `kernel`。跨层事实拆成多份。
2. 字段只认 `source-proof` 证书合同。`PROVED` 不得带 `OPEN` / `BLOCKED`。
3. 空 `proof_requests` 交空 `certificates`。不要补命题，不要自审自批。
</delta_constraints>

<output>
最终消息交回证书 YAML（`certificates:` 列表或连续文档）。不要 Write。
</output>
