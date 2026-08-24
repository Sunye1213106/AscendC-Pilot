<task>
写出 parts/bind.yaml。
</task>

<input>
- Scan receipt: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/repo_scan.yaml`
- UO: `<UO_ROOT>`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/bind_init/parts/bind.yaml`
</input>

<delta_constraints>
1. 只写 bind.yaml；不要写 harness.yaml 或正式 tg/init.yaml。
2. 身份字段由框架写入，不要从 stub 抄进 YAML。
3. 两列不得共用 `uo.id`。多列共喂的聚合 kwargs 不是任何一列的身份。
</delta_constraints>

<output>
写入 `parts/bind.yaml`。
</output>
