# TG bind-init

把测试脚本仓扫描结果绑到 CodeMap，写出 **一份** `init.yaml` 草稿。正式文件由 `bind_promote` 写入。

## 方法

1. 读 `runs/<run_id>/receipts/repo_scan.yaml`：入口、`--case`、表头（含 xls/xlsx）、argparse。
2. 有脚本仓：为每一列写 `mapping`（脚本读点如 `get_case` / `CaseConfig.xxx` + 算子仓/UO 标识符）。mapping 空则本步失败。
3. 写 `modes.precision` / `modes.perf`：脚本怎么跑。FAG 精度是 `only_grad`，性能是 `profiler`，禁止标成 `--golden-only`。
4. 写值域、`golden`（函数名 + uo 标识符或无）、脚本实际比对口径、`generate_inputs` 能力。
5. `uo_digest` 由 promote 写入；草稿可留空。
6. 查语义：简单查询主控/本步 `pilot_cli` `uo-query`；复杂查询并行 `Task(agent=uo-query)`。禁止 Grep 算子仓。

## 禁止

- 写正式 `tg/init.yaml`
- 把精度启发式标成 `--golden-only`
- 无 mapping 却声称 script_repo 已绑定
