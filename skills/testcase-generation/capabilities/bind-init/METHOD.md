# TG bind-init

`/tg-init` 在 `repo_scan` 之后 **两路** `tg-analyst`：`bind-harness` 写 `parts/harness.yaml`，`bind-columns` 写 `parts/bind.yaml`（同一轮更好；ACK 只认两份到齐，不认顺序/并行）。正式 `tg/init.yaml` 由主控裁判放行后的 `bind_promote` 写入。测试脚本仓可选；无仓也两路都跑。

本 METHOD 是父 Action 索引。各切片只读自己的 METHOD（`bind-harness` / `bind-columns`）。

## 方法

1. 读 `runs/<run_id>/receipts/repo_scan.yaml`。路径未确认不得把仓内 `tests/` / `ut` 写成 `script_repo`。
2. **harness 切片**：golden / compare / modes / generate_inputs / findings。
3. **columns 切片**：table_kind / entry / case_arg / columns / mapping / domains / findings。只映射测试仓与算子，不要标 PR 焦点。
4. 查语义：只用 `pilot_cli` `uo-query`（列/口径 → 标识符；禁止当 PR 审查）。
5. `uo_digest` 由 promote 写入；草稿可留空。

## 禁止

- 写正式 `tg/init.yaml`
- 把精度启发式标成 `--golden-only`
- 无 mapping 却声称 script_repo 已绑定
- 把列或 CSV 标成 PR 焦点 / 本次测试目标
- 无仓时假装脚本仓已就绪
