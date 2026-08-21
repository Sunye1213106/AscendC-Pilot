<task>
通读两路草稿。不要写文件、不要问用户。没问题下一发 PASS；有问题 REWORK 点名切片。
</task>

<input>
- harness: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/bind_init/parts/harness.yaml`
- bind: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/bind_init/parts/bind.yaml`
- Scan: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/repo_scan.yaml`
</input>

<delta_constraints>
1. 通读内容当裁判，不是只做字段差集。交叉核对两路 `call.kind`。
2. `script_meta` 不得有假 UO；api_arg/attr 必须有标识符。domains 必须做了 profile vs operator 比较。
3. 不要写 referee.yaml。不要 AskQuestion。下一发 intent=`PASS` 或 `REWORK bind` / `REWORK harness,bind`。
</delta_constraints>

<output>
不写文件。下一发带 PASS 或 REWORK。
</output>
