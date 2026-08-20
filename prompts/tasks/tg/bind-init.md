<task>
父 Action：两路并行写出 harness.yaml 与 bind.yaml。本 stub 在 fanout 时不会单独派发；各切片只用自己的 AXIS FOCUS。
</task>

<input>
- Scan receipt: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/repo_scan.yaml`
- UO: `<UO_ROOT>`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/bind_init`
</input>

<delta_constraints>
1. 只写本切片声明的 yaml；不要写正式 `tg/init.yaml`。
2. 无脚本仓：不要假装已有仓。精度口径写脚本真实比对方式；禁止 `--golden-only`。
3. 查语义用 uo-query 路由。
</delta_constraints>

<output>
写入本切片草稿 yaml。不要写正式 `tg/init.yaml`。
</output>
