<task>
通读两路草稿。不要写文件、不要问用户。没问题下一发 PASS；有问题 REWORK 点名切片。
</task>

<input>
- harness: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/bind_init/parts/harness.yaml`
- bind: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/bind_init/parts/bind.yaml`
- Scan: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/receipts/repo_scan.yaml`
</input>

<delta_constraints>
1. 通读内容当裁判。不要写 referee.yaml。不要 AskQuestion。
2. 下一发 intent=`PASS` 或 `REWORK bind` / `REWORK harness` / `REWORK harness,bind`。
</delta_constraints>

<output>
不写文件。下一发带 PASS 或 REWORK。
</output>
