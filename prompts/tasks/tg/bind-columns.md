<task>
写出 parts/bind.yaml：table_kind、entry、case_arg、columns、mapping、domains、findings。
</task>

<input>
- Scan receipt: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/repo_scan.yaml`
- UO: `<UO_ROOT>`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/bind_init/parts/bind.yaml`
</input>

<delta_constraints>
1. 只写 bind.yaml；不要写 harness.yaml 或正式 tg/init.yaml。
2. 有仓却 mapping 为空则本步失败；不要发明列、不要空值域。
3. 无仓时列来自 Host API，kind=default_input。查语义用 uo-query。
</delta_constraints>

<output>
写入 `parts/bind.yaml`。
</output>
