<task>
写出 parts/bind.yaml：调用接口 → CSV 列 → 剩余列 role/encoding；domains 做 profile vs operator 比较。
</task>

<input>
- Scan receipt: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/repo_scan.yaml`
- UO: `<UO_ROOT>`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/bind_init/parts/bind.yaml`
</input>

<delta_constraints>
1. 只写 bind.yaml；不要写 harness.yaml 或正式 tg/init.yaml。
2. 先记 call.kind/api/site，再绑 API 入参。script_meta 禁止编造 uo_id。
3. 未从卡片复制 file:line 时禁止 around。身份字段由框架写入。
4. 无仓时不要假装 script_repo。
</delta_constraints>

<output>
写入 `parts/bind.yaml`。
</output>
