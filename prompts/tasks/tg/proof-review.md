<task>
审查 `source_proof` 交回的证书。只给 `accept` / `reject` / `defer`。不要补证，不要写 exclusion。
</task>

<input>
- Certificates: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/source_proof/`
- Worklog: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/worklog.md`
- Replay: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/replay_round.yaml`
</input>

<delta_constraints>
1. `obligation` 必须是义务 id，不是散文 claim。不要写未加引号的 `on:`（YAML 1.1 会当成布尔键）。
2. 形式不合法不得 `accept`。搜索失败或裸 Host reject 不得升级 exclusion。
3. 本窗不改证书正文。
</delta_constraints>

<output>
最终消息交回审查 YAML。不要 Write。

```text
reviews:
- verdict: accept | reject | defer
  obligation: <id>
  broken: <obligation> <citation>   # reject 时必填
```
</output>
