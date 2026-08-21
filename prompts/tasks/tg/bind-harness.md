<task>
写出 parts/harness.yaml：golden、compare、modes、generate_inputs、call.kind、findings。
</task>

<input>
- Scan receipt: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/repo_scan.yaml`
- UO: `<UO_ROOT>`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/bind_init/parts/harness.yaml`
</input>

<delta_constraints>
1. 只写 harness.yaml；不要写 bind.yaml 或正式 tg/init.yaml。
2. 在 golden/modes 之外记下同一 call.kind（pta / aclnn / mixed）。
3. 精度口径写脚本真实比对方式；禁止把精度标成 `--golden-only`。
4. 身份字段由框架写入，不要从 stub 抄进 YAML。
</delta_constraints>

<output>
写入 `parts/harness.yaml`。
</output>
