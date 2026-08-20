# TG bind-review

主控 **通读** `parts/harness.yaml` 与 `parts/bind.yaml` 当裁判，不是只做 key 差集。**不要写文件**。不要 `AskQuestion`。parts 已齐时禁止 `force_new`。

对照 `repo_scan.yaml` 的 `tables[].profile` 打回「把 D 写成 DTemplateNum 那组 enum」「PSE_type 只有 0/1」这类错误。

## 清单

- 两份是否自洽（A 说的造数/比对，B 的列能否支撑）
- 有没有发明列、空 mapping、空值域
- domains 是否引用 profile：shape 列（`D`/`S1`/`B`）是 range，不是 `*TemplateNum` enum
- `dim_*` / TilingKey 维是否来自 uo-query 标识符或 `Dim=Name`，而不是抄 profile 众数
- `mapping.uo_id` 不要把 TemplateNum 挂到 shape 列；`Layout` 不要挂 `SplitAxis`
- 枚举跟 Host 标识符走（`PseType` 0–3，`SparseMode` 含 7/8），不要信脚本注释 `# 0 1`
- `get_case` 读到的列都要进 mapping（profile 列并集），例如 `is_sink`
- runner `--case` 与 validator `--validate` 分开写
- golden 与算子逻辑矛盾是否写清楚
- 精度/性能口径是否来自脚本事实（禁止把精度标成 `--golden-only`）
- `generate_inputs` 是否写了造数缺口（空 / 标量 / inf-nan / 边界 / 对齐 / 非法 range）；依赖列有没有被当成独立可填
- 无仓时有没有假装 `script_repo`
- 有没有把列/CSV 标成 PR 焦点或本次测试目标（应 retract；PR 范围不是 init 的事）

## 下一发

没问题：下一发 `pilot_run(tg-init)`，`intent=PASS`（或 `通过`）。

有问题：`intent=REWORK bind` 或 `REWORK harness,bind`（或 `打回 bind`），后面跟原因。必须点名 `harness` 和/或 `bind`。引擎自己写内部 verdict；不要写 `referee.yaml`。
