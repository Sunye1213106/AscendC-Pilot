<task>
根据测试脚本仓扫描结果和 CodeMap，写出 init.yaml 草稿：列、映射、值域、golden、精度/性能怎么跑。
</task>

<input>
- Scan receipt: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/repo_scan.yaml`
- UO: `<UO_ROOT>`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/bind_init`
</input>

<delta_constraints>
1. 有脚本仓却 mapping 为空则本步失败；不要发明列。
2. 精度口径写脚本真实比对方式；禁止把 FAG 精度标成 `--golden-only`。
3. golden 挂脚本函数名 + uo 标识符；没有就写无。
4. 查语义用 uo-query 路由，禁止 Grep 算子仓。
</delta_constraints>

<output>
写入本步草稿 yaml（完整 init.yaml 字段）。不要写正式 `tg/init.yaml`。
</output>
