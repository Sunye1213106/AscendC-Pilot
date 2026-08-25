<task>
通读两路草稿。不要写文件、不要问用户。没问题下一发 PASS；有问题 REWORK 点名切片。
</task>

<input>
- harness: d:\PR-review\AscendC-Pilot\skills\bind-init-workspace\iteration-7\eval\parts\harness.yaml
- bind: d:\PR-review\AscendC-Pilot\skills\bind-init-workspace\iteration-7\eval\parts\bind.yaml
- Scan: d:\PR-review\AscendC-Pilot\skills\bind-init-workspace\iteration-7\eval\repo_scan.yaml
- Method: d:\PR-review\AscendC-Pilot\skills\bind-init-workspace\iteration-7\eval\inject\method_review.md
</input>

<delta_constraints>
1. 通读内容当裁判。不要写 referee.yaml。不要 AskQuestion。
2. 下一发 intent=`PASS` 或 `REWORK bind` / `REWORK harness` / `REWORK harness,bind`。
</delta_constraints>

<output>
不写文件。下一发带 PASS 或 REWORK。
</output>
