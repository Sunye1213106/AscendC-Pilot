<task>
写出 parts/harness.yaml：golden、compare、modes、generate_inputs、findings。
</task>

<input>
- Scan receipt: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/repo_scan.yaml`
- UO: `<UO_ROOT>`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/bind_init/parts/harness.yaml`
</input>

<delta_constraints>
1. 只写 harness.yaml；不要写 bind.yaml 或正式 tg/init.yaml。
2. 精度口径写脚本真实比对方式；禁止把精度标成 `--golden-only`。
3. 无仓时不要假装 script_repo。查语义用 uo-query。
</delta_constraints>

<output>
写入 `parts/harness.yaml`。
</output>
