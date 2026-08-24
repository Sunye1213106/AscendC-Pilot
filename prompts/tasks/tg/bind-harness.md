<task>
写出 parts/harness.yaml。
</task>

<input>
- Scan receipt: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/repo_scan.yaml`
- UO: `<UO_ROOT>`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/bind_init/parts/harness.yaml`
</input>

<delta_constraints>
1. 只写 harness.yaml；不要写 bind.yaml 或正式 tg/init.yaml。
2. 身份字段由框架写入，不要从 stub 抄进 YAML。
3. `entry` / 表清单以 receipt 为准；没有 `error` 的表不要写成读失败。
4. 默认 mode 是性能时必须写进 findings，不要把默认当精度。
</delta_constraints>

<output>
写入 `parts/harness.yaml`。
</output>
