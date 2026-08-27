<task>
只处理 coverage_eval 标成 MISS / UNKNOWN 的义务。交回 `actions` YAML（refine / proof_requests / stop）。禁止宣布 HIT，禁止写 exclusion。
</task>

<input>
- Plan: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/plan.md`
- Worklog: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/worklog.md`
- Replay: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/replay_round.yaml`
</input>

<output>
最终消息交回 `actions` YAML。不要 Write staging / 正式 `tg/worklog.md`。
</output>
